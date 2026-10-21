#!/usr/bin/env python3
"""Log in to the Daikin Onecta API once and test what a Loxone Virtual Output can send.

Usage: python3 tools/onecta_probe.py [--login]   (--login: ignore saved tokens, e.g. other account)

Run it yourself: it asks for your Daikin developer app's client id and secret and
never prints tokens. It
  1. reuses saved tokens (refreshing them when expired) or opens the Daikin login; after logging in, you paste the URL from the browser's
     address bar (it contains the code) and it exchanges the code for tokens;
  2. reads /v1/gateway-devices and prints the climate-control setpoints it finds;
  3. re-sends the CURRENT room setpoint (so nothing changes) with PUT, POST and
     PATCH, with and without Content-Type, and prints Daikin's status codes.

Tokens are saved to onecta_tokens.local.json and the device JSON to
onecta_devices.raw.json (both git-ignored). About 8 API calls of the 200/day budget.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTHORIZE_URL = "https://idp.onecta.daikineurope.com/v1/oidc/authorize"
TOKEN_URL = "https://idp.onecta.daikineurope.com/v1/oidc/token"
API_URL = "https://api.onecta.daikineurope.com"
SCOPE = "openid onecta:basic.integration offline_access"
# Daikin's CloudFront WAF blocks localhost/127.0.0.1 redirect URIs (HTTP 403), so use a
# LAN address. The page doesn't need to exist: the code is read from the address bar.
REDIRECT_URI = os.environ.get("ONECTA_REDIRECT_URI", "http://192.168.10.10/daikin-callback")

ROOT = Path(__file__).resolve().parent.parent
TOKENS_FILE = ROOT / "onecta_tokens.local.json"
DEVICES_FILE = ROOT / "onecta_devices.raw.json"


def request(method: str, url: str, *, headers: dict | None = None, body: bytes | None = None,
            timeout: int = 30) -> tuple[int, str]:
    """Return (status, body); status 0 means no response within the timeout."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")
    except (TimeoutError, OSError) as err:
        return 0, f"no response ({err})"


def read_code(state: str) -> str:
    print("After logging in, the browser lands on an error or login page. That's expected.")
    redirected = input("Paste the full URL from the address bar: ").strip()
    # The code can be nested, e.g. my.home-assistant.io wraps it as
    # .../_change/?redirect=oauth%2F%3Fcode%3D...%26state%3D..., so decode repeatedly.
    for _ in range(4):
        redirected = urllib.parse.unquote(redirected)
    code = re.search(r"[?&]code=([^&#\s]+)", redirected)
    found_state = re.search(r"[?&]state=([^&#\s]+)", redirected)
    if not code or not found_state or found_state.group(1) != state:
        raise SystemExit("No code with the matching state in that URL; run the script again and paste the new URL.")
    return code.group(1)


def login() -> dict:
    print("Daikin developer app (https://developer.cloud.daikineurope.com)")
    print(f"Its redirect URI must be exactly: {REDIRECT_URI}\n")
    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client secret (hidden): ").strip()
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
    })
    print("\nOpening the Daikin login in your browser. If it doesn't open, visit:\n" + url + "\n")
    webbrowser.open(url)
    code = read_code(state)
    status, text = request("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"},
                           body=urllib.parse.urlencode({
                               "grant_type": "authorization_code",
                               "code": code,
                               "redirect_uri": REDIRECT_URI,
                               "client_id": client_id,
                               "client_secret": client_secret,
                           }).encode())
    if status != 200:
        raise SystemExit(f"Token exchange failed: HTTP {status} {text[:300]}")
    tokens = json.loads(text)
    tokens.update(client_id=client_id, client_secret=client_secret, obtained_at=int(time.time()))
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    TOKENS_FILE.chmod(0o600)
    print(f"Logged in. Tokens saved to {TOKENS_FILE.name}")
    print(f"  access_token length:  {len(tokens['access_token'])} chars (Loxone tested up to 1502)")
    print(f"  refresh_token length: {len(tokens.get('refresh_token', ''))} chars")
    print(f"  expires_in: {tokens.get('expires_in')} s\n")
    return tokens


def save_tokens(tokens: dict) -> None:
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    TOKENS_FILE.chmod(0o600)


def load_or_refresh_tokens() -> dict | None:
    """Reuse saved tokens; refresh them when the access token is (nearly) expired."""
    if not TOKENS_FILE.exists():
        return None
    tokens = json.loads(TOKENS_FILE.read_text())
    if time.time() < tokens["obtained_at"] + tokens.get("expires_in", 3600) - 120:
        print(f"Using saved tokens from {TOKENS_FILE.name}\n")
        return tokens
    status, text = request("POST", TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"},
                           body=urllib.parse.urlencode({
                               "grant_type": "refresh_token",
                               "refresh_token": tokens["refresh_token"],
                               "client_id": tokens["client_id"],
                               "client_secret": tokens["client_secret"],
                           }).encode())
    if status != 200:
        print(f"Refreshing saved tokens failed (HTTP {status}); logging in again.\n")
        return None
    fresh = json.loads(text)
    fresh.update(client_id=tokens["client_id"], client_secret=tokens["client_secret"], obtained_at=int(time.time()))
    save_tokens(fresh)
    new_refresh = fresh.get("refresh_token") != tokens["refresh_token"]
    print(f"Refreshed saved tokens (new refresh token issued: {new_refresh})\n")
    return fresh


def find_target(devices: list) -> tuple[str, str, str] | None:
    """Pick an onOffMode to re-send with its current value (changes nothing).

    Prefers a settable one on an online gateway. Falls back to an offline/read-only
    device: PATCH then returns a quick API error, and comparing PUT/POST against that
    still shows whether those methods are routed at all.
    """
    candidates = []
    for gateway in devices:
        online = gateway.get("isCloudConnectionUp", {}).get("value", True)
        for mp in gateway.get("managementPoints", []):
            on_off = mp.get("onOffMode", {})
            if mp.get("managementPointType") == "climateControl" and "value" in on_off:
                name = mp.get("name", {}).get("value", mp["embeddedId"])
                candidates.append((bool(on_off.get("settable")) and online, name, gateway, mp, on_off["value"]))
    if not candidates:
        return None
    candidates.sort(key=lambda c: not c[0])
    usable, name, gateway, mp, value = candidates[0]
    print(f"Test target: {name} ({gateway.get('deviceModel')}), onOffMode = {value}")
    if not usable:
        print("  Note: no online/settable device; expect PATCH to return an error too. Compare PUT/POST against it.")
    return gateway["id"], mp["embeddedId"], value


def main() -> None:
    tokens = (None if "--login" in sys.argv else load_or_refresh_tokens()) or login()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    status, text = request("GET", f"{API_URL}/v1/gateway-devices", headers=auth)
    if status != 200:
        raise SystemExit(f"Reading devices failed: HTTP {status} {text[:300]}")
    DEVICES_FILE.write_text(text)
    devices = json.loads(text)
    print(f"Read {len(devices)} gateway device(s), {len(text)} bytes. Saved to {DEVICES_FILE.name}\n")

    target = find_target(devices)
    if target is None:
        raise SystemExit("No settable onOffMode found to test with.")
    gateway_id, mp_id, value = target
    url = f"{API_URL}/v1/gateway-devices/{gateway_id}/management-points/{mp_id}/characteristics/onOffMode"
    body = json.dumps({"value": value}).encode()
    print(f"Re-sending the current value {value!r} (no actual change):")

    # PATCH first as the control: it is the documented method and must return 204.
    tests = [
        ("PATCH", True), ("PATCH", False), ("PUT", True), ("POST", True), ("PUT", False), ("POST", False),
    ]
    for method, with_type in tests:
        headers = dict(auth)
        if with_type:
            headers["Content-Type"] = "application/json"
        status, text = request(method, url, headers=headers, body=body, timeout=15)
        label = "with" if with_type else "without"
        result = "no response (timeout)" if status == 0 else f"HTTP {status} {text[:120].strip()}"
        print(f"  {method:5} {label:7} Content-Type -> {result}", flush=True)
        time.sleep(3)

    # POST with a method-override header: would let a Loxone Virtual Output reach PATCH.
    print("\nPOST with method-override headers (same no-op onOffMode body):")
    for header in ("X-HTTP-Method-Override", "X-Method-Override", "X-HTTP-Method"):
        headers = dict(auth, **{"Content-Type": "application/json", header: "PATCH"})
        status, text = request("POST", url, headers=headers, body=body, timeout=15)
        result = "no response (timeout)" if status == 0 else f"HTTP {status} {text[:120].strip()}"
        print(f"  POST + {header}: PATCH -> {result}", flush=True)
        time.sleep(3)

    probe_schedules(devices, auth)
    print("\nHTTP 204 = accepted. Send this whole output back.")


def probe_schedules(devices: list, auth: dict) -> None:
    """PUT the CURRENT schedule selection and schedule set back unchanged.

    These endpoints use PUT (which a Loxone Virtual Output can send), unlike
    characteristics, which only accept PATCH.
    """
    for gateway in devices:
        if not gateway.get("isCloudConnectionUp", {}).get("value", True):
            continue
        for mp in gateway.get("managementPoints", []):
            schedule = mp.get("schedule", {}).get("value", {})
            mode = schedule.get("currentMode", {}).get("value")
            mode_data = schedule.get("modes", {}).get(mode)
            if not mode_data:
                continue
            name = mp.get("name", {}).get("value", mp["embeddedId"])
            base = f"{API_URL}/v1/gateway-devices/{gateway['id']}/management-points/{mp['embeddedId']}/schedule/{mode}"
            print(f"\nSchedules on {name} (mode {mode}), re-sent unchanged:")

            current = {"scheduleId": mode_data["currentSchedule"]["value"], "enabled": mode_data["enabled"]["value"]}
            for with_type in (True, False):
                headers = dict(auth, **({"Content-Type": "application/json"} if with_type else {}))
                status, text = request("PUT", f"{base}/current", headers=headers,
                                       body=json.dumps(current).encode(), timeout=15)
                label = "with" if with_type else "without"
                result = "no response (timeout)" if status == 0 else f"HTTP {status} {text[:120].strip()}"
                print(f"  PUT schedule/{mode}/current {current} {label} Content-Type -> {result}", flush=True)
                time.sleep(3)

            schedules = {sid: {"actions": s.get("actions", {})} for sid, s in mode_data.get("schedules", {}).items()}
            headers = dict(auth, **{"Content-Type": "application/json"})
            status, text = request("PUT", f"{base}/schedules", headers=headers,
                                   body=json.dumps(schedules).encode(), timeout=15)
            result = "no response (timeout)" if status == 0 else f"HTTP {status} {text[:160].strip()}"
            print(f"  PUT schedule/{mode}/schedules (all {len(schedules)} unchanged) -> {result}", flush=True)
            return


if __name__ == "__main__":
    main()

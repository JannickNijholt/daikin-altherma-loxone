#!/usr/bin/env python3
"""Log in to the Daikin Onecta API once and test what a Loxone Virtual Output can send.

Usage: python3 tools/onecta_probe.py

Run it yourself: it asks for your Daikin developer app's client id and secret and
never prints tokens. It
  1. opens the Daikin login; after logging in, you paste the URL from the browser's
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


def request(method: str, url: str, *, headers: dict | None = None, body: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")


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


def find_setpoint(devices: list) -> tuple[str, str, str, float] | None:
    for gateway in devices:
        for mp in gateway.get("managementPoints", []):
            if mp.get("managementPointType") != "climateControl":
                continue
            name = mp.get("name", {}).get("value", mp["embeddedId"])
            modes = mp.get("temperatureControl", {}).get("value", {}).get("operationModes", {})
            mode = mp.get("operationMode", {}).get("value", "heating")
            setpoints = modes.get(mode, {}).get("setpoints", {})
            print(f"{name}: gateway {gateway['id']}, management point {mp['embeddedId']}, mode {mode}")
            for key, sp in setpoints.items():
                print(f"    {key} = {sp.get('value')} (min {sp.get('minValue')}, max {sp.get('maxValue')}, step {sp.get('stepValue')})")
            for key in ("roomTemperature", "leavingWaterOffset"):
                if key in setpoints:
                    return gateway["id"], mp["embeddedId"], f"/operationModes/{mode}/setpoints/{key}", setpoints[key]["value"]
    return None


def main() -> None:
    tokens = login()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    status, text = request("GET", f"{API_URL}/v1/gateway-devices", headers=auth)
    if status != 200:
        raise SystemExit(f"Reading devices failed: HTTP {status} {text[:300]}")
    DEVICES_FILE.write_text(text)
    devices = json.loads(text)
    print(f"Read {len(devices)} gateway device(s), {len(text)} bytes. Saved to {DEVICES_FILE.name}\n")

    target = find_setpoint(devices)
    if target is None:
        raise SystemExit("No climate-control setpoint found to test with.")
    gateway_id, mp_id, path, value = target
    url = f"{API_URL}/v1/gateway-devices/{gateway_id}/management-points/{mp_id}/characteristics/temperatureControl"
    body = json.dumps({"value": value, "path": path}).encode()
    print(f"\nRe-sending the current value {value} for {path} (no actual change):")

    tests = [
        ("PUT", True), ("POST", True), ("PUT", False), ("POST", False), ("PATCH", False), ("PATCH", True),
    ]
    for method, with_type in tests:
        headers = dict(auth)
        if with_type:
            headers["Content-Type"] = "application/json"
        status, text = request(method, url, headers=headers, body=body)
        label = "with" if with_type else "without"
        print(f"  {method:5} {label:7} Content-Type -> HTTP {status} {text[:120].strip()}")
        time.sleep(3)

    print("\nHTTP 204 = accepted. Send this whole output back.")


if __name__ == "__main__":
    main()

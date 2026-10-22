"""Daikin Onecta cloud API: OAuth2 login, token refresh and the few calls the bridge needs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode

import aiohttp

from .model import Command

_LOGGER = logging.getLogger(__name__)

AUTHORIZE_URL = "https://idp.onecta.daikineurope.com/v1/oidc/authorize"
TOKEN_URL = "https://idp.onecta.daikineurope.com/v1/oidc/token"
API_URL = "https://api.onecta.daikineurope.com"
SCOPE = "openid onecta:basic.integration offline_access"
REFRESH_MARGIN = 120  # refresh the access token this many seconds before it expires


class AuthError(Exception):
    """No valid login: the user has to log in (again) via the web UI."""


class RateLimited(Exception):
    def __init__(self, retry_after: int | None):
        super().__init__(f"Daikin rate limit reached, retry after {retry_after}s")
        self.retry_after = retry_after


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Daikin API returned HTTP {status}: {body[:200]}")
        self.status = status


def write_private_json(path: Path, data: dict) -> None:
    """Atomically write a JSON file readable only by the service user."""
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def extract_code(url: str, state: str) -> str | None:
    """Find code+state in a redirected URL, also when nested (my.home-assistant.io)."""
    for _ in range(4):
        url = unquote(url)
    code = re.search(r"[?&]code=([^&#\s]+)", url)
    found_state = re.search(r"[?&]state=([^&#\s]+)", url)
    if code and found_state and found_state.group(1) == state:
        return code.group(1)
    return None


@dataclass
class RateLimit:
    day: int | None = None
    minute: int | None = None
    retry_after: int | None = None

    @classmethod
    def from_headers(cls, headers: Any) -> RateLimit:
        def as_int(name: str) -> int | None:
            try:
                return int(headers.get(name))
            except (TypeError, ValueError):
                return None
        return cls(as_int("X-RateLimit-Remaining-day"), as_int("X-RateLimit-Remaining-minute"), as_int("Retry-After"))


class Onecta:
    """OAuth credentials, tokens and API calls. Settings and tokens live in data_dir."""

    def __init__(self, data_dir: Path, session: aiohttp.ClientSession):
        self.settings_file = data_dir / "settings.json"
        self.tokens_file = data_dir / "tokens.json"
        self.session = session
        self.settings = read_json(self.settings_file)
        self.tokens = read_json(self.tokens_file)
        self.rate_limit = RateLimit()
        self._pending_state: str | None = None
        self._refresh_lock = asyncio.Lock()

    # ---- configuration --------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("client_id") and self.settings.get("client_secret") and self.redirect_uri)

    @property
    def logged_in(self) -> bool:
        return bool(self.tokens.get("refresh_token"))

    @property
    def redirect_uri(self) -> str:
        return self.settings.get("redirect_uri", "")

    def save_settings(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        if client_secret == "" and self.settings.get("client_secret"):
            client_secret = self.settings["client_secret"]  # keep the stored secret
        self.settings = {"client_id": client_id.strip(), "client_secret": client_secret.strip(),
                         "redirect_uri": redirect_uri.strip()}
        write_private_json(self.settings_file, self.settings)

    def logout(self) -> None:
        self.tokens = {}
        write_private_json(self.tokens_file, self.tokens)

    # ---- login ----------------------------------------------------------------------

    def authorize_url(self) -> str:
        self._pending_state = secrets.token_urlsafe(16)
        return AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code",
            "client_id": self.settings["client_id"],
            "redirect_uri": self.redirect_uri,
            "scope": SCOPE,
            "state": self._pending_state,
        })

    async def finish_login(self, redirected_url: str) -> None:
        if not self._pending_state:
            raise AuthError("Start the login from this page first")
        code = extract_code(redirected_url, self._pending_state)
        if code is None:
            raise AuthError("No authorization code with the expected state in that URL; start the login again")
        self._pending_state = None
        await self._token_request({"grant_type": "authorization_code", "code": code,
                                   "redirect_uri": self.redirect_uri})
        _LOGGER.info("Logged in to Daikin Onecta")

    async def _token_request(self, form: dict) -> None:
        form = dict(form, client_id=self.settings.get("client_id", ""),
                    client_secret=self.settings.get("client_secret", ""))
        async with self.session.post(TOKEN_URL, data=form) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise AuthError(f"Daikin token endpoint returned HTTP {resp.status}: {text[:200]}")
        data = json.loads(text)
        self.tokens = {
            "access_token": data["access_token"],
            # Daikin rotates refresh tokens: the old one is invalid once a new one is issued.
            "refresh_token": data.get("refresh_token", self.tokens.get("refresh_token")),
            "expires_at": time.time() + int(data.get("expires_in", 3600)),
        }
        write_private_json(self.tokens_file, self.tokens)

    async def access_token(self) -> str:
        if not self.logged_in:
            raise AuthError("Not logged in")
        async with self._refresh_lock:
            if time.time() > self.tokens.get("expires_at", 0) - REFRESH_MARGIN:
                _LOGGER.debug("Refreshing Daikin access token")
                await self._token_request({"grant_type": "refresh_token",
                                           "refresh_token": self.tokens["refresh_token"]})
            return self.tokens["access_token"]

    # ---- API ------------------------------------------------------------------------

    async def _request(self, method: str, path: str, body: dict | None = None, retry: bool = True) -> str:
        headers = {"Authorization": f"Bearer {await self.access_token()}"}
        if body is not None:
            headers["Content-Type"] = "application/json"  # Daikin answers 422 without it
        async with self.session.request(method, API_URL + path, headers=headers,
                                        data=None if body is None else json.dumps(body)) as resp:
            self.rate_limit = RateLimit.from_headers(resp.headers)
            text = await resp.text()
            if resp.status == 401 and retry:
                self.tokens["expires_at"] = 0  # force a refresh, then try once more
                return await self._request(method, path, body, retry=False)
            if resp.status in (401, 403):
                raise AuthError(f"Daikin rejected the login (HTTP {resp.status})")
            if resp.status == 429:
                raise RateLimited(self.rate_limit.retry_after)
            if resp.status >= 400:
                raise ApiError(resp.status, text)
            return text

    async def gateway_devices(self) -> list[dict]:
        return json.loads(await self._request("GET", "/v1/gateway-devices"))

    async def patch(self, gateway_id: str, command: Command) -> None:
        body: dict[str, Any] = {"value": command.value}
        if command.path:
            body["path"] = command.path
        await self._request(
            "PATCH",
            f"/v1/gateway-devices/{gateway_id}/management-points/{command.management_point}"
            f"/characteristics/{command.characteristic}",
            body,
        )

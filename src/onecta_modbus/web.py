"""Small web UI: Daikin login, status, unit IDs and a live register view."""

from __future__ import annotations

import base64
import binascii
import hmac
import time
from datetime import datetime
from html import escape

from aiohttp import web

from . import __version__
from .bridge import Bridge
from .model import Device
from .onecta import AuthError
from .registers import HOLDING, REGISTERS, STATUS_OK, STATUS_TEXT, UNAVAILABLE, UNSUPPORTED

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#667085;--line:#e4e7ec;--accent:#0a7cc1;--ok:#12805c;--warn:#b54708;--bad:#c01048}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--text:#e6e9ef;--muted:#98a2b3;--line:#2a303c;--accent:#4fb3f0;--ok:#3ccb8f;--warn:#f79009;--bad:#f0547f}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
h1{font-size:22px;margin:0}h2{font-size:16px;margin:0 0 12px}a{color:var(--accent)}small,.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:16px;overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.stat b{display:block;font-size:20px}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;font-weight:600;border:1px solid currentColor}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
input[type=text],input[type=password],input[type=number]{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);width:100%}
input[type=number]{width:76px}label{display:block;margin:12px 0 4px;font-weight:600}
button,.button{font:inherit;font-weight:600;padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;text-decoration:none;display:inline-block}
button.secondary{background:transparent;color:var(--accent)}form.inline{display:inline}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;background:var(--bg);padding:1px 5px;border-radius:5px;word-break:break-all}
ul.log{list-style:none;padding:0;margin:0;font-size:13px}ul.log li{padding:4px 0;border-bottom:1px solid var(--line)}
"""


def page(title: str, body: str) -> web.Response:
    html = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{escape(title)}</title>"
            f"<style>{CSS}</style></head><body><main><header><h1>{escape(title)}</h1>"
            f"<small>Onecta → Modbus bridge {__version__} · <a href='/'>Status</a> · <a href='/setup'>Setup</a></small>"
            f"</header>{body}</main></body></html>")
    return web.Response(text=html, content_type="text/html")


def fmt_time(ts: float | None) -> str:
    if not ts:
        return "–"
    if ts == float("inf"):
        return "after login"
    return datetime.fromtimestamp(ts).strftime("%d-%m %H:%M:%S")


def fmt(value, suffix: str = "") -> str:
    return "–" if value is None else f"{value:g}{suffix}" if isinstance(value, (int, float)) else escape(str(value))


def default_redirect(request: web.Request) -> str:
    return f"{request.scheme}://{request.host}/auth/callback"


def is_loopback(url: str) -> bool:
    return any(host in url for host in ("//localhost", "//127.", "//[::1]"))


class WebUI:
    def __init__(self, bridge: Bridge, modbus_port: int, password: str = ""):
        self.bridge = bridge
        self.onecta = bridge.onecta
        self.modbus_port = modbus_port
        self.password = password

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.auth_middleware])
        app.add_routes([
            web.get("/", self.index),
            web.get("/setup", self.setup), web.post("/setup", self.save_setup),
            web.get("/login", self.login), web.get("/auth/callback", self.callback),
            web.post("/login/paste", self.paste), web.post("/logout", self.logout),
            web.post("/refresh", self.refresh), web.post("/units", self.save_units),
            web.get("/registers/{unit}", self.registers),
            web.get("/api/state", self.state), web.get("/healthz", self.health),
        ])
        return app

    @web.middleware
    async def auth_middleware(self, request: web.Request, handler):
        if self.password and request.path != "/healthz":
            header = request.headers.get("Authorization", "")
            try:
                supplied = base64.b64decode(header.removeprefix("Basic ")).decode().partition(":")[2]
            except (binascii.Error, UnicodeDecodeError):
                supplied = ""
            if not hmac.compare_digest(supplied, self.password):
                return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="onecta-modbus"'})
        return await handler(request)

    # ---- pages ----------------------------------------------------------------------

    async def index(self, request: web.Request) -> web.Response:
        b = self.bridge
        tone = "ok" if b.status == STATUS_OK else "warn" if b.status in (3, 5) else "bad"
        body = [f"<div class=card><div class=row style='margin:0'><span class='badge {tone}'>{escape(STATUS_TEXT[b.status])}</span>"]
        if b.last_error:
            body.append(f"<small>{escape(b.last_error)}</small>")
        body.append("</div>")

        if not self.onecta.configured:
            body.append("<p>First enter your Daikin developer app details.</p><a class=button href='/setup'>Set up</a>")
        elif not self.onecta.logged_in or b.status == 2:
            body.append(self.login_block())
        body.append("</div>")

        rl = self.onecta.rate_limit
        body.append(f"""<div class='card grid'>
          <div class=stat><small>Modbus TCP</small><b>{escape(request.host.split(':')[0])}:{self.modbus_port}</b></div>
          <div class=stat><small>Last poll</small><b>{fmt_time(b.last_poll)}</b></div>
          <div class=stat><small>Next poll</small><b>{fmt_time(b.next_poll_at if b.last_poll else None)}</b></div>
          <div class=stat><small>API calls left today</small><b>{fmt(rl.day)}</b></div></div>""")

        rows = []
        for gateway, unit in sorted(b.unit_by_gateway.items(), key=lambda item: item[1]):
            d = b.devices.get(gateway)
            if d is None:
                continue
            c = d.climate
            heat = Device.setpoint(c, "heating", "roomTemperature") or {}
            offset = Device.setpoint(c, "heating", "leavingWaterOffset") or {}
            rows.append(
                f"<tr><td><input type=number name='{escape(gateway)}' value='{unit}' min=1 max=247></td>"
                f"<td><b>{escape(d.name)}</b><br><small>{escape(d.model or d.data.get('deviceModel', ''))}</small></td>"
                f"<td>{'<span class=ok>online</span>' if d.online else '<span class=bad>offline</span>'}</td>"
                f"<td>{fmt(Device.value(c, 'onOffMode'))} · {fmt(Device.value(c, 'operationMode'))}</td>"
                f"<td>{fmt(Device.sensor(c, 'roomTemperature'), ' °C')}</td><td>{fmt(heat.get('value'), ' °C')}</td>"
                f"<td>{fmt(Device.sensor(c, 'leavingWaterTemperature'), ' °C')}</td><td>{fmt(offset.get('value'))}</td>"
                f"<td>{fmt(Device.sensor(c, 'outdoorTemperature'), ' °C')}</td>"
                f"<td>{fmt(Device.value(c, 'errorCode'))}</td><td><a href='/registers/{unit}'>registers</a></td></tr>")
        if rows:
            body.append(f"""<div class=card><h2>Devices</h2><form method=post action=/units>
              <table><tr><th>Unit ID</th><th>Name</th><th>Cloud</th><th>State</th><th>Room</th><th>Setpoint</th>
              <th>Leaving water</th><th>LWT offset</th><th>Outdoor</th><th>Error</th><th></th></tr>{''.join(rows)}</table>
              <div class=row><button class=secondary>Save unit IDs</button>
              <small>In Loxone: one Modbus server per unit, this IP, port {self.modbus_port}, unit ID as shown.</small></div>
              </form></div>""")
        if self.onecta.logged_in:
            body.append("<form method=post action=/refresh class=inline><button class=secondary>Refresh from Daikin now</button></form> ")

        events = "".join(f"<li><small>{fmt_time(ts)}</small> {escape(msg)}</li>" for ts, msg in b.events)
        body.append(f"<div class=card><h2>Activity</h2><ul class=log>{events or '<li class=muted>Nothing yet</li>'}</ul></div>")
        return page("Daikin Onecta bridge", "".join(body))

    def login_block(self) -> str:
        redirect = escape(self.onecta.redirect_uri)
        own_callback = self.onecta.redirect_uri.endswith("/auth/callback")
        paste = "" if own_callback else f"""
          <p>After logging in, Daikin sends you to <code>{redirect}</code>. Copy the full address from the
          browser's address bar and paste it here:</p>
          <form method=post action=/login/paste><input type=text name=url placeholder='https://…?code=…&state=…' required>
          <div class=row><button>Finish login</button></div></form>"""
        return f"""<p>Log in with the Daikin account that owns your units.</p>
          <a class=button href='/login' target='{'_self' if own_callback else '_blank'}'>Log in with Daikin</a>{paste}"""

    async def setup(self, request: web.Request) -> web.Response:
        s = self.onecta.settings
        suggested = default_redirect(request)
        redirect = s.get("redirect_uri") or suggested
        warn = ("<p class=bad>Daikin's firewall blocks <code>localhost</code>/<code>127.0.0.1</code> redirect URIs. "
                "Open this page via the bridge's LAN IP address instead.</p>") if is_loopback(redirect) else ""
        # A separate card: forms can't be nested, a logout button inside the settings form would submit it.
        logout = ("<div class=card><h2>3. Daikin account</h2><p>Logged in. To switch to another Daikin account, log out "
                  "and log in again (use a private browser window if Daikin remembers the old account).</p>"
                  "<form method=post action=/logout><button class=secondary>Log out of Daikin</button></form></div>"
                  if self.onecta.logged_in else "")
        return page("Setup", f"""<div class=card><h2>1. Daikin developer app</h2>
          <p>Create an app at <a href='https://developer.cloud.daikineurope.com' target=_blank>developer.cloud.daikineurope.com</a>
          (sign in with the same email and login method as the Onecta app). Set its redirect URI to:</p>
          <p><code>{escape(suggested)}</code></p>
          <p class=muted>An existing app with another redirect URI (e.g. Home Assistant's) also works: enter that URI below
          and paste the address after logging in.</p></div>
          <div class=card><h2>2. App details</h2>{warn}<form method=post action=/setup>
          <label>Client ID</label><input type=text name=client_id value='{escape(s.get('client_id', ''))}' required>
          <label>Client secret</label><input type=password name=client_secret
            placeholder='{'stored, leave empty to keep' if s.get('client_secret') else ''}' {'required' if not s.get('client_secret') else ''}>
          <label>Redirect URI (exactly as in the Daikin app)</label><input type=text name=redirect_uri value='{escape(redirect)}' required>
          <div class=row><button>Save</button></div></form></div>{logout}""")

    async def save_setup(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.onecta.save_settings(form.get("client_id", ""), form.get("client_secret", ""), form.get("redirect_uri", ""))
        self.bridge.log("Daikin app settings saved")
        raise web.HTTPSeeOther("/")

    async def login(self, request: web.Request) -> web.Response:
        if not self.onecta.configured:
            raise web.HTTPSeeOther("/setup")
        raise web.HTTPFound(self.onecta.authorize_url())

    async def _finish(self, url: str) -> web.Response:
        try:
            await self.onecta.finish_login(url)
        except AuthError as err:
            return page("Login failed", f"<div class=card><p class=bad>{escape(str(err))}</p><a href='/'>Back</a></div>")
        self.bridge.log("Logged in to Daikin")
        self.bridge.last_poll = None
        self.bridge.next_poll_at = 0
        self.bridge.wake()
        raise web.HTTPSeeOther("/")

    async def callback(self, request: web.Request) -> web.Response:
        return await self._finish(str(request.url))

    async def paste(self, request: web.Request) -> web.Response:
        return await self._finish((await request.post()).get("url", ""))

    async def logout(self, request: web.Request) -> web.Response:
        self.onecta.logout()
        self.bridge.reset()
        self.bridge.log("Logged out of Daikin; units and unit IDs cleared")
        self.bridge.wake()
        raise web.HTTPSeeOther("/")

    async def refresh(self, request: web.Request) -> web.Response:
        self.bridge.request_poll()
        self.bridge.log(f"Refresh requested; next poll {fmt_time(self.bridge.next_poll_at)} (at most once per minute)")
        raise web.HTTPSeeOther("/")

    async def save_units(self, request: web.Request) -> web.Response:
        form = await request.post()
        try:
            self.bridge.set_units({gateway: int(value) for gateway, value in form.items()
                                   if gateway in self.bridge.unit_by_gateway})
        except ValueError as err:
            return page("Invalid unit IDs", f"<div class=card><p class=bad>{escape(str(err))}</p><a href='/'>Back</a></div>")
        raise web.HTTPSeeOther("/")

    async def registers(self, request: web.Request) -> web.Response:
        unit = int(request.match_info["unit"])
        if unit not in self.bridge.gateway_by_unit:
            raise web.HTTPNotFound()
        ctx = self.bridge._context(unit)
        rows = []
        for reg in sorted(REGISTERS, key=lambda r: (r.table != HOLDING, r.offset)):
            word = reg.encode(ctx)
            value = ("unavailable" if word == UNAVAILABLE else "unsupported" if word == UNSUPPORTED
                     else f"{reg.decode(word):g} {reg.unit}" if not reg.unsigned else str(word))
            prefix = "HR" if reg.table == HOLDING else "IR"
            rows.append(f"<tr><td>{prefix}{reg.offset}</td><td>{reg.offset - 1}</td><td>{escape(reg.name)}</td>"
                        f"<td>{word}</td><td>{escape(value)}</td><td>{'yes' if reg.write else ''}</td></tr>")
        return page(f"Registers · unit {unit} · {ctx.device.name}", f"""<div class=card>
          <table><tr><th>Register</th><th>PDU address</th><th>Name</th><th>Raw</th><th>Value</th><th>Writable</th></tr>
          {''.join(rows)}</table></div>""")

    async def state(self, request: web.Request) -> web.Response:
        b = self.bridge
        return web.json_response({
            "status": b.status, "status_text": STATUS_TEXT[b.status], "error": b.last_error,
            "last_poll": b.last_poll, "next_poll": None if b.next_poll_at == float("inf") else b.next_poll_at,
            "calls_left_day": self.onecta.rate_limit.day,
            "devices": [{"unit": unit, "gateway_id": g, "name": b.device_name(g),
                         "online": b.devices[g].online if g in b.devices else None}
                        for g, unit in sorted(b.unit_by_gateway.items(), key=lambda i: i[1])],
            "events": [{"time": ts, "message": msg} for ts, msg in b.events],
        })

    async def health(self, request: web.Request) -> web.Response:
        age = None if self.bridge.last_poll is None else time.time() - self.bridge.last_poll
        healthy = self.bridge.status == STATUS_OK and age is not None and age < 3 * 3600
        return web.json_response({"healthy": healthy, "data_age": age}, status=200 if healthy else 503)

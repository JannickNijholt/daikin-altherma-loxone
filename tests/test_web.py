import asyncio
import re

from aiohttp.test_utils import TestClient, TestServer

from onecta_modbus.bridge import Bridge
from onecta_modbus.config import Config
from onecta_modbus.onecta import RateLimit
from onecta_modbus.web import WebUI


class FakeOnecta:
    def __init__(self):
        self.settings = {"client_id": "id", "client_secret": "secret", "redirect_uri": "http://192.0.2.5:8080/auth/callback"}
        self.redirect_uri = self.settings["redirect_uri"]
        self.configured = self.logged_in = True
        self.rate_limit = RateLimit()
        self.logged_out = False

    def logout(self):
        self.logged_out = True
        self.logged_in = False


def max_form_depth(html: str) -> int:
    depth = deepest = 0
    for tag in re.findall(r"</?form\b", html):
        depth += -1 if tag.startswith("</") else 1
        deepest = max(deepest, depth)
    return deepest


def test_setup_page_has_no_nested_forms_and_logout_works(tmp_path):
    async def test():
        onecta = FakeOnecta()
        bridge = Bridge(Config(data_dir=tmp_path), onecta)
        bridge.unit_by_gateway = {"old-gateway": 1}
        async with TestClient(TestServer(WebUI(bridge, 502).app())) as client:
            html = await (await client.get("/setup")).text()
            assert "Log out of Daikin" in html
            assert max_form_depth(html) == 1
            resp = await client.post("/logout", allow_redirects=False)
            assert resp.status == 303
        assert onecta.logged_out
        assert bridge.unit_by_gateway == {}
    asyncio.run(test())


def test_status_page_shows_budget(tmp_path):
    async def test():
        bridge = Bridge(Config(data_dir=tmp_path), FakeOnecta())
        async with TestClient(TestServer(WebUI(bridge, 502).app())) as client:
            resp = await client.get("/")
            html = await resp.text()
        assert resp.status == 200
        assert "Commands last hour" in html and "0 / 20" in html and "keeps 50 calls" in html
    asyncio.run(test())

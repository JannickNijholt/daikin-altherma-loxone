import asyncio

import pytest

from onecta_modbus.bridge import Bridge
from onecta_modbus.config import Config
from onecta_modbus.modbus import ModbusError
from onecta_modbus.onecta import RateLimit, RateLimited
from onecta_modbus.registers import STATUS_OK, STATUS_RATE_LIMITED


class FakeOnecta:
    def __init__(self, gateways):
        self.gateways = gateways
        self.patches = []
        self.polls = 0
        self.rate_limit = RateLimit(day=180, minute=19)
        self.configured = self.logged_in = True
        self.fail_with = None

    async def gateway_devices(self):
        self.polls += 1
        if self.fail_with:
            raise self.fail_with
        return self.gateways

    async def patch(self, gateway_id, command):
        self.patches.append((gateway_id, command))


def make_bridge(tmp_path, gateways):
    config = Config(data_dir=tmp_path, write_debounce=0.01, refresh_after_write=45)
    return Bridge(config, FakeOnecta(gateways))


def test_poll_assigns_stable_unit_ids(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        assert bridge.status == STATUS_OK
        names = {unit: bridge.device_name(g) for unit, g in bridge.gateway_by_unit.items()}
        assert names == {1: "Klimaatregeling beneden", 2: "Klimaatregeling boven"}
        reloaded = make_bridge(tmp_path, gateways)
        assert reloaded.unit_by_gateway == bridge.unit_by_gateway
    asyncio.run(test())


def test_modbus_read_uses_cached_state(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        assert bridge.read(1, "input", 49, 1) == [2030]      # IR50 beneden
        assert bridge.read(2, "holding", 0, 6)[3:6] == [1, 32767, 18]  # HR4 on, HR5 unsupported, HR6 18
        with pytest.raises(ModbusError):
            bridge.read(9, "input", 0, 1)
    asyncio.run(test())


def test_unit_known_before_first_poll_reports_status(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        fresh = make_bridge(tmp_path, gateways)          # restart: units known, no data yet
        assert fresh.read(1, "input", 49, 1) == [32766]  # unavailable
        assert fresh.read(1, "input", 100, 1) == [5]     # IR101 status: starting
    asyncio.run(test())


def test_write_patches_once_and_ignores_repeats(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        bridge.write(2, 100, [215])                      # HR101 boven = 21.5 °C
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
        command = bridge.onecta.patches[0][1]
        assert command.value == 21.5
        assert bridge.read(2, "holding", 100, 1) == [215]  # optimistic update
        bridge.write(2, 100, [215])                      # Loxone repeat: no new API call
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
    asyncio.run(test())


def test_write_debounces_slider_moves(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        for raw in (190, 195, 200, 205):
            bridge.write(2, 100, [raw])
        await asyncio.sleep(0.05)
        assert [c.value for _, c in bridge.onecta.patches] == [20.5]
    asyncio.run(test())


def test_write_equal_to_cloud_value_costs_nothing(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        bridge.write(2, 5, [18])                         # HR6 boven already 18
        bridge.write(2, 53, [5])                         # HR54 offset already 5
        await asyncio.sleep(0.05)
        assert bridge.onecta.patches == []
    asyncio.run(test())


def test_write_schedules_confirmation_poll(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        bridge.write(1, 3, [0])                          # HR4 beneden off
        await asyncio.sleep(0.05)
        assert bridge.onecta.patches[0][1].value == "off"
        assert bridge.next_poll_at - bridge.last_poll <= 60
    asyncio.run(test())


def test_refresh_register_requests_poll(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        bridge.last_poll -= 3600
        bridge.write(1, 103, [1])                        # HR104 refresh
        await asyncio.sleep(0.05)
        assert bridge.next_poll_at <= bridge.last_poll + 3600 + 1
        assert bridge.onecta.patches == []
    asyncio.run(test())


def test_rate_limit_backs_off(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        bridge.onecta.fail_with = RateLimited(retry_after=600)
        await bridge.poll()
        assert bridge.status == STATUS_RATE_LIMITED
        assert bridge.read  # still serving
    asyncio.run(test())


def test_reset_after_account_switch_restarts_unit_ids(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        bridge.onecta.gateways = [dict(gateways[0], id="old-account-gateway")]
        await bridge.poll()
        assert list(bridge.gateway_by_unit) == [1]
        bridge.reset()
        assert bridge.devices == {} and bridge.unit_by_gateway == {}
        bridge.onecta.gateways = gateways
        await bridge.poll()
        assert sorted(bridge.gateway_by_unit) == [1, 2]   # not 2 and 3
        assert make_bridge(tmp_path, gateways).unit_by_gateway == bridge.unit_by_gateway
    asyncio.run(test())


def test_set_units_validates(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        boven, beneden = bridge.gateway_by_unit[2], bridge.gateway_by_unit[1]
        with pytest.raises(ValueError):
            bridge.set_units({boven: 1, beneden: 1})
        bridge.set_units({boven: 1, beneden: 2})
        assert bridge.device_name(bridge.gateway_by_unit[1]) == "Klimaatregeling boven"
    asyncio.run(test())

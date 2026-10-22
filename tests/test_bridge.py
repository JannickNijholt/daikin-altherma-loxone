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


def make_bridge(tmp_path, gateways, **overrides):
    settings = dict(data_dir=tmp_path, write_debounce=0.01, refresh_after_write=45)
    settings.update(overrides)
    return Bridge(Config(**settings), FakeOnecta(gateways))


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
        bridge.write(2, 200, [215])                      # HR201 boven = 21.5 °C
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
        command = bridge.onecta.patches[0][1]
        assert command.value == 21.5
        assert bridge.read(2, "holding", 200, 1) == [215]  # optimistic update
        bridge.write(2, 200, [215])                      # Loxone repeat: no new API call
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
    asyncio.run(test())


def test_write_debounces_slider_moves(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways)
        await bridge.poll()
        for raw in (190, 195, 200, 205):
            bridge.write(2, 200, [raw])
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
        bridge.write(1, 203, [1])                        # HR204 refresh
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


# ---- API budget guard ------------------------------------------------------------------

@pytest.mark.parametrize("left,until_reset,expected", [
    (None, 36000, 600),     # no rate-limit info yet: normal day interval
    (200, 3600, 600),       # plenty left: never faster than the configured interval
    (60, 36000, 3600),      # 10 spare calls for 10 h: stretch, capped at the 60 min floor
    (110, 36000, 600),      # 60 spare calls for 10 h: exactly every 10 min
    (90, 36000, 900),       # 40 spare calls for 10 h: every 15 min
    (40, 36000, 3600),      # below the reserve: hourly only
])
def test_poll_interval_keeps_command_reserve(tmp_path, gateways, monkeypatch, left, until_reset, expected):
    monkeypatch.setattr("onecta_modbus.bridge.seconds_until_day_reset", lambda: until_reset)

    async def test():  # Python 3.9: asyncio primitives need a running loop
        bridge = make_bridge(tmp_path, gateways, poll_day_minutes=10, poll_night_minutes=10, command_reserve=50)
        bridge.onecta.rate_limit = RateLimit(day=left)
        assert bridge.poll_interval() == pytest.approx(expected)
    asyncio.run(test())


def test_seconds_until_day_reset_is_utc_midnight():
    from onecta_modbus.onecta import seconds_until_day_reset
    assert seconds_until_day_reset(5 * 86400 + 100) == 86300


def test_hourly_command_cap(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways, max_commands_per_hour=2)
        await bridge.poll()
        bridge.write(2, 200, [205])   # HR201
        bridge.write(2, 53, [3])      # HR54
        bridge.write(2, 3, [0])       # HR4
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 2
        assert bridge.commands_blocked == 1
        assert bridge.read(2, "input", 105, 2) == [2, 1]   # IR106 sent last hour, IR107 blocked
    asyncio.run(test())


def test_commands_stop_near_zero_budget_and_retry_later(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways, min_calls_left=5)
        await bridge.poll()
        bridge.onecta.rate_limit = RateLimit(day=5)
        bridge.write(2, 200, [205])
        await asyncio.sleep(0.05)
        assert bridge.onecta.patches == [] and bridge.commands_blocked == 1
        bridge.onecta.rate_limit = RateLimit(day=150)   # budget back (after reset)
        bridge.write(2, 200, [205])                     # same value again is retried
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
    asyncio.run(test())


def test_refresh_refused_when_budget_is_reserved(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways, command_reserve=50)
        await bridge.poll()
        bridge.last_poll -= 3600
        scheduled = bridge.next_poll_at
        bridge.onecta.rate_limit = RateLimit(day=30)
        bridge.write(1, 203, [1])                       # HR204 refresh
        await asyncio.sleep(0.05)
        assert bridge.next_poll_at == scheduled
    asyncio.run(test())


def test_no_confirmation_poll_by_default(tmp_path, gateways):
    async def test():
        bridge = make_bridge(tmp_path, gateways, refresh_after_write=0)
        await bridge.poll()
        scheduled = bridge.next_poll_at
        bridge.write(2, 200, [205])
        await asyncio.sleep(0.05)
        assert len(bridge.onecta.patches) == 1
        assert bridge.next_poll_at == scheduled
    asyncio.run(test())

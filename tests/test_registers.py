from datetime import datetime

import pytest

from onecta_modbus.model import Command, Device
from onecta_modbus.registers import (
    BY_ADDRESS, HOLDING, INPUT, REFRESH, REGISTERS, STATUS_RATE_LIMITED, UNAVAILABLE, Context,
)

NOW = datetime(2026, 10, 22, 12, 0)


def by_name(gateways, name):
    return Device(next(g for g in gateways if Device(g).name == name))


def word(device, table, offset, **ctx):
    return BY_ADDRESS[(table, offset)].encode(Context(device=device, now=NOW, **ctx))


def write(device, offset, raw):
    register = BY_ADDRESS[(HOLDING, offset)]
    return register.write(device, register.decode(raw))


def test_no_address_is_used_by_both_tables():
    holding = {r.offset for r in REGISTERS if r.table == HOLDING and r.extension}
    inputs = {r.offset for r in REGISTERS if r.table == INPUT and r.extension}
    assert not holding & inputs  # one Loxone sensor per address


def test_offsets_are_unique_and_homehub_compatible():
    homehub_holding = {1, 2, 3, 4, 6, 7, 9, 10, 12, 13, 53, 54, 55, 56, 57, 58, 59, 61, 63, 64, 65, 66, 67}
    homehub_input = {21, 22, 23, 30, 31, 32, 33, 35, 36, 37, 38, 40, 41, 42, 43, 44, 45, 49, 50, 51, 52, 53,
                     54, 55, 56, 57, 58, 59, 60, 61, 76, 77, 84, 85, 86, 87}
    for reg in REGISTERS:
        if not reg.extension:
            assert reg.offset in (homehub_holding if reg.table == HOLDING else homehub_input), reg


def test_reads_from_real_altherma_data(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    beneden = by_name(gateways, "Klimaatregeling beneden")
    assert word(boven, INPUT, 50) == 2610       # room 26.1 °C
    assert word(beneden, INPUT, 50) == 2030     # room 20.3 °C
    assert word(boven, INPUT, 40) == 1700       # leaving water 17 °C
    assert word(boven, INPUT, 44) == 1500       # outdoor 15 °C
    assert word(boven, HOLDING, 6) == 18        # room heating setpoint, whole degrees
    assert word(beneden, HOLDING, 201) == 200   # 20.0 °C x10
    assert word(boven, HOLDING, 54) == 5        # LWT offset
    assert word(boven, HOLDING, 4) == 1         # on
    assert word(boven, HOLDING, 3) == 1         # heating
    assert word(boven, HOLDING, 53) == 1        # weather dependent
    assert word(boven, INPUT, 84) == 1200       # room setpoint min 12 °C
    assert word(boven, INPUT, 85) == 3000       # room setpoint max 30 °C


def test_missing_and_unsupported_values(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    assert word(boven, HOLDING, 10) == UNAVAILABLE   # no DHW tank on these units
    assert word(boven, INPUT, 43) == UNAVAILABLE
    assert word(boven, HOLDING, 1) == UNAVAILABLE    # no fixed LWT setpoint in weather-dependent mode
    assert word(boven, INPUT, 21) == 0
    assert word(boven, INPUT, 22) == 0
    assert word(boven, INPUT, 23) == UNAVAILABLE


def test_error_code_text16(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    boven.climate["errorCode"]["value"] = "U4-01"
    boven.climate["isInErrorState"]["value"] = True
    assert word(boven, INPUT, 21) == 1
    assert word(boven, INPUT, 22) == ord("U") << 8 | ord("4")
    assert word(boven, INPUT, 23) == 1


def test_negative_values_are_twos_complement(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    boven.climate["sensoryData"]["value"]["outdoorTemperature"]["value"] = -3.5
    assert word(boven, INPUT, 44) == 0x10000 - 350


def test_energy_registers(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    series = boven.climate["consumptionData"]["value"]["electrical"]["heating"]
    months = series["m"]
    assert word(boven, INPUT, 112) == round(months[12 + NOW.month - 1] or 0)
    assert word(boven, INPUT, 113) == round(sum(v for v in months[12:] if v is not None))
    assert word(boven, INPUT, 110) == round(10 * sum(v for v in series["d"][12:] if v is not None))
    assert word(boven, INPUT, 114) == UNAVAILABLE  # no cooling consumption reported


def test_status_registers(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    assert word(boven, INPUT, 101, status=STATUS_RATE_LIMITED) == STATUS_RATE_LIMITED
    assert word(boven, INPUT, 103, data_age=42.4) == 42
    assert word(boven, INPUT, 104, calls_left_day=150) == 150
    assert word(boven, INPUT, 104) == UNAVAILABLE


def test_setpoint_writes(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    path = "/operationModes/heating/setpoints/roomTemperature"
    assert write(boven, 201, 205) == Command("climateControlMainZone", "temperatureControl", 20.5, path)
    assert write(boven, 6, 21) == Command("climateControlMainZone", "temperatureControl", 21, path)
    assert write(boven, 201, 207).value == 20.5          # rounded to the 0.5 step
    assert write(boven, 201, 400).value == 30            # clamped to the max
    offset = write(boven, 54, 0x10000 - 2)               # -2 as a signed word
    assert offset.value == -2 and offset.path.endswith("leavingWaterOffset")
    assert write(boven, 10, 50) is None                  # no DHW tank


def test_mode_and_switch_writes(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    assert write(boven, 4, 0) == Command("climateControlMainZone", "onOffMode", "off")
    assert write(boven, 4, 7) is None
    assert write(boven, 3, 1) is None                    # heating-only units: operationMode is read-only
    boven.climate["operationMode"].update(settable=True, values=["heating", "cooling", "auto"])
    assert write(boven, 3, 2) == Command("climateControlMainZone", "operationMode", "cooling")
    assert write(boven, 3, 9) is None
    assert write(boven, 204, 1) == REFRESH
    assert BY_ADDRESS[(HOLDING, 53)].write is None


def test_apply_and_current_value(gateways):
    boven = by_name(gateways, "Klimaatregeling boven")
    command = write(boven, 201, 215)
    assert boven.current_value(command) == 18
    boven.apply(command)
    assert boven.current_value(command) == 21.5
    assert word(boven, HOLDING, 201) == 215
    boven.apply(Command("climateControlMainZone", "onOffMode", "off"))
    assert word(boven, HOLDING, 4) == 0


@pytest.mark.parametrize("value,expected", [(20.5, 21), (20.4, 20), (19.5, 20)])
def test_whole_degree_rounding(gateways, value, expected):
    boven = by_name(gateways, "Klimaatregeling boven")
    boven.climate["temperatureControl"]["value"]["operationModes"]["heating"]["setpoints"]["roomTemperature"]["value"] = value
    assert word(boven, HOLDING, 6) == expected

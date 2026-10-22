"""Modbus register map: Daikin HomeHub (EKRHH) use case 3 layout plus bridge extensions.

Offsets are 1-based as in the Daikin EKRHH installer reference guide (PDU address =
offset - 1). Registers 1-99 follow the HomeHub map, so Loxone templates written for a
HomeHub work unchanged. Offsets 101+ are extensions for what Onecta offers beyond it.

Reads return 32767 for registers this bridge doesn't support and 32766 for supported
registers without data (same convention as the HomeHub).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Union

from .model import Command, Device, characteristic_command, energy, round_half_up, setpoint_command

UNSUPPORTED = 32767
UNAVAILABLE = 32766

INPUT = "input"
HOLDING = "holding"

REFRESH = "refresh"  # write action: poll the cloud now

# Bridge status (IR101)
STATUS_OK = 0
STATUS_NOT_LOGGED_IN = 1
STATUS_AUTH_FAILED = 2
STATUS_RATE_LIMITED = 3
STATUS_CLOUD_ERROR = 4
STATUS_STARTING = 5
STATUS_TEXT = {
    STATUS_OK: "OK",
    STATUS_NOT_LOGGED_IN: "Not logged in",
    STATUS_AUTH_FAILED: "Login expired, log in again",
    STATUS_RATE_LIMITED: "Daikin rate limit reached",
    STATUS_CLOUD_ERROR: "Daikin cloud error",
    STATUS_STARTING: "Starting",
}


@dataclass
class Context:
    """Everything a register can read: the device plus bridge-level state."""

    device: Device
    now: datetime
    status: int = STATUS_OK
    data_age: float | None = None
    calls_left_day: int | None = None
    calls_left_minute: int | None = None


Reader = Callable[[Context], Union[float, int, None]]
Writer = Callable[[Device, float], Union[Command, str, None]]


@dataclass(frozen=True)
class Register:
    table: str
    offset: int
    name: str
    read: Reader
    write: Writer | None = None
    scale: int = 1  # raw = value * scale
    unit: str = ""
    hint: str = ""
    unsigned: bool = False
    poll: int = 30  # suggested Loxone polling cycle in seconds
    readback: bool = True  # offer a (state) sensor for this holding register in the template
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def extension(self) -> bool:
        return self.offset > 100

    def encode(self, ctx: Context) -> int:
        value = self.read(ctx)
        if value is None:
            return UNAVAILABLE
        raw = int(value) if self.unsigned else round(value * self.scale)
        if self.unsigned:
            return max(0, min(raw, 0xFFFF))
        return max(-32768, min(raw, 32767)) & 0xFFFF

    def decode(self, word: int) -> float:
        signed = word - 0x10000 if word >= 0x8000 and not self.unsigned else word
        return signed / self.scale


# ---- readers -------------------------------------------------------------------------

def _climate(ctx: Context) -> dict | None:
    return ctx.device.climate


def _setpoint_value(mp_of: Callable[[Device], dict | None], mode: str, key: str, whole: bool = False) -> Reader:
    def read(ctx: Context) -> float | None:
        sp = Device.setpoint(mp_of(ctx.device), mode, key)
        if sp is None or sp.get("value") is None:
            return None
        return round_half_up(sp["value"]) if whole else sp["value"]
    return read


def _setpoint_limit(mode: str, key: str, bound: str) -> Reader:
    def read(ctx: Context) -> float | None:
        sp = Device.setpoint(_climate(ctx), mode, key)
        return None if sp is None else sp.get(bound)
    return read


def _sensor(mp_of: Callable[[Device], dict | None], key: str) -> Reader:
    return lambda ctx: Device.sensor(mp_of(ctx.device), key)


def _on_off(mp_of: Callable[[Device], dict | None], characteristic: str = "onOffMode") -> Reader:
    def read(ctx: Context) -> int | None:
        value = Device.value(mp_of(ctx.device), characteristic)
        return None if value is None else int(value == "on")
    return read


MODE_TO_INT = {"auto": 0, "heating": 1, "cooling": 2}
INT_TO_MODE = {v: k for k, v in MODE_TO_INT.items()}


def _operation_mode(ctx: Context) -> int | None:
    value = Device.value(_climate(ctx), "operationMode")
    return MODE_TO_INT.get(value) if value is not None else None


def _actual_operation(ctx: Context) -> int | None:
    value = Device.value(_climate(ctx), "operationMode")
    return {"heating": 1, "cooling": 2}.get(value) if value is not None else None


def _weather_dependent(ctx: Context) -> int | None:
    mode = Device.value(_climate(ctx), "setpointMode")
    if mode is None:
        return None
    return 0 if mode == "fixed" else 1


def _abnormality(ctx: Context) -> int:
    points = [mp for mp in (ctx.device.climate, ctx.device.dhw) if mp is not None]
    if any(Device.value(mp, "isInErrorState") for mp in points):
        return 1
    if any(Device.value(mp, "isInWarningState") or Device.value(mp, "isInCautionState") for mp in points):
        return 2
    return 0


def _error_parts(ctx: Context) -> tuple[str, int | None] | None:
    code = (Device.value(_climate(ctx), "errorCode") or "").strip()
    if code.replace("-", "").replace("0", "") == "":
        return None
    main, _, sub = code.partition("-")
    return main[:2].ljust(2), int(sub) if sub.isdigit() else None


def _error_code(ctx: Context) -> int:
    parts = _error_parts(ctx)
    if parts is None:
        return 0
    text = parts[0].encode("ascii", "replace")
    return text[0] << 8 | text[1]


def _error_sub(ctx: Context) -> int:
    parts = _error_parts(ctx)
    if parts is None or parts[1] is None:
        return UNAVAILABLE
    return parts[1]


def _energy(mp_of: Callable[[Device], dict | None], purpose: str, period: str) -> Reader:
    return lambda ctx: energy(mp_of(ctx.device), purpose, period, ctx.now)


def _const(value: float | None) -> Reader:
    return lambda ctx: value


# ---- writers -------------------------------------------------------------------------

def _climate_mp(device: Device) -> dict | None:
    return device.climate


def _dhw_mp(device: Device) -> dict | None:
    return device.dhw


def _write_setpoint(mp_of: Callable[[Device], dict | None], mode: str, key: str) -> Writer:
    return lambda device, value: setpoint_command(mp_of(device), mode, key, value)


def _write_on_off(mp_of: Callable[[Device], dict | None], characteristic: str = "onOffMode") -> Writer:
    def write(device: Device, value: float) -> Command | None:
        if value not in (0, 1):
            return None
        return characteristic_command(mp_of(device), characteristic, "on" if value else "off")
    return write


def _write_operation_mode(device: Device, value: float) -> Command | None:
    mode = INT_TO_MODE.get(int(value))
    return characteristic_command(device.climate, "operationMode", mode) if mode else None


def _write_refresh(device: Device, value: float) -> str | None:
    return REFRESH if value else None


# ---- the map -------------------------------------------------------------------------

ON_OFF = "0: OFF\n1: ON"
WD_MODES = "0: Fixed\n1: Weather dependent\n(read-only on this bridge)"

REGISTERS: list[Register] = [
    # HomeHub holding registers (read/write)
    Register(HOLDING, 1, "LWT Main heating setpoint", _setpoint_value(_climate_mp, "heating", "leavingWaterTemperature", True),
             _write_setpoint(_climate_mp, "heating", "leavingWaterTemperature"), unit="°C",
             hint="Only in fixed LWT mode; whole degrees", tags=("lwt",)),
    Register(HOLDING, 2, "LWT Main cooling setpoint", _setpoint_value(_climate_mp, "cooling", "leavingWaterTemperature", True),
             _write_setpoint(_climate_mp, "cooling", "leavingWaterTemperature"), unit="°C",
             hint="Only in fixed LWT mode; whole degrees", tags=("lwt", "cooling")),
    Register(HOLDING, 3, "Operation mode", _operation_mode, _write_operation_mode,
             hint="0: Auto\n1: Heating\n2: Cooling (only modes the unit supports)", tags=("main",)),
    Register(HOLDING, 4, "Space heating/cooling ON/OFF", _on_off(_climate_mp), _write_on_off(_climate_mp),
             hint=ON_OFF, tags=("main",)),
    Register(HOLDING, 6, "Room heating setpoint Main", _setpoint_value(_climate_mp, "heating", "roomTemperature", True),
             _write_setpoint(_climate_mp, "heating", "roomTemperature"), unit="°C",
             hint="Whole degrees (HomeHub format). Use HR101 for 0.5 °C steps", tags=("main",)),
    Register(HOLDING, 7, "Room cooling setpoint Main", _setpoint_value(_climate_mp, "cooling", "roomTemperature", True),
             _write_setpoint(_climate_mp, "cooling", "roomTemperature"), unit="°C",
             hint="Whole degrees (HomeHub format). Use HR102 for 0.5 °C steps", tags=("cooling",)),
    Register(HOLDING, 10, "DHW reheat setpoint", _setpoint_value(_dhw_mp, "heating", "domesticHotWaterTemperature", True),
             _write_setpoint(_dhw_mp, "heating", "domesticHotWaterTemperature"), unit="°C",
             hint="Units with a DHW tank only", tags=("dhw",)),
    Register(HOLDING, 12, "DHW ON/OFF", _on_off(_dhw_mp), _write_on_off(_dhw_mp), hint=ON_OFF, tags=("dhw",)),
    Register(HOLDING, 13, "DHW booster (powerful) ON/OFF", _on_off(_dhw_mp, "powerfulMode"),
             _write_on_off(_dhw_mp, "powerfulMode"), hint=ON_OFF, tags=("dhw",)),
    Register(HOLDING, 53, "Weather dependent mode Main", _weather_dependent, None, hint=WD_MODES, poll=300,
             tags=("main",)),
    Register(HOLDING, 54, "WD LWT Main heating offset", _setpoint_value(_climate_mp, "heating", "leavingWaterOffset"),
             _write_setpoint(_climate_mp, "heating", "leavingWaterOffset"), unit="°C", hint="-10..10 °C",
             tags=("main",)),
    Register(HOLDING, 55, "WD LWT Main cooling offset", _setpoint_value(_climate_mp, "cooling", "leavingWaterOffset"),
             _write_setpoint(_climate_mp, "cooling", "leavingWaterOffset"), unit="°C", hint="-10..10 °C",
             tags=("cooling",)),

    # HomeHub input registers (read-only)
    Register(INPUT, 21, "Unit abnormality", _abnormality, hint="0: No error\n1: Fault\n2: Warning", tags=("main",)),
    Register(INPUT, 22, "Unit abnormality code (raw)", _error_code, unsigned=True,
             hint="2 ASCII chars: INT(v/256), MOD(v;256). 0 = no error", tags=("main",)),
    Register(INPUT, 23, "Unit abnormality sub code", _error_sub, hint="32766 if none", tags=("main",)),
    Register(INPUT, 38, "Operation mode", _actual_operation, hint="1: Heating\n2: Cooling", tags=("main",)),
    Register(INPUT, 40, "Leaving water temperature", _sensor(_climate_mp, "leavingWaterTemperature"), scale=100,
             unit="°C", tags=("main",)),
    Register(INPUT, 43, "DHW temperature", _sensor(_dhw_mp, "tankTemperature"), scale=100, unit="°C", tags=("dhw",)),
    Register(INPUT, 44, "Outside air temperature", _sensor(_climate_mp, "outdoorTemperature"), scale=100, unit="°C",
             tags=("main",)),
    Register(INPUT, 50, "Room temperature Main", _sensor(_climate_mp, "roomTemperature"), scale=100, unit="°C",
             tags=("main",)),
    Register(INPUT, 54, "LWT Main heating setpoint lower limit", _setpoint_limit("heating", "leavingWaterTemperature", "minValue"),
             scale=100, unit="°C", poll=300, tags=("lwt",)),
    Register(INPUT, 55, "LWT Main heating setpoint upper limit", _setpoint_limit("heating", "leavingWaterTemperature", "maxValue"),
             scale=100, unit="°C", poll=300, tags=("lwt",)),
    Register(INPUT, 84, "Room heating setpoint lower limit", _setpoint_limit("heating", "roomTemperature", "minValue"),
             scale=100, unit="°C", poll=300, tags=("main",)),
    Register(INPUT, 85, "Room heating setpoint upper limit", _setpoint_limit("heating", "roomTemperature", "maxValue"),
             scale=100, unit="°C", poll=300, tags=("main",)),
    Register(INPUT, 86, "Room cooling setpoint lower limit", _setpoint_limit("cooling", "roomTemperature", "minValue"),
             scale=100, unit="°C", poll=300, tags=("cooling",)),
    Register(INPUT, 87, "Room cooling setpoint upper limit", _setpoint_limit("cooling", "roomTemperature", "maxValue"),
             scale=100, unit="°C", poll=300, tags=("cooling",)),

    # Extensions: holding
    Register(HOLDING, 101, "Room heating setpoint (0.5 °C steps)", _setpoint_value(_climate_mp, "heating", "roomTemperature"),
             _write_setpoint(_climate_mp, "heating", "roomTemperature"), scale=10, unit="°C",
             hint="Raw value x10; rounded to the unit's 0.5 °C step", tags=("main",)),
    Register(HOLDING, 102, "Room cooling setpoint (0.5 °C steps)", _setpoint_value(_climate_mp, "cooling", "roomTemperature"),
             _write_setpoint(_climate_mp, "cooling", "roomTemperature"), scale=10, unit="°C",
             hint="Raw value x10; rounded to the unit's 0.5 °C step", tags=("cooling",)),
    Register(HOLDING, 103, "Room auto setpoint (0.5 °C steps)", _setpoint_value(_climate_mp, "auto", "roomTemperature"),
             _write_setpoint(_climate_mp, "auto", "roomTemperature"), scale=10, unit="°C",
             hint="Raw value x10; used in operation mode Auto", tags=("cooling",)),
    Register(HOLDING, 104, "Refresh from cloud now", _const(0), _write_refresh,
             hint="Write 1 to poll Daikin now (costs one API call, max once per minute)", readback=False,
             tags=("main",)),

    # Extensions: input
    Register(INPUT, 101, "Bridge status", lambda ctx: ctx.status, poll=60,
             hint="0 OK, 1 not logged in, 2 login expired, 3 rate limited, 4 cloud error, 5 starting", tags=("main",)),
    Register(INPUT, 102, "Unit online in Daikin cloud", lambda ctx: int(ctx.device.online), hint="0/1", poll=60,
             tags=("main",)),
    Register(INPUT, 103, "Data age", lambda ctx: None if ctx.data_age is None else min(ctx.data_age, 32000),
             unit="s", hint="Seconds since the last successful cloud poll", poll=60, tags=("main",)),
    Register(INPUT, 104, "Daikin API calls left today", lambda ctx: ctx.calls_left_day, poll=300, tags=("main",)),
    Register(INPUT, 105, "Daikin API calls left this minute", lambda ctx: ctx.calls_left_minute, poll=300,
             tags=("diagnostic",)),
    Register(INPUT, 110, "Heating energy today", _energy(_climate_mp, "heating", "today"), scale=10, unit="kWh",
             poll=300, tags=("main",)),
    Register(INPUT, 111, "Heating energy yesterday", _energy(_climate_mp, "heating", "yesterday"), scale=10,
             unit="kWh", poll=300, tags=("main",)),
    Register(INPUT, 112, "Heating energy this month", _energy(_climate_mp, "heating", "month"), unit="kWh", poll=300,
             tags=("main",)),
    Register(INPUT, 113, "Heating energy this year", _energy(_climate_mp, "heating", "year"), unit="kWh", poll=300,
             tags=("main",)),
    Register(INPUT, 114, "Cooling energy today", _energy(_climate_mp, "cooling", "today"), scale=10, unit="kWh",
             poll=300, tags=("cooling",)),
    Register(INPUT, 115, "Cooling energy yesterday", _energy(_climate_mp, "cooling", "yesterday"), scale=10,
             unit="kWh", poll=300, tags=("cooling",)),
    Register(INPUT, 116, "Cooling energy this month", _energy(_climate_mp, "cooling", "month"), unit="kWh", poll=300,
             tags=("cooling",)),
    Register(INPUT, 117, "Cooling energy this year", _energy(_climate_mp, "cooling", "year"), unit="kWh", poll=300,
             tags=("cooling",)),
    Register(INPUT, 118, "DHW energy today", _energy(_dhw_mp, "heating", "today"), scale=10, unit="kWh", poll=300,
             tags=("dhw",)),
    Register(INPUT, 119, "DHW energy this month", _energy(_dhw_mp, "heating", "month"), unit="kWh", poll=300,
             tags=("dhw",)),
]

BY_ADDRESS: dict[tuple[str, int], Register] = {(r.table, r.offset): r for r in REGISTERS}
assert len(BY_ADDRESS) == len(REGISTERS), "duplicate register offsets"

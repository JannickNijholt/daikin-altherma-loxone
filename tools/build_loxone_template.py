#!/usr/bin/env python3
"""Build the Loxone Modbus TCP template for a Daikin HomeHub (EKRHH), use case 3.

Usage: python3 tools/build_loxone_template.py [--check]

The register definitions below are the single source of truth; the XML in
loxone/templates/ is generated from them. Register offsets are 1-based as in the
Daikin EKRHH installer reference guide (4P744838-1E, chapter 9); Loxone expects the
0-based PDU address, so ModbusAddress = offset - 1.

--check validates the definitions and verifies the committed XML is up to date.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

OUTPUT = Path(__file__).resolve().parent.parent / "loxone" / "templates" / "MB_Daikin_HomeHub_EKRHH.xml"

TEMPLATE_TITLE = "Daikin HomeHub EKRHH (Altherma, Modbus TCP)"
TEMPLATE_HINT = (
    "Daikin HomeHub EKRHH, use case 3 (Modbus for Daikin Altherma). "
    "Modbus TCP port 502. Set the unit ID (Channel) to the value configured in the ONECTA app. "
    "Raw values 32765/32766/32767 mean: waiting for value / unavailable / unsupported."
)
MIN_LOXONE_VERSION = "15000227"  # Loxone Config 15, same as the Loxone Library Daikin template
UNIT_ID = 1

# Loxone ModbusCmd function codes
READ_HOLDING = 3
READ_INPUT = 4
WRITE_SINGLE = 6

# Loxone ModbusDataType codes
UINT16 = 32
INT16 = 33

SPECIAL_VALUES = "Raw 32765 = waiting, 32766 = unavailable, 32767 = unsupported."


@dataclass(frozen=True)
class Kind:
    """How a Daikin data type maps onto a Loxone Modbus object."""

    data_type: int
    scale: int  # raw value = engineering value * scale
    unit: str


TEMP16 = Kind(INT16, 100, "<v.1>°C")
POW16 = Kind(INT16, 100, "<v.2> kW")
FLOW = Kind(INT16, 100, "<v.1> l/min")
DEGREES = Kind(INT16, 1, "<v>°C")  # holding-register setpoints are whole °C (Int16)
ENUM = Kind(INT16, 1, "<v>")
RAW = Kind(UINT16, 1, "<v>")


@dataclass(frozen=True)
class Register:
    offset: int
    name: str
    kind: Kind
    hint: str = ""


# Input registers (read-only, FC 4)
INPUT_REGISTERS = [
    Register(21, "Unit abnormality", ENUM, "0: No error\n1: Fault\n2: Warning"),
    Register(22, "Unit abnormality code (raw)", RAW,
             "Text16: 2 ASCII chars. High byte = INT(v/256), low byte = MOD(v;256). Example 21816 = 'U8'."),
    Register(23, "Unit abnormality sub code", RAW, "32766 if no error, else 0..99"),
    Register(30, "Circulation pump running", ENUM, "0: OFF\n1: ON"),
    Register(31, "Compressor running", ENUM, "0: OFF\n1: ON"),
    Register(32, "Booster heater running", ENUM, "0: OFF\n1: ON"),
    Register(33, "Disinfection operation", ENUM, "0: OFF\n1: ON"),
    Register(35, "Defrost", ENUM, "0: OFF\n1: ON"),
    Register(36, "Hot start", ENUM, "0: OFF\n1: ON"),
    Register(37, "3-way valve", ENUM, "0: Space heating\n1: DHW"),
    Register(38, "Operation mode", ENUM, "1: Heating\n2: Cooling"),
    Register(40, "Leaving water temperature PHE", TEMP16, "-100.00..100.00°C"),
    Register(41, "Leaving water temperature BUH", TEMP16, "-100.00..100.00°C"),
    Register(42, "Return water temperature", TEMP16, "-100.00..100.00°C"),
    Register(43, "DHW temperature", TEMP16, "-100.00..100.00°C"),
    Register(44, "Outside air temperature", TEMP16, "-100.00..100.00°C"),
    Register(45, "Liquid refrigerant temperature", TEMP16, "-100.00..100.00°C"),
    Register(49, "Flow rate", FLOW, "Litres/minute"),
    Register(50, "Room temperature Main (remote controller)", TEMP16, "-100.00..100.00°C"),
    Register(51, "Heat pump power consumption", POW16, "0..20 kW"),
    Register(52, "DHW normal operation", ENUM, "0: Idle/buffering\n1: Operating"),
    Register(53, "Space heating/cooling normal operation", ENUM, "0: Idle/buffering\n1: Operating"),
    Register(54, "LWT Main heating setpoint lower limit", TEMP16, "Field setting range"),
    Register(55, "LWT Main heating setpoint upper limit", TEMP16, "Field setting range"),
    Register(56, "LWT Main cooling setpoint lower limit", TEMP16, "Field setting range"),
    Register(57, "LWT Main cooling setpoint upper limit", TEMP16, "Field setting range"),
    Register(58, "LWT Add heating setpoint lower limit", TEMP16, "Field setting range"),
    Register(59, "LWT Add heating setpoint upper limit", TEMP16, "Field setting range"),
    Register(60, "LWT Add cooling setpoint lower limit", TEMP16, "Field setting range"),
    Register(61, "LWT Add cooling setpoint upper limit", TEMP16, "Field setting range"),
    Register(76, "DHW upper temperature", TEMP16, "-127.00..127.00°C"),
    Register(77, "DHW lower temperature", TEMP16, "-127.00..127.00°C"),
    Register(84, "Room heating setpoint lower limit", TEMP16, "Field setting range"),
    Register(85, "Room heating setpoint upper limit", TEMP16, "Field setting range"),
    Register(86, "Room cooling setpoint lower limit", TEMP16, "Field setting range"),
    Register(87, "Room cooling setpoint upper limit", TEMP16, "Field setting range"),
]

THERMOSTAT_NOTE = (
    "Not operational on Altherma 3 R / 3 M with Micon ID 20002203. "
    "Only valid with [C-07]=1 and external thermostat type [C-05]=0."
)

# Holding registers (read/write, FC 3 / FC 6)
HOLDING_REGISTERS = [
    Register(1, "LWT Main heating setpoint", DEGREES, "Depending on field settings (clamped to min/max)"),
    Register(2, "LWT Main cooling setpoint", DEGREES, "Depending on field settings (clamped to min/max)"),
    Register(3, "Operation mode", ENUM, "0: Auto\n1: Heating\n2: Cooling\n(32766 on heating-only units)"),
    Register(4, "Space heating/cooling ON/OFF", ENUM, "0: OFF\n1: ON"),
    Register(6, "Room heating setpoint Main", DEGREES, "12..30°C, whole degrees"),
    Register(7, "Room cooling setpoint Main", DEGREES, "15..35°C, whole degrees"),
    Register(9, "Quiet mode", ENUM, "0: OFF\n1: ON"),
    Register(10, "DHW reheat setpoint", DEGREES,
             "30..60°C. Only applied with tank enabled, heat pump mode 'Reheat only' and setpoint mode 'Fixed'"),
    Register(12, "DHW reheat ON/OFF", ENUM, "0: OFF\n1: ON"),
    Register(13, "DHW booster (powerful) ON/OFF", ENUM, "0: OFF\n1: ON"),
    Register(53, "Weather dependent mode Main", ENUM,
             "0: Fixed\n1: Weather dependent\n2: Fixed + scheduled\n3: Weather dependent + scheduled"),
    Register(54, "WD LWT Main heating offset", DEGREES, "-10..10°C"),
    Register(55, "WD LWT Main cooling offset", DEGREES, "-10..10°C"),
    Register(56, "Smart Grid operation mode", ENUM,
             "0: Free running\n1: Forced off\n2: Recommended on\n3: Forced on"),
    Register(57, "Power limit recommended on / buffering", POW16,
             "0..20 kW. Temporarily max(4.5 kW, value) for 15 min after compressor start"),
    Register(58, "General power limit", POW16,
             "0..20 kW. Temporarily max(4.5 kW, value) for 15 min after compressor start"),
    Register(59, "Thermostat Main input A", ENUM, "0: OFF\n1: ON\n" + THERMOSTAT_NOTE),
    Register(61, "Thermostat Add input A", ENUM, "0: OFF\n1: ON\n" + THERMOSTAT_NOTE),
    Register(63, "LWT Add heating setpoint", DEGREES, "Depending on field settings (clamped to min/max)"),
    Register(64, "LWT Add cooling setpoint", DEGREES, "Depending on field settings (clamped to min/max)"),
    Register(65, "Weather dependent mode Add", ENUM,
             "0: Fixed\n1: Weather dependent\n2: Fixed + scheduled\n3: Weather dependent + scheduled"),
    Register(66, "WD LWT Add heating offset", DEGREES, "-10..10°C"),
    Register(67, "WD LWT Add cooling offset", DEGREES, "-10..10°C"),
]

# Polling cycles in seconds
FAST_POLL = 15
STATE_POLL = 60
LIMIT_POLL = 300
# Re-send interval for actuators; HomeHub writes are change based, so Daikin
# recommends periodically refreshing the desired state from the client side.
REPEAT_RATE = 60

LIMIT_OFFSETS = {54, 55, 56, 57, 58, 59, 60, 61, 84, 85, 86, 87}


def attrs(**values: object) -> str:
    return " ".join(f"{key}={quoteattr(str(value), {chr(10): '&#10;'})}" for key, value in values.items() if value is not None)


def scaling(kind: Kind, sensor: bool) -> dict[str, int]:
    # Sensors map raw (Source) -> Loxone value (Dest); actuators map Loxone value
    # (Source) -> raw (Dest). 100 -> 100 is the identity used by Loxone exports.
    if kind.scale == 1:
        return {"SourceValHigh": 100, "DestValHigh": 100}
    if sensor:
        return {"SourceValHigh": kind.scale, "DestValHigh": 1}
    return {"SourceValHigh": 1, "DestValHigh": kind.scale}


def command(prefix: str, register: Register, cmd: int, *, sensor: bool, suffix: str = "", poll: int | None = None) -> str:
    hint = register.hint
    if sensor and register.kind is not RAW:
        hint = f"{hint}\n{SPECIAL_VALUES}" if hint else SPECIAL_VALUES
    address = register.offset - 1
    return "\t<ModbusCmd " + attrs(
        Title=f"{prefix}{register.offset:02d} {register.name}{suffix}",
        Comment=f"Daikin EKRHH register offset {register.offset}",
        HintText=hint,
        ModbusAddress=address if address else None,
        ModbusCmd=cmd,
        ModbusDataType=register.kind.data_type,
        ModbusPollingCycle=poll,
        Unit=register.kind.unit,
        Analog="true",
        Sensor="true" if sensor else "false",
        **scaling(register.kind, sensor),
        RepeatRate=None if sensor else REPEAT_RATE,
    ) + "/>"


def build() -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f"<Modbus {attrs(Title=TEMPLATE_TITLE, Comment='', HintText=TEMPLATE_HINT, Channel=UNIT_ID)}>",
        f'\t<Info templateType="7" minVersion="{MIN_LOXONE_VERSION}"/>',
    ]
    for register in INPUT_REGISTERS:
        poll = LIMIT_POLL if register.offset in LIMIT_OFFSETS else FAST_POLL
        lines.append(command("IR", register, READ_INPUT, sensor=True, poll=poll))
    for register in HOLDING_REGISTERS:
        lines.append(command("HR", register, READ_HOLDING, sensor=True, suffix=" (state)", poll=STATE_POLL))
    for register in HOLDING_REGISTERS:
        lines.append(command("HR", register, WRITE_SINGLE, sensor=False))
    lines.append("</Modbus>")
    return "\n".join(lines) + "\n"


def validate(xml: str) -> list[str]:
    errors = []
    root = ElementTree.fromstring(xml)
    seen = set()
    titles = set()
    input_offsets = {r.offset for r in INPUT_REGISTERS}
    holding_offsets = {r.offset for r in HOLDING_REGISTERS}
    for cmd in root.iter("ModbusCmd"):
        title = cmd.get("Title")
        offset = int(cmd.get("ModbusAddress", "0")) + 1
        function = int(cmd.get("ModbusCmd"))
        key = (function, offset, cmd.get("Sensor"))
        if key in seen:
            errors.append(f"duplicate command {key}")
        seen.add(key)
        if title in titles:
            errors.append(f"duplicate title {title!r}")
        titles.add(title)
        allowed = input_offsets if function == READ_INPUT else holding_offsets
        if offset not in allowed:
            errors.append(f"{title!r}: offset {offset} is not a known register for FC {function}")
        if not title.startswith(("IR", "HR")) or int(title[2:4]) != offset:
            errors.append(f"{title!r}: title does not match offset {offset}")
        if (function == WRITE_SINGLE) == (cmd.get("Sensor") == "true"):
            errors.append(f"{title!r}: FC {function} does not match Sensor={cmd.get('Sensor')}")
    return errors


def main() -> int:
    xml = build()
    errors = validate(xml)
    if errors:
        print("\n".join(errors))
        return 1
    if "--check" in sys.argv:
        current = OUTPUT.read_text(encoding="utf-8-sig") if OUTPUT.exists() else ""
        if current != xml:
            print(f"{OUTPUT} is out of date; run tools/build_loxone_template.py")
            return 1
        print(f"OK: {OUTPUT.name} is valid and up to date")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(xml, encoding="utf-8-sig")
    print(f"Wrote {OUTPUT} ({xml.count('<ModbusCmd')} commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

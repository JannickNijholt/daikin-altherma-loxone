# Daikin HomeHub (EKRHH) – Use case 3 Modbus register map

Summarised from the *Daikin HomeHub EKRHH Installer reference guide*, 4P744838-1E (2026.01),
chapter 9. Always check the latest revision of that guide before relying on a register.

## Transport

| | Modbus TCP | Modbus RTU |
|---|---|---|
| Medium | Ethernet (HomeHub LAN port) | 3-wire RS-485 |
| Port / serial | 502 (plain), 802 (TLS) | 9600 baud, 8N1 |
| Unit / slave id | as configured | 1–247 |

- Register numbers below are **1-based offsets**. The PDU address is `offset - 1`.
- Configuration (enable use case 3, TCP/RTU, slave id) is done in the **ONECTA app**.
- Writes are *change based*: the HomeHub only forwards a write when the value changes.
  Daikin recommends that the client re-writes its desired state periodically.

## Data types

| Type | Encoding | Scaling |
|---|---|---|
| Temp16 | signed 16-bit | ÷ 100 → °C |
| Pow16 | signed 16-bit | ÷ 100 → kW (× 100 when writing) |
| Int16 | signed 16-bit | none |
| Text16 | 2 ASCII chars (high byte, low byte) | error code, e.g. `U8` |

Special values: `32767` unsupported, `32766` unavailable in this configuration,
`32765` value not loaded yet.

## Holding registers (read/write, FC 3 / FC 6 / FC 16)

| Offset | Name | Values |
|---|---|---|
| 1 | Leaving water Main heating setpoint | per field settings |
| 2 | Leaving water Main cooling setpoint | per field settings |
| 3 | Operation mode | 0 auto, 1 heating, 2 cooling (32766 on heating-only units) |
| 4 | Space heating/cooling ON/OFF | 0/1 |
| 6 | Room thermostat heating setpoint Main | 12–30 °C |
| 7 | Room thermostat cooling setpoint Main | 15–35 °C |
| 9 | Quiet mode | 0/1 |
| 10 | DHW reheat setpoint | 30–60 °C (only with tank enabled, *Reheat only*, *Fixed*) |
| 12 | DHW reheat ON/OFF | 0/1 |
| 13 | DHW booster (powerful) ON/OFF | 0/1 |
| 53 | Weather-dependent mode Main | 0 fixed, 1 WD, 2 fixed+sched, 3 WD+sched |
| 54 | WD Main LWT heating offset | −10…10 °C |
| 55 | WD Main LWT cooling offset | −10…10 °C |
| 56 | Smart Grid mode | 0 free, 1 forced off, 2 recommended on, 3 forced on |
| 57 | Power limit during *recommended on* / buffering | Pow16, 0–20 kW |
| 58 | General power limit | Pow16, 0–20 kW |
| 59 | Thermostat Main input A | 0/1 (*) |
| 61 | Thermostat Add input A | 0/1 (*) |
| 63 | Leaving water Add heating setpoint | per field settings |
| 64 | Leaving water Add cooling setpoint | per field settings |
| 65 | Weather-dependent mode Add | as 53 |
| 66 | WD Add LWT heating offset | −10…10 °C |
| 67 | WD Add LWT cooling offset | −10…10 °C |

(*) Not operational on Altherma 3 R / 3 M with Micon ID 20002203. Only valid with
external thermostat type `[C-05]=0` when `[C-07]=1`.

Out-of-range setpoint writes are clamped to the configured min/max. Out-of-range
writes to other registers are ignored.

## Input registers (read-only, FC 4)

| Offset | Name | Type |
|---|---|---|
| 21 | Unit abnormality (0 ok, 1 fault, 2 warning) | Int16 |
| 22 | Unit abnormality code | Text16 |
| 23 | Unit abnormality sub code (32766 = no error) | Int16 |
| 30 | Circulation pump running | 0/1 |
| 31 | Compressor running | 0/1 |
| 32 | Booster heater running | 0/1 |
| 33 | Disinfection operation | 0/1 |
| 35 | Defrost | 0/1 |
| 36 | Hot start | 0/1 |
| 37 | 3-way valve (0 space heating, 1 DHW) | 0/1 |
| 38 | Operation mode (1 heating, 2 cooling) | Int16 |
| 40 | Leaving water temperature PHE | Temp16 |
| 41 | Leaving water temperature BUH | Temp16 |
| 42 | Return water temperature | Temp16 |
| 43 | DHW temperature | Temp16 |
| 44 | Outside air temperature | Temp16 |
| 45 | Liquid refrigerant temperature | Temp16 |
| 49 | Flow rate (l/min × 100) | Int16 |
| 50 | Remote-controller room temperature Main | Temp16 |
| 51 | Heat pump power consumption | Pow16 |
| 52 | DHW normal operation (0 idle, 1 operating) | Int16 |
| 53 | Space heating/cooling normal operation | Int16 |
| 54–61 | LWT Main/Add heating/cooling setpoint lower/upper limits | Temp16 |
| 76 | DHW upper temperature | Temp16 |
| 77 | DHW lower temperature | Temp16 |
| 84–87 | Room heating/cooling setpoint lower/upper limits | Temp16 |

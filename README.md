# Daikin Altherma × Loxone

Daikin Altherma heat pumps in a Loxone Miniserver, without Home Assistant.

**`onecta-modbus`** is a small service (LXC, Raspberry Pi or Docker) that logs in to the
Daikin Onecta cloud and offers the units to Loxone over **Modbus TCP, with the same register
map as the Daikin HomeHub**. Loxone uses its native Modbus support, and one template covers
reading and control.

```text
Loxone ──Modbus TCP :502──▶ onecta-modbus ──HTTPS/OAuth2──▶ Daikin Onecta cloud ──▶ Altherma units
                              └─ web UI :8080 (Daikin login, status, live registers)
```

- Room temperature, setpoint (0.5 °C), leaving-water offset, on/off, outdoor and leaving-water
  temperature, errors, energy per day/month/year
- Stays within Daikin's ~200 API calls/day; writes only cost a call when a value changes
- HomeHub-compatible: swap in a real Daikin HomeHub later by changing only the IP in Loxone

**Get started: [docs/bridge.md](docs/bridge.md)** (install, Daikin login, Loxone setup)

## Why a bridge

| Route | Result | Details |
|---|---|---|
| Local API on the BRP069A78 WLAN cartridges | ❌ none exists | [finding](docs/findings/2026-10-21-brp069a78-local-api.md) |
| Onecta cloud straight from the Miniserver | ⚠️ read works, control doesn't | Virtual Outputs handle HTTPS, tokens and saved responses, but Onecta commands need HTTP PATCH, which Loxone can't send. [Feasibility tests](docs/loxone-only-feasibility.md) |
| **Onecta → Modbus bridge** | ✅ full read + control | [docs/bridge.md](docs/bridge.md) |
| Daikin HomeHub EKRHH (hardware, local Modbus) | ✅ native, needs hardware | Your Altherma 3 M units with MMI 7.8.0 are compatible. [HomeHub template](docs/loxone-setup.md), [plan](docs/PLAN.md) |

## Repository layout

| Path | Contents |
|---|---|
| `src/onecta_modbus/` | The bridge (Python 3.9+, only dependency: aiohttp) |
| `tests/` | Tests, incl. an anonymised fixture of the real units |
| `deploy/` | LXC/Debian installer, systemd unit, settings file |
| `Dockerfile`, `docker-compose.yml` | Container alternative |
| `loxone/templates/` | Loxone Modbus templates: bridge (`MB_Onecta_Bridge*.xml`) and HomeHub (`MB_Daikin_HomeHub_EKRHH.xml`) |
| `loxone/picoc/` | PicoC programs used to test the Miniserver's capabilities |
| `docs/` | Bridge guide, register maps, feasibility tests, findings, original plan |
| `tools/` | Template generators, Onecta probe, adapter probe, fixture sanitizer |

## Development

```bash
pip install -e '.[test]' && pytest
python3 tools/build_bridge_template.py   # bridge templates + docs/bridge-registers.md
python3 tools/build_loxone_template.py   # HomeHub template
```

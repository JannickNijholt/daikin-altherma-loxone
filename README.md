# Daikin Altherma × Loxone

Native integration of two Daikin Altherma heat pumps into a Loxone Miniserver, replacing
the current Home Assistant + [Daikin Onecta](https://github.com/jwillemsen/daikin_onecta)
setup.

## TL;DR

- The installed **BRP069A78 WLAN cartridges have no local API**. They only talk to the
  Daikin cloud ([finding](docs/findings/2026-10-21-brp069a78-local-api.md)).
- The Onecta cloud API needs OAuth2, which the Miniserver can't do on its own.
- **Native route:** add a **Daikin HomeHub (EKRHH)** per heat pump and connect it to the
  Miniserver over **Modbus TCP** (Daikin "use case 3"). This is local, works within
  seconds, and Loxone ships a template for it. The Onecta app keeps working.

Full plan, options and open questions: **[docs/PLAN.md](docs/PLAN.md)**

## Loxone template

**[`loxone/templates/MB_Daikin_HomeHub_EKRHH.xml`](loxone/templates/MB_Daikin_HomeHub_EKRHH.xml)**
is a Modbus TCP device template for the Daikin HomeHub (use case 3). It covers all input
and holding registers, with scaling applied. Import and wiring instructions are in
**[docs/loxone-setup.md](docs/loxone-setup.md)**.

## Repository layout

| Path | Contents |
|---|---|
| `docs/PLAN.md` | Integration plan, options, phases, open questions |
| `docs/findings/` | Dated test results from the real installation |
| `docs/reference/` | Register maps and protocol notes |
| `tools/` | Read-only diagnostic scripts |
| `loxone/templates/` | Loxone Config Modbus templates (generated) |

## Tools

```bash
python3 tools/build_loxone_template.py          # regenerate the Loxone template
python3 tools/build_loxone_template.py --check  # validate it is correct and up to date
python3 tools/probe_brp069a78.py 192.168.10.7 192.168.10.3
```

The probe checks the WLAN cartridges for local APIs. It is read-only and redacts identifiers.

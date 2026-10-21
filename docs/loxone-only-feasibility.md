# Can the Daikin Onecta cloud API be used from Loxone alone?

Date: 2026-10-21. Context: the BRP069A78 cartridges have no local API
([finding](findings/2026-10-21-brp069a78-local-api.md)), so without extra hardware the
Daikin cloud API is the only way in.

## What the Miniserver would have to do

| # | Step | Frequency |
|---|---|---|
| 1 | One-time login in a browser → authorization code → exchange for tokens | once (can be done on a laptop) |
| 2 | **Refresh tokens:** `POST https://idp.onecta.daikineurope.com/v1/oidc/token` with a form body containing the **current refresh token** | every < 60 min (access token lives 3600 s) |
| 3 | **Read two values from the JSON response:** the new `access_token` and the new `refresh_token`. The old refresh token is invalid after each use. | every refresh |
| 4 | **Store both tokens** (and survive a reboot, or the chain breaks and you must log in again) | every refresh |
| 5 | **Read state:** `GET https://api.onecta.daikineurope.com/v1/gateway-devices` with header `Authorization: Bearer <access_token>`, then parse the JSON | every ~10 min (200 calls/day limit) |
| 6 | **Send commands:** `PATCH …/characteristics/temperatureControl` with header `Authorization: Bearer …` and a JSON body | on change |

Verified on 2026-10-21: Daikin's endpoints reject plain HTTP (`403`), so **every step
needs HTTPS**.

## What Loxone offers

| Loxone feature | HTTPS | Custom header | Dynamic text in header/body | Reads response | PATCH | Verdict |
|---|---|---|---|---|---|---|
| Virtual HTTP Input | ✅ (Gen 2) | ❌ | ❌ | ✅ (pattern match) | ❌ GET only | can't send the Bearer token or POST |
| Virtual Output | ✅ (Gen 2) | ✅ fixed text | ❌ only numeric `<v>` | ❌ | ❌ GET/POST/PUT/DELETE | can't insert a changing token, can't read the new one |
| PicoC program block | ❓ **unknown** | ✅ (raw request) | ✅ | ✅ | ✅ (raw request) | **works only if PicoC can open HTTPS connections** |

Storing tokens isn't the problem. A PicoC program can keep them in memory, and Virtual
Text Inputs can hold values. The blocker is **HTTPS from a program block**:

- Plain TCP streams (`/dev/tcp/…`) are documented and work, but Daikin refuses plain HTTP.
- Implementing TLS yourself in PicoC (an interpreted C subset) is not realistic.
- No public documentation or forum post confirms HTTPS support in PicoC. Loxone's own
  documentation site is offline at the time of writing, so this couldn't be checked there.

## How to settle it: a 2-minute test on your Miniserver

[`loxone/picoc/https_capability_test.c`](../loxone/picoc/https_capability_test.c) tests
`httpget` and stream connections over HTTP (controls) and HTTPS, and writes the result to
TQ1/TQ2.

- **If an HTTPS test reports `OK`**, a Loxone-only integration is technically possible. A
  PicoC program does steps 2–6. The one-time login (step 1) is done once on a laptop. Expect
  some fragility: parsing large JSON in PicoC, memory limits, and a re-login if the token
  chain breaks (e.g. after a long power outage).
- **If every HTTPS test reports `FAIL`/`NO-STREAM`**, the Miniserver cannot talk to the
  Daikin cloud on its own. The options are then:
  1. **Daikin HomeHub (EKRHH)** per heat pump: truly native, local Modbus TCP. Template is
     ready ([loxone-setup.md](loxone-setup.md)).
  2. **A small always-on helper** (Docker container or LoxBerry plugin) that only does the
     Daikin login. It replaces Home Assistant but isn't Loxone-only.

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

## Result (2026-10-21): not possible with Loxone alone

Test run on the Miniserver with
[`loxone/picoc/https_capability_test.c`](../loxone/picoc/https_capability_test.c):

| Test | Result |
|---|---|
| `httpget` plain HTTP (control) | OK |
| `httpget("https://…")` | OK (slow). It's GET only either way |
| Stream `/dev/tcp/…/80` (control) | OK |
| Stream `/dev/tls`, `/dev/ssl`, `/dev/tcps` on 443 | FAIL: no TLS for raw streams |

Checked against Daikin the same day:

- The token endpoint only accepts **POST**. A plain GET gets no response. A GET with a body
  or with `X-HTTP-Method-Override` / `X-Method-Override` / `X-HTTP-Method: POST` is
  rejected by CloudFront with `403`.

The hourly token refresh needs an **HTTPS POST whose response is read**. No Loxone
mechanism combines these:

| Mechanism | HTTPS | POST | Reads response |
|---|---|---|---|
| PicoC `httpget` | ✅ | ❌ | ✅ |
| PicoC streams | ❌ | ✅ | ✅ |
| Virtual Output | ✅ | ✅ | ❌ |

~~**Conclusion:** the Daikin cloud API can't be used from the Miniserver alone.~~

**Correction:** Virtual Output commands have **"Save HTTP response"** (*HTTP antwoord
opslaan*). The reply is written to `/user/common/<file>` on the Miniserver and can be read
back by a Virtual HTTP Input (command recognition) or PicoC. So the combination
**Virtual Output (HTTPS POST) + saved response + local read** covers the token refresh,
*if* the remaining unknowns resolve:

| # | Open question | How to test |
|---|---|---|
| 1 | Does `<v>` in a Virtual Output header/body accept **text** from a program block (tokens are text)? | [`loxone/picoc/vo_text_test.c`](../loxone/picoc/vo_text_test.c) against httpbin.org |
| 2 | Commands need **PATCH**, but Virtual Outputs offer GET/POST/PUT/DELETE. Does the Onecta API accept PUT/POST on characteristics? | curl with a real Onecta access token |
| 3 | A PATCH-like command needs the token in the header **and** the value in the body, but there is only one `<v>`. | depends on 1 and 2 |

### Confirmed on the Miniserver (2026-10-21, firmware 17.1.6.30)

| Capability | Result | Evidence |
|---|---|---|
| Virtual Output HTTPS POST | ✅ | httpbin echo `"url": "https://httpbin.org/post"` |
| Text from a program block (Txt1) inserted via `<v>` in **header** | ✅ | `"X-Lox-Test": "abc123XYZ-1"` |
| Same `<v>` text in **body** | ✅ | `"data": "token=abc123XYZ-1"` |
| Save HTTP response to a file | ✅ | needs a **path** in *HTTP antwoord opslaan*; a bare filename wrote nothing |
| Default Content-Type | `text/xml; charset=utf-8` | |
| Content-Type override via header field (`Content-Type: …\r\nAuthorization: Bearer <v>`) | ✅ | single `Content-Type: application/x-www-form-urlencoded; charset=utf-8`, body parsed as form |
| Token-length text (1502 chars) in header **and** body | ✅ | `Content-Length: 1541` = 39 + 1502, nothing truncated |
| PicoC rejects pointer arithmetic (`text + 1500`) | ⚠️ | "invalid operation"; copy characters instead |
| Save path for *HTTP antwoord opslaan* | ✅ `/user/common/<name>` | read back via `/dev/fsget/user/common/<name>` |
| PicoC `fopen`/`fread` of the saved response | ✅ | `/user/common/votest.txt bytes=495` |
| PicoC `fopen("w")`/`fprintf` + read back | ✅ | `write+read: token-backup-test`, so tokens can be persisted |
| One `<v>` carrying headers + blank line + JSON body (header field `<v>`, body empty, PUT) | ✅ | `"Authorization": "Bearer TESTTOKEN-2"`, `"json": {"n": 2, "value": 21.5}`, exact `Content-Length` |
| `Content-Type` inside that `<v>` | ⚠️ dropped | not received; check whether Onecta requires it ([`tools/onecta_probe.py`](../tools/onecta_probe.py)) |

So question 1 is answered: **yes**, and the Daikin token refresh is possible with a
Virtual Output. Still open:

- Question 2: does the Onecta API accept PUT/POST (Loxone has no PATCH), and does it need
  `Content-Type`? Run [`tools/onecta_probe.py`](../tools/onecta_probe.py) with a real login.

If 1 fails: Loxone can't send the tokens, so no Loxone-only integration is possible.
If 1 works but 2 fails: Loxone-only **read** (temperatures, setpoints, status) works, but
**control** doesn't.

## Original test plan

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

### Daikin login: redirect URI

Daikin's CloudFront firewall rejects the authorize request with **HTTP 403** when the
`redirect_uri` is `http://localhost…` or `http://127.0.0.1…`. LAN addresses
(`http://192.168.10.10/…`) and HTTPS URLs pass through to the Daikin login. The redirect
target doesn't need to exist: the authorization code is read from the browser's address
bar. This project uses `http://192.168.10.10/daikin-callback`, so the code never leaves
the LAN.

### Onecta API: which methods work (tested 2026-10-21 on "Klimaatregeling boven")

| Request | Result |
|---|---|
| `PATCH …/characteristics/onOffMode` + `Content-Type: application/json` | **204** |
| Same without `Content-Type` | **422 INVALID_REQUEST**: Content-Type is required |
| `PUT` / `POST` on characteristics (with or without Content-Type) | **no response (timeout)**: not supported |

Consequences for a Loxone-only setup:

- **Reading** (GET + Bearer) and the **token refresh** (POST to the IdP) work with
  Virtual Outputs.
- **Characteristics** (room setpoint, leaving-water offset, on/off, mode) only accept
  PATCH, which Virtual Outputs can't send.
- **Schedules** have their own **PUT** endpoints (`schedule/{mode}/current`,
  `schedule/{mode}/schedules`, see
  [daikin-controller-cloud#108](https://github.com/Apollon77/daikin-controller-cloud/issues/108)).
  On these Altherma 3 M units, schedule actions support `roomTemperature` (12–30 °C,
  whole degrees). A schedule with one constant action can therefore set the room setpoint
  from Loxone. The leaving-water offset and on/off have no schedule action.

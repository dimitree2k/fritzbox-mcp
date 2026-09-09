# Spec: fritzbox-mcp v0.2.0 — Feature Set

Status: REVISED — draft cross-reviewed, findings folded in
Target branch: `development`
Scope guard: one prerequisite fix + three features + one micro-tool. Everything else is explicitly out of scope.

---

## Feature 0 (prerequisite): Fix the web session helper

### Context
`_get_web_session()` (`server.py:80`) backs `fritzbox_security_check` and `fritzbox_web_action`, and Features 2 and 3 add load on the same path. It has three defects today:

1. **No request timeout on any call** (`server.py:87`, `:102`, `:276`, `:425`). The tools are `async def` but call blocking `requests`; an unreachable or wedged box hangs the asyncio event loop, so the *whole* MCP server stops answering — not just the offending tool.
2. **Scheme hardcoded to `http://`**, so the SID and every `data.lua` response cross the LAN in cleartext, with no way to opt into TLS.
3. **Full PBKDF2 login on every call** — two HTTP round trips plus two PBKDF2 rounds per tool invocation, and Fritz!OS keeps only a bounded number of concurrent sessions.

### Decision
- Add `timeout=10` to all four `requests` calls. This is the blocking fix; it ships regardless of the rest of v0.2.0.
- Read the scheme from a new optional `FRITZBOX_SCHEME` env var (default `http`), so `https` is available without a code change. Update `.env.example`.
- Cache the SID at module level; validate with `login_sid.lua?sid=<sid>` and re-login only when the box reports it stale. ~8 lines.

### Justification
Item 1 is a live availability bug in shipped code, not a v0.2.0 feature. Items 2 and 3 are the difference between adding tools to this helper being safe and making an existing weakness worse.

### Consequences
`.env.example` gains one variable (the only change to it in this release). A stale-SID path needs a manual smoke test against a real box.

### Revisit trigger
If TLS becomes the default on the target Fritz!OS versions, flip the `FRITZBOX_SCHEME` default and drop the plaintext path.

---

## Feature 1: Tool Annotations

### Context
The server exposes write tools (device blocking, UPnP toggle, guest WiFi, generic web/TR-064 escape hatches) next to read tools with no machine-readable way for MCP clients to tell them apart. The current MCP spec (2025-11-25 / 2026-07-28) defines tool annotations for exactly this.

### Decision
Add `annotations` to every tool via the SDK 2.0 decorator (`MCPServer.tool(annotations=ToolAnnotations(...))`).

**Note on naming:** the Python fields are snake_case (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`); the camelCase names in the MCP spec are Pydantic aliases. Code uses the snake_case form.

| Tools | Annotations |
|-------|-------------|
| `device_list`, `device_info`, `connection_status`, `port_forwards`, `firmware_info`, `wifi_status`, `logs`, `security_check`, `list_services`, `smart_home_devices`, `line_stats` | `read_only_hint=True` |
| `set_device_profile`, `toggle_upnp`, `toggle_wifi_guest` | `read_only_hint=False`, `idempotent_hint=True` |
| `wake_on_lan` | `read_only_hint=False`, `destructive_hint=False` |
| `web_action`, `call_action`, `reboot`, `smart_home_switch` | `read_only_hint=False`, `destructive_hint=True` |
| all tools | `open_world_hint=False` |

Notes:
- `destructive_hint` **defaults to true** when `read_only_hint=False`, so stating it on a write tool adds no information. It is stated explicitly only on the escape hatches and `reboot`, where it is load-bearing documentation, and set to `False` only on `wake_on_lan` — the one write tool that performs no update at all. Blocking a device, disabling UPnP and disabling guest WiFi are *not* "additive updates" per the SDK definition, so they keep the destructive default; `idempotent_hint=True` carries the useful signal that they are reversible and repeat-safe.
- `smart_home_switch` accepts `toggle`, which is not repeat-safe, so it gets no `idempotent_hint` even though `on`/`off` alone would qualify.
- `web_action` and `call_action` are dual-mode (read/write). Annotations are static per tool, so they are annotated for their worst case: a client that trusts `read_only_hint=False` is safe, the reverse is not.

### Justification
~15 lines total diff, zero runtime cost, and it documents intent in code instead of prose.

### Consequences
**No security property is gained.** The SDK is explicit: *"all properties in ToolAnnotations are hints… Clients should never make tool use decisions based on ToolAnnotations received from untrusted servers."* Annotations improve UI affordances and client-side prompting; they are not authorization, and this spec makes no claim that they gate anything.

Corollary: a `confirm` parameter on `reboot` would be theatre. `fritzbox_call_action` already accepts arbitrary service/action pairs, and reboot is nothing more than `DeviceConfig1 Reboot` — any guard on the named tool is bypassed by the generic one. Real gating belongs at `call_action` (an allow/deny list) or nowhere; it is out of scope here.

### Revisit trigger
If we add a permission layer (allow-list of write actions via env var), annotations become its input — and that layer, not the annotations, is the control.

---

## Feature 2: Smart Home Tools

### Context
Fritz!Box routers control DECT smart home devices (switchable plugs, thermostats, sensors, blinds). Competing servers offer this; it is the largest functional gap.

### Decision
**Use `fritzconnection`'s existing support rather than writing an AHA-HTTP client.** The installed dependency already covers this on two levels:

- `fritzconnection.lib.fritzhomeauto.FritzHomeAutomation` — TR-064 service `X_AVM-DE_Homeauto1`. `get_device_information_list()` returns **parsed dicts**, `set_switch(ain, on)` writes. No XML handling, no web session, no SID.
- `FritzConnection.call_http(command, ain, **kwargs)` — the AHA-HTTP passthrough for anything TR-064 does not reach (blinds, `hkr`). It manages its own SID, honours the configured scheme and port, and supports both PBKDF2 and legacy MD5 auth. It returns `{"content-type", "encoding", "content"}` where `content` is **raw response text** — an AHA caller still parses it.

Two tools:

1. `fritzbox_smart_home_devices() -> str` — `FritzHomeAutomation.get_device_information_list()`. Read-only.
2. `fritzbox_smart_home_switch(ain: str, state: "on" | "off" | "toggle") -> str` — `set_switch()` for `on`/`off`; `call_http("setswitchtoggle", ain)` for `toggle`. Returns the resulting state.

**Output contract** (the router reports everything as strings; the tool converts and names units):

| Field | Type | Unit / note |
|-------|------|-------------|
| `ain`, `name`, `product` | str | — |
| `present` | bool | device reachable |
| `temperature_c` | float \| null | °C; `null` when the device has no temperature sensor |
| `battery_percent` | int \| null | %; `null` on mains-powered devices |
| `power_w`, `energy_wh` | float \| null | W / Wh; `null` unless the device meters |
| `switch_state` | "on" \| "off" \| null | `null` on non-switchable devices |

`null` means *this device class does not report the field* and is expected on most devices — capabilities vary per device, and no field is guaranteed present.

### Justification
- The dependency is already installed and already does it. Hand-rolling `getdevicelistinfos` against `_get_web_session()` would duplicate `FritzHttp` while inheriting the defects Feature 0 fixes.
- TR-064 covers the two tools above end-to-end with parsed output. `call_http` is reserved for what TR-064 genuinely does not expose; per fritzconnection's own docs `call_action` is ~5–6× faster than `call_http`, so TR-064 is preferred where both work.
- **No dedicated temperature tool.** The device list already carries `temperature_c` for every device that has a sensor; a per-AIN tool would be a second round trip for a field the caller already has.

Alternatives rejected:
- *Thermostat setpoint writing* (`hkr` encoding is fiddly and model-dependent): deferred, see Out of Scope.
- *Full AHA passthrough tool*: `fritzbox_call_action` already covers TR-064 discovery, and AHA has no discovery to expose. YAGNI until an uncovered device class is actually requested.

### Consequences
Requires the Fritz!Box user to have **Smart Home** permission (README already recommends it). Missing the right returns HTTP 403, which `fritzconnection` raises as `FritzAuthorizationError` — caught and returned as a plain "user lacks Smart Home permission" message rather than a traceback. Households with no DECT devices get an empty list, not an error.

### Revisit trigger
First user request for thermostat scheduling or blind control → extend via `call_http` with `hkr`/`blind` commands.

---

## Feature 3: Line Health Tools

### Context
The data needed for "is my connection okay?" lives in TR-064 (`WANCommonInterfaceConfig`, `WANDSLInterfaceConfig`), but the server surfaces only external IP, uptime and rates.

### Decision
Most of the primitives already exist on `FritzStatus` and are simply not exposed. Three additions:

1. Extend `fritzbox_connection_status` with `fs.bytes_sent` / `fs.bytes_received`. Use the **properties, not raw `call_action`**: they prefer the 64-bit `X_AVM_DE_TotalBytes*64` fields and fall back to the legacy counters only on old Fritz!OS. The raw `GetTotalBytesSent/Received` actions return TR-064 `ui4` values that wrap at 4 GB and are meaningless on a live line. `GetCommonLinkProperties` needs no work — `max_linked_bit_rate` is already in the response (`server.py:176`).
2. New tool `fritzbox_line_stats() -> str`:
   - `fs.noise_margin` and `fs.attenuation` — already implemented in `FritzStatus`, currently unexposed. Free.
   - FEC/CRC/ES error counters and resync count from `WANDSLInterfaceConfig1` `GetStatisticsTotal`. This is the only genuinely new TR-064 work.
   - Graceful degradation: cable/fibre boxes lack `WANDSLInterfaceConfig1` entirely; missing fields return `"unavailable"` rather than raising, per-field, same pattern as the DNS fallback at `server.py:162-167`.
3. Micro-tool `fritzbox_reboot() -> str`: `fc.reboot()` — one line, the library wraps `DeviceConfig1 Reboot`. Destructive hint; docstring warns the box drops offline for ~2 minutes. No `confirm` parameter, for the reason given under Feature 1.

### Justification
Enables the highest-value use case on real diagnostic data. Reusing the `FritzStatus` properties cuts this to roughly 25 lines, most of it the `GetStatisticsTotal` parsing and the per-field fallback.

### Consequences
Cable/fibre users get `"unavailable"` for the DSL block — acceptable; the dominant German install base is DSL. Byte counters are cumulative since last resync, not a rate; the docstring says so, since an LLM will otherwise read them as throughput.

### Revisit trigger
Cable/fibre parity if requested (`WANCableInterfaceConfig1` exists).

---

## Cross-cutting

**Testing**: there is no test file in the repo today — this **creates** `test_server.py`, not extends one. Scope: an in-memory SDK 2.0 `Client(mcp)` asserting all 19 tools are listed and that annotations are present and correct on each; plus parsing-logic unit tests with TR-064 / AHA responses mocked at the `call_action` / `call_http` boundary. Live-box smoke test stays manual, one documented command in the README.

**Tool count**: 15 today + 4 new (`smart_home_devices`, `smart_home_switch`, `line_stats`, `reboot`) = **19**.

**Docs**: README tools table gains the new tools. Its section headers are also wrong today — "Curated tools (11)" sits over 12 rows, "Generic tools (4)" over 3 — fix while editing. `.env.example` gains `FRITZBOX_SCHEME` (Feature 0).

**Version**: bumped to 0.2.0 in `pyproject.toml` when merging to main.

## Explicitly out of scope for v0.2.0

- A permission/allow-list layer over `fritzbox_call_action` — the only thing that would make write-gating real; needs its own design
- PyPI publishing / `uvx` entry point — after feature freeze, separate step
- Thermostat setpoint writes, blind/shutter control, call deflection, VPN, phonebook
- Scheduled/delayed actions (needs a persistent background process)
- HTTP transport, remote deployment concerns

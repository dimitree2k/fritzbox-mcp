# Spec: fritzbox-mcp v0.2.0 — Feature Set

Status: DRAFT — awaiting review
Target branch: `development`
Scope guard: three features + two micro-tools. Everything else is explicitly out of scope.

---

## Feature 1: Tool Annotations (readOnlyHint / destructiveHint)

### Context
The server exposes write tools (device blocking, UPnP toggle, guest WiFi, generic web/TR-064 escape hatches) next to read tools with no machine-readable way for MCP clients to tell them apart. The current MCP spec (2025-11-25 / 2026-07-28) defines tool annotations exactly for this; clients may use them to gate or warn on destructive calls.

### Decision
Add `annotations` to every existing tool via the SDK 2.0 decorator (verified available: `MCPServer.tool(annotations: ToolAnnotations)`):

| Hint | Applies to |
|------|-----------|
| `readOnlyHint=True` | device_list, device_info, connection_status, port_forwards, firmware_info, wifi_status, logs, security_check, list_services |
| `readOnlyHint=False, destructiveHint=True` | set_device_profile, toggle_upnp, toggle_wifi_guest, wake_on_lan, web_action (when apply=True), call_action |
| `openWorldHint=False` | all tools (the Fritz!Box is a closed world; helps clients plan discovery) |

Notes:
- Hints are **advisory per spec** — no behavior change in the server itself.
- `web_action` and `call_action` are dual-mode (read/write). They get `destructiveHint=True` because their worst case writes settings; a client that trusts `readOnlyHint=False` is safe, the reverse is not.

### Justification
~15 lines total diff, zero runtime cost, immediately useful to annotation-aware clients, and it documents intent in code instead of prose.

### Consequences
Clients ignoring hints see no change. Clients honoring them get correct gating for free.

### Revisit trigger
If we add a permission layer (e.g., allow-list of write actions via env var), annotations become its input.

---

## Feature 2: Smart Home Tools (AVM AHA-HTTP API)

### Context
Fritz!Box routers control DECT smart home devices (switchable plugs, thermostats, sensors, blind shutters) exclusively via the AHA-HTTP API (`/webservices/homeautoswitch.lua`) — TR-064 does not cover it. Competing servers offer this; it is the largest functional gap.

### Decision
Reuse the existing PBKDF2 web session helper `_get_web_session()` (same auth mechanism as `data.lua`). Add three tools:

1. `fritzbox_smart_home_devices() -> str` — `switchcmd=getdevicelistinfos`, return parsed JSON list: AIN, name, type (switch/thermometer/sensor/blind), battery level, present flag, temperature, power/energy where reported. Read-only.
2. `fritzbox_smart_home_switch(ain: str, state: "on" | "off" | "toggle") -> str` — `setswitchon/setswitchoff/setswitchtoggle`, then re-read state and return it (verify-after-write pattern already used by existing write tools). Destructive hint.
3. `fritzbox_smart_home_temperature(ain: str) -> str` — current temperature from `gettemperature` for thermostat/sensor devices. Read-only.

XML parsing with stdlib `xml.etree.ElementTree` (already imported); attributes map directly to dict entries.

### Justification
- Session/auth code exists → incremental cost is ~120 lines for full smart-home coverage of the common device classes.
- Three tools instead of one generic `aha_call`: AHA has no service/action discovery like TR-064, so a generic escape hatch buys nothing; curated names are self-documenting.
- No new dependency: requests + ElementTree are already in use.

Alternatives rejected:
- *Thermostat setpoint writing* (`hkr` temp offset encoding is fiddly and model-dependent): deferred, see Out of Scope.
- *Full AHA passthrough*: same reasoning as above; YAGNI until someone needs an uncovered device class.

### Consequences
Requires the Fritz!Box user to have **Smart Home** permission (README already recommends this).

### Revisit trigger
First user request for thermostat scheduling or blind control → extend with `hkr`/`blind` commands.

---

## Feature 3: Line Health Tools

### Context
Competing servers market "network health analysis". The data needed lives in TR-064 (`WANCommonInterfaceConfig`, `WANDSLInterfaceConfig`) but our server only surfaces WAN status superficially (external IP, uptime, rates).

### Decision
Two additions:

1. Extend `fritzbox_connection_status` with link properties: `GetCommonLinkProperties` (max/downstream rates, physical link status) and byte counters (`GetTotalBytesReceived/Sent`) — merged into the existing response, no new tool.
2. New tool `fritzbox_line_stats() -> str`: DSL-specific diagnostics from `WANDSLInterfaceConfig1` (`GetInfo`, `GetStatisticsTotal` where available): SNR margin, attenuation, FEC/CRC error counters, DSL resyncs. Graceful degradation: fields absent on cable/fiber boxes return `"unavailable"` rather than failing (cable models expose different services — handled via try/except per field, same pattern as DNS fallback in existing code).
3. Micro-tool `fritzbox_reboot() -> str`: `DeviceConfig1 Reboot`. Destructive hint, docstring warns that the box drops offline for ~2 minutes.

### Justification
Enables the highest-value LLM use case ("is my connection okay?") on real diagnostic data instead of surface stats. Cost: ~60 lines. Reboot is 3 lines and rounds out the ops story; every competing server has it.

### Consequences
Cable/fiber users get partial data — acceptable; the dominant German install base is DSL.

### Revisit trigger
Cable/fiber feature parity if requested (services exist: `WANCableInterfaceConfig1`).

---

## Cross-cutting

**Testing**: extend the in-memory client test (SDK 2.0 `Client(mcp)`) to assert: all 15+6 tools listed, annotations present and correct on every tool. TR-064/AHA responses are mocked at the `call_action`/session boundary for unit tests of parsing logic; live-box smoke test stays manual (one command documented in README).

**Docs**: README tools table gains the new tools; `.env.example` unchanged (no new variables).

**Version**: bumped to 0.2.0 when merging to main.

## Explicitly out of scope for v0.2.0

- PyPI publishing / `uvx` entry point — after feature freeze, separate step
- Thermostat setpoint writes, blind/shutter control, call deflection, VPN, phonebook
- Scheduled/delayed actions (needs persistent background process)
- HTTP transport, remote deployment concerns

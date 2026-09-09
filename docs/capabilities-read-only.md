# Fritz!Box MCP capabilities

This is the operator guide for the Fritz!Box MCP server in this repository. It
describes what an MCP client can ask, what each tool actually returns, and
which capabilities are safe for a read-only session. Runtime values are
router-specific and are intentionally not embedded in this repository guide.

## Safety boundary

The safest read-only tool set is the set marked `read_only_hint=True` in
`server.py`:

| Tool | Read-only purpose |
| --- | --- |
| `fritzbox_device_list` | List known network devices. |
| `fritzbox_device_info` | Inspect one device by IP or MAC address. |
| `fritzbox_connection_status` | Inspect WAN state, address, uptime, speeds, and DNS when available. |
| `fritzbox_wan_link_status` | Inspect WAN access type, physical link state, and link speeds. |
| `fritzbox_wan_traffic_stats` | Inspect cumulative WAN byte and packet counters. |
| `fritzbox_port_forwards` | List active port-forwarding rules. |
| `fritzbox_firmware_info` | Inspect model, firmware version, update state, and uptime. |
| `fritzbox_wifi_status` | Inspect Wi-Fi networks without returning passwords or keys. |
| `fritzbox_wifi_clients` | Inspect currently associated Wi-Fi clients. |
| `fritzbox_wifi_statistics` | Inspect Wi-Fi packet counters by network. |
| `fritzbox_wifi_channel_info` | Inspect Wi-Fi channel and frequency-band information. |
| `fritzbox_lan_config` | Inspect LAN address, DHCP, DNS, and router configuration. |
| `fritzbox_ethernet_status` | Inspect LAN Ethernet link state and traffic counters. |
| `fritzbox_logs` | Read recent Fritz!Box system events. |
| `fritzbox_security_check` | Read the web UI security diagnostic data. |
| `fritzbox_list_services` | Discover the TR-064 services and actions exposed by this router. |
| `fritzbox_smart_home_devices` | Inspect DECT smart-home devices and reported telemetry. |
| `fritzbox_line_stats` | Inspect DSL diagnostics, when the router provides them. |

Tool annotations are guidance for an MCP client, not a permission system. A
read-only workflow must also avoid the generic tools described below when they
can write.

Credentials stay in `.env`. Do not paste them into a prompt, and do not ask
the MCP to return them. Wi-Fi passwords and encryption keys are not returned by
the curated Wi-Fi tool.

## Planned read-only capabilities

The following capabilities are documented for future dedicated tools. They are
not currently exposed as named tools, so they must not be treated as available
curated capabilities yet. The current live service inventory is model- and
firmware-dependent; use `fritzbox_list_services` before any separately
approved read-only investigation.

| Planned tool | Read-only source and scope | Explicit boundary |
| --- | --- | --- |
| `fritzbox_routing_table` | `Layer3Forwarding1.GetForwardNumberOfEntries` plus `GetGenericForwardingEntry`; active routes and default gateway. | Never call `AddForwardingEntry`, `DeleteForwardingEntry`, or `SetForwardingEntryEnable`. |
| `fritzbox_time_status` | `Time1.GetInfo`; router time, time zone, and NTP state. | Never call `SetNTPServers`. |
| `fritzbox_speedtest_status` | `X_AVM-DE_Speedtest1.GetInfo` and `GetStatistics`; existing speed-test state and results. | Never call `ResetStatistics` or `SetConfig`. |
| `fritzbox_wifi_security_status` | `WLANConfiguration*.GetBasBeaconSecurityProperties` and security-mode metadata only. | Never request `GetSecurityKeys`, WPS PIN data, or any Wi-Fi setter. |
| `fritzbox_dect_handsets` | `X_AVM-DE_Dect1` inventory getters for connected DECT handsets. | Never call device update or any handset-control action. |
| `fritzbox_remote_access_status` | `X_AVM-DE_RemoteAccess1.GetInfo` and sanitized DDNS status. | Never call `SetConfig`, `SetDDNSConfig`, `SetEnable`, or certificate setters. |
| `fritzbox_storage_status` | `X_AVM-DE_Storage1.GetInfo`; basic NAS/storage availability. | Do not return account secrets; never call storage setters or WAN exposure actions. |
| `fritzbox_myfritz_status` | `X_AVM-DE_MyFritz1.GetInfo` and service-state getters. | Never call `SetMyFRITZ` or `SetServiceByIndex`. |

These planned tools must not expose Wi-Fi keys, WPS PINs, user passwords, VoIP
credentials, or other account secrets. The service families are listed in
the official [FRITZ! TR-064 overview](https://fritz.support/resources/TR-064_Overview.pdf);
the Wi-Fi security getter is documented in the [WLANConfiguration specification](https://fritz.support/resources/TR-064_WLAN_Configuration.pdf),
and speed-test statistics in the [Speedtest specification](https://fritz.support/resources/TR-064_Speedtest.pdf).

## Natural-language requests

These requests map directly to the safe tool set:

| Ask | Tool |
| --- | --- |
| “List all devices currently known to the router.” | `fritzbox_device_list` |
| “Show details for `192.168.178.20`.” | `fritzbox_device_info` |
| “Is the internet connection up? Show the external IP and uptime.” | `fritzbox_connection_status` |
| “Show the WAN access type, physical link state, and link speeds.” | `fritzbox_wan_link_status` |
| “Show cumulative WAN bytes and packets sent and received.” | `fritzbox_wan_traffic_stats` |
| “List all active port forwards.” | `fritzbox_port_forwards` |
| “What firmware is installed, and is an update available?” | `fritzbox_firmware_info` |
| “Show the Wi-Fi SSIDs, enabled state, channel, standard, and security type. Do not show keys.” | `fritzbox_wifi_status` |
| “List current Wi-Fi clients with signal and link speed.” | `fritzbox_wifi_clients` |
| “Show Wi-Fi packet counters for each network.” | `fritzbox_wifi_statistics` |
| “Show Wi-Fi channels, possible channels, and frequency bands.” | `fritzbox_wifi_channel_info` |
| “Show the LAN address range, DHCP state, DNS servers, and subnet.” | `fritzbox_lan_config` |
| “Show the LAN Ethernet link state and traffic counters.” | `fritzbox_ethernet_status` |
| “Show the last 20 router log entries.” | `fritzbox_logs(max_entries=20)` |
| “Run a read-only security audit.” | `fritzbox_security_check` |
| “Show the DECT smart-home devices and their current telemetry without changing them.” | `fritzbox_smart_home_devices` |
| “Show line quality and DSL error counters; clearly label unavailable fields.” | `fritzbox_line_stats` |
| “Which TR-064 services and actions does this router expose?” | `fritzbox_list_services` |

The client should preserve the read-only constraint in the request. For
example, “check whether guest Wi-Fi is enabled” is a read request, while
“enable guest Wi-Fi” is a setting change and is outside this guide.

## Curated read-only tools

### `fritzbox_device_list`

No arguments. It reads the FritzHosts table and returns a JSON list with:

- `name`
- `ip`
- `mac`
- `status` (`online` or `offline`)
- `interface` / connection type

This is the right tool for inventory and online/offline status. It is not a
network scan; it reports what the Fritz!Box knows.

### `fritzbox_device_info`

Argument:

- `ip_or_mac`: an IPv4 address or a MAC address

It returns the detailed host entry supplied by the Fritz!Box. Use it after
`fritzbox_device_list` when one device needs more information.

### `fritzbox_connection_status`

No arguments. It reads and returns, when supported:

- connection and link state
- external IPv4 address
- external IPv6 address
- uptime
- maximum and linked bit rates
- transmission rate
- cumulative bytes sent and received
- model name
- DNS server data

DNS is best effort: the server tries the WAN IP service and then the WAN PPP
service. Some fields are technology-specific. On a cable or fiber box, DSL
or IPv6-related values may be `null` or absent even when the internet
connection is healthy.

### `fritzbox_wan_link_status`

No arguments. It reads `WANCommonInterfaceConfig1.GetCommonLinkProperties` and
returns, where reported:

- WAN access type and physical link state
- upstream and downstream maximum bit rates
- current upstream and downstream maximum speeds

This tool only reads WAN link properties. It does not request, terminate, or
reconfigure the connection.

### `fritzbox_wan_traffic_stats`

No arguments. It reads the four counter actions from
`WANCommonInterfaceConfig1` and returns:

- cumulative bytes sent and received
- cumulative packets sent and received

These counters are totals reported by the router, not current throughput
rates. The tool only reads them and does not affect the WAN connection.

### `fritzbox_port_forwards`

No arguments. It reads the number of mappings and then retrieves each mapping.
The result includes protocol, external port, internal host, internal port,
enabled state, and description. If the service is unavailable, the tool
returns an error object rather than changing anything.

### `fritzbox_firmware_info`

No arguments. It reads `DeviceInfo1.GetInfo` and FritzStatus data and returns:

- model
- installed firmware version
- whether an update is available
- device uptime

It does not start an update.

### `fritzbox_wifi_status`

No arguments. It checks `WLANConfiguration1` through
`WLANConfiguration4`, stopping when the next service is unavailable. Each
returned network contains:

- `index`
- `ssid`
- `enabled`
- `channel`
- `standard`
- `beacon_type`
- `mac` / BSSID

The tool never requests or returns a Wi-Fi password or key. Treat SSIDs,
BSSIDs, and the other network identifiers as local-network information.

### `fritzbox_wifi_clients`

No arguments. It reads the associated-client entries from each available
`WLANConfiguration` service and returns, where reported:

- Wi-Fi network index and SSID
- association index and authentication state
- client MAC and IP address
- signal strength
- negotiated link speed

This is an inventory read. It does not disconnect, block, rename, reconfigure,
or otherwise change a client or Wi-Fi network.

### `fritzbox_wifi_statistics`

No arguments. It reads `GetInfo` and `GetStatistics` from each available
`WLANConfiguration` service and returns, where reported:

- network index and SSID
- total packets sent and received

This tool only reads Wi-Fi counters. It does not request security keys or
change a network, radio, or client.

### `fritzbox_wifi_channel_info`

No arguments. It reads `GetInfo` and `GetChannelInfo` from each available
`WLANConfiguration` service and returns, where reported:

- network index and SSID
- current channel and possible channels
- automatic-channel state and frequency band

This tool only reads channel telemetry. It does not change channel selection,
radio settings, or Wi-Fi security settings.

### `fritzbox_lan_config`

No arguments. It reads `LANHostConfigManagement1.GetInfo` and returns, where
reported:

- DHCP enabled state
- DHCP address range and reserved-address field
- DNS servers and local domain name
- router address and subnet mask

This tool only reads the LAN and DHCP configuration. It does not change the
address range, DHCP state, DNS settings, reservations, or router address.

### `fritzbox_ethernet_status`

No arguments. It reads `LANEthernetInterfaceConfig1.GetInfo` and
`GetStatistics` and returns, where reported:

- link enabled state, status, MAC address, maximum bit rate, and duplex mode
- bytes sent and received
- packets sent and received

This tool only reads Ethernet state and counters. It does not enable, disable,
or otherwise reconfigure the LAN interface.

### `fritzbox_logs`

Argument:

- `max_entries`: maximum number of entries, default `50`

It reads the Fritz!Box event log and returns the newest entries first. A log
entry can contain operational or security-relevant details, so avoid sharing
the raw output more broadly than necessary.

### `fritzbox_security_check`

No arguments. It reads the Fritz!Box web UI `secCheck` diagnostic page and
normalizes the returned data into these areas:

- firewall filters, exposed services, port forwards, and MyFRITZ!
- Wi-Fi encryption, WPS, Stick & Surf, MAC filtering, isolation, active devices, and networks
- user names, permissions, and the three most recent logins per user
- authentication mode and two-factor status
- NAS remote services, shares, and users
- telephony rules and SIP encryption details
- Fritz!OS update data
- ISP remote management / TR-069
- LAN services
- USP / remote access settings

This is a read of diagnostics. It does not change firewall, Wi-Fi, user,
NAS, telephony, or remote-access settings.

### `fritzbox_smart_home_devices`

No arguments. It reads the DECT smart-home inventory and reports, where a
device supports the field:

- AIN and name
- product and presence
- switch state
- temperature in °C
- battery percentage
- power in watts
- energy in Wh

Unsupported or unreported device fields are returned as `null`. This tool does
not switch a plug or thermostat.

### `fritzbox_line_stats`

No arguments. It reads noise margin and attenuation, then attempts the total
DSL error statistics: FEC, CRC, HEC, retrains, and severely errored seconds.

This is a DSL-oriented tool. Cable and fiber routers may return empty values
or an explicit unavailable error. That is an expected capability difference,
not evidence that the WAN connection is down.

## Capability discovery and generic tools

### `fritzbox_list_services`

This is read-only. It returns the services currently exposed by the router and
the actions available under each service. Optional argument:

- `filter`: case-insensitive text filter applied to service and action names,
  for example `wlan`, `host`, or `upnp`

Use it to discover model-specific support before considering a generic TR-064
call. Service names can differ across Fritz!OS versions and models; for
example, newer cable firmware can expose canonical WAN service names even when
older helper code expects shortened aliases.

### `fritzbox_call_action`

This is **not** part of the safe read-only set. It can call any TR-064 action,
including actions that change settings. Its annotation is intentionally
`read_only_hint=False` and `destructive_hint=True`.

For a separately approved read-only investigation, the safe sequence is:

1. Call `fritzbox_list_services`.
2. Select a known read action whose semantics are explicitly read-only, such
   as an appropriate `GetInfo` or `GetStatusInfo` action.
3. Pass only the required JSON arguments.
4. Do not use actions named `Set...`, `Enable`, `Disable`, `Add`, `Delete`,
   `Remove`, `Reboot`, `Disallow...`, or similar mutation operations.

The name alone is not a complete safety proof. If the action semantics are
unclear, do not call it in a read-only session.

### `fritzbox_web_action`

This is also outside the safe set. It can read a web UI page when
`apply=False`, but the same tool can write settings when `apply=True`. Known
page IDs include `secCheck`, `trafapp`, `netSet`, `netDev`, `wSet`, `wKey`,
`wGuest`, and `chan`.

For this repository's read-only operating mode, do not call this tool. In
particular, never pass `apply=True` or submit fields from a prompt that has not
been explicitly approved as a settings change.

## Non-read-only-capable tools: do not use in a read-only session

The server currently exposes 26 named tools: 18 are annotated read-only and
the following 8 are not. This is the complete list of named tools that must be
excluded from a strictly read-only session:

| Tool | Change or side effect |
| --- | --- |
| `fritzbox_set_device_profile` | Blocks or restores a device's WAN access. |
| `fritzbox_toggle_upnp` | Enables or disables UPnP port forwarding. |
| `fritzbox_toggle_wifi_guest` | Enables or disables the guest Wi-Fi network. |
| `fritzbox_wake_on_lan` | Sends a Wake-on-LAN packet and changes the target device's power state if it responds. |
| `fritzbox_smart_home_switch` | Switches a DECT smart-home device on, off, or toggles it. |
| `fritzbox_reboot` | Reboots the router and interrupts internet and telephony for about two minutes. |
| `fritzbox_call_action` | May execute any mutating TR-064 action. |
| `fritzbox_web_action` | May submit web UI settings when `apply=True`. |

Do not infer permission to use these tools from a request to “check” a setting.
Checking and changing are separate operations.

## Runtime verification

The implementation can be checked against any configured router with the
read-only smoke commands below. The result depends on the router model,
firmware, permissions, and enabled services, so the repository does not record
SSIDs, IP addresses, logs, device inventories, firmware versions, or other
live values.

Successful execution of a curated tool confirms that the local credentials,
network path, and that tool's router capability are available. It does not
prove that every optional service or every generic action is supported.

## Read-only smoke checks

Run these from a fresh terminal so the current `.env` values are loaded. They
invoke only read tools directly; they do not start a long-running server and do
not modify the router:

```bash
uv run python -c 'import asyncio, server; print(asyncio.run(server.fritzbox_wifi_status()))'
uv run python -c 'import asyncio, server; print(asyncio.run(server.fritzbox_connection_status()))'
```

If `.env` was changed in VS Code, open a new terminal before running the
commands. Existing terminals keep their old environment. In VS Code,
`python.terminal.useEnvFile` can be enabled so Python terminals receive the
project `.env` automatically.

For a protocol-level check, start the MCP server through the configured MCP
client and use one of the natural-language requests above. The server uses
stdio transport and connects lazily on the first tool call.

## Troubleshooting

### Authentication fails with HTTP 401

Use the Fritz!Box user password, not the Wi-Fi password. The user needs the
Fritz!Box settings permission; Smart Home permission is additionally needed
for the smart-home inventory. After changing `.env`, restart the MCP client or
use a fresh terminal/server process.

### `WANIPConn1` or another service is unknown

Service names vary by model and firmware. The server includes compatibility
aliases for canonical WAN names used by some newer cable firmware. Restart the
MCP server after changing code so the lazy connection is recreated, then retry
the read-only call.

### `Invalid Action` or a field is unavailable

TR-064 support is model-specific. A helper can request an action that exists
on DSL models but not on a cable model. Treat a documented `null` or
`unavailable` value as a capability result, and use `fritzbox_list_services`
before investigating a generic action.

### The service discovery page logs an `igddesc.xml` warning

The warning means the optional UPnP device description could not be retrieved.
It is not, by itself, an authentication or connection failure. Check the
actual tool result and the subsequent connection log.

## Source of truth

The tool inventory and behavior in this document are derived from
`server.py`. The safety classification follows each tool's MCP annotations and
the implementation's actual calls. The live section is deliberately narrower:
it records only read-only calls that were actually run against the current
router on the date above.

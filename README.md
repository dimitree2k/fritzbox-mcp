# fritzbox-mcp

MCP server for managing AVM Fritz!Box routers from Claude Code (or any MCP client).

Uses [fritzconnection](https://github.com/kbr/fritzconnection) to talk TR-064 over your local network. Single Python file, stdio transport, no compilation needed.

## Tools

**Curated tools** (11):

| Tool | Description |
|------|-------------|
| `fritzbox_device_list` | All network devices (name, IP, MAC, online/offline) |
| `fritzbox_device_info` | Detailed info for one device (by IP or MAC) |
| `fritzbox_connection_status` | WAN status (external IP, uptime, speed) |
| `fritzbox_port_forwards` | Active port forwarding rules |
| `fritzbox_firmware_info` | Firmware version + update availability |
| `fritzbox_wifi_status` | WiFi networks (SSID, channel, standard) |
| `fritzbox_logs` | Recent system event log |
| `fritzbox_security_check` | Full security audit (firewall, WiFi, users, NAS, telephony, TR-069) |
| `fritzbox_set_device_profile` | Block/allow a device's internet access |
| `fritzbox_toggle_upnp` | Enable/disable UPnP port forwarding |
| `fritzbox_toggle_wifi_guest` | Enable/disable guest WiFi |
| `fritzbox_wake_on_lan` | Send Wake-on-LAN packet |

**Generic tools** (4):

| Tool | Description |
|------|-------------|
| `fritzbox_list_services` | Discover all TR-064 services and actions |
| `fritzbox_call_action` | Call any TR-064 action by name |
| `fritzbox_web_action` | Read/write any Fritz!Box web UI page via data.lua |

The generic tools let the LLM discover and use any Fritz!Box capability without needing a dedicated tool. `fritzbox_list_services` + `fritzbox_call_action` cover TR-064, while `fritzbox_web_action` covers settings only available through the web UI (stealth mode, global filters, parental controls, etc.).

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/dimitree2k/fritzbox-mcp.git
cd fritzbox-mcp
```

Create a `.env` file with your Fritz!Box credentials:

```bash
cp .env.example .env
# Edit .env with your values
```

```
FRITZBOX_HOST=192.168.178.1
FRITZBOX_USER=your_username
FRITZBOX_PASSWORD=your_password
```

> Create a dedicated Fritz!Box user under System > Fritz!Box Users with "Fritz!Box Settings" and "Smart Home" permissions. Don't reuse your admin account.

Register with Claude Code:

```bash
claude mcp add -s user fritzbox -- uv run --directory /path/to/fritzbox-mcp python server.py
```

Restart Claude Code. The 15 tools will be available in all sessions.

## Fritz!Box User Setup

1. Open http://fritz.box in your browser
2. Go to **System > Fritz!Box Users > Add User**
3. Set a username and password
4. Enable permissions: **Fritz!Box Settings**, **Smart Home** (for device management)
5. Save

## How It Works

- **stdio transport** -- Claude Code spawns the server as a subprocess, communicates via stdin/stdout
- **Credentials** stay in `.env` (gitignored), never exposed to the LLM
- **Lazy connection** -- connects to the Fritz!Box on first tool call, not at startup
- **Dual API** -- TR-064 for standard operations, web UI session for security diagnostics
- **All logging to stderr** -- stdout is reserved for MCP protocol

## License

[MIT](https://opensource.org/licenses/MIT)

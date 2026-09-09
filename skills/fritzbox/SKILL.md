---
name: fritzbox
description: Manage AVM Fritz!Box routers - list devices, check WAN/WiFi status, audit security settings, block device internet access, toggle guest WiFi or UPnP, send Wake-on-LAN, read event logs, and call arbitrary TR-064 actions. Use when the user asks about their router, home network devices, port forwards, WiFi settings, or Fritz!Box security.
license: MIT
metadata:
  author: dimitree2k
  version: "1.0"
---

# Fritz!Box Control

Drive an AVM Fritz!Box router from any agent. Two access paths:

- **TR-064** (SOAP over port 49000) — standard API, most operations. Use via [fritzconnection](https://github.com/kbr/fritzconnection).
- **Web UI** (`data.lua`) — settings not exposed via TR-064 (stealth mode, global filters, parental controls).

## Setup

Requires Python 3.11+ and a Fritz!Box user account (System > Fritz!Box Users) with **Fritz!Box Settings** and **Smart Home** permissions. Never use the admin account.

```bash
pip install fritzconnection requests
```

Credentials come from environment variables (or a `.env` file):

```
FRITZBOX_HOST=192.168.178.1   # default
FRITZBOX_USER=your_username
FRITZBOX_PASSWORD=your_password
```

## Quick start

```python
from fritzconnection import FritzConnection
fc = FritzConnection(address=host, user=user, password=password)
```

## Common recipes

### List network devices

```python
from fritzconnection.lib.fritzhosts import FritzHosts
hosts = FritzHosts(fc=fc)
for h in hosts.get_hosts_info():
    print(h["name"], h["ip"], "online" if h["status"] else "offline")
```

### WAN / connection status

```python
from fritzconnection.lib.fritzstatus import FritzStatus
fs = FritzStatus(fc=fc)
print(fs.is_connected, fs.external_ip, fs.str_uptime, fs.update_available)
```

### Discover everything else (TR-064)

```python
# All services and their actions:
for name, service in fc.services.items():
    print(name, sorted(service.actions))
# Call any action:
result = fc.call_action("DeviceInfo1", "GetInfo")
```

Useful services/actions: `X_AVM-DE_HostFilter1` (WAN block per device), `X_AVM-DE_UPnP1`, `WLANConfiguration{1..4}` (WiFi), `Hosts1:X_AVM-DE_WakeOnLANByMACAddress`.

### Block/allow a device's internet access

```python
fc.call_action("X_AVM-DE_HostFilter1", "DisallowWANAccessByIP",
               NewIPv4Address="192.168.178.26", NewDisallow=True)
# Verify:
fc.call_action("X_AVM-DE_HostFilter1", "GetWANAccessByIP",
               NewIPv4Address="192.168.178.26")
```

### Web UI pages (data.lua) — for settings without TR-064 support

Authenticate via PBKDF2 challenge against `/login_sid.lua?version=2`, then POST form fields with `sid` + `page` to `http://<host>/data.lua`. Known page IDs: `trafapp` (global filters/stealth), `secCheck` (security diagnostics), `netSet`, `wSet`, `wGuest`. If the response `pid` is `overview`, the page was rejected.

## Safety rules

- Write operations (`apply=True` posts, `SetConfig`, `DisallowWANAccess`) need explicit user intent - confirm before changing firewall, UPnP, or per-device blocking.
- Never expose or log the password; never return WiFi keys.
- Prefer read-only calls unless asked to change something.

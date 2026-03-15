#!/usr/bin/env python3
"""Fritz!Box MCP Server — Claude Code integration via fritzconnection."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fritzconnection import FritzConnection
from fritzconnection.lib.fritzhosts import FritzHosts
from fritzconnection.lib.fritzstatus import FritzStatus
from fritzconnection.lib.fritzwlan import FritzWLAN
from mcp.server.fastmcp import FastMCP

# All logging to stderr — stdout is reserved for MCP stdio transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("fritzbox-mcp")

# Load .env from project directory (credentials never in Claude's settings)
load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Fritz!Box connection (lazy singleton)
# ---------------------------------------------------------------------------

_fc: FritzConnection | None = None
_fh: FritzHosts | None = None
_fs: FritzStatus | None = None
_fw: FritzWLAN | None = None


def _get_fc() -> FritzConnection:
    global _fc
    if _fc is None:
        host = os.environ.get("FRITZBOX_HOST", "192.168.178.1")
        user = os.environ["FRITZBOX_USER"]
        password = os.environ["FRITZBOX_PASSWORD"]
        _fc = FritzConnection(address=host, user=user, password=password)
        log.info("Connected to Fritz!Box %s at %s", _fc.modelname, host)
    return _fc


def _get_hosts() -> FritzHosts:
    global _fh
    if _fh is None:
        _fh = FritzHosts(fc=_get_fc())
    return _fh


def _get_status() -> FritzStatus:
    global _fs
    if _fs is None:
        _fs = FritzStatus(fc=_get_fc())
    return _fs


def _get_wlan() -> FritzWLAN:
    global _fw
    if _fw is None:
        _fw = FritzWLAN(fc=_get_fc())
    return _fw


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("fritzbox")

# ---- Read tools -----------------------------------------------------------


@mcp.tool()
async def fritzbox_device_list() -> str:
    """List all known network devices with name, IP, MAC, online status, and connection type."""
    hosts = _get_hosts()
    entries = hosts.get_hosts_info()
    rows = []
    for h in entries:
        rows.append({
            "name": h.get("name", ""),
            "ip": h.get("ip", ""),
            "mac": h.get("mac", ""),
            "status": "online" if h.get("status") else "offline",
            "interface": h.get("interface_type", ""),
        })
    rows.sort(key=lambda r: (r["status"] != "online", r["name"].lower()))
    return json.dumps(rows, indent=2)


@mcp.tool()
async def fritzbox_device_info(ip_or_mac: str) -> str:
    """Get detailed info for a specific device by IP address or MAC address.

    Args:
        ip_or_mac: Device IP address (e.g. 192.168.178.20) or MAC address (e.g. AA:BB:CC:DD:EE:FF)
    """
    hosts = _get_hosts()
    if ":" in ip_or_mac and not ip_or_mac.replace(":", "").replace(".", "").isdigit():
        # MAC address
        info = hosts.get_specific_host_entry(ip_or_mac)
    else:
        # IP address
        info = hosts.get_specific_host_entry_by_ip(ip_or_mac)
    return json.dumps(info, indent=2, default=str)


@mcp.tool()
async def fritzbox_connection_status() -> str:
    """Get WAN connection info: external IP, uptime, link speed, DNS, connection state."""
    fs = _get_status()
    fc = _get_fc()

    # Get DNS servers via raw call
    dns_info = {}
    try:
        dns_info = fc.call_action("WANIPConnection1", "GetDNSServers")
    except Exception:
        try:
            dns_info = fc.call_action("WANPPPConnection1", "GetDNSServers")
        except Exception:
            pass

    result = {
        "connected": fs.is_connected,
        "linked": fs.is_linked,
        "external_ip": fs.external_ip,
        "external_ipv6": fs.external_ipv6,
        "uptime": fs.str_uptime,
        "max_bit_rate": fs.str_max_bit_rate,
        "max_linked_bit_rate": fs.str_max_linked_bit_rate,
        "transmission_rate": fs.str_transmission_rate,
        "model": fs.modelname,
    }
    if dns_info:
        result["dns_servers"] = dns_info
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def fritzbox_port_forwards() -> str:
    """List all active port forwarding rules."""
    fc = _get_fc()
    forwards = []
    try:
        count_result = fc.call_action("WANIPConnection1", "GetPortMappingNumberOfEntries")
        count = count_result.get("NewPortMappingNumberOfEntries", 0)
        for i in range(count):
            entry = fc.call_action(
                "WANIPConnection1",
                "GetGenericPortMappingEntry",
                NewPortMappingIndex=i,
            )
            forwards.append({
                "protocol": entry.get("NewProtocol", ""),
                "external_port": entry.get("NewExternalPort", ""),
                "internal_host": entry.get("NewInternalClient", ""),
                "internal_port": entry.get("NewInternalPort", ""),
                "enabled": entry.get("NewEnabled", False),
                "description": entry.get("NewPortMappingDescription", ""),
            })
    except Exception as e:
        return json.dumps({"error": str(e), "note": "No port forwards or service unavailable"})
    return json.dumps(forwards, indent=2)


@mcp.tool()
async def fritzbox_firmware_info() -> str:
    """Check current firmware version and whether an update is available."""
    fs = _get_status()
    fc = _get_fc()
    device_info = fc.call_action("DeviceInfo1", "GetInfo")
    result = {
        "model": fs.modelname,
        "firmware_version": device_info.get("NewSoftwareVersion", "unknown"),
        "update_available": fs.update_available,
        "device_uptime": fs.str_uptime,
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def fritzbox_wifi_status() -> str:
    """Get WiFi network status: enabled state, channel, SSID, standard. No passwords exposed."""
    fc = _get_fc()
    networks = []
    for service_idx in range(1, 5):
        service = f"WLANConfiguration{service_idx}"
        try:
            info = fc.call_action(service, "GetInfo")
            networks.append({
                "index": service_idx,
                "ssid": info.get("NewSSID", ""),
                "enabled": info.get("NewEnable", False),
                "channel": info.get("NewChannel", 0),
                "standard": info.get("NewStandard", ""),
                "beacon_type": info.get("NewBeaconType", ""),
                "mac": info.get("NewBSSID", ""),
            })
        except Exception:
            break
    return json.dumps(networks, indent=2)


@mcp.tool()
async def fritzbox_logs(max_entries: int = 50) -> str:
    """Get recent Fritz!Box system event log entries.

    Args:
        max_entries: Maximum number of log entries to return (default 50)
    """
    fs = _get_status()
    log_entries = fs.get_avm_device_log()
    # log_entries is a list of strings, newest first
    entries = log_entries[:max_entries] if log_entries else []
    return json.dumps(entries, indent=2, ensure_ascii=False)


# ---- Generic TR-064 tools ------------------------------------------------


@mcp.tool()
async def fritzbox_list_services(filter: str = "") -> str:
    """List all TR-064 services available on the Fritz!Box, with their actions.

    Use this to discover what the router supports before calling fritzbox_call_action.

    Args:
        filter: Optional case-insensitive filter on service or action names (e.g. "wlan", "host", "upnp")
    """
    fc = _get_fc()
    result = {}
    for service_name in sorted(fc.services):
        service = fc.services[service_name]
        actions = sorted(service.actions)
        if filter:
            f = filter.lower()
            if f not in service_name.lower() and not any(f in a.lower() for a in actions):
                continue
        result[service_name] = actions
    return json.dumps(result, indent=2)


@mcp.tool()
async def fritzbox_call_action(service: str, action: str, arguments: str = "{}") -> str:
    """Call any TR-064 action on the Fritz!Box.

    Use fritzbox_list_services to discover available services and actions first.
    Arguments are passed as a JSON object with NewXxx parameter names.

    Examples:
        service="X_AVM-DE_HostFilter1", action="GetWANAccessByIP", arguments='{"NewIPv4Address": "192.168.178.26"}'
        service="DeviceInfo1", action="GetInfo", arguments='{}'

    Args:
        service: TR-064 service name (e.g. "DeviceInfo1", "X_AVM-DE_UPnP1")
        action: Action name (e.g. "GetInfo", "SetConfig")
        arguments: JSON object of action arguments (default: "{}")
    """
    fc = _get_fc()
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return json.dumps({"success": False, "error": f"Invalid JSON arguments: {e}"})
    try:
        result = fc.call_action(service, action, **args)
        return json.dumps({
            "success": True,
            "service": service,
            "action": action,
            "result": result,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ---- Write tools (restricted) --------------------------------------------


@mcp.tool()
async def fritzbox_set_device_profile(ip_address: str, disallow: bool) -> str:
    """Block or allow a device's internet (WAN) access by IP address.

    Args:
        ip_address: Device IP address (e.g. 192.168.178.26)
        disallow: True to block internet access, False to restore it
    """
    fc = _get_fc()
    try:
        fc.call_action(
            "X_AVM-DE_HostFilter1",
            "DisallowWANAccessByIP",
            NewIPv4Address=ip_address,
            NewDisallow=disallow,
        )
        # Verify
        check = fc.call_action(
            "X_AVM-DE_HostFilter1",
            "GetWANAccessByIP",
            NewIPv4Address=ip_address,
        )
        return json.dumps({
            "success": True,
            "ip": ip_address,
            "wan_blocked": check.get("NewDisallow", None),
            "wan_access": check.get("NewWANAccess", None),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
async def fritzbox_toggle_upnp(enabled: bool) -> str:
    """Enable or disable UPnP port forwarding on the router.

    When disabled, devices on the network cannot automatically open ports to the internet.

    Args:
        enabled: True to enable UPnP, False to disable
    """
    fc = _get_fc()
    try:
        fc.call_action(
            "X_AVM-DE_UPnP1",
            "SetConfig",
            NewEnable=enabled,
            NewUPnPMediaServer=False,
        )
        # Verify
        check = fc.call_action("X_AVM-DE_UPnP1", "GetInfo")
        return json.dumps({
            "success": True,
            "upnp_enabled": check.get("NewEnable", None),
            "upnp_media_server": check.get("NewUPnPMediaServer", None),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
async def fritzbox_toggle_wifi_guest(enabled: bool) -> str:
    """Enable or disable the guest WiFi network.

    Args:
        enabled: True to enable guest WiFi, False to disable
    """
    fw = _get_wlan()
    try:
        # Guest WiFi is typically WLANConfiguration3
        fc = _get_fc()
        if enabled:
            fc.call_action("WLANConfiguration3", "Enable")
        else:
            fc.call_action("WLANConfiguration3", "Disable")
        # Verify
        info = fc.call_action("WLANConfiguration3", "GetInfo")
        return json.dumps({
            "success": True,
            "guest_wifi_enabled": info.get("NewEnable", None),
            "ssid": info.get("NewSSID", ""),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool()
async def fritzbox_wake_on_lan(mac_address: str) -> str:
    """Send a Wake-on-LAN magic packet to wake a device.

    Args:
        mac_address: Device MAC address (e.g. AA:BB:CC:DD:EE:FF)
    """
    hosts = _get_hosts()
    try:
        hosts.set_wakeonlan_status(mac_address, enabled=True)
        fc = _get_fc()
        fc.call_action(
            "Hosts1",
            "X_AVM-DE_WakeOnLANByMACAddress",
            NewMACAddress=mac_address,
        )
        return json.dumps({
            "success": True,
            "mac": mac_address,
            "message": "WOL packet sent",
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    log.info("Starting Fritz!Box MCP server (stdio transport)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

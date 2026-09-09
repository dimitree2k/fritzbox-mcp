"""Tests for fritzbox-mcp server.

Run: uv run python -m unittest test_server.py -v
No real Fritz!Box needed: TR-064/AHA calls are faked at the
call_action / property boundary.
"""

import asyncio
import json
import unittest

from mcp import Client

import server


def _fake_fc():
    class FakeFC:
        def __init__(self):
            self.calls = []

        def call_action(self, service, action, **kwargs):
            self.calls.append((service, action))
            if action == "GetStatisticsTotal":
                return {
                    "NewFECErrors": 12,
                    "NewCRCErrors": 3,
                    "NewHECErrors": 0,
                    "NewLinkRetrain": 2,
                    "NewSeverelyErroredSecs": 1,
                }
            return {}

        def call_http(self, command, identifier=None, **kwargs):
            self.calls.append(("AHA", command))
            return {"content-type": "text/plain", "encoding": "utf-8", "content": ""}

        def reboot(self):
            self.calls.append(("DeviceConfig1", "Reboot"))

    return FakeFC()


class FakeStatus:
    str_noise_margin = ("6.5 dB", "8.1 dB")
    str_attenuation = ("2.0 dB", "18.4 dB")


def _ha_device_fixture(**overrides):
    """Realistic GetGenericDeviceInfos payload (FRITZ!DECT 200)."""
    d = {
        "NewAIN": "08761 0114116",
        "NewDeviceName": "FRITZ!DECT 200 #1",
        "NewProductName": "FRITZ!DECT 200",
        "NewPresent": "CONNECTED",
        "NewSwitchIsValid": "VALID",
        "NewSwitchState": "ON",
        "NewTemperatureIsValid": "VALID",
        "NewTemperatureCelsius": "225",  # tenth-degrees -> 22.5 C
        "NewMultimeterIsValid": "VALID",
        "NewMultimeterPower": 1673,      # mW -> 1.67 W
        "NewMultimeterEnergy": 5182,     # Wh
        "NewBatteryLevel": "",           # mains-powered -> null
    }
    d.update(overrides)
    return d


class TestToolSurface(unittest.IsolatedAsyncioTestCase):
    async def _tools(self) -> dict:
        # Client must be entered and exited within one task
        async with Client(server.mcp) as c:
            result = await c.list_tools()
            return {t.name: t for t in result.tools}

    def test_all_26_tools_listed(self):
        tools = asyncio.run(self._tools())
        expected = {
            "fritzbox_device_list", "fritzbox_device_info", "fritzbox_connection_status",
            "fritzbox_port_forwards", "fritzbox_firmware_info", "fritzbox_wifi_status",
            "fritzbox_wifi_clients",
            "fritzbox_lan_config",
            "fritzbox_ethernet_status",
            "fritzbox_wifi_statistics",
            "fritzbox_wifi_channel_info",
            "fritzbox_wan_link_status",
            "fritzbox_wan_traffic_stats",
            "fritzbox_logs", "fritzbox_security_check", "fritzbox_set_device_profile",
            "fritzbox_toggle_upnp", "fritzbox_toggle_wifi_guest", "fritzbox_wake_on_lan",
            "fritzbox_web_action", "fritzbox_list_services", "fritzbox_call_action",
            "fritzbox_smart_home_devices", "fritzbox_smart_home_switch",
            "fritzbox_line_stats", "fritzbox_reboot",
        }
        self.assertEqual(expected, set(tools))

    def test_read_only_hints(self):
        tools = asyncio.run(self._tools())
        for name in [
            "fritzbox_device_list", "fritzbox_device_info", "fritzbox_connection_status",
            "fritzbox_port_forwards", "fritzbox_firmware_info", "fritzbox_wifi_status",
            "fritzbox_wifi_clients",
            "fritzbox_lan_config",
            "fritzbox_ethernet_status",
            "fritzbox_wifi_statistics",
            "fritzbox_wifi_channel_info",
            "fritzbox_wan_link_status",
            "fritzbox_wan_traffic_stats",
            "fritzbox_logs", "fritzbox_security_check", "fritzbox_list_services",
            "fritzbox_smart_home_devices", "fritzbox_line_stats",
        ]:
            self.assertTrue(tools[name].annotations.read_only_hint, name)

    def test_idempotent_write_hints(self):
        tools = asyncio.run(self._tools())
        for name in ["fritzbox_set_device_profile", "fritzbox_toggle_upnp", "fritzbox_toggle_wifi_guest"]:
            ann = tools[name].annotations
            self.assertFalse(ann.read_only_hint, name)
            self.assertTrue(ann.idempotent_hint, name)

    def test_wake_on_lan_not_destructive(self):
        tools = asyncio.run(self._tools())
        ann = tools["fritzbox_wake_on_lan"].annotations
        self.assertFalse(ann.read_only_hint)
        self.assertFalse(ann.destructive_hint)

    def test_destructive_hints(self):
        tools = asyncio.run(self._tools())
        for name in ["fritzbox_web_action", "fritzbox_call_action", "fritzbox_reboot", "fritzbox_smart_home_switch"]:
            ann = tools[name].annotations
            self.assertFalse(ann.read_only_hint, name)
            self.assertTrue(ann.destructive_hint, name)

    def test_open_world_false_everywhere(self):
        tools = asyncio.run(self._tools())
        for name, tool in tools.items():
            self.assertFalse(tool.annotations.open_world_hint, name)


class TestWifiClients(unittest.IsolatedAsyncioTestCase):
    async def test_lists_associated_clients_without_write_actions(self):
        class FakeWifiFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service != "WLANConfiguration1":
                    raise Exception("unsupported service")
                if action == "GetInfo":
                    return {"NewSSID": "Main WiFi"}
                if action == "GetTotalAssociations":
                    return {"NewTotalAssociations": 1}
                if action == "GetGenericAssociatedDeviceInfo":
                    return {
                        "NewAssociatedDeviceAuthState": "Authenticated",
                        "NewAssociatedDeviceMACAddress": "AA:BB:CC:DD:EE:FF",
                        "NewAssociatedDeviceIPAddress": "192.168.178.20",
                        "NewX_AVM-DE_SignalStrength": 72,
                        "NewX_AVM-DE_Speed": 866,
                    }
                raise Exception("unsupported service")

        old_fc = server._fc
        fc = FakeWifiFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_wifi_clients())
        finally:
            server._fc = old_fc

        self.assertEqual(result, [{
            "network_index": 1,
            "ssid": "Main WiFi",
            "index": 0,
            "status": "Authenticated",
            "mac": "AA:BB:CC:DD:EE:FF",
            "ip": "192.168.178.20",
            "signal": 72,
            "speed": 866,
        }])
        self.assertTrue(all(action in {"GetInfo", "GetTotalAssociations", "GetGenericAssociatedDeviceInfo"}
                            for _, action, _ in fc.calls))


class TestLanConfig(unittest.IsolatedAsyncioTestCase):
    async def test_reads_lan_config_without_write_actions(self):
        class FakeLanFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service == "LANHostConfigManagement1" and action == "GetInfo":
                    return {
                        "NewDHCPServerEnable": True,
                        "NewMinAddress": "192.168.178.20",
                        "NewMaxAddress": "192.168.178.200",
                        "NewReservedAddresses": "",
                        "NewDNSServers": "192.168.178.1",
                        "NewDomainName": "fritz.box",
                        "NewIPRouters": "192.168.178.1",
                        "NewSubnetMask": "255.255.255.0",
                    }
                raise Exception("unsupported action")

        old_fc = server._fc
        fc = FakeLanFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_lan_config())
        finally:
            server._fc = old_fc

        self.assertEqual(result, {
            "dhcp_enabled": True,
            "min_address": "192.168.178.20",
            "max_address": "192.168.178.200",
            "reserved_addresses": "",
            "dns_servers": "192.168.178.1",
            "domain_name": "fritz.box",
            "ip_routers": "192.168.178.1",
            "subnet_mask": "255.255.255.0",
        })
        self.assertEqual(fc.calls, [("LANHostConfigManagement1", "GetInfo", {})])


class TestEthernetStatus(unittest.IsolatedAsyncioTestCase):
    async def test_reads_ethernet_status_and_statistics(self):
        class FakeEthernetFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service != "LANEthernetInterfaceConfig1":
                    raise Exception("unsupported service")
                if action == "GetInfo":
                    return {
                        "NewEnable": True,
                        "NewStatus": "Up",
                        "NewMACAddress": "AA:BB:CC:DD:EE:FF",
                        "NewMaxBitRate": "Auto",
                        "NewDuplexMode": "Auto",
                    }
                if action == "GetStatistics":
                    return {
                        "NewBytesSent": 100,
                        "NewBytesReceived": 200,
                        "NewPacketsSent": 10,
                        "NewPacketsReceived": 20,
                    }
                raise Exception("unsupported action")

        old_fc = server._fc
        fc = FakeEthernetFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_ethernet_status())
        finally:
            server._fc = old_fc

        self.assertEqual(result, {
            "enabled": True,
            "status": "Up",
            "mac": "AA:BB:CC:DD:EE:FF",
            "max_bit_rate": "Auto",
            "duplex_mode": "Auto",
            "bytes_sent": 100,
            "bytes_received": 200,
            "packets_sent": 10,
            "packets_received": 20,
        })
        self.assertEqual(
            fc.calls,
            [
                ("LANEthernetInterfaceConfig1", "GetInfo", {}),
                ("LANEthernetInterfaceConfig1", "GetStatistics", {}),
            ],
        )


class TestWifiStatistics(unittest.IsolatedAsyncioTestCase):
    async def test_reads_wifi_statistics_without_write_actions(self):
        class FakeWifiStatsFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service == "WLANConfiguration1" and action == "GetInfo":
                    return {"NewSSID": "Main WiFi"}
                if service == "WLANConfiguration1" and action == "GetStatistics":
                    return {
                        "NewTotalPacketsSent": 100,
                        "NewTotalPacketsReceived": 200,
                    }
                raise Exception("unsupported service")

        old_fc = server._fc
        fc = FakeWifiStatsFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_wifi_statistics())
        finally:
            server._fc = old_fc

        self.assertEqual(result, [{
            "index": 1,
            "ssid": "Main WiFi",
            "packets_sent": 100,
            "packets_received": 200,
        }])
        self.assertTrue(all(action in {"GetInfo", "GetStatistics"} for _, action, _ in fc.calls))


class TestWifiChannelInfo(unittest.IsolatedAsyncioTestCase):
    async def test_reads_wifi_channel_info_without_write_actions(self):
        class FakeWifiChannelFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service == "WLANConfiguration1" and action == "GetInfo":
                    return {"NewSSID": "Main WiFi"}
                if service == "WLANConfiguration1" and action == "GetChannelInfo":
                    return {
                        "NewChannel": 1,
                        "NewPossibleChannels": "1,2,3",
                        "NewX_AVM-DE_AutoChannelEnabled": True,
                        "NewX_AVM-DE_FrequencyBand": "2400",
                    }
                raise Exception("unsupported service")

        old_fc = server._fc
        fc = FakeWifiChannelFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_wifi_channel_info())
        finally:
            server._fc = old_fc

        self.assertEqual(result, [{
            "index": 1,
            "ssid": "Main WiFi",
            "channel": 1,
            "possible_channels": "1,2,3",
            "auto_channel": True,
            "frequency_band": "2400",
        }])
        self.assertTrue(all(action in {"GetInfo", "GetChannelInfo"} for _, action, _ in fc.calls))


class TestWanLinkStatus(unittest.IsolatedAsyncioTestCase):
    async def test_reads_wan_link_properties_without_write_actions(self):
        class FakeWanFC:
            def __init__(self):
                self.calls = []

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service == "WANCommonInterfaceConfig1" and action == "GetCommonLinkProperties":
                    return {
                        "NewWANAccessType": "X_AVM-DE_Cable",
                        "NewPhysicalLinkStatus": "Up",
                        "NewLayer1UpstreamMaxBitRate": 100,
                        "NewLayer1DownstreamMaxBitRate": 1000,
                        "NewX_AVM-DE_UpstreamCurrentMaxSpeed": 80,
                        "NewX_AVM-DE_DownstreamCurrentMaxSpeed": 900,
                    }
                raise Exception("unsupported action")

        old_fc = server._fc
        fc = FakeWanFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_wan_link_status())
        finally:
            server._fc = old_fc

        self.assertEqual(result, {
            "access_type": "X_AVM-DE_Cable",
            "physical_link_status": "Up",
            "upstream_max_bit_rate": 100,
            "downstream_max_bit_rate": 1000,
            "upstream_current_max_speed": 80,
            "downstream_current_max_speed": 900,
        })
        self.assertEqual(
            fc.calls,
            [("WANCommonInterfaceConfig1", "GetCommonLinkProperties", {})],
        )


class TestWanTrafficStats(unittest.IsolatedAsyncioTestCase):
    async def test_reads_wan_counters_without_write_actions(self):
        class FakeWanFC:
            def __init__(self):
                self.calls = []
                self.values = {
                    "GetTotalBytesSent": {"NewTotalBytesSent": 100},
                    "GetTotalBytesReceived": {"NewTotalBytesReceived": 200},
                    "GetTotalPacketsSent": {"NewTotalPacketsSent": 10},
                    "GetTotalPacketsReceived": {"NewTotalPacketsReceived": 20},
                }

            def call_action(self, service, action, **kwargs):
                self.calls.append((service, action, kwargs))
                if service == "WANCommonInterfaceConfig1" and action in self.values:
                    return self.values[action]
                raise Exception("unsupported action")

        old_fc = server._fc
        fc = FakeWanFC()
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_wan_traffic_stats())
        finally:
            server._fc = old_fc

        self.assertEqual(result, {
            "bytes_sent": 100,
            "bytes_received": 200,
            "packets_sent": 10,
            "packets_received": 20,
        })
        self.assertEqual(
            fc.calls,
            [
                ("WANCommonInterfaceConfig1", "GetTotalBytesSent", {}),
                ("WANCommonInterfaceConfig1", "GetTotalBytesReceived", {}),
                ("WANCommonInterfaceConfig1", "GetTotalPacketsSent", {}),
                ("WANCommonInterfaceConfig1", "GetTotalPacketsReceived", {}),
            ],
        )


class TestSmartHomeParsing(unittest.TestCase):
    def test_full_device_normalization(self):
        out = server._normalize_ha_device(_ha_device_fixture())
        self.assertEqual(out["ain"], "08761 0114116")
        self.assertEqual(out["name"], "FRITZ!DECT 200 #1")
        self.assertTrue(out["present"])
        self.assertEqual(out["temperature_c"], 22.5)
        self.assertEqual(out["power_w"], 1.67)
        self.assertEqual(out["energy_wh"], 5182.0)
        self.assertIsNone(out["battery_percent"])
        self.assertEqual(out["switch_state"], "on")

    def test_absent_capability_fields_are_null(self):
        bare = _ha_device_fixture(
            NewSwitchIsValid="INVALID", NewSwitchState="",
            NewTemperatureIsValid="INVALID", NewTemperatureCelsius="255",
            NewMultimeterIsValid="INVALID", NewMultimeterPower="",
            NewMultimeterEnergy="", NewPresent="DISCONNECTED",
        )
        out = server._normalize_ha_device(bare)
        self.assertFalse(out["present"])
        self.assertIsNone(out["temperature_c"])
        self.assertIsNone(out["power_w"])
        self.assertIsNone(out["energy_wh"])
        self.assertIsNone(out["switch_state"])


class TestLineStats(unittest.IsolatedAsyncioTestCase):
    async def test_counters_parsed(self):
        old_fc = server._fc
        server._fc = _fake_fc()
        server._fs = FakeStatus()
        try:
            result = json.loads(await server.fritzbox_line_stats())
        finally:
            server._fc = old_fc
            server._fs = None
        self.assertEqual(result["noise_margin_db"], ["6.5 dB", "8.1 dB"])
        self.assertEqual(result["dsl_errors"]["fec_errors"], 12)
        self.assertEqual(result["dsl_errors"]["crc_errors"], 3)
        self.assertEqual(result["dsl_errors"]["resync_count"], 2)

    async def test_cable_box_degrades_gracefully(self):
        old_fc = server._fc
        server._fc = _fake_fc()
        server._fc.call_action = lambda *a, **k: (_ for _ in ()).throw(Exception("no such service"))
        server._fs = FakeStatus()
        try:
            result = json.loads(await server.fritzbox_line_stats())
        finally:
            server._fc = old_fc
            server._fs = None
        self.assertIn("unavailable", result["dsl_errors"]["error"])


class TestSwitchValidation(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_state_rejected_without_router_call(self):
        fc = _fake_fc()
        old_fc = server._fc
        server._fc = fc
        try:
            result = json.loads(await server.fritzbox_smart_home_switch("123", "explode"))
        finally:
            server._fc = old_fc
        self.assertFalse(result["success"])
        self.assertEqual(fc.calls, [])  # nothing reached the router


if __name__ == "__main__":
    unittest.main()

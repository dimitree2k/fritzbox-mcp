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

    def test_all_19_tools_listed(self):
        tools = asyncio.run(self._tools())
        expected = {
            "fritzbox_device_list", "fritzbox_device_info", "fritzbox_connection_status",
            "fritzbox_port_forwards", "fritzbox_firmware_info", "fritzbox_wifi_status",
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

"""隔离宿主 SDK 的插件入口检查；不代表已在真实 MoviePilot 中安装验证。"""

from abc import ABC, abstractmethod
import json
import unittest
from unittest.mock import patch

from helpers import PLUGIN_DIR, load_plugin


class HostBase(ABC):
    @abstractmethod
    def init_plugin(self, config=None): ...
    @abstractmethod
    def get_state(self): ...
    @abstractmethod
    def get_api(self): ...
    @abstractmethod
    def get_form(self): ...
    @abstractmethod
    def get_page(self): ...
    @abstractmethod
    def stop_service(self): ...


class PluginContractTests(unittest.TestCase):
    def setUp(self):
        module = self.enterContext(load_plugin(HostBase))
        self.module = module
        self.plugin = module.WindowsQbSmb()
        self.addCleanup(self.plugin.stop_service)

    def test_invalid_configuration_never_enables_runtime(self):
        self.plugin.init_plugin({"enabled": True, "windows_root": "E:/Downloads"})
        self.assertFalse(self.plugin.get_state())
        self.assertEqual(self.plugin.get_api(), [])
        self.plugin.stop_service()
        self.plugin.stop_service()
        self.assertFalse(self.plugin.get_state())

    def test_forms_are_serializable_and_mark_development_status(self):
        form, defaults = self.plugin.get_form()
        text = json.dumps(form, ensure_ascii=False)
        self.assertIn("实验版", text)
        self.assertIn("windows_root", text)
        self.assertIn("MoviePilot 存储路径", text)
        self.assertIn("local:/downloads", text)
        self.assertNotIn("必须选择 SMB", text)
        self.assertEqual(defaults["smb_root"], "smb:/")
        self.assertFalse(defaults["enabled"])
        json.dumps(self.plugin.get_page(), ensure_ascii=False)

    def test_disabled_does_not_resolve_host(self):
        with patch.object(self.module, "RuntimeAdapter") as adapter:
            self.plugin.init_plugin({"enabled": False})
            adapter.assert_not_called()

    def test_reinitialize_stops_previous_and_scheduler_failure_disables(self):
        config = {"enabled": True, "downloader": "Windows qB",
                  "windows_root": "E:/Downloads", "smb_root": "smb:/"}
        with patch.object(self.module, "RuntimeAdapter") as factory:
            first = factory.return_value
            self.plugin.init_plugin(config)
            self.assertTrue(self.plugin.get_state())
            self.assertEqual(self.plugin.get_service()[0]["kwargs"], {"seconds": 30})
            self.plugin.init_plugin(config)
            first.stop.assert_called_once()
            first.refresh.side_effect = RuntimeError("契约已改变")
            self.plugin._check_runtime()
            self.assertFalse(self.plugin.get_state())
            self.assertIn("契约已改变", self.plugin.get_page()[0]["text"])

    def test_manifest_matches_entry(self):
        root = PLUGIN_DIR.parents[1]
        metadata = json.loads((root / "package.v3.json").read_text())["WindowsQbSmb"]
        self.assertEqual(metadata["version"], self.plugin.plugin_version)
        self.assertEqual(metadata["name"], self.plugin.plugin_name)
        self.assertEqual(metadata["description"], self.plugin.plugin_desc)

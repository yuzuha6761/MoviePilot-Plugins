"""隔离宿主 SDK 的插件入口检查；不代表已在真实 MoviePilot 中安装验证。"""

from abc import ABC, abstractmethod
import json
from types import SimpleNamespace
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

    def test_forms_are_serializable_and_show_usage_hints(self):
        form, defaults = self.plugin.get_form()
        text = json.dumps(form, ensure_ascii=False)
        self.assertNotIn("实验版", text)
        self.assertNotIn("方法契约", text)
        self.assertIn("windows_root", text)
        self.assertIn("转换前路径前缀", text)
        self.assertIn("转换后路径前缀", text)
        self.assertIn("/downloads", text)
        self.assertNotIn("存储路径", text)
        self.assertNotIn("SMB", text)
        self.assertIn("添加映射", text)
        self.assertIn("删除映射", text)
        self.assertIn("所选下载器共用", text)
        self.assertEqual(defaults["downloaders"], [])
        self.assertEqual(defaults["mappings"], [])
        self.assertFalse(defaults["enabled"])
        json.dumps(self.plugin.get_page(), ensure_ascii=False)

    def test_downloader_options_use_sdk_and_filter_disabled_or_other_types(self):
        from app.sdk.services import ServiceConfigHelper
        ServiceConfigHelper.get_downloader_configs.return_value = [
            SimpleNamespace(name="Windows qB", enabled=True, type="qbittorrent"),
            SimpleNamespace(name="Second qB", enabled=True, type="qbittorrent"),
            SimpleNamespace(name="Disabled", enabled=False, type="qbittorrent"),
            SimpleNamespace(name="Transmission", enabled=True, type="transmission"),
        ]
        form, _ = self.plugin.get_form()
        select = next(item["props"] for item in form[0]["content"]
                      if item.get("props", {}).get("model") == "downloaders")
        self.assertEqual(select["items"], [{"title": n, "value": n}
                                         for n in ("Windows qB", "Second qB")])
        self.assertTrue(select["multiple"])

    def test_discovery_failure_still_allows_editing_configuration(self):
        with patch.object(self.module, "get_downloader_names", side_effect=RuntimeError("offline")):
            form, _ = self.plugin.get_form()
        self.assertIn("下载器列表读取失败", json.dumps(form, ensure_ascii=False))

    def test_current_configuration_reopens_without_writing_configuration(self):
        config = {"enabled": False, "downloaders": ["Windows qB"], "mappings": [
            {"windows_root": "E:/Downloads", "storage_root": "/downloads"},
            {"windows_root": "F:/Temp", "storage_root": "/temp"},
        ]}
        self.plugin.init_plugin(config)
        _, defaults = self.plugin.get_form()
        # 与宿主 API 一样，将持久化配置覆盖到表单默认值上。
        merged = {**defaults, **config}
        self.assertEqual(merged["downloaders"], config["downloaders"])
        self.assertEqual(merged["mappings"], config["mappings"])
        self.assertEqual(self.plugin._config, config)


    def test_disabled_does_not_resolve_host(self):
        with patch.object(self.module, "RuntimeAdapter") as adapter:
            self.plugin.init_plugin({"enabled": False})
            adapter.assert_not_called()

    def test_reinitialize_stops_previous_and_scheduler_failure_disables(self):
        config = {
            "downloaders": ["Windows qB"],
            "mappings": [
                {"windows_root": "E:/Downloads", "storage_root": "smb:/"},
            ],
            "enabled": True,
        }
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
        import tomllib
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], self.plugin.plugin_version)
        self.assertIn("v" + self.plugin.plugin_version, metadata["history"])

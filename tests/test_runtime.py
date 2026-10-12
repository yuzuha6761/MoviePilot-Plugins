"""纯离线宿主替身；不导入真实 MP、不访问下载器、SMB 或数据库。"""

from concurrent.futures import ThreadPoolExecutor
import ast
from functools import wraps
from pathlib import Path
import unittest
from unittest.mock import patch

from helpers import load_plugin


class HostPaths:
    def normalize_path(self, path, downloader):
        return "original-send:" + str(path)

    def normalize_return_path(self, path, downloader):
        return "original-return:" + str(path)

    def get_default_config_name(self):
        return self.default_name


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        plugin = self.enterContext(load_plugin())
        self.runtime = __import__(plugin.__name__ + ".runtime", fromlist=["RuntimeAdapter"])
        self.config = self.runtime.RuntimeConfig.from_dict({
            "downloader": "Windows qB", "windows_root": "E:/Downloads", "smb_root": "smb:/"})
        self.host_class = type("QbModule", (HostPaths,), {})
        self.host = self.runtime.HostBindings("v3.1.4", self.host_class, ("Windows qB", "Linux qB"))
        self.digests = {n: self.runtime.source_digest(getattr(HostPaths, n)) for n in
                        ("normalize_path", "normalize_return_path", "get_default_config_name")}
        self.adapter = self.make_adapter()
        self.adapter.start()

    def make_adapter(self, config=None):
        adapter = self.runtime.RuntimeAdapter(config or self.config, lambda: self.host, self.digests)
        self.addCleanup(adapter.stop)
        return adapter

    def module(self, default="Windows qB"):
        instance = self.host_class()
        instance.default_name = default
        return instance

    def test_selected_downloader_both_directions_and_root(self):
        module = self.module()
        self.assertEqual(module.normalize_path(Path("smb:/Movie/A.mkv"), "Windows qB"),
                         "E:/Downloads/Movie/A.mkv")
        self.assertEqual(module.normalize_return_path(Path(r"e:/DOWNLOADS\Movie\A.mkv"), None),
                         "smb:/Movie/A.mkv")
        self.assertEqual(module.normalize_return_path(Path(r"E:\Downloads"), None), "smb:/")

    def test_other_downloader_and_default_untouched(self):
        for module, name in [(self.module(), "Linux qB"), (self.module("Linux qB"), None)]:
            self.assertEqual(module.normalize_path(Path("/data"), name), "original-send:/data")
            self.assertEqual(module.normalize_return_path(Path("/data"), name), "original-return:/data")
        self.assertEqual(HostPaths().normalize_path(Path("/data"), None), "original-send:/data")

    def test_unmapped_or_invalid_never_falls_back_to_local(self):
        for path in ["F:/Temp/Movie", "E:/Downloads2/Movie", "E:/Downloads/../Movie", "/linux"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.module().normalize_return_path(Path(path), None)
        for path in ["local:/data", "/data", "E:/Downloads", "smb:/../escape"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.module().normalize_path(Path(path), None)

    def test_temp_directory_and_multi_share(self):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({"downloader": "Windows qB",
            "windows_root": "E:/Downloads", "smb_root": "smb:/downloads",
            "windows_temp_root": "F:/Incomplete", "smb_temp_root": "smb:/temp"})
        self.make_adapter(config).start()
        module = self.module()
        self.assertEqual(module.normalize_return_path(Path(r"F:\Incomplete\中文 Movie\A.mkv"), None),
                         "smb:/temp/中文 Movie/A.mkv")
        self.assertEqual(module.normalize_path(Path("smb:/downloads/Movie"), None), "E:/Downloads/Movie")
        self.assertEqual(module.normalize_return_path(Path("E:/Downloads"), None), "smb:/downloads")

    def test_temp_rule_requires_pair_and_no_overlap(self):
        base = {"downloader": "Windows qB", "windows_root": "E:/Downloads", "smb_root": "smb:/"}
        for extra in [{"windows_temp_root": "F:/Temp"},
                      {"windows_temp_root": "F:/Temp", "smb_temp_root": "smb:/temp"},
                      {"windows_temp_root": "E:/Downloads/temp", "smb_temp_root": "smb:/other"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.runtime.RuntimeConfig.from_dict({**base, **extra})

    def test_local_runtime_and_temp_mapping_without_filesystem_queries(self):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({"downloader": "Windows qB",
            "windows_root": "E:/Downloads", "smb_root": "/downloads",
            "windows_temp_root": "F:/Temp", "smb_temp_root": "local:/incomplete"})
        self.make_adapter(config).start()
        with patch.object(Path, "exists", side_effect=AssertionError("不应检查路径")), \
                patch.object(Path, "stat", side_effect=AssertionError("不应读取元数据")):
            module = self.module()
            for path in ("/downloads/Movie", "local:/downloads/Movie"):
                self.assertEqual(module.normalize_path(Path(path), None), "E:/Downloads/Movie")
            self.assertEqual(module.normalize_return_path(Path(r"F:\Temp\Movie\A.mkv"), None),
                             "/incomplete/Movie/A.mkv")
            self.assertEqual(module.normalize_return_path(Path(r"E:\Downloads\Movie\A.mkv"), None),
                             "/downloads/Movie/A.mkv")
            with self.assertRaises(ValueError):
                module.normalize_path(Path("/Downloads/Movie"), None)

    def test_local_scheme_root_survives_posix_path(self):
        config = self.runtime.RuntimeConfig.from_dict({"downloader": "Windows qB",
            "windows_root": "E:/Downloads", "smb_root": "local:/"})
        self.assertEqual(config.convert(Path("local:/"), returning=False), "E:/Downloads")
        self.assertEqual(config.convert(Path("E:/Downloads"), returning=True), "/")

    def test_local_aliases_overlap_but_different_storage_schemes_do_not(self):
        base = {"downloader": "Windows qB", "windows_root": "E:/Downloads",
                "smb_root": "/downloads", "windows_temp_root": "F:/Temp"}
        with self.assertRaises(ValueError):
            self.runtime.RuntimeConfig.from_dict({**base, "smb_temp_root": "local:/downloads/temp"})
        config = self.runtime.RuntimeConfig.from_dict({**base, "smb_temp_root": "smb:/downloads"})
        self.assertEqual(config.convert(Path("smb:/downloads/Movie"), returning=False), "F:/Temp/Movie")
        self.assertEqual(config.convert(Path("/downloads/Movie"), returning=False), "E:/Downloads/Movie")

    def test_repeated_start_and_stop_restore_inheritance(self):
        original = self.host_class.normalize_path
        self.adapter.start()
        self.assertIs(self.host_class.normalize_path, original)
        self.adapter.stop()
        self.adapter.stop()
        self.assertNotIn("normalize_path", vars(self.host_class))
        self.assertIs(self.host_class.normalize_path, HostPaths.normalize_path)

    def test_new_instance_after_config_reload_is_covered(self):
        self.assertEqual(self.module().normalize_path(Path("smb:/"), None), "E:/Downloads")
        # 重建实例并更换默认下载器，不依赖首次初始化时的实例缓存。
        self.assertEqual(self.module("Linux qB").normalize_path(Path("smb:/"), None),
                         "original-send:smb:")

    def test_python_class_reload_revalidates_and_restores_old_class(self):
        old = self.host_class
        self.host_class = type("ReloadedQbModule", (HostPaths,), {})
        self.host = self.runtime.HostBindings("v3.1.4", self.host_class, ("Windows qB",))
        self.adapter.refresh()
        self.assertNotIn("normalize_path", vars(old))
        self.assertEqual(self.module().normalize_path(Path("smb:/"), None), "E:/Downloads")

    def test_unsupported_version_or_missing_downloader_removes_patches(self):
        for version, names in [("v3.1.5", ("Windows qB",)), ("v3.1.4", ())]:
            self.host = self.runtime.HostBindings(version, self.host_class, names)
            with self.assertRaises(self.runtime.CompatibilityError):
                self.adapter.refresh()
            self.assertFalse(self.adapter.is_active())
            self.assertNotIn("normalize_path", vars(self.host_class))

    def test_other_plugin_before_install_rejected_without_mutation(self):
        self.adapter.stop()
        original = HostPaths.normalize_path
        @wraps(original)
        def external(*args, **kwargs):
            return original(*args, **kwargs)
        self.host_class.normalize_path = external
        with self.assertRaises(self.runtime.CompatibilityError):
            self.adapter.start()
        self.assertIs(self.host_class.normalize_path, external)
        self.assertNotIn("normalize_return_path", vars(self.host_class))

    def test_other_plugin_after_install_preserved_and_inner_wrapper_deactivated(self):
        original = self.host_class.normalize_path
        @wraps(original)
        def external(*args, **kwargs):
            return original(*args, **kwargs)
        self.host_class.normalize_path = external
        self.adapter.stop()
        self.assertIs(self.host_class.normalize_path, external)
        self.assertEqual(self.module().normalize_path(Path("smb:/"), None), "original-send:smb:")

    def test_second_plugin_instance_cannot_steal_wrappers(self):
        other = self.make_adapter()
        with self.assertRaises(self.runtime.CompatibilityError):
            other.start()
        other.stop()
        self.assertTrue(self.adapter.is_active())

    def test_changed_method_same_signature_rejected(self):
        self.adapter.stop()
        def changed(self, path, downloader):
            return "changed"
        self.host_class.normalize_path = changed
        with self.assertRaises(self.runtime.CompatibilityError):
            self.adapter.start()

    def test_source_digest_ignores_empty_optional_ast_fields(self):
        tree = ast.parse("def method():\n    return 1\n")
        expected = self.runtime.tree_digest(tree)
        del tree.body[0].type_params
        self.assertEqual(self.runtime.tree_digest(tree), expected)
        tree.body[0].body[0].value.value = 2
        self.assertNotEqual(self.runtime.tree_digest(tree), expected)

    def test_partial_install_failure_rolls_back_first_method(self):
        self.adapter.stop()
        class RejectSecondPatch(type):
            def __setattr__(cls, name, value):
                if name == "normalize_return_path":
                    raise RuntimeError("模拟宿主拒绝第二个包装")
                super().__setattr__(name, value)
        self.host_class = RejectSecondPatch("QbModule", (HostPaths,), {})
        self.host = self.runtime.HostBindings("v3.1.4", self.host_class, ("Windows qB",))
        with self.assertRaises(RuntimeError):
            self.adapter.start()
        self.assertFalse(self.adapter.is_active())
        self.assertNotIn("normalize_path", vars(self.host_class))

    def test_health_check_detects_later_wrapper_and_preserves_it(self):
        original = self.host_class.normalize_path
        @wraps(original)
        def external(*args, **kwargs):
            return original(*args, **kwargs)
        self.host_class.normalize_path = external
        with self.assertRaises(self.runtime.CompatibilityError):
            self.adapter.refresh()
        self.assertIs(self.host_class.normalize_path, external)
        self.assertFalse(self.adapter.is_active())
        self.assertEqual(self.module().normalize_path(Path("smb:/"), None), "original-send:smb:")

    def test_concurrent_conversion_and_stop_have_consistent_results(self):
        module = self.module()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(module.normalize_path, Path("smb:/"), None) for _ in range(30)]
            self.adapter.stop()
            results = [f.result() for f in futures]
        self.assertTrue(set(results) <= {"E:/Downloads", "original-send:smb:"})
        self.assertFalse(self.adapter.is_active())

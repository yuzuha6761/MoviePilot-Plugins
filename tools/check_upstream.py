"""从指定的可信本地源码提取 MP 原方法，替代宿主边界后执行离线回归。

不导入 MoviePilot，不建立网络/数据库连接。此脚本不下载或修改上游源码。
用法：python3 tools/check_upstream.py /path/to/MoviePilot
"""

import ast
import enum
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from helpers import load_plugin  # noqa: E402


SOURCE = Path(sys.argv.pop(1)).resolve()


def extract(relative, class_name, names, namespace, bases=()):
    file = SOURCE / relative
    tree = ast.parse(file.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if set(names) != {n.name for n in node.body}:
        raise AssertionError(f"上游方法缺失：{class_name}")
    node.bases = [ast.Name(id=b, ctx=ast.Load()) for b in bases]
    node.keywords = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(file), "exec"), namespace)
    return namespace[class_name]


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        plugin = self.enterContext(load_plugin())
        self.runtime = __import__(plugin.__name__ + ".runtime", fromlist=["RuntimeAdapter"])
        self.configs = [SimpleNamespace(name="Windows qB", default=True, path_mapping=[]),
                        SimpleNamespace(name="Linux qB", default=False, path_mapping=[])]
        self.query = enum.Enum("Query", {v.upper(): v for v in
                              ("all", "completed", "paused", "transfer", "downloading")})
        self.storage = enum.Enum("Storage", {"SMB": "smb", "Local": "local"})
        self.namespace = dict(Path=Path,
            ServiceConfigHelper=SimpleNamespace(get_downloader_configs=lambda: self.configs),
            StorageSchema=self.storage, TorrentQueryStatus=self.query,
            DownloadTaskState=self.query, DownloaderTorrent=lambda **kw: SimpleNamespace(**kw),
            MetaInfo=lambda name: SimpleNamespace(name=name, year=None, season_episode=None),
            size_tools=SimpleNamespace(format_compact_size=str),
            time_tools=SimpleNamespace(format_duration=str), get_runtime_setting=lambda key: None,
            text_tools=SimpleNamespace(random_string=lambda size: "test-tag"),
            _QBITTORRENT_PAUSED_STATES={"pauseddl", "pausedup", "stoppedup", "stoppeddl"},
            _QBITTORRENT_DOWNLOADING_STATES={"downloading", "stalleddl"})
        base = extract("app/modules/__init__.py", "_DownloaderBase", [
            "normalize_path", "normalize_return_path", "get_default_config_name",
            "__replace_path_prefix", "__strip_storage_prefix"], self.namespace)
        self.module_class = extract("app/modules/qbittorrent/__init__.py", "QbittorrentModule", [
            "download", "list_torrents", "update_torrent", "init_module",
            "__normalize_torrent_state"], self.namespace, ("_DownloaderBase",))
        self.module = self.module_class()
        self.module._default_config_name = None
        self.module.get_config = lambda name: next(c for c in self.configs
                                                    if c.name == (name or "Windows qB"))
        self.module._normalize_query_status = lambda status: status or self.query.ALL
        self.module._get_torrent_info = lambda content: (None, content)
        self.sent = []
        self.rows = {"Windows qB": [], "Linux qB": []}
        self.servers = {}
        for name in self.rows:
            self.servers[name] = SimpleNamespace(
                get_torrents=lambda name=name, **kw: ([dict(row) for row in self.rows[name]], False),
                get_completed_torrents=lambda name=name, **kw: [dict(row) for row in self.rows[name]],
                get_downloading_torrents=lambda name=name, **kw: [dict(row) for row in self.rows[name]],
                add_torrent=lambda **kw: (self.sent.append(kw) or True, ["hash"]),
                delete_torrents_tag=lambda *args, **kw: True,
                get_content_layout=lambda: "Original", is_force_resume=lambda: False,
                set_torrent_location=lambda **kw: self.sent.append(kw) or True)
        self.module.get_instances = lambda: self.servers
        self.module.get_instance = lambda name: self.servers[name or "Windows qB"]
        # 使用真实摘要，不绕过生产版本/源码校验。
        version_tree = ast.parse((SOURCE / "version.py").read_text())
        version = next(ast.literal_eval(n.value) for n in version_tree.body
                       if isinstance(n, ast.Assign) and any(
                           isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in n.targets))
        host = self.runtime.HostBindings(version, self.module_class, tuple(self.rows))
        config = self.runtime.RuntimeConfig.from_dict({
            "downloaders": ["Windows qB"],
            "mappings": [
                {"windows_root": "E:/Downloads", "storage_root": "smb:/"},
            ],
        })
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=lambda: host)
        self.addCleanup(self.adapter.stop)
        self.adapter.start()

    def test_original_download_and_location_update(self):
        result = self.module.download("magnet:?xt=urn:btih:test", Path("smb:/"), "", downloader=None)
        self.assertEqual(result[1], "hash")
        self.assertEqual(self.sent[0]["download_dir"], "E:/Downloads")
        self.module.update_torrent("hash", save_path="smb:/中文 Movie")
        self.assertEqual(self.sent[1]["location"], "E:/Downloads/中文 Movie")

    def test_mismatched_storage_type_reports_path_before_sending_to_qb(self):
        for action in (
            lambda: self.module.download("magnet:?xt=urn:btih:test", Path("/Movie"), ""),
            lambda: self.module.update_torrent("hash", save_path="/Movie"),
        ):
            with self.assertRaises(ValueError) as raised:
                action()
            message = str(raised.exception)
            self.assertIn("下载器 'Windows qB'", message)
            self.assertIn("待匹配路径='/Movie'", message)
            self.assertIn("已配置前缀=['smb:/']", message)
            self.assertEqual(self.sent, [])

    def test_original_methods_with_backslash_drive_root(self):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({
            "downloaders": ["Windows qB"],
            "mappings": [{"windows_root": "E:\\", "storage_root": "/disk"}],
        })
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=self.adapter._resolver)
        self.addCleanup(self.adapter.stop)
        self.adapter.start()
        self.module.download("magnet:?xt=urn:btih:test", Path("/disk"), "")
        self.assertEqual(self.sent[-1]["download_dir"], "E:/")
        self.module.update_torrent("hash", save_path="/disk/中文 Movie")
        self.assertEqual(self.sent[-1]["location"], "E:/中文 Movie")
        for root in ("E:/", "E:\\"):
            self.rows["Windows qB"] = [{"name": "Movie", "content_path": r"E:\Movie\A.mkv",
                                       "save_path": root, "state": "uploading"}]
            task = self.module.list_torrents(downloader="Windows qB")[0]
            self.assertEqual(task.save_path, "/disk")
            self.assertEqual(task.content_path, "/disk/Movie/A.mkv")

    def test_original_methods_with_local_storage(self):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({
            "downloaders": ["Windows qB"],
            "mappings": [
                {"windows_root": "E:/Downloads", "storage_root": "local:/downloads"},
            ],
        })
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=self.adapter._resolver)
        self.addCleanup(self.adapter.stop)
        self.adapter.start()
        result = self.module.download("magnet:?xt=urn:btih:test", Path("local:/downloads"), "")
        self.assertEqual(result[1], "hash")
        self.assertEqual(self.sent[0]["download_dir"], "E:/Downloads")
        self.module.update_torrent("hash", save_path="/downloads/中文 Movie")
        self.assertEqual(self.sent[1]["location"], "E:/Downloads/中文 Movie")
        self.rows["Windows qB"] = [{"name": "Movie", "content_path": r"E:\Downloads\Movie\A.mkv",
                                    "save_path": r"E:\Downloads", "state": "uploading"}]
        task = self.module.list_torrents(downloader="Windows qB")[0]
        self.assertEqual(task.content_path, "/downloads/Movie/A.mkv")
        self.assertEqual(task.save_path, "/downloads")

    def test_original_methods_with_multiple_downloaders_and_mappings(self):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({
            "downloaders": ["Windows qB", "Linux qB"],
            "mappings": [
                {"windows_root": "E:/Downloads", "storage_root": "smb:/downloads"},
                {"windows_root": "F:/Temp", "storage_root": "/temp"},
                {"windows_root": "G:/TV", "storage_root": "/tv"},
            ],
        })
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=self.adapter._resolver)
        self.addCleanup(self.adapter.stop)
        self.adapter.start()
        for name in config.downloaders:
            self.module.download("magnet:?xt=urn:btih:test", Path("smb:/downloads"), "", downloader=name)
            self.assertEqual(self.sent[-1]["download_dir"], "E:/Downloads")
            self.module.update_torrent("hash", save_path="/tv/Movie", downloader=name)
            self.assertEqual(self.sent[-1]["location"], "G:/TV/Movie")
            self.rows[name] = [{"name": "Movie", "content_path": r"F:\Temp\Movie\A.mkv",
                                "save_path": r"F:\Temp", "state": "uploading"}]
            task = self.module.list_torrents(downloader=name)[0]
            self.assertEqual(task.content_path, "/temp/Movie/A.mkv")
            self.assertEqual(task.save_path, "/temp")

    def test_original_list_all_statuses_and_content_fallback(self):
        self.rows["Linux qB"] = [{"name": "Linux", "save_path": "/data", "state": "uploading"}]
        for raw in [r"E:\Downloads\中文 Movie\A.mkv", r"e:/DOWNLOADS\中文 Movie\A.mkv"]:
            self.rows["Windows qB"] = [{"name": "中文 Movie", "content_path": raw,
                                        "save_path": r"E:\Downloads", "state": "uploading"}]
            for status in (self.query.ALL, self.query.TRANSFER, self.query.COMPLETED):
                tasks = self.module.list_torrents(status=status)
                self.assertEqual(len(tasks), 2)
                self.assertEqual(tasks[0].content_path, "smb:/中文 Movie/A.mkv")
                self.assertEqual(tasks[0].save_path, "smb:/")
                self.assertEqual(tasks[1].content_path, "/data/Linux")
            self.rows["Windows qB"][0].pop("content_path")
            self.rows["Windows qB"][0]["state"] = "downloading"
            task = self.module.list_torrents(status=self.query.DOWNLOADING, downloader="Windows qB")[0]
            self.assertEqual(task.content_path, "smb:/中文 Movie")
            task = self.module.list_torrents(hashs="hash", downloader="Windows qB")[0]
            self.assertEqual(task.content_path, "smb:/中文 Movie")

    def test_original_smb_standard_root_still_checks_connection(self):
        import time
        class StorageQueryError(Exception):
            pass
        class SMBConnectionError(Exception):
            pass
        namespace = dict(Path=Path, time=time, StorageQueryError=StorageQueryError,
                         SMBConnectionError=SMBConnectionError,
                         _SchemaFileItem=lambda **kw: SimpleNamespace(**kw))
        smb_class = extract("app/modules/filemanager/storages/smb.py", "SMB",
                            ["get_item_strict", "_check_connection", "_relative_path"], namespace)
        smb = smb_class()
        smb.schema = self.storage.SMB
        smb._server_path = r"\\server\downloads"
        smb._connected = True
        with patch.dict(sys.modules, {"smbclient": SimpleNamespace()}):
            uri = self.module.normalize_return_path(Path(r"E:\Downloads"), None)
            item = smb.get_item_strict(Path(uri.removeprefix("smb:")))
            self.assertEqual((item.storage, item.path, item.type), ("smb", "/", "dir"))
            smb._connected = False
            with self.assertRaises(StorageQueryError):
                smb.get_item_strict(Path("/"))
        # 原归属校验未被更改，相似前缀及其他共享仍被拒绝。
        with self.assertRaises(ValueError):
            smb._relative_path(r"\\server\downloads2\file.mkv")


if __name__ == "__main__":
    unittest.main(verbosity=2)

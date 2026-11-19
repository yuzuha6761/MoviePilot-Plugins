"""从指定的可信本地源码提取 MP 原方法，替代宿主边界后执行离线回归。

不导入 MoviePilot，不建立网络/数据库连接。此脚本不下载或修改上游源码。
用法：python3 tools/check_upstream.py /path/to/MoviePilot
"""

import ast
import enum
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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


def extract_optional_helpers(relative, names, namespace):
    """新版将纯字段读取函数移到模块级；仍执行原函数，不导入宿主依赖。"""
    file = SOURCE / relative
    tree = ast.parse(file.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in names and not n.decorator_list]
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(file), "exec"), namespace)


def extract_optional_constants(relative, names, namespace):
    """仅读取原源码中的常量字面量，不导入宿主 schema 及其依赖。"""
    tree = ast.parse((SOURCE / relative).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    namespace[target.id] = ast.literal_eval(node.value)


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        plugin = self.enterContext(load_plugin())
        self.runtime = __import__(plugin.__name__ + ".runtime", fromlist=["RuntimeAdapter"])
        self.configs = [SimpleNamespace(name="Windows qB", default=True, path_mapping=[]),
                        SimpleNamespace(name="Linux qB", default=False, path_mapping=[])]
        self.query = enum.Enum("Query", {v.upper(): v for v in
                              ("all", "completed", "paused", "transfer", "downloading")})
        self.storage = enum.Enum("Storage", {"SMB": "smb", "Local": "local"})
        self.namespace = dict(Path=Path, logger=Mock(),
            ServiceConfigHelper=SimpleNamespace(get_downloader_configs=lambda: self.configs),
            StorageSchema=self.storage, TorrentQueryStatus=self.query,
            DownloadTaskState=self.query, DownloaderTorrent=lambda **kw: SimpleNamespace(**kw),
            MetaInfo=lambda name: SimpleNamespace(name=name, year=None, season_episode=None),
            size_tools=SimpleNamespace(format_compact_size=str),
            time_tools=SimpleNamespace(format_duration=str), get_runtime_setting=lambda key: None,
            text_tools=SimpleNamespace(random_string=lambda size: "test-tag"),
            torrent_rules=SimpleNamespace(download_hashes=lambda content: frozenset(("hash",))),
            _QBITTORRENT_PAUSED_STATES={"pauseddl", "pausedup", "stoppedup", "stoppeddl"},
            _QBITTORRENT_DOWNLOADING_STATES={"downloading", "stalleddl"})
        extract_optional_constants("app/schemas/download.py",
                                   {"DOWNLOAD_TASK_ALREADY_EXISTS"}, self.namespace)
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
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=lambda: (host,))
        self.addCleanup(self.adapter.stop)
        self.adapter.start()

    def test_original_download_and_location_update(self):
        result = self.module.download("magnet:?xt=urn:btih:test", Path("smb:/"), "", downloader=None)
        self.assertEqual(result[1], "hash")
        self.assertEqual(self.sent[0]["download_dir"], "E:/Downloads")
        self.module.update_torrent("hash", save_path="smb:/中文 Movie")
        self.assertEqual(self.sent[1]["location"], "E:/Downloads/中文 Movie")

    def test_reviewed_contract_refresh_and_restore(self):
        from importlib import import_module
        compatibility = import_module(self.runtime.__package__ + ".compatibility")
        hosts = self.adapter._resolver()
        previous_0_2_6 = {
            kind: {**methods, "download": compatibility.RELEASE_3_2_2_DOWNLOAD_DIGESTS[kind]}
            for kind, methods in compatibility.UPDATED_METHOD_DIGESTS.items()
        }
        for host in hosts:
            # 在新版原方法上复现旧摘要拒绝接管，确保修复没有绕过源码检查。
            for previous in (compatibility.BASELINE_METHOD_DIGESTS,
                             compatibility.UPDATED_METHOD_DIGESTS, previous_0_2_6):
                old = previous[host.downloader_type]
                if self.runtime.source_digest(host.module_class.download) != old["download"]:
                    with self.assertRaisesRegex(self.runtime.CompatibilityError, "download 实现不在已核对"):
                        self.runtime.RuntimeAdapter(
                            self.adapter.config, digests=previous)._validate(host)
        originals = [(host.module_class, name, getattr(host.module_class, name).__wrapped__)
                     for host in hosts for name in ("normalize_path", "normalize_return_path")]
        self.adapter.refresh()
        self.assertTrue(self.adapter.is_active())
        self.adapter.stop()
        for cls, name, original in originals:
            self.assertIs(getattr(cls, name), original)
        self.adapter.start()
        self.assertTrue(self.adapter.is_active())

    def test_existing_qb_task_preserves_result_and_mapped_directory(self):
        # 覆盖 3.2.2 实际变化的分支，常量取自上游源码。
        server = self.servers["Windows qB"]
        server.add_torrent = Mock(return_value=(False, []))
        server.delete_torrents_tag = Mock(return_value=True)
        self.module._get_torrent_info = lambda content: (SimpleNamespace(name="Movie", total_size=100), content)
        self.rows["Windows qB"] = [{"hash": "hash", "name": "Movie", "total_size": 100, "tags": ""}]
        result = self.module.download("magnet:?xt=urn:btih:test", Path("smb:/Movie"), "")
        self.assertEqual(result, ("Windows qB", "hash", "Original", "下载任务已存在"))
        self.assertEqual(server.add_torrent.call_args.kwargs["download_dir"], "E:/Downloads/Movie")
        server.delete_torrents_tag.assert_called_once_with("hash", "test-tag")

    def test_qb_episode_selection_receives_mapped_directory(self):
        if "episode_selection" not in inspect.signature(self.module.download).parameters:
            self.skipTest("此宿主没有 episode_selection 参数")
        selection = object()
        expected = ("Windows qB", "hash", "Original", "添加下载成功")
        self.module._finish_selected_download = Mock(return_value=expected)
        result = self.module.download("magnet:?xt=urn:btih:test", Path("smb:/Movie"), "",
                                      episodes={1}, custom_words="规则", episode_selection=selection)
        self.assertEqual(result, expected)
        self.assertEqual(self.sent[-1]["download_dir"], "E:/Downloads/Movie")
        self.assertTrue(self.sent[-1]["is_paused"])
        self.module._finish_selected_download.assert_called_once_with(
            self.servers["Windows qB"], "hash", {1}, "规则", None, "Original", selection)

    def test_qb_existing_task_does_not_repeat_episode_selection(self):
        if "episode_selection" not in inspect.signature(self.module.download).parameters:
            self.skipTest("此宿主没有新版重复任务选集语义")
        server = self.servers["Windows qB"]
        server.add_torrent = Mock(return_value=(False, []))
        server.delete_torrents_tag = Mock(return_value=True)
        self.rows["Windows qB"] = [{"hash": "hash", "name": "Movie", "tags": ""}]
        self.module._finish_selected_download = Mock(side_effect=AssertionError("不应重新选集"))
        result = self.module.download("magnet:?xt=urn:btih:test", Path("smb:/Movie"), "",
                                      episodes={1}, episode_selection=object())
        self.assertEqual(result, ("Windows qB", "hash", "Original", "下载任务已存在"))
        self.assertEqual(server.add_torrent.call_args.kwargs["download_dir"], "E:/Downloads/Movie")
        self.module._finish_selected_download.assert_not_called()
        server.delete_torrents_tag.assert_called_once_with("hash", "test-tag")

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


class TransmissionUpstreamTests(unittest.TestCase):
    """复用 qBittorrent 替身，验证同时启用两种真实模块方法。"""

    test_reviewed_contract_refresh_and_restore = UpstreamTests.test_reviewed_contract_refresh_and_restore

    def setUp(self):
        UpstreamTests.setUp(self)
        self.adapter.stop()
        qb_host = self.adapter._resolver()[0]
        self.configs.extend([
            SimpleNamespace(name="Windows TR", default=False, path_mapping=[]),
            SimpleNamespace(name="Linux TR", default=False, path_mapping=[]),
        ])
        namespace = {**self.namespace, "logger": Mock(),
                     "_TRANSMISSION_PAUSED_STATES": {"stopped"},
                     "_TRANSMISSION_DOWNLOADING_STATES": {"download_pending", "downloading"}}
        extract_optional_helpers("app/modules/transmission/__init__.py",
                                 {"_get_torrent_attr", "_normalize_transmission_progress"}, namespace)
        self.tr_class = extract("app/modules/transmission/__init__.py", "TransmissionModule", [
            "download", "list_torrents", "update_torrent", "init_module",
            "__normalize_torrent_state"], namespace, ("_DownloaderBase",))
        self.tr = self.tr_class()
        self.tr._default_config_name = None
        self.tr.get_config = lambda name: next(c for c in self.configs
                                               if c.name == (name or self.tr.get_default_config_name()))
        self.tr._normalize_query_status = lambda status: status or self.query.ALL
        self.tr._get_torrent_info = lambda content: (None, content)
        self.tr_rows = {"Windows TR": [], "Linux TR": []}
        self.tr_sent = []
        self.tr_servers = {}
        for name in self.tr_rows:
            self.tr_servers[name] = SimpleNamespace(
                add_torrent=lambda **kw: (self.tr_sent.append(kw) or SimpleNamespace(hashString="tr-hash")),
                set_torrent_location=lambda **kw: self.tr_sent.append(kw) or True,
                get_torrents=lambda name=name, **kw: (list(self.tr_rows[name]), False),
                get_completed_torrents=lambda name=name, **kw: list(self.tr_rows[name]),
                get_downloading_torrents=lambda name=name, **kw: list(self.tr_rows[name]))
            # 新客户端返回 (任务, 是否已存在)，旧版仍使用 add_torrent。
            server = self.tr_servers[name]
            server.add_torrent_with_status = lambda server=server, **kw: (server.add_torrent(**kw), False)
        self.tr.get_instance = lambda name: self.tr_servers.get(name or self.tr.get_default_config_name())
        self.tr.get_instances = lambda: self.tr_servers
        self.module.get_instance = lambda name: self.servers.get(name or self.module.get_default_config_name())
        self.hosts = (qb_host, self.runtime.HostBindings(qb_host.version, self.tr_class,
                                                       tuple(self.tr_rows), "transmission"))
        self.use_prefix("/downloads")

    def use_prefix(self, prefix, root=r"E:\Downloads"):
        self.adapter.stop()
        config = self.runtime.RuntimeConfig.from_dict({
            "downloaders": ["Windows qB", "Windows TR"],
            "mappings": [{"windows_root": root, "storage_root": prefix}],
        })
        self.adapter = self.runtime.RuntimeAdapter(config, resolver=lambda: self.hosts)
        self.addCleanup(self.adapter.stop)
        self.adapter.start()

    def test_both_original_download_and_location_update(self):
        for prefix, root in (("/downloads", r"E:\Downloads"), ("smb:/", "E:\\")):
            self.use_prefix(prefix, root)
            expected = root.replace("\\", "/")
            for module, name, sent in ((self.module, "Windows qB", self.sent),
                                       (self.tr, "Windows TR", self.tr_sent)):
                result = module.download("magnet:?xt=urn:btih:test", Path(prefix), "", downloader=name)
                self.assertTrue(result[1])
                self.assertEqual(sent[-1]["download_dir"], expected)
                module.update_torrent("hash", downloader=name, save_path=prefix.rstrip("/") + "/中文 Movie")
                self.assertEqual(sent[-1]["location"], expected.rstrip("/") + "/中文 Movie")
        # 未选中的 Transmission 配置使用原下发路径逻辑。
        self.tr.download("magnet:?xt=urn:btih:test", Path("/linux"), "", downloader="Linux TR")
        self.assertEqual(self.tr_sent[-1]["download_dir"], "/linux")

    def test_global_default_downloader_resolves_to_its_own_type(self):
        for default, module, other, sent in (("Windows TR", self.tr, self.module, self.tr_sent),
                                             ("Windows qB", self.module, self.tr, self.sent)):
            for conf in self.configs:
                conf.default = conf.name == default
            self.module._default_config_name = None
            self.tr._default_config_name = None
            self.assertIsNone(other.download("magnet:?xt=urn:btih:test", Path("/downloads"), ""))
            result = module.download("magnet:?xt=urn:btih:test", Path("/downloads"), "")
            self.assertEqual(result[0], default)
            self.assertEqual(sent[-1]["download_dir"], "E:/Downloads")

    def test_transmission_original_lists_all_query_modes(self):
        for raw, prefix, root in ((r"e:\DOWNLOADS", "/downloads", r"E:\Downloads"),
                                  ("E:/Downloads\\", "smb:/downloads", r"E:\Downloads"),
                                  ("E:/", "smb:/", "E:\\")):
            self.use_prefix(prefix, root)
            self.tr_rows["Windows TR"] = [SimpleNamespace(
                download_dir=raw, name="中文 Movie", hashString="tr-hash", labels=[], status="seeding")]
            self.tr_rows["Linux TR"] = [SimpleNamespace(
                download_dir="/linux", name="Other", hashString="other", labels=[], status="seeding")]
            for status, native in ((self.query.ALL, "seeding"), (self.query.TRANSFER, "seeding"),
                                   (self.query.COMPLETED, "seeding"), (self.query.PAUSED, "stopped"),
                                   (self.query.DOWNLOADING, "downloading")):
                self.tr_rows["Windows TR"][0].status = native
                tasks = self.tr.list_torrents(downloader="Windows TR", status=status)
                self.assertEqual(tasks[0].content_path, prefix.rstrip("/") + "/中文 Movie")
                self.assertEqual(tasks[0].save_path, prefix)
            tasks = self.tr.list_torrents(hashs="tr-hash", downloader="Windows TR")
            self.assertEqual(tasks[0].content_path, prefix.rstrip("/") + "/中文 Movie")
            self.assertEqual(self.tr.list_torrents(downloader="Linux TR")[0].save_path, "/linux")
            self.assertEqual(len(self.tr.list_torrents()), 2)

    def test_transmission_mismatch_never_reaches_client(self):
        with self.assertRaisesRegex(ValueError, "Windows TR"):
            self.tr.download("magnet:?xt=urn:btih:test", Path("smb:/downloads"), "", downloader="Windows TR")
        with self.assertRaisesRegex(ValueError, "Windows TR"):
            self.tr.update_torrent("hash", downloader="Windows TR", save_path="/other")
        self.assertEqual(self.tr_sent, [])

    def test_existing_transmission_task_preserves_result_and_mapped_directory(self):
        server = self.tr_servers["Windows TR"]
        server.add_torrent = Mock(return_value=None)
        self.tr._get_torrent_info = lambda content: (SimpleNamespace(name="Movie", total_size=100), content)
        self.tr_rows["Windows TR"] = [SimpleNamespace(hashString="hash", name="Movie", total_size=100, labels=[])]
        result = self.tr.download("magnet:?xt=urn:btih:test", Path("/downloads/Movie"), "",
                                  downloader="Windows TR")
        self.assertEqual(result, ("Windows TR", "hash", "Original", "下载任务已存在"))
        self.assertEqual(server.add_torrent.call_args.kwargs["download_dir"], "E:/Downloads/Movie")

    def test_transmission_existing_task_does_not_repeat_episode_selection(self):
        if "episode_selection" not in inspect.signature(self.tr.download).parameters:
            self.skipTest("此宿主没有新版重复任务选集语义")
        server = self.tr_servers["Windows TR"]
        task = SimpleNamespace(hashString="hash", name="Movie", labels=[])
        self.tr._select_download_files = Mock(side_effect=AssertionError("不应重新选集"))
        self.tr._discard_failed_selection = Mock(side_effect=AssertionError("不应清理已有任务"))
        # 同时覆盖 RPC 直接返回重复任务和添加失败后按哈希查找到已有任务。
        for response in ((task, True), (None, False)):
            with self.subTest(response=response):
                server.add_torrent_with_status = Mock(return_value=response)
                self.tr_rows["Windows TR"] = [task]
                result = self.tr.download("magnet:?xt=urn:btih:test", Path("/downloads/Movie"), "",
                                          downloader="Windows TR", episodes={1}, episode_selection=object())
                self.assertEqual(result, ("Windows TR", "hash", "Original", "下载任务已存在"))
                self.assertEqual(server.add_torrent_with_status.call_args.kwargs["download_dir"],
                                 "E:/Downloads/Movie")
                self.tr._select_download_files.assert_not_called()
                self.tr._discard_failed_selection.assert_not_called()

    def test_transmission_episode_selection_and_failure_result(self):
        if "episode_selection" not in inspect.signature(self.tr.download).parameters:
            self.skipTest("此宿主没有 episode_selection 参数")
        selection = object()
        server = self.tr_servers["Windows TR"]
        for selected in (True, False):
            with self.subTest(selected=selected):
                self.tr._select_download_files = Mock(return_value=(selected, "选集失败"))
                self.tr._discard_failed_selection = Mock(return_value="选集失败，已清理新任务")
                result = self.tr.download("magnet:?xt=urn:btih:test", Path("/downloads/Movie"), "",
                                          downloader="Windows TR", episodes={1}, custom_words="规则",
                                          episode_selection=selection)
                self.assertEqual(self.tr_sent[-1]["download_dir"], "E:/Downloads/Movie")
                self.assertTrue(self.tr_sent[-1]["is_paused"])
                self.tr._select_download_files.assert_called_once_with(
                    server, "tr-hash", {1}, "规则", selection)
                if selected:
                    self.assertEqual(result, ("Windows TR", "tr-hash", "Original", "添加下载任务成功"))
                    self.tr._discard_failed_selection.assert_not_called()
                else:
                    self.assertEqual(result, (None, None, None, "选集失败，已清理新任务"))
                    self.tr._discard_failed_selection.assert_called_once_with(server, "tr-hash", "选集失败")


if __name__ == "__main__":
    unittest.main(verbosity=2)

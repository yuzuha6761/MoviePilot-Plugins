"""验证真实问题中的分隔符、根目录、目录边界和越界输入。"""

import unittest

from helpers import load_mapping

PathMapping = load_mapping()


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.rule = PathMapping("E:/qBittorrent_download", "smb:/")

    def test_windows_separators_and_case(self):
        for path in [
            "E:/qBittorrent_download/Movie/movie.mkv",
            r"E:\qBittorrent_download\Movie\movie.mkv",
            r"E:/qBittorrent_download\Movie\movie.mkv",
            "e:/QBITTORRENT_DOWNLOAD/Movie/movie.mkv",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.rule.to_storage(path), "smb:/Movie/movie.mkv")

    def test_root_round_trip(self):
        self.assertEqual(self.rule.to_storage("E:/qBittorrent_download/"), "smb:/")
        self.assertEqual(self.rule.to_windows("smb:/"), "E:/qBittorrent_download")

    def test_nested_round_trip_preserves_suffix(self):
        windows = "E:/qBittorrent_download/电影/Example.S01E01.mkv"
        self.assertEqual(self.rule.to_windows(self.rule.to_storage(windows)), windows)

    def test_multi_share_namespace(self):
        rule = PathMapping("E:/qBittorrent_download", "smb:/qBittorrent_download")
        self.assertEqual(rule.to_storage("E:/qBittorrent_download"), "smb:/qBittorrent_download")
        self.assertEqual(rule.to_windows("smb:/qBittorrent_download/Jellyfin/a.mkv"),
                         "E:/qBittorrent_download/Jellyfin/a.mkv")

    def test_windows_segment_boundary(self):
        for path in ["E:/qBittorrent_download2/a.mkv", "E:/", "F:/qBittorrent_download/a"]:
            with self.subTest(path=path):
                self.assertIsNone(self.rule.to_storage(path))

    def test_smb_segment_boundary(self):
        rule = PathMapping("E:/Downloads", "smb:/Downloads")
        self.assertIsNone(rule.to_windows("smb:/Downloads2/a.mkv"))
        self.assertIsNone(rule.to_windows("smb:/"))
        self.assertEqual(rule.to_windows("smb:/downloads/a.mkv"), "E:/Downloads/a.mkv")

    def test_rejects_relative_and_traversal_paths(self):
        for path in ["E:relative", "/Downloads", "E:/qBittorrent_download/../outside",
                     "E:/qBittorrent_download/a:stream", "E:/qBittorrent_download/\x00"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.rule.to_storage(path)
        for uri in ["smb:/../outside", "local:/../outside", r"smb:/Movie\a.mkv"]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                self.rule.to_windows(uri)

    def test_rejects_invalid_configuration(self):
        for windows, smb in [("E:Downloads", "smb:/"), ("E:/Downloads", "Downloads"),
                             ("E:/../Downloads", "smb:/"), ("E:/Downloads", "smb:/../a")]:
            with self.subTest(windows=windows, smb=smb), self.assertRaises(ValueError):
                PathMapping(windows, smb)

    def test_drive_root_mapping(self):
        rule = PathMapping("E:/", "smb:/disk")
        self.assertEqual(rule.to_storage("E:/Movie/a.mkv"), "smb:/disk/Movie/a.mkv")
        self.assertEqual(rule.to_windows("smb:/disk"), "E:/")

    def test_local_paths_and_uri_round_trip(self):
        for storage in ("/downloads", "local:/downloads"):
            with self.subTest(storage=storage):
                rule = PathMapping("E:/Downloads", storage)
                self.assertEqual(rule.to_storage(r"e:\DOWNLOADS\中文 Movie\A.mkv"),
                                 "/downloads/中文 Movie/A.mkv")
                for path in ("/downloads/中文 Movie/A.mkv", "local:/downloads/中文 Movie/A.mkv"):
                    self.assertEqual(rule.to_windows(path), "E:/Downloads/中文 Movie/A.mkv")

    def test_local_path_case_and_directory_boundary(self):
        rule = PathMapping("E:/Downloads", "/Downloads")
        for path in ("/downloads/A.mkv", "/Downloads2/A.mkv", "/", "local:/downloads/A.mkv"):
            with self.subTest(path=path):
                self.assertIsNone(rule.to_windows(path))
        self.assertEqual(rule.to_windows("/Downloads/Movie/A.mkv"), "E:/Downloads/Movie/A.mkv")

    def test_local_and_smb_namespaces_are_distinct(self):
        local = PathMapping("E:/Downloads", "/Downloads")
        smb = PathMapping("E:/Downloads", "smb:/Downloads")
        self.assertIsNone(local.to_windows("smb:/Downloads/A.mkv"))
        self.assertIsNone(smb.to_windows("/Downloads/A.mkv"))
        self.assertIsNone(smb.to_windows("local:/Downloads/A.mkv"))

    def test_local_root_round_trip(self):
        for storage in ("/", "local:/"):
            rule = PathMapping("E:/Downloads", storage)
            self.assertEqual(rule.to_storage("E:/Downloads"), "/")
            self.assertEqual(rule.to_windows("local:/"), "E:/Downloads")
            self.assertEqual(rule.to_windows("/Movie/A.mkv"), "E:/Downloads/Movie/A.mkv")

    def test_invalid_local_storage_paths(self):
        for path in ("relative/path", "local:relative", "//server/share", "ftp:/Downloads",
                     "/downloads/../outside", "/downloads/a:stream", "/downloads/\x00", r"/downloads\A"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                PathMapping("E:/Downloads", path)

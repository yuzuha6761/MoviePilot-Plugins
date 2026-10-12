"""验证 Windows 返回路径的单向前缀转换，不访问文件系统。"""

import unittest

from helpers import load_mapping

PathMapping = load_mapping()


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.rule = PathMapping(r"E:\qBittorrent_download", "/downloads")

    def test_windows_separators_case_and_suffix(self):
        for path in [r"E:\qBittorrent_download\中文 Movie\A.mkv",
                     "E:/qBittorrent_download/中文 Movie/A.mkv",
                     r"e:/QBITTORRENT_DOWNLOAD\中文 Movie/A.mkv"]:
            with self.subTest(path=path):
                self.assertEqual(self.rule.convert(path), "/downloads/中文 Movie/A.mkv")

    def test_configuration_separator_styles(self):
        for root in [r"E:\Downloads\Movies", "E:/Downloads/Movies", r"E:/Downloads\Movies"]:
            with self.subTest(root=root):
                rule = PathMapping(root, "/Movies")
                self.assertEqual(rule.convert(r"e:\downloads\movies\A.mkv"), "/Movies/A.mkv")

    def test_exact_prefix_and_trailing_slashes(self):
        for root in [r"E:\Downloads", "E:/Downloads/", "E:\\Downloads\\"]:
            rule = PathMapping(root, "/downloads/")
            self.assertEqual(rule.convert(r"E:\Downloads"), "/downloads")
            self.assertEqual(rule.convert("E:/Downloads/"), "/downloads")

    def test_directory_boundary_and_other_drive(self):
        for path in ["E:/qBittorrent_download2/a.mkv", "E:/", "F:/qBittorrent_download/a"]:
            with self.subTest(path=path):
                self.assertIsNone(self.rule.convert(path))

    def test_drive_root_and_output_root(self):
        for root in ["E:/", "E:\\"]:
            rule = PathMapping(root, "/")
            self.assertEqual(rule.convert("E:/"), "/")
            self.assertEqual(rule.convert(r"E:\Movie\A.mkv"), "/Movie/A.mkv")

    def test_output_prefix_case_is_preserved(self):
        rule = PathMapping(r"E:\Downloads", "/Downloads/MOVIES")
        self.assertEqual(rule.convert(r"e:\DOWNLOADS\Movie\A.mkv"), "/Downloads/MOVIES/Movie/A.mkv")

    def test_uri_output_prefixes(self):
        for prefix, expected in [("local:/downloads", "/downloads"),
                                 ("smb:/downloads", "smb:/downloads"), ("smb:/", "smb:/")]:
            rule = PathMapping(r"E:\Downloads", prefix)
            self.assertEqual(rule.convert(r"E:\Downloads"), expected)
            self.assertEqual(rule.convert(r"E:\Downloads\A.mkv"), expected.rstrip("/") + "/A.mkv")

    def test_rejects_invalid_returned_paths(self):
        for path in ["E:relative", "/Downloads", "E:/qBittorrent_download/../outside",
                     r"E:\qBittorrent_download\..\outside", "E:/qBittorrent_download/a:stream",
                     "E:/qBittorrent_download/\x00"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.rule.convert(path)

    def test_rejects_invalid_prefixes(self):
        for root in ["E:Downloads", "/Downloads", "E:/../Downloads"]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                PathMapping(root, "/downloads")
        for prefix in ["relative", "//server/share", "/downloads/../outside",
                       "/downloads/a:stream", "/downloads/\x00", r"/downloads\A"]:
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                PathMapping(r"E:\Downloads", prefix)

    def test_reverse_mapping_preserves_suffix_and_normalizes_separators(self):
        self.assertEqual(self.rule.to_windows("/downloads/中文 Movie/A.mkv"),
                         "E:/qBittorrent_download/中文 Movie/A.mkv")
        self.assertEqual(self.rule.to_windows("/downloads"), "E:/qBittorrent_download")
        self.assertEqual(self.rule.convert(self.rule.to_windows("/downloads/中文 Movie/A.mkv")),
                         "/downloads/中文 Movie/A.mkv")

    def test_reverse_mapping_checks_directory_boundary_and_linux_case(self):
        for path in ("/downloads2/Movie", "/Downloads/Movie", "/other"):
            with self.subTest(path=path):
                self.assertIsNone(self.rule.to_windows(path))

    def test_reverse_mapping_uri_prefixes_keep_identity(self):
        local = PathMapping(r"E:\Downloads", "local:/downloads")
        smb = PathMapping(r"F:\Downloads", "smb:/downloads")
        for path in ("/downloads/Movie", "local:/downloads/Movie"):
            self.assertEqual(local.to_windows(path), "E:/Downloads/Movie")
            self.assertIsNone(smb.to_windows(path))
        self.assertEqual(smb.to_windows("smb:/DOWNLOADS/Movie"), "F:/Downloads/Movie")
        self.assertIsNone(local.to_windows("smb:/downloads/Movie"))

    def test_reverse_mapping_rejects_invalid_input(self):
        for path in ("downloads/Movie", "/downloads/../outside", r"/downloads\Movie",
                     "/downloads/a:stream", "/downloads/\x00"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.rule.to_windows(path)

    def test_reverse_mapping_to_drive_root(self):
        rule = PathMapping("E:\\", "/disk")
        self.assertEqual(rule.to_windows("/disk"), "E:/")
        self.assertEqual(rule.to_windows("/disk/Movie"), "E:/Movie")

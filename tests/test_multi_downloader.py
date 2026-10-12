"""双类型下载器适配的隔离测试；不连接真实服务。"""

from functools import wraps
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from helpers import load_plugin
from test_runtime import HostPaths


class MultiDownloaderTests(unittest.TestCase):
    def setUp(self):
        plugin = self.enterContext(load_plugin())
        self.runtime = sys.modules[plugin.__name__ + '.runtime']
        self.qb = type('QbModule', (HostPaths,), {})
        self.tr = type('TrModule', (HostPaths,), {})
        self.hosts = [
            self.runtime.HostBindings('3.1.4', self.qb, ('Windows qB', 'Linux qB'), 'qbittorrent'),
            self.runtime.HostBindings('3.1.4', self.tr, ('Windows TR', 'Linux TR'), 'transmission'),
        ]
        digest = {name: self.runtime.source_digest(getattr(HostPaths, name)) for name in
                  ('normalize_path', 'normalize_return_path', 'get_default_config_name')}
        self.digests = {'qbittorrent': digest, 'transmission': digest}

    def adapter(self, names=('Windows qB', 'Windows TR')):
        config = self.runtime.RuntimeConfig.from_dict({
            'downloaders': list(names),
            'mappings': [{'windows_root': r'E:\Downloads', 'storage_root': '/downloads'}],
        })
        adapter = self.runtime.RuntimeAdapter(config, lambda: tuple(self.hosts), self.digests)
        self.addCleanup(adapter.stop)
        return adapter

    def instance(self, cls, default):
        module = cls()
        module.default_name = default
        return module

    def assert_unpatched(self, cls):
        for name in ('normalize_path', 'normalize_return_path'):
            self.assertNotIn(name, vars(cls))

    def test_transmission_only_leaves_qb_and_base_unpatched(self):
        adapter = self.adapter(('Windows TR',))
        adapter.start()
        self.assert_unpatched(self.qb)
        module = self.instance(self.tr, 'Windows TR')
        self.assertEqual(module.normalize_path(Path('/downloads/Movie'), None), 'E:/Downloads/Movie')
        self.assertEqual(module.normalize_return_path(Path(r'E:\Downloads\Movie'), None), '/downloads/Movie')
        self.assertEqual(HostPaths().normalize_path('/downloads', None), 'original-send:/downloads')
        adapter.stop()
        self.assert_unpatched(self.tr)

    def test_mixed_selection_is_scoped_by_type_and_name(self):
        self.adapter().start()
        for cls, selected, other, wrong_type in (
            (self.qb, 'Windows qB', 'Linux qB', 'Windows TR'),
            (self.tr, 'Windows TR', 'Linux TR', 'Windows qB'),
        ):
            module = self.instance(cls, selected)
            for name in (None, selected):
                self.assertEqual(module.normalize_path('/downloads/A', name), 'E:/Downloads/A')
                self.assertEqual(module.normalize_return_path(r'E:\Downloads\A', name), '/downloads/A')
            for name in (other, wrong_type):
                self.assertEqual(module.normalize_path('/downloads/A', name), 'original-send:/downloads/A')
                self.assertEqual(module.normalize_return_path('/data/A', name), 'original-return:/data/A')
            module.default_name = other
            self.assertEqual(module.normalize_path('/downloads/A', None), 'original-send:/downloads/A')

    def test_reload_repeated_start_and_stop_restore_both_classes(self):
        adapter = self.adapter()
        adapter.start()
        wrapper = self.qb.normalize_path
        adapter.start()
        self.assertIs(self.qb.normalize_path, wrapper)
        old_tr = self.tr
        self.tr = type('ReloadedTR', (HostPaths,), {})
        self.hosts[1] = self.runtime.HostBindings('3.1.4', self.tr, ('Windows TR',), 'transmission')
        adapter.refresh()
        self.assert_unpatched(old_tr)
        self.assertEqual(self.instance(self.tr, 'Windows TR').normalize_path('/downloads', None), 'E:/Downloads')
        self.assertEqual(self.instance(self.qb, 'Windows qB').normalize_path('/downloads', None), 'E:/Downloads')
        adapter.stop()
        adapter.stop()
        self.assert_unpatched(self.qb)
        self.assert_unpatched(self.tr)

    def test_type_change_reassigns_same_selected_name(self):
        adapter = self.adapter(('Windows qB',))
        adapter.start()
        self.hosts[0] = self.runtime.HostBindings('3.1.4', self.qb, ('Linux qB',), 'qbittorrent')
        self.hosts[1] = self.runtime.HostBindings('3.1.4', self.tr, ('Windows qB',), 'transmission')
        adapter.refresh()
        self.assert_unpatched(self.qb)
        self.assertEqual(self.instance(self.tr, 'Windows qB').normalize_path('/downloads', None), 'E:/Downloads')

    def test_duplicate_name_across_types_rejected(self):
        self.hosts[1] = self.runtime.HostBindings('3.1.4', self.tr, ('Windows qB',), 'transmission')
        with self.assertRaisesRegex(self.runtime.CompatibilityError, '重复'):
            self.adapter(('Windows qB',)).start()
        self.assert_unpatched(self.qb)
        self.assert_unpatched(self.tr)

    def test_all_contracts_checked_before_installing_any_class(self):
        def changed(self, path, downloader):
            return 'changed'
        self.tr.normalize_path = changed
        with self.assertRaises(self.runtime.CompatibilityError):
            self.adapter().start()
        self.assert_unpatched(self.qb)
        self.assertIs(self.tr.normalize_path, changed)
        self.assertNotIn('normalize_return_path', vars(self.tr))
        # 未选中的类型不参与契约检查。
        adapter = self.adapter(('Windows qB',))
        adapter.start()
        self.assertTrue(adapter.is_active())

    def test_partial_install_failure_rolls_back_all_classes(self):
        class RejectReturn(type):
            def __setattr__(cls, name, value):
                if name == 'normalize_return_path':
                    raise RuntimeError('模拟 Transmission 拒绝第二个包装')
                super().__setattr__(name, value)
        self.tr = RejectReturn('TR', (HostPaths,), {})
        self.hosts[1] = self.runtime.HostBindings('3.1.4', self.tr, ('Windows TR',), 'transmission')
        adapter = self.adapter()
        with self.assertRaises(RuntimeError):
            adapter.start()
        self.assertFalse(adapter.is_active())
        self.assert_unpatched(self.qb)
        self.assert_unpatched(self.tr)

    def test_removed_downloader_disables_both_types(self):
        adapter = self.adapter()
        adapter.start()
        self.hosts.pop()
        with self.assertRaises(self.runtime.CompatibilityError):
            adapter.refresh()
        self.assertFalse(adapter.is_active())
        self.assert_unpatched(self.qb)
        self.assert_unpatched(self.tr)

    def test_external_transmission_wrapper_preserved_on_failed_refresh(self):
        adapter = self.adapter()
        adapter.start()
        original = self.tr.normalize_path
        @wraps(original)
        def external(*args, **kwargs):
            return original(*args, **kwargs)
        self.tr.normalize_path = external
        with self.assertRaises(self.runtime.CompatibilityError):
            adapter.refresh()
        self.assert_unpatched(self.qb)
        self.assertIs(self.tr.normalize_path, external)
        self.assertEqual(self.instance(self.tr, 'Windows TR').normalize_path('/downloads', None),
                         'original-send:/downloads')

    def test_resolver_groups_enabled_sdk_configs_by_type(self):
        from app.sdk.services import ServiceConfigHelper
        ServiceConfigHelper.get_downloader_configs.return_value = [
            SimpleNamespace(name='Windows qB', enabled=True, type='qbittorrent'),
            SimpleNamespace(name='Windows TR', enabled=True, type='transmission'),
            SimpleNamespace(name='Disabled TR', enabled=False, type='transmission'),
            SimpleNamespace(name='Unsupported', enabled=True, type='rtorrent'),
        ]
        modules = {'app.modules.qbittorrent': SimpleNamespace(QbittorrentModule=self.qb),
                   'app.modules.transmission': SimpleNamespace(TransmissionModule=self.tr)}
        with patch.object(self.runtime, 'import_module', side_effect=modules.__getitem__), \
                patch.dict(sys.modules, {'app.runtime.version': SimpleNamespace(get_app_version=lambda: '3.1.4')}):
            hosts = self.runtime.resolve_host()
        self.assertEqual([(host.downloader_type, host.downloader_names) for host in hosts],
                         [('qbittorrent', ('Windows qB',)), ('transmission', ('Windows TR',))])

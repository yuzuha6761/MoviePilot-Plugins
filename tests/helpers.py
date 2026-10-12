"""通过文件路径加载纯转换模块，避免引入 MoviePilot 运行时。"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock, patch
from contextlib import contextmanager

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins.v3" / "windowsqbsmb"


def load_mapping():
    name = "_windowsqbsmb_mapping_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "mapping.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module.PathMapping


@contextmanager
def load_plugin(base=object):
    """替代 SDK 边界，保留包结构以测试相对导入。"""
    name = "_windowsqbsmb_entry_test"
    sdk = ModuleType("app.sdk.plugin")
    sdk._PluginBase = base
    logging = ModuleType("app.sdk.logging")
    logging.logger = Mock()
    services = ModuleType("app.sdk.services")
    services.ServiceConfigHelper = Mock()
    services.ServiceConfigHelper.get_downloader_configs.return_value = []
    stubs = {"app": ModuleType("app"), "app.sdk": ModuleType("app.sdk"),
             "app.sdk.plugin": sdk, "app.sdk.logging": logging, "app.sdk.services": services}
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**stubs, name: module}):
        spec.loader.exec_module(module)
        yield module

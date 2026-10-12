"""MoviePilot 内部接口适配边界；不建立连接、不改写下载器配置。"""

import ast
from dataclasses import dataclass
from functools import wraps
import hashlib
import inspect
from pathlib import PurePath
import textwrap
import threading

from .mapping import PathMapping
from .compatibility import METHOD_DIGESTS, SUPPORTED_VERSION


class CompatibilityError(RuntimeError):
    """宿主版本、方法或包装所有权不满足已核对的契约。"""


def source_digest(method):
    """忽略行号和格式变化，检测同版本内的方法实现变更。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    return tree_digest(tree)


def tree_digest(tree):
    # Python 3.13 起 ast.dump 默认省略部分空字段，不能直接拿它做跨版本摘要。
    # 固定字段顺序并省略空的可选字段，保持离线 3.12 与宿主 3.14 的表示一致。
    def canonical(value):
        if isinstance(value, ast.AST):
            return (type(value).__name__, tuple(
                (name, canonical(item)) for name, item in sorted(ast.iter_fields(value))
                if item is not None and item != []))
        if isinstance(value, list):
            return tuple(canonical(item) for item in value)
        return value
    return hashlib.sha256(repr(canonical(tree)).encode()).hexdigest()


@dataclass(frozen=True)
class HostBindings:
    version: str
    module_class: type
    downloader_names: tuple[str, ...]


def resolve_host():
    """仅启用时加载宿主；公开配置接口与内部适配集中在此处。"""
    from app.sdk.services import ServiceConfigHelper
    from app.modules.qbittorrent import QbittorrentModule
    from app.runtime.version import get_app_version

    names = tuple(c.name for c in ServiceConfigHelper.get_downloader_configs()
                  if c.enabled and c.type == "qbittorrent")
    return HostBindings(get_app_version(), QbittorrentModule, names)


@dataclass(frozen=True)
class RuntimeConfig:
    downloader: str
    mappings: tuple[PathMapping, ...]

    @classmethod
    def from_dict(cls, config):
        name = str(config.get("downloader") or "").strip()
        if not name:
            raise ValueError("请填写已启用的 qBittorrent 下载器配置名称")
        # 保留已有配置键名；smb_root / smb_temp_root 的值也可为本地存储路径。
        rules = [PathMapping(str(config.get("windows_root") or "").strip(),
                             str(config.get("smb_root") or "").strip())]
        temp_windows = str(config.get("windows_temp_root") or "").strip()
        temp_storage = str(config.get("smb_temp_root") or "").strip()
        if temp_windows or temp_storage:
            rules.append(PathMapping(temp_windows, temp_storage))
        # 双向规则不允许重叠，否则无法保证往返一致。
        if len(rules) == 2:
            a, b = rules
            if (a.to_storage(b.windows_root) is not None or b.to_storage(a.windows_root) is not None
                    or a.to_windows(b.storage_root) is not None
                    or b.to_windows(a.storage_root) is not None):
                raise ValueError("主目录与临时目录映射不能重叠；根目录已覆盖的子目录无需单独配置")
        return cls(name, tuple(rules))

    def convert(self, path, *, returning):
        value = str(path)
        # POSIX Path 会把 smb:/、local:/ 的尾斜杠去掉；恢复已知协议根。
        # Windows 盘符根同样会变成 E:，只在显式配置了该盘符根时恢复。
        if isinstance(path, PurePath):
            if not returning and value in {"smb:", "local:"}:
                value += "/"
            elif returning and any(value.casefold() + "/" == rule.windows_root.casefold()
                                   for rule in self.mappings):
                value += "/"
        for rule in self.mappings:
            result = rule.to_storage(value) if returning else rule.to_windows(value)
            if result is not None:
                return result
        raise ValueError("路径不在 Windows qBittorrent 路径映射范围内，请检查保存目录或临时目录")


_MISSING = object()
_INSTALL_LOCK = threading.RLock()
_OWNER = "_windowsqbsmb_runtime_owner"


class RuntimeAdapter:
    """只覆盖 qBittorrent 模块的两个转换入口，其他下载器仍调用原方法。

    配置重载保留同一个模块类，包装自动作用于新实例。Python 类重载时，
    refresh 显式重新核对契约并迁移包装。卸载后被第三方保留的旧包装只透传。
    """

    def __init__(self, config, resolver=resolve_host, digests=None):
        self.config = config
        self._resolver = resolver
        self._digests = METHOD_DIGESTS if digests is None else digests
        self._lock = threading.RLock()
        self._patches = []
        self._host_class = None
        self._active = False

    def _validate(self, host):
        if host.version.lstrip("v") != SUPPORTED_VERSION:
            raise CompatibilityError(f"尚未适配 MoviePilot {host.version}，仅核对 {SUPPORTED_VERSION}")
        if self.config.downloader not in host.downloader_names:
            raise CompatibilityError("指定的 qBittorrent 下载器不存在或未启用")
        for name, digest in self._digests.items():
            method = getattr(host.module_class, name, None)
            if getattr(method, _OWNER, None) is self:
                method = method.__wrapped__
            elif getattr(method, _OWNER, None) is not None:
                raise CompatibilityError(f"{name} 已由另一个 Windows qBittorrent 路径映射插件实例接管")
            try:
                if hasattr(method, "__wrapped__") or source_digest(method) != digest:
                    raise CompatibilityError(f"{name} 实现已变更或已有其他包装，拒绝接管")
            except (TypeError, OSError, IndentationError, SyntaxError) as error:
                raise CompatibilityError(f"无法验证 {name} 的源码契约") from error
        for name in ("normalize_path", "normalize_return_path"):
            method = getattr(host.module_class, name)
            parameters = list(inspect.signature(method).parameters.values())
            if ([p.name for p in parameters] != ["self", "path", "downloader"]
                    or any(p.kind != p.POSITIONAL_OR_KEYWORD for p in parameters)):
                raise CompatibilityError(f"{name} 签名不兼容")

    def _wrapper(self, original, returning):
        @wraps(original)
        def wrapped(module, path, downloader):
            # 锁覆盖一次纯转换。其他下载器的原方法在锁外执行。
            with self._lock:
                if self._active:
                    selected = downloader or module.get_default_config_name()
                    if selected == self.config.downloader:
                        return self.config.convert(path, returning=returning)
            return original(module, path, downloader)
        setattr(wrapped, _OWNER, self)
        return wrapped

    def start(self):
        with _INSTALL_LOCK, self._lock:
            host = self._resolver()
            self._validate(host)
            if self._active and self._host_class is host.module_class:
                return
            self.stop()
            try:
                for name in ("normalize_path", "normalize_return_path"):
                    original = getattr(host.module_class, name)
                    own_value = vars(host.module_class).get(name, _MISSING)
                    wrapper = self._wrapper(original, name == "normalize_return_path")
                    setattr(host.module_class, name, wrapper)
                    self._patches.append((host.module_class, name, own_value, wrapper))
                self._host_class = host.module_class
                self._active = True
            except Exception:
                self.stop()
                raise

    def refresh(self):
        """重新验证并处理类重载；失败时撤销本插件仍持有的包装。"""
        try:
            self.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        with _INSTALL_LOCK, self._lock:
            self._active = False
            for target, name, original, wrapper in reversed(self._patches):
                if vars(target).get(name) is wrapper:
                    if original is _MISSING:
                        delattr(target, name)
                    else:
                        setattr(target, name, original)
            self._patches.clear()
            self._host_class = None

    def is_active(self):
        with self._lock:
            return self._active and all(getattr(target, name) is wrapper
                                        for target, name, _, wrapper in self._patches)

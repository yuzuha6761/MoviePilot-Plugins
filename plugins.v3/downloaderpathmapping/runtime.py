"""MoviePilot 内部接口适配边界；不建立连接、不改写下载器配置。"""

import ast
from dataclasses import dataclass
from functools import wraps
import hashlib
import inspect
from importlib import import_module
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
    downloader_type: str = "qbittorrent"


def get_downloader_configs():
    """通过公开 SDK 读取配置，不连接下载器。"""
    from app.sdk.services import ServiceConfigHelper

    return tuple(c for c in ServiceConfigHelper.get_downloader_configs()
                 if c.enabled and c.type in METHOD_DIGESTS)


def get_downloader_names():
    return tuple(dict.fromkeys(c.name for c in get_downloader_configs()))


def resolve_host():
    """仅启用时加载宿主；公开配置接口与内部适配集中在此处。"""
    from app.runtime.version import get_app_version

    configs = get_downloader_configs()
    version = get_app_version()
    hosts = []
    for kind, class_name in (("qbittorrent", "QbittorrentModule"),
                             ("transmission", "TransmissionModule")):
        names = tuple(dict.fromkeys(c.name for c in configs if c.type == kind))
        if names:
            module = import_module(f"app.modules.{kind}")
            hosts.append(HostBindings(version, getattr(module, class_name), names, kind))
    return tuple(hosts)


@dataclass(frozen=True)
class RuntimeConfig:
    downloaders: tuple[str, ...]
    mappings: tuple[PathMapping, ...]

    @classmethod
    def from_dict(cls, config):
        names = config.get("downloaders")
        if (not isinstance(names, list) or not names
                or any(not isinstance(name, str) or not name.strip() for name in names)):
            raise ValueError("请选择至少一个已启用的 qBittorrent 或 Transmission 下载器")
        names = tuple(dict.fromkeys(name.strip() for name in names))
        entries = config.get("mappings")
        if not isinstance(entries, list) or not entries:
            raise ValueError("请添加至少一条路径映射")
        rules = []
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise ValueError(f"第 {index} 条映射格式不正确")
            windows, storage = entry.get("windows_root"), entry.get("storage_root")
            if not isinstance(windows, str) or not isinstance(storage, str):
                raise ValueError(f"第 {index} 条映射需填写转换前、后的路径前缀")
            try:
                rules.append(PathMapping(windows.strip(), storage.strip()))
            except ValueError as error:
                raise ValueError(f"第 {index} 条映射：{error}") from error
        # 两侧前缀均不能重叠，避免反向转换无法唯一确定 Windows 路径。
        for index, a in enumerate(rules):
            for other_index, b in enumerate(rules[index + 1:], index + 1):
                if (a.convert(b.windows_root) is not None
                        or b.convert(a.windows_root) is not None
                        or a.to_windows(b.storage_root) is not None
                        or b.to_windows(a.storage_root) is not None):
                    raise ValueError(f"第 {index + 1}、{other_index + 1} 条映射重叠；"
                                     "转换前、后路径前缀均不能重复或互相包含")
        return cls(names, tuple(rules))

    def convert(self, path, *, returning=True):
        value = str(path)
        # POSIX Path 会移除 URI 根和盘符根的尾斜杠，按转换方向恢复。
        if isinstance(path, PurePath):
            if not returning and value in {"smb:", "local:"}:
                value += "/"
            elif returning and any(
                    value.casefold() + "/" == rule.windows_root.replace("\\", "/").casefold()
                    for rule in self.mappings):
                value += "/"
        for rule in self.mappings:
            result = rule.convert(value) if returning else rule.to_windows(value)
            if result is not None:
                return result
        direction = "返回路径未匹配转换前路径前缀" if returning else "下发路径未匹配转换后路径前缀"
        prefixes = [rule.windows_root if returning else rule.storage_root for rule in self.mappings]
        raise ValueError(f"{direction}：待匹配路径={value!r}，已配置前缀={prefixes!r}。"
                         "请核对目录前缀和路径类型（本地 / 或 local:/、SMB smb:/）")


_MISSING = object()
_INSTALL_LOCK = threading.RLock()
_OWNER = "_downloaderpathmapping_runtime_owner"


class RuntimeAdapter:
    """按类型覆盖所选下载器的下发和返回路径入口，其他下载器调用原方法。

    配置重载保留同一个模块类，包装自动作用于新实例。Python 类重载时，
    refresh 显式重新核对契约并迁移包装。卸载后被第三方保留的旧包装只透传。
    """

    def __init__(self, config, resolver=resolve_host, digests=None):
        self.config = config
        self._resolver = resolver
        self._digests = METHOD_DIGESTS if digests is None else digests
        self._lock = threading.RLock()
        self._patches = []
        self._hosts = ()
        self._active = False

    def _validate(self, host):
        if host.version.lstrip("v") != SUPPORTED_VERSION:
            raise CompatibilityError(f"尚未适配 MoviePilot {host.version}，仅核对 {SUPPORTED_VERSION}")
        if host.downloader_type not in self._digests:
            raise CompatibilityError(f"尚未适配下载器类型 {host.downloader_type}")
        for name, digest in self._digests[host.downloader_type].items():
            method = getattr(host.module_class, name, None)
            if getattr(method, _OWNER, None) is self:
                method = method.__wrapped__
            elif getattr(method, _OWNER, None) is not None:
                raise CompatibilityError(f"{name} 已由另一个下载器路径映射插件实例接管")
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

    def _wrapper(self, original, returning, names):
        @wraps(original)
        def wrapped(module, path, downloader):
            # 锁覆盖一次纯转换。其他下载器的原方法在锁外执行。
            with self._lock:
                if self._active:
                    selected = downloader or module.get_default_config_name()
                    if selected in names:
                        try:
                            return self.config.convert(path, returning=returning)
                        except ValueError as error:
                            raise ValueError(f"下载器 {selected!r}：{error}") from error
            return original(module, path, downloader)
        setattr(wrapped, _OWNER, self)
        return wrapped

    def start(self):
        with _INSTALL_LOCK, self._lock:
            available = self._resolver()
            for name in self.config.downloaders:
                owners = [host for host in available if name in host.downloader_names]
                if not owners:
                    raise CompatibilityError(f"指定的下载器 {name!r} 不存在、未启用或类型不支持")
                if len(owners) != 1:
                    raise CompatibilityError(f"下载器名称 {name!r} 在多个类型中重复，请修改为唯一名称")
            hosts = tuple(HostBindings(host.version, host.module_class,
                          tuple(name for name in host.downloader_names if name in self.config.downloaders),
                          host.downloader_type) for host in available
                          if any(name in self.config.downloaders for name in host.downloader_names))
            # 所有类型先通过检查，再统一安装；任一类型失败时不留下半套包装。
            for host in hosts:
                self._validate(host)
            if self._active and self._hosts == hosts:
                return
            self.stop()
            try:
                for host in hosts:
                    for name in ("normalize_path", "normalize_return_path"):
                        original = getattr(host.module_class, name)
                        own_value = vars(host.module_class).get(name, _MISSING)
                        wrapper = self._wrapper(original, returning=name == "normalize_return_path",
                                                names=frozenset(host.downloader_names))
                        setattr(host.module_class, name, wrapper)
                        self._patches.append((host.module_class, name, own_value, wrapper))
                self._hosts = hosts
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
            self._hosts = ()

    def is_active(self):
        with self._lock:
            return self._active and all(getattr(target, name) is wrapper
                                        for target, name, _, wrapper in self._patches)

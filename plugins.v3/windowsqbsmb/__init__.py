"""Windows qBittorrent 路径映射插件入口。"""

from typing import Any
from functools import wraps
from threading import RLock

from app.sdk.plugin import _PluginBase
from app.sdk.logging import logger

from .runtime import RuntimeAdapter, RuntimeConfig


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return call


class WindowsQbSmb(_PluginBase):
    """默认关闭；仅在宿主契约检查通过后启用实验性运行时适配。"""

    plugin_name = "Windows qBittorrent 路径映射"
    plugin_desc = "配置 Windows qBittorrent 与 MoviePilot 本地或 SMB 存储的双向路径映射，兼容混合斜杠和临时目录，无需修改 MoviePilot 镜像。实验版。"
    plugin_icon = ""
    plugin_version = "0.1.0"
    plugin_author = "Local"
    plugin_config_prefix = "windowsqbsmb_"
    plugin_order = 50
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._lifecycle_lock = RLock()

    @_serialized
    def init_plugin(self, config: dict[str, Any] | None = None) -> None:
        """先卸载旧包装，配置有效且版本匹配时接管转换入口。"""
        self.stop_service()
        self._config = dict(config or {})
        if self._config.get("enabled") is not True:
            return
        try:
            self._runtime = RuntimeAdapter(RuntimeConfig.from_dict(self._config))
            self._runtime.start()
            self._status = "运行时适配已启用。"
        except Exception as error:
            self.stop_service()
            self._status = f"启用失败：{error}"
            logger.error(f"{self.plugin_name}：{self._status}")

    @_serialized
    def get_state(self) -> bool:
        runtime = getattr(self, "_runtime", None)
        return bool(runtime and runtime.is_active())

    @_serialized
    def get_service(self) -> list:
        if not self.get_state():
            return []
        return [{"id": "WindowsQbSmbRuntimeCheck", "name": "Windows qBittorrent 路径映射运行检查",
                 "trigger": "interval", "func": self._check_runtime,
                 "kwargs": {"seconds": 30}}]

    @_serialized
    def _check_runtime(self) -> None:
        runtime = getattr(self, "_runtime", None)
        if runtime is None:
            return
        try:
            runtime.refresh()
        except Exception as error:
            self.stop_service()
            self._status = f"适配已停止：{error}；请核对宿主后重新保存配置。"
            logger.error(f"{self.plugin_name}：{self._status}")

    @staticmethod
    def get_command() -> list:
        return []

    def get_api(self) -> list:
        return []

    def get_form(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """提供独立 Windows 路径输入，避免宿主 POSIX 路径表单的限制。"""
        fields = [
            ("downloader", "下载器配置名称", "与 MoviePilot 下载器名称一致"),
            ("windows_root", "Windows 下载根路径", "例如 E:/qBittorrent_download"),
            ("smb_root", "MoviePilot 存储路径", "本地例如 /downloads 或 local:/downloads；SMB 例如 smb:/"),
            ("windows_temp_root", "Windows 临时目录（可选）", "仅临时目录在主映射范围外时填写"),
            ("smb_temp_root", "临时目录存储路径（可选）", "与 Windows 临时目录成对填写，可使用本地或 SMB 路径"),
        ]
        content = [{
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal"},
            "text": "实验版，仅适配已核对的 MoviePilot 3.1.4 方法契约。"
                    "下载目录选择与映射一致的本地或 SMB 存储；未映射路径会报错。",
        }, {"component": "VSwitch", "props": {"model": "enabled", "label": "启用运行时适配"}}]
        content.extend({
            "component": "VTextField",
            "props": {"model": key, "label": label, "hint": hint, "persistent-hint": True},
        } for key, label, hint in fields)
        return [{"component": "VForm", "content": content}], {
            "enabled": False, "downloader": "", "windows_root": "", "smb_root": "smb:/",
            "windows_temp_root": "", "smb_temp_root": "",
        }

    @_serialized
    def get_page(self) -> list:
        return [{
            "component": "VAlert", "props": {"type": "info"},
            "text": getattr(self, "_status", "运行时适配未启用。"),
        }]

    @_serialized
    def stop_service(self) -> None:
        """只移除仍归本插件所有的包装，保留其他插件后来安装的包装。"""
        runtime = getattr(self, "_runtime", None)
        if runtime is not None:
            runtime.stop()
        self._runtime = None
        self._status = "运行时适配未启用。"

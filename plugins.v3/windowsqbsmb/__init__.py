"""下载器路径映射插件入口。"""

from typing import Any
from functools import wraps
from threading import RLock

from app.sdk.plugin import _PluginBase
from app.sdk.logging import logger

from .runtime import RuntimeAdapter, RuntimeConfig, get_downloader_names


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return call


class WindowsQbSmb(_PluginBase):
    """默认关闭；仅在宿主契约检查通过后启用实验性运行时适配。"""

    plugin_name = "下载器路径映射"
    plugin_desc = "将 Windows qBittorrent 返回路径转换为 Linux 风格，并在下载下发、修改保存位置时反向转换，支持多下载器和多条前缀映射。"
    plugin_icon = ""
    plugin_version = "0.2.2"
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
        return [{"id": "WindowsQbSmbRuntimeCheck", "name": "下载器路径映射运行检查",
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
        """动态发现下载器，使用宿主表单事件添加、切换和删除映射。"""
        defaults = {"enabled": False, "downloaders": [], "mappings": [], "mapping_index": 0}
        notice = ""
        try:
            names = get_downloader_names()
            if not names:
                notice = "未发现已启用的 qBittorrent 下载器，请先在 MoviePilot 中配置并启用，再重新打开此页面。"
        except Exception:
            names = ()
            notice = "下载器列表读取失败，请检查 MoviePilot 下载器配置后重新打开此页面。"
        content = [{
            "component": "VAlert",
            "props": {"type": "info", "variant": "tonal", "class": "mb-4"},
            "text": "返回路径按“转换前 → 转换后”替换前缀，并统一为正斜杠。"
                    "下载下发和修改保存位置时按相反方向转换。所选下载器共用以下映射；"
                    "两侧路径前缀均不能重叠，未匹配的路径会提示错误。",
        }, {"component": "VSwitch", "props": {"model": "enabled", "label": "启用运行时适配"}}, {
            "component": "VSelect",
            "props": {"model": "downloaders", "label": "下载器（可多选）",
                      "items": [{"title": name, "value": name} for name in names],
                      "multiple": True, "chips": True, "closable-chips": True,
                      "hint": "自动读取 MoviePilot 中已启用的 qBittorrent 下载器",
                      "persistent-hint": True, "class": "mb-4"},
        }]
        if notice:
            content.append({"component": "VAlert", "props": {"type": "warning", "class": "mb-4"},
                            "text": notice})
        content.extend([{
            "component": "VSelect",
            "props": {"model": "mapping_index", "label": "映射关系",
                      "items": "{{ mappings.map((item, index) => ({value: index, title: "
                               "(index + 1) + '. ' + (item.windows_root || '待填写转换前前缀')"
                               " + ' → ' + (item.storage_root || '待填写转换后前缀')})) }}",
                      "disabled": "{{ !mappings.length }}",
                      "hint": "添加后填写下方路径；选择已有映射可修改或删除",
                      "persistent-hint": True, "class": "mb-4"},
        }])
        # FormRender 仅对顶层键提供 v-model；数组项用表达式和更新事件绑定。
        for key, label, hint in [
            ("windows_root", "转换前路径前缀",
             r"例如 E:\qBittorrent_download 或 F:\Incomplete；支持反斜杠、正斜杠及混用"),
            ("storage_root", "转换后路径前缀",
             "本地例如 /downloads；SMB 使用 smb:/downloads，须与下发路径类型一致"),
        ]:
            content.append({
                "component": "VTextField",
                "props": {"modelValue": "{{ mappings[mapping_index]?." + key + " || '' }}",
                          "onUpdate:modelValue": "value => { if (mappings[mapping_index]) "
                                                  "mappings[mapping_index]." + key + " = value; }",
                          "disabled": "{{ !mappings[mapping_index] }}", "label": label,
                          "hint": hint, "persistent-hint": True, "class": "mb-4"},
            })
        content.extend([{
            "component": "VBtn", "text": "添加映射",
            "props": {"color": "primary", "variant": "tonal", "class": "mr-3", "type": "button",
                      "onClick": "() => { mappings.push({windows_root: '', storage_root: ''}); "
                                 "mapping_index = mappings.length - 1; }"},
        }, {
            "component": "VBtn", "text": "删除映射",
            "props": {"color": "error", "variant": "text", "type": "button",
                      "disabled": "{{ !mappings[mapping_index] }}",
                      "onClick": "() => { if (mappings[mapping_index]) mappings.splice(mapping_index, 1); "
                                 "mapping_index = Math.max(0, Math.min(mapping_index, mappings.length - 1)); }"},
        }])
        return [{"component": "VForm", "content": content}], defaults

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

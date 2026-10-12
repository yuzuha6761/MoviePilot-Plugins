"""Windows 与正斜杠路径的双向前缀转换；不访问文件系统。"""

from dataclasses import dataclass
import re


def _segments(value: str) -> tuple[str, ...]:
    """拒绝目录穿越、NUL 与路径段中的协议/盘符分隔符。"""
    parts = tuple(part for part in value.split("/") if part)
    if any(part in {".", ".."} or "\x00" in part or ":" in part for part in parts):
        raise ValueError("路径包含非法目录段")
    return parts


def _windows(value: str) -> tuple[str, tuple[str, ...]]:
    normalized = value.replace("\\", "/")
    if not re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError(r"需要 Windows 盘符绝对路径，例如 E:\Downloads")
    return normalized[:2], _segments(normalized[3:])


def _output(value: str) -> tuple[str, tuple[str, ...]]:
    """解析转换后前缀，支持绝对路径和 URI，不查询实际存储。"""
    if "\\" in value:
        raise ValueError("转换后路径前缀需使用正斜杠")
    if value.startswith("smb:/"):
        return "smb:/", _segments(value[len("smb:/"):])
    if value.startswith("local:/"):
        return "/", _segments(value[len("local:/"):])
    if value.startswith("/") and not value.startswith("//"):
        return "/", _segments(value)
    raise ValueError("转换后路径前缀需以 / 开头，例如 /downloads")


@dataclass(frozen=True)
class PathMapping:
    """一条路径规则；返回 None 表示路径不在该规则范围内。"""

    windows_root: str
    storage_root: str

    def __post_init__(self) -> None:
        _windows(self.windows_root)
        _output(self.storage_root)

    def convert(self, path: str) -> str | None:
        """替换返回路径前缀，统一分隔符并保留后缀大小写。"""
        drive, parts = _windows(path)
        root_drive, root_parts = _windows(self.windows_root)
        count = len(root_parts)
        if drive.casefold() != root_drive.casefold():
            return None
        if tuple(p.casefold() for p in parts[:count]) != tuple(
            p.casefold() for p in root_parts
        ):
            return None
        prefix, output_parts = _output(self.storage_root)
        return prefix + "/".join(output_parts + parts[count:])

    def to_windows(self, path: str) -> str | None:
        """下发下载或修改保存位置时反向替换前缀，统一输出正斜杠。"""
        prefix, parts = _output(path)
        root_prefix, root_parts = _output(self.storage_root)
        if prefix != root_prefix:
            return None
        count = len(root_parts)
        matched = parts[:count]
        # SMB 前缀不区分大小写；Linux 路径按大小写精确匹配。
        if prefix == "smb:/":
            matched = tuple(part.casefold() for part in matched)
            root_parts = tuple(part.casefold() for part in root_parts)
        if matched != root_parts:
            return None
        drive, windows_parts = _windows(self.windows_root)
        return drive + "/" + "/".join(windows_parts + parts[count:])

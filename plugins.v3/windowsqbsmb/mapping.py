"""Windows 与 MoviePilot 本地/SMB 路径转换；不依赖宿主或真实文件系统。"""

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
        raise ValueError("需要 Windows 盘符绝对路径，例如 E:/Downloads")
    return normalized[:2], _segments(normalized[3:])


def _storage(value: str) -> tuple[str, tuple[str, ...]]:
    """识别存储身份；本地绝对路径与 local: URI 使用同一命名空间。"""
    if "\\" in value:
        raise ValueError("MoviePilot 存储路径需使用正斜杠")
    if value.startswith("smb:/"):
        return "smb", _segments(value[len("smb:/"):])
    if value.startswith("local:/"):
        return "local", _segments(value[len("local:/"):])
    if value.startswith("/") and not value.startswith("//"):
        return "local", _segments(value)
    raise ValueError("需要本地绝对路径、local:/ 或 smb:/ 存储路径")


@dataclass(frozen=True)
class PathMapping:
    """一条路径规则；返回 None 表示路径不在该规则范围内。"""

    windows_root: str
    storage_root: str

    def __post_init__(self) -> None:
        _windows(self.windows_root)
        _storage(self.storage_root)

    def to_storage(self, path: str) -> str | None:
        """转换下载器原生路径，按完整目录段匹配 Windows 根。"""
        drive, parts = _windows(path)
        root_drive, root_parts = _windows(self.windows_root)
        count = len(root_parts)
        if drive.casefold() != root_drive.casefold():
            return None
        if tuple(p.casefold() for p in parts[:count]) != tuple(
            p.casefold() for p in root_parts
        ):
            return None
        scheme, storage_parts = _storage(self.storage_root)
        prefix = "smb:/" if scheme == "smb" else "/"
        return prefix + "/".join(storage_parts + parts[count:])

    def to_windows(self, uri: str) -> str | None:
        """转换 MP 存储 URI，向下载器统一输出正斜杠路径。"""
        scheme, parts = _storage(uri)
        root_scheme, root_parts = _storage(self.storage_root)
        if scheme != root_scheme:
            return None
        count = len(root_parts)
        # Windows SMB 维持不区分大小写；Linux 本地路径按大小写精确匹配。
        prefix = parts[:count]
        if scheme == "smb":
            prefix = tuple(p.casefold() for p in prefix)
            root_parts = tuple(p.casefold() for p in root_parts)
        if prefix != root_parts:
            return None
        drive, windows_parts = _windows(self.windows_root)
        return drive + "/" + "/".join(windows_parts + parts[count:])

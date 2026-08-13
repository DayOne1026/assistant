from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings


class Storage(ABC):
    """文件存储抽象。LocalStorage 写磁盘 storage_root；
    S3/OSS 可替换实现，接口不变。
    图片命名约定：media/{user_id}/{uuid}.{ext}——UUID 名防碰撞、目录按用户隔离。
    """

    @abstractmethod
    def write(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    def read(self, path: str) -> bytes: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...


class LocalStorage(Storage):
    def __init__(self, root: str):
        self._root = Path(root).resolve()

    def _full(self, path: str) -> Path:
        p = (self._root / path).resolve()
        if not p.is_relative_to(self._root):  # 防目录穿越
            raise ValueError(f"非法路径: {path}")
        return p

    def write(self, path: str, data: bytes) -> None:
        p = self._full(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def read(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    def delete(self, path: str) -> None:
        self._full(path).unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return self._full(path).exists()


_storage: Storage | None = None


def get_storage() -> Storage:
    """FastAPI 依赖：全局单例（06 图片库用）。"""
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().storage_root)
    return _storage

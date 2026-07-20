from __future__ import annotations

import hashlib
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Callable, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_SCHEMA_VERSION = "3"
_CACHE_LOCK = RLock()


def _safe_namespace(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return cleaned or "frame"


def _cache_directory() -> Path:
    data_root = (ROOT / "data").resolve(strict=False)
    cache_root = CACHE_DIR.resolve(strict=False)
    try:
        cache_root.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("Parquet 缓存目录超出 data 目录") from exc
    return cache_root


@lru_cache(maxsize=256)
def _sha256_for_stat(path_text: str, size: int, modified_ns: int) -> str:
    del size, modified_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    return _sha256_for_stat(str(resolved), stat.st_size, stat.st_mtime_ns)


def files_revision(paths: Iterable[Path]) -> tuple[tuple[str, int, int, str], ...]:
    revision = []
    for path in sorted((Path(item).resolve(strict=True) for item in paths), key=str):
        stat = path.stat()
        revision.append((str(path), stat.st_size, stat.st_mtime_ns, file_sha256(path)))
    return tuple(revision)


def revision_digest(namespace: str, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(CACHE_SCHEMA_VERSION.encode("ascii"))
    digest.update(namespace.encode("utf-8"))
    for path, size, modified_ns, content_hash in files_revision(paths):
        digest.update(path.encode("utf-8"))
        digest.update(str(size).encode("ascii"))
        digest.update(str(modified_ns).encode("ascii"))
        digest.update(content_hash.encode("ascii"))
    return digest.hexdigest()


@lru_cache(maxsize=64)
def _read_parquet_cached(path_text: str, size: int, modified_ns: int) -> pd.DataFrame:
    del size, modified_ns
    return pd.read_parquet(path_text)


def _read_cached(path: Path) -> pd.DataFrame:
    stat = path.stat()
    return _read_parquet_cached(str(path), stat.st_size, stat.st_mtime_ns).copy(deep=False)


def _atomic_write_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{destination.stem}-",
        suffix=".parquet.tmp",
        dir=destination.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        compatible = frame.copy()
        object_columns = [column for column in compatible.columns if compatible[column].dtype == object]
        for column in object_columns:
            compatible[column] = compatible[column].map(
                lambda value: None if _is_missing_scalar(value) else str(value)
            ).astype("string")
        compatible.to_parquet(temporary, index=False)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _is_missing_scalar(value) -> bool:
    try:
        missing = pd.isna(value)
        return isinstance(missing, bool) and missing
    except (TypeError, ValueError):
        return False


def load_or_build_parquet(
    namespace: str,
    source_paths: Iterable[Path],
    loader: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    paths = tuple(Path(item) for item in source_paths)
    digest = revision_digest(namespace, paths)
    safe_namespace = _safe_namespace(namespace)
    cache_dir = _cache_directory()
    cache_path = cache_dir / f"{safe_namespace}-{digest[:24]}.parquet"

    with _CACHE_LOCK:
        if cache_path.exists():
            try:
                return _read_cached(cache_path)
            except (OSError, ValueError, TypeError):
                cache_path.unlink(missing_ok=True)

        frame = loader()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Parquet 缓存加载器必须返回 DataFrame")
        _atomic_write_parquet(frame, cache_path)
        _read_parquet_cached.cache_clear()
        result = _read_cached(cache_path)

        for stale in cache_dir.glob(f"{safe_namespace}-*.parquet"):
            if stale != cache_path:
                stale.unlink(missing_ok=True)
        return result


def clear_parquet_memory_cache() -> None:
    _sha256_for_stat.cache_clear()
    _read_parquet_cached.cache_clear()

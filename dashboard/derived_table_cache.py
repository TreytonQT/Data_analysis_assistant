"""Atomic, typed Parquet bundles for expensive derived dashboard tables."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from threading import RLock
from typing import Callable

import pandas as pd

from app_paths import DATA_DIR

_BUNDLE_VERSION = 1
_BUNDLE_LOCK = RLock()


def _cache_root() -> Path:
    def normalized(path: Path) -> Path:
        resolved = str(path.resolve(strict=False))
        if resolved.startswith("\\\\?\\UNC\\"):
            resolved = "\\\\" + resolved[8:]
        elif resolved.startswith("\\\\?\\"):
            resolved = resolved[4:]
        return Path(resolved)

    data_root = normalized(DATA_DIR)
    root = normalized(DATA_DIR / "cache" / "derived")
    try:
        root.relative_to(data_root)
    except ValueError as exc:
        raise ValueError("派生表缓存目录超出 data 目录") from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path: Path, payload: dict) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{path.name}.", suffix=".tmp",
        dir=path.parent, delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_dtypes(frame: pd.DataFrame, dtypes: dict[str, str]) -> pd.DataFrame:
    for column, dtype in dtypes.items():
        if column not in frame.columns:
            raise ValueError(f"派生表缓存缺少列：{column}")
        if dtype == "object":
            frame[column] = frame[column].astype(object).mask(frame[column].isna(), pd.NA)
        else:
            frame[column] = frame[column].astype(dtype)
    return frame


def _read_bundle(manifest_path: Path, namespace: str, revision: str) -> tuple[dict[str, pd.DataFrame], dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("version") != _BUNDLE_VERSION
        or manifest.get("namespace") != namespace
        or manifest.get("revision") != revision
    ):
        raise ValueError("派生表缓存清单版本不匹配")
    root = manifest_path.parent.resolve()
    frames: dict[str, pd.DataFrame] = {}
    for name, item in manifest["frames"].items():
        file_name = item["file"]
        if Path(file_name).name != file_name or not file_name.endswith(".parquet"):
            raise ValueError("派生表缓存文件路径无效")
        path = root / file_name
        frame = pd.read_parquet(path)
        if list(frame.columns) != item["columns"]:
            raise ValueError("派生表缓存列结构已变化")
        frames[name] = _restore_dtypes(frame, item["dtypes"])
    return frames, manifest.get("metadata", {})


def _prune_old_bundles(root: Path, safe_namespace: str) -> None:
    limits = {
        "replenishment-base": 4,
        "listing-source-tables": 2,
        "listing-event-pair": 64,
    }
    keep = limits.get(safe_namespace, 4)
    manifests = []
    for path in root.glob(f"{safe_namespace}-*.json"):
        try:
            manifests.append((path.stat().st_mtime_ns, path))
        except OSError:
            continue
    manifests.sort(key=lambda item: item[0], reverse=True)
    for _, stale_manifest in manifests[keep:]:
        try:
            manifest = json.loads(stale_manifest.read_text(encoding="utf-8"))
            for item in manifest.get("frames", {}).values():
                file_name = item.get("file", "")
                if Path(file_name).name == file_name and file_name.startswith(stale_manifest.stem + "-"):
                    (root / file_name).unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        try:
            stale_manifest.unlink(missing_ok=True)
        except OSError:
            pass


def load_or_build_frame_bundle(
    namespace: str,
    revision: str,
    loader: Callable[[], tuple[dict[str, pd.DataFrame], dict]],
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Load related frames from one committed manifest, or build and persist them."""
    safe_namespace = re.sub(r"[^0-9A-Za-z_-]+", "-", namespace).strip("-") or "frames"
    digest = hashlib.sha256(revision.encode("utf-8")).hexdigest()[:32]
    root = _cache_root()
    stem = f"{safe_namespace}-{digest}"
    manifest_path = root / f"{stem}.json"

    with _BUNDLE_LOCK:
        if manifest_path.exists():
            try:
                return _read_bundle(manifest_path, namespace, revision)
            except Exception:
                manifest_path.unlink(missing_ok=True)

        frames, metadata = loader()
        if not all(isinstance(frame, pd.DataFrame) for frame in frames.values()):
            raise TypeError("派生表缓存加载器必须返回 DataFrame")
        manifest_frames: dict[str, dict] = {}
        try:
            for name, frame in frames.items():
                safe_name = re.sub(r"[^0-9A-Za-z_-]+", "-", name).strip("-") or "frame"
                file_name = f"{stem}-{safe_name}.parquet"
                destination = root / file_name
                handle = tempfile.NamedTemporaryFile(
                    prefix=f".{stem}-{safe_name}.", suffix=".parquet.tmp",
                    dir=root, delete=False,
                )
                temporary = Path(handle.name)
                handle.close()
                try:
                    frame.to_parquet(temporary, index=False)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
                manifest_frames[name] = {
                    "file": file_name,
                    "columns": list(frame.columns),
                    "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
                }
            _atomic_json(
                manifest_path,
                {
                    "version": _BUNDLE_VERSION,
                    "namespace": namespace,
                    "revision": revision,
                    "frames": manifest_frames,
                    "metadata": metadata,
                },
            )
        except Exception:
            manifest_path.unlink(missing_ok=True)
            for item in manifest_frames.values():
                (root / item["file"]).unlink(missing_ok=True)
            return frames, metadata

        _prune_old_bundles(root, safe_namespace)
        return frames, metadata

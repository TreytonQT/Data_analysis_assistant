from __future__ import annotations

import io
import zipfile
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException, UploadFile


ALLOWED_TABLE_EXTENSIONS = {".csv", ".xlsx", ".xls"}
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_XLSX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_XLSX_ENTRIES = 2_000


def safe_upload_name(filename: str | None, fallback: str, allowed: set[str] | None = None) -> str:
    name = (filename or fallback).strip()
    windows = PureWindowsPath(name)
    if (
        not name
        or Path(name).name != name
        or windows.name != name
        or any(char in name for char in ("/", "\\", ":"))
        or any(ord(char) < 32 for char in name)
    ):
        raise HTTPException(422, "文件名只能使用 basename，不得包含路径")
    suffix = Path(name).suffix.lower()
    if suffix not in (allowed or ALLOWED_TABLE_EXTENSIONS):
        allowed_text = "、".join(sorted(allowed or ALLOWED_TABLE_EXTENSIONS))
        raise HTTPException(422, f"仅支持 {allowed_text} 文件")
    return name


async def read_upload_limited(
    upload: UploadFile,
    *,
    fallback_name: str,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    allowed: set[str] | None = None,
) -> tuple[str, bytes]:
    name = safe_upload_name(upload.filename, fallback_name, allowed)
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(min(1024 * 1024, max_bytes + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(413, f"文件超过 {max_bytes // (1024 * 1024)}MB 限制")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(422, "上传文件为空")
    if Path(name).suffix.lower() == ".xlsx":
        validate_xlsx_archive(data)
    return name, data


def validate_xlsx_archive(
    data: bytes,
    *,
    max_uncompressed_bytes: int = DEFAULT_MAX_XLSX_UNCOMPRESSED_BYTES,
    max_entries: int = DEFAULT_MAX_XLSX_ENTRIES,
) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise HTTPException(413, f"XLSX 内部文件数超过 {max_entries} 限制")
            total = 0
            for entry in entries:
                total += entry.file_size
                if entry.file_size > max_uncompressed_bytes:
                    raise HTTPException(413, "XLSX 单个解压条目过大")
                if entry.compress_size and entry.file_size / entry.compress_size > 500:
                    raise HTTPException(413, "XLSX 压缩比异常")
                if total > max_uncompressed_bytes:
                    raise HTTPException(413, f"XLSX 解压后超过 {max_uncompressed_bytes // (1024 * 1024)}MB 限制")
    except HTTPException:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise HTTPException(422, "XLSX 文件结构损坏") from exc

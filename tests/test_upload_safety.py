from __future__ import annotations

import asyncio
import io
import unittest
import zipfile

from fastapi import HTTPException, UploadFile

from backend.upload_safety import read_upload_limited, safe_upload_name, validate_xlsx_archive


class UploadSafetyTests(unittest.TestCase):
    def test_accepts_basename_and_normalizes_extension_check_case(self) -> None:
        self.assertEqual(safe_upload_name("数据.CSV", "fallback.csv"), "数据.CSV")

    def test_rejects_relative_absolute_windows_drive_and_unc_paths(self) -> None:
        invalid_names = [
            "../report.csv",
            "folder/report.csv",
            "/tmp/report.csv",
            r"folder\report.csv",
            r"C:\temp\report.csv",
            r"\\server\share\report.csv",
        ]
        for filename in invalid_names:
            with self.subTest(filename=filename), self.assertRaises(HTTPException) as caught:
                safe_upload_name(filename, "fallback.csv")
            self.assertEqual(caught.exception.status_code, 422)

    def test_rejects_disallowed_and_double_extensions(self) -> None:
        for filename in ["report.exe", "report.csv.exe", "report", "report.zip"]:
            with self.subTest(filename=filename), self.assertRaises(HTTPException) as caught:
                safe_upload_name(filename, "fallback.csv")
            self.assertEqual(caught.exception.status_code, 422)

    def test_limited_reader_rejects_oversized_and_empty_uploads(self) -> None:
        oversized = UploadFile(filename="report.csv", file=io.BytesIO(b"123456"))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(read_upload_limited(oversized, fallback_name="report.csv", max_bytes=5))
        self.assertEqual(caught.exception.status_code, 413)

        empty = UploadFile(filename="report.csv", file=io.BytesIO(b""))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(read_upload_limited(empty, fallback_name="report.csv", max_bytes=5))
        self.assertEqual(caught.exception.status_code, 422)

    def test_limited_reader_returns_data_at_exact_limit(self) -> None:
        upload = UploadFile(filename="report.csv", file=io.BytesIO(b"12345"))
        name, data = asyncio.run(read_upload_limited(upload, fallback_name="fallback.csv", max_bytes=5))
        self.assertEqual(name, "report.csv")
        self.assertEqual(data, b"12345")

    @staticmethod
    def _xlsx_archive(entries: list[tuple[str, bytes]]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_xlsx_archive_rejects_excess_entries_and_uncompressed_size(self) -> None:
        many_entries = self._xlsx_archive([("a.xml", b"1"), ("b.xml", b"2")])
        with self.assertRaises(HTTPException) as caught:
            validate_xlsx_archive(many_entries, max_entries=1)
        self.assertEqual(caught.exception.status_code, 413)

        too_large = self._xlsx_archive([("sheet.xml", b"123456")])
        with self.assertRaises(HTTPException) as caught:
            validate_xlsx_archive(too_large, max_uncompressed_bytes=5)
        self.assertEqual(caught.exception.status_code, 413)

    def test_xlsx_archive_rejects_corruption(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            validate_xlsx_archive(b"not a zip archive")
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

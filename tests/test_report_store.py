import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from dashboard.report_store import (
    delete_upload_record,
    get_latest_source_path,
    get_operational_sales_source_path,
    load_latest_source_record,
    load_operational_sales_source_record,
    load_reports_from_records,
    load_upload_records,
    normalize_uploaded_report_month,
    persist_latest_source,
    persist_operational_sales_source,
    persist_uploaded_reports,
    validate_report_month,
)


class FakeUpload:
    def __init__(self, name: str, data: str | bytes):
        self.name = name
        self._data = data if isinstance(data, bytes) else data.encode("utf-8-sig")

    def getvalue(self):
        return self._data


def report_csv(month: str, sales: int = 100) -> str:
    return (
        "销售专员,月份,国家,店铺,销售额--FBA销售额,COD,毛利润\n"
        f"A,{month},德国,6-ZXU 德国,{sales},0,20\n"
    )


class ReportStoreTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._temporary_directory.cleanup()

    def temporary_data_dir(self) -> Path:
        return Path(self._temporary_directory.name)

    def test_persist_and_reload_records(self):
        data_dir = self.temporary_data_dir()
        persist_uploaded_reports([FakeUpload("jan.csv", report_csv("2026-01"))], data_dir)

        records = load_upload_records(data_dir)
        reports = load_reports_from_records(records, data_dir)

        self.assertEqual(records["月份"].tolist(), ["2026-01"])
        self.assertEqual(reports.loc[0, "月份"], "2026-01")
        self.assertEqual(reports.loc[0, "店铺编码"], "ZXU")

    def test_duplicate_month_replaces_existing_record(self):
        data_dir = self.temporary_data_dir()
        persist_uploaded_reports([FakeUpload("old.csv", report_csv("2026-04", 100))], data_dir)
        result = persist_uploaded_reports([FakeUpload("new.csv", report_csv("2026-04", 200))], data_dir)

        records = load_upload_records(data_dir)
        reports = load_reports_from_records(records, data_dir)

        self.assertTrue(result[0].replaced)
        self.assertEqual(len(records), 1)
        self.assertEqual(records.loc[0, "原始文件名"], "new.csv")
        self.assertEqual(reports.loc[0, "销售额--FBA销售额"], 200)

    def test_delete_record_removes_report(self):
        data_dir = self.temporary_data_dir()
        persist_uploaded_reports([FakeUpload("jan.csv", report_csv("2026-01"))], data_dir)

        deleted = delete_upload_record("2026-01", data_dir)
        records = load_upload_records(data_dir)

        self.assertTrue(deleted)
        self.assertTrue(records.empty)
        self.assertFalse((data_dir / "reports" / "2026-01.csv").exists())

    def test_operational_sales_source_keeps_latest_upload_only(self):
        data_dir = self.temporary_data_dir()
        persist_operational_sales_source(FakeUpload("old.xlsx", b"old-data"), data_dir)
        latest_path = persist_operational_sales_source(FakeUpload("new.xls", b"new-data"), data_dir)

        records = load_operational_sales_source_record(data_dir)
        source_path = get_operational_sales_source_path(data_dir)

        self.assertEqual(len(records), 1)
        self.assertEqual(records.loc[0, "原始文件名"], "new.xls")
        self.assertEqual(records.loc[0, "保存文件名"], "operational_sales.xls")
        self.assertEqual(latest_path.name, "operational_sales.xls")
        self.assertEqual(source_path, latest_path)
        self.assertFalse((data_dir / "sources" / "operational_sales.xlsx").exists())
        self.assertEqual(latest_path.read_bytes(), b"new-data")

    def test_generic_latest_source_keeps_latest_upload_only(self):
        data_dir = self.temporary_data_dir()
        persist_latest_source(FakeUpload("gross_old.xlsx", b"old-data"), "gross_profit", "毛利原始表", data_dir)
        latest_path = persist_latest_source(FakeUpload("gross_new.xls", b"new-data"), "gross_profit", "毛利原始表", data_dir)

        records = load_latest_source_record("gross_profit", data_dir)
        source_path = get_latest_source_path("gross_profit", data_dir)

        self.assertEqual(len(records), 1)
        self.assertEqual(records.loc[0, "数据源"], "毛利原始表")
        self.assertEqual(records.loc[0, "原始文件名"], "gross_new.xls")
        self.assertEqual(records.loc[0, "保存文件名"], "gross_profit.xls")
        self.assertEqual(latest_path.name, "gross_profit.xls")
        self.assertEqual(source_path, latest_path)
        self.assertFalse((data_dir / "sources" / "gross_profit.xlsx").exists())
        self.assertEqual(latest_path.read_bytes(), b"new-data")

    def test_generic_latest_source_accepts_csv_suffix(self):
        data_dir = self.temporary_data_dir()
        latest_path = persist_latest_source(FakeUpload("gross.csv", b"csv-data"), "gross_profit", "毛利原始表", data_dir)
        records = load_latest_source_record("gross_profit", data_dir)

        self.assertEqual(latest_path.name, "gross_profit.csv")
        self.assertEqual(records.loc[0, "保存文件名"], "gross_profit.csv")
        self.assertEqual(get_latest_source_path("gross_profit", data_dir), latest_path)

    def test_report_month_requires_exact_legal_year_month(self):
        for value in ["2026-1", "2026-00", "2026-13", "2026-01-01", "../../evil", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report_month(value)
        self.assertEqual(validate_report_month("2026-12"), "2026-12")

    def test_exported_full_month_date_range_normalizes_to_strict_month(self):
        self.assertEqual(normalize_uploaded_report_month("2026-07-01~2026-07-31"), "2026-07")
        self.assertEqual(normalize_uploaded_report_month("2024-02-01 ～ 2024-02-29"), "2024-02")
        for value in ["2026-07-02~2026-07-31", "2026-07-01~2026-08-31", "2026-02-01~2026-02-30"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_uploaded_report_month(value)

        data_dir = self.temporary_data_dir()
        result = persist_uploaded_reports([FakeUpload("july.csv", report_csv("2026-07-01~2026-07-31"))], data_dir)
        self.assertEqual(result[0].month, "2026-07")
        self.assertTrue((data_dir / "reports" / "2026-07.csv").exists())

    def test_batch_validation_finishes_before_any_report_is_written(self):
        data_dir = self.temporary_data_dir()

        with self.assertRaisesRegex(ValueError, "合法的 YYYY-MM"):
            persist_uploaded_reports(
                [FakeUpload("valid.csv", report_csv("2026-01")), FakeUpload("invalid.csv", report_csv("2026-13"))],
                data_dir,
            )

        self.assertFalse((data_dir / "upload_records.csv").exists())
        self.assertEqual(list((data_dir / "reports").glob("*.csv")), [])

    def test_invalid_batch_keeps_existing_report_and_index_unchanged(self):
        data_dir = self.temporary_data_dir()
        persist_uploaded_reports([FakeUpload("old.csv", report_csv("2026-01", 100))], data_dir)
        old_index = (data_dir / "upload_records.csv").read_bytes()

        with self.assertRaises(ValueError):
            persist_uploaded_reports(
                [FakeUpload("replacement.csv", report_csv("2026-01", 999)), FakeUpload("invalid.csv", report_csv("bad"))],
                data_dir,
            )

        self.assertEqual((data_dir / "upload_records.csv").read_bytes(), old_index)
        reports = load_reports_from_records(load_upload_records(data_dir), data_dir)
        self.assertEqual(reports.loc[0, "销售额--FBA销售额"], 100)

    def test_report_replacement_rolls_back_when_index_commit_fails(self):
        data_dir = self.temporary_data_dir()
        persist_uploaded_reports([FakeUpload("old.csv", report_csv("2026-01", 100))], data_dir)

        with patch("dashboard.report_store.save_upload_records", side_effect=OSError("index failure")):
            with self.assertRaisesRegex(OSError, "index failure"):
                persist_uploaded_reports([FakeUpload("new.csv", report_csv("2026-01", 999))], data_dir)

        records = load_upload_records(data_dir)
        reports = load_reports_from_records(records, data_dir)
        self.assertEqual(records.loc[0, "原始文件名"], "old.csv")
        self.assertEqual(reports.loc[0, "销售额--FBA销售额"], 100)

    def test_report_index_rejects_non_whitelisted_paths(self):
        data_dir = self.temporary_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        index = data_dir / "upload_records.csv"
        header = "月份,原始文件名,保存文件名,上传时间,文件大小\n"
        for saved_name in ["../escape.csv", "C:\\escape.csv", "2026-02.csv"]:
            with self.subTest(saved_name=saved_name):
                index.write_text(header + f"2026-01,x.csv,{saved_name},now,1\n", encoding="utf-8-sig")
                with self.assertRaisesRegex(ValueError, "非法保存文件名"):
                    load_upload_records(data_dir)

    def test_source_index_rejects_non_whitelisted_paths(self):
        data_dir = self.temporary_data_dir()
        sources = data_dir / "sources"
        sources.mkdir(parents=True)
        (sources / "gross_profit_source.csv").write_text(
            "数据源,原始文件名,保存文件名,上传时间,文件大小\n毛利,x.csv,../escape.csv,now,1\n",
            encoding="utf-8-sig",
        )

        with self.assertRaisesRegex(ValueError, "非法保存文件名"):
            load_latest_source_record("gross_profit", data_dir)

        with self.assertRaisesRegex(ValueError, "未知数据源"):
            get_latest_source_path("../gross_profit", data_dir)

    def test_source_replacement_rolls_back_when_index_commit_fails(self):
        data_dir = self.temporary_data_dir()
        old_path = persist_latest_source(FakeUpload("old.csv", b"old-data"), "gross_profit", "毛利原始表", data_dir)

        with patch("dashboard.report_store._atomic_write_frame", side_effect=OSError("index failure")):
            with self.assertRaisesRegex(OSError, "index failure"):
                persist_latest_source(FakeUpload("new.csv", b"new-data"), "gross_profit", "毛利原始表", data_dir)

        self.assertEqual(old_path.read_bytes(), b"old-data")
        self.assertEqual(load_latest_source_record("gross_profit", data_dir).loc[0, "原始文件名"], "old.csv")

    def test_invalid_source_suffix_does_not_replace_existing_source(self):
        data_dir = self.temporary_data_dir()
        old_path = persist_latest_source(FakeUpload("old.csv", b"old-data"), "gross_profit", "毛利原始表", data_dir)

        with self.assertRaisesRegex(ValueError, "不支持"):
            persist_latest_source(FakeUpload("new.exe", b"new-data"), "gross_profit", "毛利原始表", data_dir)

        self.assertEqual(old_path.read_bytes(), b"old-data")


if __name__ == "__main__":
    unittest.main()

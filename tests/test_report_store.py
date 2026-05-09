import unittest
import uuid
from pathlib import Path

from dashboard.report_store import (
    delete_upload_record,
    get_operational_sales_source_path,
    load_operational_sales_source_record,
    load_reports_from_records,
    load_upload_records,
    persist_operational_sales_source,
    persist_uploaded_reports,
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
    def temporary_data_dir(self) -> Path:
        return Path.cwd() / "data" / "test_report_store" / uuid.uuid4().hex

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


if __name__ == "__main__":
    unittest.main()

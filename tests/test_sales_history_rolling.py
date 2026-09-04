from __future__ import annotations

import calendar
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from dashboard.data_processing import build_sales_history_monthly_summary
from dashboard.report_store import (
    load_sales_history_records,
    persist_uploaded_sales_history,
)


class FakeUpload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def monthly_csv(month: str, values: list[int], asin: str = " B001 ") -> bytes:
    year, month_number = (int(part) for part in month.split("-"))
    days = calendar.monthrange(year, month_number)[1]
    assert len(values) == days
    row = {
        "asin": asin,
        "msku": "M001",
        "国家": "德国",
        "小计": sum(values),
    }
    row.update({f"{month_number:02d}-{day:02d}销量": values[day - 1] for day in range(1, days + 1)})
    return pd.DataFrame([row]).to_csv(index=False).encode("utf-8-sig")


def monthly_csv_with_zero_asin_row(month: str) -> bytes:
    """Build an export that includes a zero-sales SKU row without an ASIN."""
    year, month_number = (int(part) for part in month.split("-"))
    days = calendar.monthrange(year, month_number)[1]
    frame = pd.read_csv(io.BytesIO(monthly_csv(month, [1] * days)), dtype=object)
    zero_row = frame.iloc[0].copy()
    zero_row["asin"] = ""
    zero_row["msku"] = "M-ZERO"
    zero_row["小计"] = "0"
    for day in range(1, days + 1):
        zero_row[f"{month_number:02d}-{day:02d}销量"] = "0"
    return pd.concat([frame, pd.DataFrame([zero_row])], ignore_index=True).to_csv(index=False).encode("utf-8-sig")


def upload_for(month: str, values: list[int] | None = None) -> FakeUpload:
    year, month_number = (int(part) for part in month.split("-"))
    days = calendar.monthrange(year, month_number)[1]
    return FakeUpload(
        f"销量统计_{month}-01 ~ {month}-{days:02d}.csv",
        monthly_csv(month, values or [1] * days),
    )


class SalesHistoryRollingTests(unittest.TestCase):
    def test_first_upload_requires_and_persists_twelve_contiguous_months(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            uploads = [upload_for(f"{year:04d}-{month:02d}") for year, month in [(2025, month) for month in range(8, 13)] + [(2026, month) for month in range(1, 8)]]
            results, evicted = persist_uploaded_sales_history(uploads, data_dir, today=date(2026, 8, 6))
            self.assertEqual(len(results), 12)
            self.assertEqual(evicted, [])
            self.assertEqual(load_sales_history_records(data_dir)["月份"].tolist(), [f"2025-{month:02d}" for month in range(8, 13)] + [f"2026-{month:02d}" for month in range(1, 8)])

    def test_new_month_rolls_out_oldest_month(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            initial = [upload_for(f"{year:04d}-{month:02d}") for year, month in [(2025, month) for month in range(8, 13)] + [(2026, month) for month in range(1, 8)]]
            persist_uploaded_sales_history(initial, data_dir, today=date(2026, 8, 6))
            results, evicted = persist_uploaded_sales_history([upload_for("2026-08")], data_dir, today=date(2026, 9, 2))
            self.assertEqual(results[0].month, "2026-08")
            self.assertEqual(evicted, ["2025-08"])
            self.assertNotIn("2025-08", load_sales_history_records(data_dir)["月份"].tolist())
            self.assertIn("2026-08", load_sales_history_records(data_dir)["月份"].tolist())

    def test_zero_sales_row_without_asin_does_not_block_month_replacement(self):
        months = [(2025, month) for month in range(8, 13)] + [(2026, month) for month in range(1, 8)]
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            persist_uploaded_sales_history(
                [upload_for(f"{year:04d}-{month:02d}") for year, month in months],
                data_dir,
                today=date(2026, 8, 6),
            )
            upload = FakeUpload(
                "销量统计_2026-08-01 ~ 2026-08-31.csv",
                monthly_csv_with_zero_asin_row("2026-08"),
            )
            results, evicted = persist_uploaded_sales_history([upload], data_dir, today=date(2026, 9, 1))
            self.assertEqual(results[0].month, "2026-08")
            self.assertFalse(results[0].replaced)
            self.assertEqual(evicted, ["2025-08"])
            records = load_sales_history_records(data_dir)
            self.assertNotIn("2025-08", records["月份"].tolist())
            self.assertIn("2026-08", records["月份"].tolist())

    def test_cross_month_zero_run_excludes_both_month_edges(self):
        months = [(2025, month) for month in range(8, 13)] + [(2026, month) for month in range(1, 8)]
        sources: list[tuple[str, Path]] = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for year, month in months:
                label = f"{year:04d}-{month:02d}"
                values = [1] * calendar.monthrange(year, month)[1]
                if label == "2025-08":
                    values[-5:] = [0] * 5
                if label == "2025-09":
                    values[:5] = [0] * 5
                path = root / f"{label}.csv"
                path.write_bytes(monthly_csv(label, values))
                sources.append((label, path))
            summary, _ = build_sales_history_monthly_summary(sources)
            row = summary.loc[summary["ASIN"].eq("B001")].iloc[0]
            self.assertEqual(row["历史1月计入天数"], 26)
            self.assertEqual(row["历史2月计入天数"], 25)


if __name__ == "__main__":
    unittest.main()

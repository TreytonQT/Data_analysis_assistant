from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backend.dashboard_api import _replenishment_listing_summary
from backend.listing_prices import (
    _cached_sales_response_source,
    _sales_response,
    cached_listing_bundle,
    clear_listing_cache,
    listing_history,
    latest_listing_wide,
    load_listing_index,
    load_snapshot,
    normalize_listing_workbook,
    observation_rows,
    observations,
    persist_listing_snapshot,
)


COLUMNS = ["MSKU", "ASIN", "国家", "币种", "售价(总价)", "运费", "积分", "价格", "优惠价"]


def workbook(rows: list[list[object]]) -> bytes:
    output = io.BytesIO()
    pd.DataFrame(rows, columns=COLUMNS).to_excel(output, index=False, sheet_name="sheet1")
    return output.getvalue()


def test_normalizes_listing_semantics_and_unavailable_price():
    data = workbook([
        [" sku-1 ", "asin-1", "德国", "EUR", 90, 0, 0, 100, 90],
        ["sku-2", "asin-2", "FR", "EUR", 0, 0, 0, 100, 0],
    ])
    _, frame, stats = normalize_listing_workbook(data, "2026-09-16")
    assert len(frame) == 2
    assert frame.loc[0, "MSKU"] == "SKU-1"
    assert frame.loc[0, "当前实际总价"] == 90
    assert pd.isna(frame.loc[1, "当前实际总价"])
    assert stats["unavailable_count"] == 1


def test_same_day_idempotency_and_event_gap(tmp_path: Path):
    persist_listing_snapshot("Listing20260910.xlsx", workbook([["sku-1", "asin-1", "DE", "EUR", 100, 0, 0, 100, 100]]), tmp_path)
    current_file = workbook([["sku-1", "asin-1", "DE", "EUR", 80, 0, 0, 100, 80]])
    first = persist_listing_snapshot("Listing20260912.xlsx", current_file, tmp_path)
    second = persist_listing_snapshot("Listing20260912.xlsx", current_file, tmp_path)
    assert first["replaced"] is False
    assert second["idempotent"] is True
    assert len(load_listing_index(tmp_path)) == 2
    assert len(load_snapshot("2026-09-12", tmp_path)) == 1
    events = observation_rows(data_dir=tmp_path)
    assert events[0]["gap_days"] == 2
    assert events[0]["observed_as"] == "首次观察到"


class ObservationPaginationTests(unittest.TestCase):
    def test_observation_page_defers_verification_and_sales_response_until_after_pagination(self):
        events = pd.DataFrame([
            {"date": f"2026-09-{day:02d}", "sku": f"SKU-{day}", "asin": f"ASIN-{day}", "country": "DE", "type": "实际总价涨跌", "old_effective_price": 10.0, "new_effective_price": 9.0}
            for day in (10, 11, 12)
        ])
        with (
            patch("backend.listing_prices._filtered_observation_event_frame", return_value=events),
            patch("backend.listing_prices._bulk_verification_status", return_value=["未登记变价"]) as verify,
            patch("backend.listing_prices._launch_prices", return_value=pd.DataFrame(columns=["MSKU", "DE", "FR", "ES", "IT"])),
            patch("backend.listing_prices._sales_response_source", return_value=(pd.DataFrame(), ())) as sales_source,
            patch("backend.listing_prices._sales_response", return_value={"status": "数据不足"}) as sales_response,
        ):
            result = observations(page=2, page_size=1)

        assert result["total"] == 3
        assert [row["sku"] for row in result["rows"]] == ["SKU-11"]
        assert result["rows"][0]["verification_status"] == "未登记变价"
        assert verify.call_count == 1
        assert len(verify.call_args.args[0]) == 1
        assert verify.call_args.args[0][0]["sku"] == "SKU-11"
        sales_source.assert_called_once_with()
        sales_response.assert_called_once()


    def test_sales_response_index_converts_daily_units_once_and_preserves_window_totals(self):
        days = pd.date_range("2026-09-03", "2026-09-13", freq="D")
        sales_row = {"MSKU": "SKU-1", "ASIN": "ASIN-1", "国家": "DE"}
        for day in days:
            sales_row[day.strftime("%m-%d") + "销量"] = "3" if day.day >= 11 else "2"
        frame = pd.DataFrame([sales_row])
        _cached_sales_response_source.cache_clear()
        try:
            with tempfile.TemporaryDirectory() as directory:
                latest = Path(directory) / "sales.csv"
                latest.write_text("fixture", encoding="utf-8")
                with (
                    patch("backend.dashboard_api.load_source_frame", return_value=frame),
                    patch("dashboard.report_store.get_sales_history_paths", return_value=[]),
                ):
                    source, specs = _cached_sales_response_source(((str(latest), latest.stat().st_size, latest.stat().st_mtime_ns),), str(latest))
            self.assertTrue(pd.api.types.is_numeric_dtype(source["09-03销量"]))
            result = _sales_response(
                {"sku": "SKU-1", "asin": "ASIN-1", "country": "DE", "date": "2026-09-10", "type": "实际总价涨跌", "old_effective_price": 10, "new_effective_price": 9},
                (source, specs),
            )
            self.assertEqual(result["baseline_units"], 14)
            self.assertEqual(result["post_units"], 9)
            self.assertEqual(result["daily_change"], 0.5)
        finally:
            _cached_sales_response_source.cache_clear()

    def test_observation_status_filter_counts_all_matches_before_pagination(self):
        events = pd.DataFrame([
            {"date": f"2026-09-{day:02d}", "sku": f"SKU-{day}", "asin": f"ASIN-{day}", "country": "DE", "type": "实际总价涨跌", "old_effective_price": 10.0, "new_effective_price": 9.0}
            for day in (10, 11, 12)
        ])
        with (
            patch("backend.listing_prices._filtered_observation_event_frame", return_value=events),
            patch("backend.listing_prices._bulk_verification_status", return_value=["其他", "命中", "命中"]) as verify,
            patch("backend.listing_prices._launch_prices", return_value=pd.DataFrame(columns=["MSKU", "DE", "FR", "ES", "IT"])),
            patch("backend.listing_prices._sales_response_source", return_value=(pd.DataFrame(), ())),
            patch("backend.listing_prices._sales_response", return_value={"status": "数据不足"}),
        ):
            result = observations(status="命中", page=2, page_size=1)

        assert result["total"] == 2
        assert [row["sku"] for row in result["rows"]] == ["SKU-12"]
        assert verify.call_count == 1
        assert len(verify.call_args.args[0]) == 3



def test_replacing_a_middle_snapshot_rebuilds_only_current_pair_results(tmp_path: Path):
    persist_listing_snapshot("Listing20260910.xlsx", workbook([["sku-1", "asin-1", "DE", "EUR", 100, 0, 0, 100, 100]]), tmp_path)
    persist_listing_snapshot("Listing20260911.xlsx", workbook([["sku-1", "asin-1", "DE", "EUR", 90, 0, 0, 90, 90]]), tmp_path)
    persist_listing_snapshot("Listing20260912.xlsx", workbook([["sku-1", "asin-1", "DE", "EUR", 80, 0, 0, 80, 80]]), tmp_path)

    _, _, initial_events = cached_listing_bundle(tmp_path)
    last_day_event = next(row for row in initial_events if row["date"] == "2026-09-12")
    assert last_day_event["old_effective_price"] == 90

    persist_listing_snapshot("Listing20260911.xlsx", workbook([["sku-1", "asin-1", "DE", "EUR", 95, 0, 0, 95, 95]]), tmp_path)
    _, _, replaced_events = cached_listing_bundle(tmp_path)
    replaced_last_day_event = next(row for row in replaced_events if row["date"] == "2026-09-12")
    assert replaced_last_day_event["old_effective_price"] == 95


def test_cached_events_are_json_safe_before_and_after_disk_reload(tmp_path: Path):
    persist_listing_snapshot("Listing20260910.xlsx", workbook([
        ["SKU-MISSING", "ASIN-1", "DE", "EUR", 0, 0, 0, 0, 0],
        ["SKU-EXISTING", "ASIN-2", "DE", "EUR", 10, 0, 0, 12, 10],
    ]), tmp_path)
    persist_listing_snapshot("Listing20260911.xlsx", workbook([
        ["SKU-MISSING", "ASIN-1", "DE", "EUR", 8, 0, 0, 10, 8],
        ["SKU-EXISTING", "ASIN-2", "DE", "EUR", 11, 0, 0, 12, 11],
    ]), tmp_path)

    with patch("dashboard.derived_table_cache.DATA_DIR", tmp_path):
        clear_listing_cache()
        first = cached_listing_bundle(tmp_path)[2]
        # This raises on the pre-fix NaN generated when only some rows lack
        # previous prices, reproducing the production HTTP 500 on a cache miss.
        json.dumps(first, allow_nan=False)
        missing = next(event for event in first if event["sku"] == "SKU-MISSING" and event["type"] == "恢复可售")
        assert missing["old_base_price"] is None
        assert missing["old_effective_price"] is None
        assert missing["new_effective_price"] == 8

        clear_listing_cache()
        reloaded = cached_listing_bundle(tmp_path)[2]
        json.dumps(reloaded, allow_nan=False)
        assert reloaded == first


def listing_source(*rows: tuple[str, str, float | None]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "MSKU": sku,
            "ASIN": asin,
            "DE_当前实际总价": current,
            "DE_开售价": 10,
            "DE_较开售价变化": None if current is None else current / 10 - 1,
        }
        for sku, asin, current in rows
    ])


def price_event(*, sku: str, old: float | None, new: float | None, date: str, previous: str, event_type: str = "实际总价涨跌", gap_days: int = 1, observed_as: str | None = None) -> dict[str, object]:
    return {
        "sku": sku,
        "asin": "ASIN-1",
        "country": "DE",
        "type": event_type,
        "old_effective_price": old,
        "new_effective_price": new,
        "date": date,
        "previous_date": previous,
        "gap_days": gap_days,
        "observed_as": observed_as or ("首次观察到" if gap_days > 1 else "连续观察"),
    }


def test_replenishment_summary_exposes_latest_actual_price_change_without_average():
    events = [
        price_event(sku="SKU-1", old=10, new=20, date="2026-09-17", previous="2026-09-16"),
        price_event(sku="SKU-1", old=20, new=22, date="2026-09-18", previous="2026-09-17"),
        price_event(sku="SKU-1", old=10, new=99, date="2026-09-18", previous="2026-09-17", event_type="Listing原价涨跌"),
    ]
    summary = _replenishment_listing_summary("ASIN-1", ["SKU-1"], listing_source(("SKU-1", "ASIN-1", 22)), events)
    latest = summary["countries"]["DE"]["latest_change"]
    assert latest["status"] == "变价"
    assert latest["old_price"] == 20
    assert latest["new_price"] == 22
    assert latest["amount_change"] == 2
    assert latest["date"] == "2026-09-18"

    mixed_events = [
        price_event(sku="SKU-1", old=10, new=20, date="2026-09-17", previous="2026-09-16"),
        price_event(sku="SKU-2", old=10, new=30, date="2026-09-17", previous="2026-09-16"),
    ]
    mixed = _replenishment_listing_summary(
        "ASIN-1",
        ["SKU-1", "SKU-2"],
        listing_source(("SKU-1", "ASIN-1", 20), ("SKU-2", "ASIN-1", 30)),
        mixed_events,
        {"SKU-1": 10, "SKU-2": 100},
    )
    mixed_latest = mixed["countries"]["DE"]["latest_change"]
    assert mixed_latest["status"] == "多SKU变价"
    assert mixed_latest["old_price"] is None
    assert mixed_latest["new_price"] is None
    assert len(mixed_latest["items"]) == 2
    assert mixed_latest["representative_sku"] == "SKU-2"
    assert mixed_latest["representative_sales"] == 100
    assert mixed_latest["representative_new_price"] == 30
    assert mixed_latest["representative_amount_change"] == 20
    assert mixed["countries"]["DE"]["current_price"] is None


def test_replenishment_summary_keeps_gap_and_no_change_semantics():
    gap = _replenishment_listing_summary(
        "ASIN-1",
        ["SKU-1"],
        listing_source(("SKU-1", "ASIN-1", 20)),
        [price_event(sku="SKU-1", old=10, new=20, date="2026-09-17", previous="2026-09-14", gap_days=3)],
    )
    assert gap["countries"]["DE"]["latest_change"]["observed_as"] == "首次观察到"
    assert gap["countries"]["DE"]["latest_change"]["gap_days"] == 3

    no_change = _replenishment_listing_summary(
        "ASIN-1", ["SKU-1"], listing_source(("SKU-1", "ASIN-1", 20)), [],
    )
    assert no_change["countries"]["DE"]["current_price"] == 20
    assert no_change["countries"]["DE"]["latest_change"] is None

    inconsistent_current = _replenishment_listing_summary(
        "ASIN-1",
        ["SKU-1", "SKU-2"],
        listing_source(("SKU-1", "ASIN-1", 20), ("SKU-2", "ASIN-1", 30)),
        [],
    )
    assert inconsistent_current["countries"]["DE"]["latest_change"]["status"] == "多SKU变价"
    assert inconsistent_current["countries"]["DE"]["current_price"] is None

def test_replenishment_summary_exposes_chronological_price_history(tmp_path: Path):
    persist_listing_snapshot("Listing20260916.xlsx", workbook([["SKU-1", "ASIN-1", "DE", "EUR", 10, 0, 0, 12, 10]]), tmp_path)
    persist_listing_snapshot("Listing20260917.xlsx", workbook([["SKU-1", "ASIN-1", "DE", "EUR", 20, 0, 0, 20, 0]]), tmp_path)
    source = latest_listing_wide(tmp_path)
    summary = _replenishment_listing_summary(
        "ASIN-1",
        ["SKU-1"],
        source,
        [],
        {"SKU-1": 100},
        listing_history(tmp_path),
    )
    points = summary["countries"]["DE"]["history"]
    assert [point["date"] for point in points] == ["2026-09-16", "2026-09-17"]
    assert points[-1]["current_price"] == 20
    assert points[-1]["amount_change"] == 10
    assert summary["countries"]["DE"]["representative_sku"] == "SKU-1"

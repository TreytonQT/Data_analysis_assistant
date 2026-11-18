from __future__ import annotations

import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.db as db
import backend.listing_prices as listing
import backend.variants as variants
from backend.variant_names import common_product_name, normalized_product_name, product_name_similarity, split_variant_name


def clear_variant_caches():
    for cache in (variants._cached_operational, variants._cached_base, variants._cached_display):
        cache.cache_clear()


def frame(*rows):
    return pd.DataFrame(rows, columns=["MSKU", "ASIN", "国家", "父ASIN", "变体属性"])


def workbook(rows, variant_columns=True):
    columns = [*listing.LISTING_REQUIRED, *listing.LISTING_VARIANT_COLUMNS] if variant_columns else listing.LISTING_REQUIRED
    buffer = io.BytesIO()
    pd.DataFrame(rows, columns=columns).to_excel(buffer, index=False)
    return buffer.getvalue()


class VariantGroupingTests(unittest.TestCase):
    def test_transitive_cross_country_groups_and_sku_granularity(self):
        groups = variants.build_variant_groups(frame(
            ("sku1", "X", "DE", "A", "[color:Schwarz]"),
            ("sku1", "X", "FR", "B", "[color:Noir]"),
            ("sku2", "Y", "FR", "B", "[size:2]"),
            ("sku2", "Y", "ES", "C", "[size:Dos]"),
            ("sku3", "Y", "ES", "C", "[size:Dos]"),
            ("skip", "SELF", "IT", "SELF", ""),
            ("skip", "NONE", "IT", "", ""),
        ))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["parent_asins"], ["A", "B", "C"])
        self.assertEqual(len(groups[0]["children"]), 3)
        self.assertEqual(groups[0]["children"][0]["sites"][1]["attributes"], "[color:Noir]")

    def test_metrics_not_multiplied_by_listing_sites_and_missing_images_are_strict(self):
        groups = variants.build_variant_groups(frame(
            ("S1", "A1", "DE", "P", ""), ("S1", "A1", "FR", "P", ""),
            ("S2", "A2", "DE", "P", ""), ("S3", "A3", "DE", "P", "")))
        operational = pd.DataFrame([
            {"MSKU": "S1", "ASIN": "A1", "日均销量": 3, "开发员": "甲"},
            {"MSKU": "S1", "ASIN": "A1", "日均销量": 2, "开发员": "乙"},
            {"MSKU": "S2", "ASIN": "A2", "日均销量": 0},
        ])
        result = variants.enrich_groups(groups, operational, {("S2", "A2"): {"url": "https://example.com/2.png"}})[0]
        self.assertEqual(result["children"][0]["daily_sales"], 5)
        self.assertEqual(result["children"][1]["daily_sales"], 0)
        self.assertIsNone(result["children"][2]["daily_sales"])
        self.assertEqual(result["representative_sku"], "S1")
        self.assertIsNone(result["image"])
        missing = variants.enrich_groups(groups, pd.DataFrame(), {("S1", "A1"): {"url": "https://example.com/1.png"}})[0]
        self.assertIsNone(missing["representative_sku"])
        self.assertIsNone(missing["image"])
        operational.loc[0, "日均销量"] = 0
        operational.loc[1, "日均销量"] = 0
        tied = variants.enrich_groups(groups, operational, {})[0]
        self.assertEqual(tied["representative_sku"], "S1")

    def test_assembled_names_follow_sales_with_deterministic_fallbacks(self):
        groups = variants.build_variant_groups(frame(("S1", "A1", "DE", "P", ""),
                                                     ("S2", "A2", "DE", "P", ""),
                                                     ("S3", "A3", "FR", "P", "")))
        rows = [
            {"MSKU": "S1", "ASIN": "A1", "日均销量": 3, "本地SKU名称": "最高销量原品名（红）(2.5)"},
            {"MSKU": "S1", "ASIN": "A1", "日均销量": 2, "本地SKU名称": "最高销量原品名（红）(2.5)"},
            {"MSKU": "S2", "ASIN": "A2", "日均销量": 4, "本地SKU名称": "次高销量原品名"},
            {"MSKU": "S3", "ASIN": "A3", "日均销量": None, "本地SKU名称": "缺销量品名"},
        ]
        def name():
            return variants.enrich_groups(groups, pd.DataFrame(rows), {})[0]["product_name"]
        self.assertEqual(name(), rows[0]["本地SKU名称"])
        rows[0]["本地SKU名称"] = rows[1]["本地SKU名称"] = ""
        self.assertEqual(name(), "次高销量原品名")
        rows[2]["本地SKU名称"] = ""
        self.assertEqual(name(), "缺销量品名")
        rows[0]["本地SKU名称"] = rows[1]["本地SKU名称"] = "编号较小原品名"
        rows[2]["本地SKU名称"] = "编号较大原品名"
        rows[0]["日均销量"] = rows[1]["日均销量"] = 0
        rows[2]["日均销量"] = 0
        self.assertEqual(name(), "编号较小原品名")
        for row in rows:
            row["日均销量"] = None
        self.assertEqual(name(), "编号较小原品名")
        rows.reverse()
        self.assertEqual(name(), "编号较小原品名")
        for row in rows:
            row["本地SKU名称"] = ""
        self.assertEqual(name(), "")

    def test_virtual_two_packs_do_not_connect_or_inflate_groups(self):
        source = frame(("A1", "AX", "DE", "P1", ""), ("A2", "AY", "DE", "P1", ""),
                       ("B1", "BX", "DE", "P2", ""), ("B2", "BY", "DE", "P2", ""),
                       ("VMP_ORIGINAL_2_PK", "LINK", "DE", "P1", ""),
                       ("vmp_original_2_pk", "LINK", "FR", "P2", ""),
                       ("VMP_ORIGINAL_3_PK", "THREE", "FR", "P1", ""))
        groups = variants.build_variant_groups(source)
        self.assertEqual(len(groups), 2)
        self.assertEqual({tuple(group["parent_asins"]) for group in groups}, {("P1",), ("P2",)})
        self.assertTrue(any(child["sku"] == "VMP_ORIGINAL_3_PK" for group in groups for child in group["children"]))
        self.assertFalse(variants.is_virtual_two_pack("NORMAL_2_PK"))

    def test_operational_store_wins_and_prefix_is_only_a_fallback(self):
        source = frame(("ZXU261101CQT001", "A1", "DE", "P", ""),
                       ("ZXU261101CQT002", "A2", "FR", "P", ""))
        assembled = variants.build_variant_groups(source)
        operational = pd.DataFrame([
            {"MSKU": sku, "ASIN": asin, "店铺名称": "运营一部-YAP-德国,运营一部-YAP-法国"}
            for sku, asin in [("ZXU261101CQT001", "A1"), ("ZXU261101CQT002", "A2")]])
        groups = variants.build_store_groups(assembled, pd.DataFrame(), operational, {})
        self.assertEqual([(group["store_code"], group["store_inferred"]) for group in groups], [("YAP", False)])
        groups = variants.build_store_groups(assembled, pd.DataFrame(), pd.DataFrame(), {})
        self.assertEqual([(group["store_code"], group["store_inferred"]) for group in groups], [("ZXU", True)])
        unknown = variants.build_variant_groups(frame(("SKU-A", "A1", "DE", "P", ""), ("SKU-B", "A2", "DE", "P", "")))
        self.assertEqual(variants.build_store_groups(unknown, pd.DataFrame(), pd.DataFrame(), {})[0]["store_code"], variants.UNKNOWN_STORE)

    def test_parent_relationships_are_evaluated_within_each_store(self):
        assembled = variants.build_variant_groups(frame(("ZXU001", "X", "DE", "P", ""), ("ZXU002", "Y", "FR", "P", "")))
        standalone = frame(("YAP001", "X", "DE", "", ""), ("YAP002", "Y", "FR", "", ""))
        operational = pd.DataFrame([{"MSKU": sku, "ASIN": asin, "本地SKU名称": "完整手机挂绳长款"}
                                    for sku, asin in [("YAP001", "X"), ("YAP002", "Y")]])
        groups = variants.build_store_groups(assembled, standalone, operational, variants._operational_metrics(operational))
        self.assertEqual({(group["store_code"], group["relation_kind"]) for group in groups},
                         {("ZXU", "assembled"), ("YAP", "unassembled")})

    def test_attachment_baseline_when_available(self):
        path = Path("D:/Listing20261106-2118630112866983938.xlsx")
        if not path.is_file():
            self.skipTest("User attachment is local only")
        _, normalized, _ = listing.normalize_listing_workbook(path.read_bytes(), "2026-11-06")
        groups = variants.build_variant_groups(normalized)
        self.assertLessEqual(sum(len(group["children"]) for group in groups), 991)
        self.assertTrue(all(not variants.is_virtual_two_pack(child["sku"]) for group in groups for child in group["children"]))


class VariantApiTests(unittest.TestCase):
    def setUp(self):
        clear_variant_caches()
        temp_root = Path(__file__).resolve().parents[1] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.current = frame(("S1", "A1", "DE", "P1", "颜色"), ("S1B", "A1B", "DE", "P1", "颜色"),
                             ("S2", "A2", "FR", "P2", "尺寸"), ("S2B", "A2B", "FR", "P2", "尺寸"))
        self.source = "v1"
        self.db_patch = patch.object(db, "DB_PATH", self.root / "app.db")
        self.db_patch.start()
        db.initialize_database()
        self.source_patch = patch.object(variants, "_source_groups", side_effect=lambda _: ("2026-11-06", True, variants.build_variant_groups(self.current)))
        self.source_patch.start()
        self.revision_patch = patch.object(variants, "listing_source_revision", side_effect=lambda: self.source + ":" + variants._digest(self.current.to_json()))
        self.revision_patch.start()
        self.standalone_patch = patch.object(variants, "_standalone_rows", return_value=pd.DataFrame())
        self.standalone_patch.start()
        self.path_patch = patch("dashboard.report_store.get_latest_source_path", return_value=None)
        self.path_patch.start()
        self.image_patch = patch("backend.dashboard_api._optional_sku_image_map", return_value=pd.DataFrame())
        self.image_mock = self.image_patch.start()
        self.op_revision_patch = patch.object(variants, "_operational_revision",
                                              side_effect=lambda: variants._digest(variants._operational_source().to_json()))
        self.op_revision_patch.start()
        self.image_revision_patch = patch.object(variants, "_image_revision",
                                                 side_effect=lambda: variants._digest(self.image_mock.return_value.to_json()))
        self.image_revision_patch.start()
        app = FastAPI()
        app.include_router(variants.router)
        self.client = TestClient(app)

    def tearDown(self):
        for mock in (self.image_revision_patch, self.op_revision_patch, self.image_patch, self.path_patch, self.standalone_patch, self.revision_patch, self.source_patch, self.db_patch):
            mock.stop()
        self.temp.cleanup()
        clear_variant_caches()

    def view(self, **params):
        response = self.client.get("/api/variants", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, index, sku, view=None):
        view = view or self.view()
        return self.client.put(f"/api/variants/{view['rows'][index]['key']}/parent-sku", json={"parent_sku": sku, "revision": view["revision"]})

    def store_fixture(self):
        self.current = frame(("ZXU001", "AX", "DE", "P_SHARED", ""),
                             ("ZXU002", "AY", "FR", "P_SHARED", ""),
                             ("YAP001", "AX", "DE", "P_SHARED", ""),
                             ("YAP002", "AY", "FR", "P_SHARED", ""))
        return pd.DataFrame([{"MSKU": row["MSKU"], "ASIN": row["ASIN"], "本地SKU名称": "手机挂绳长款",
                              "开发员": "甲" if row["MSKU"].startswith("ZXU") else "乙",
                              "店铺名称": "运营一部-" + row["MSKU"][:3] + "-德国", "日均销量": 1}
                             for row in self.current.to_dict("records")])

    def add_legacy_assignment(self):
        with db.connect() as conn:
            conn.execute("""INSERT INTO variant_parent_skus
                (group_key, parent_sku, parent_asins, child_asins, candidate_skus, needs_confirmation, updated_at)
                VALUES ('legacy-record', 'LEGACY', '["P_SHARED"]', '["AX","AY"]', '[]', 0, '2026-11-01')""")

    def test_store_filters_preserve_rows_counts_and_do_not_change_other_store(self):
        operational = self.store_fixture()
        with patch.object(variants, "_operational_source", return_value=operational):
            all_rows = self.view()
            self.assertEqual(all_rows["stores"], ["YAP", "ZXU"])
            self.assertEqual(all_rows["total"], 2)
            self.assertEqual(len({group["key"] for group in all_rows["rows"]}), 2)
            zx = self.view(stores="ZXU", page_size=1)
            self.assertEqual(zx["total"], 1)
            self.assertEqual({child["sku"] for child in zx["rows"][0]["children"]}, {"ZXU001", "ZXU002"})
            self.assertEqual(self.view(stores="YAP,ZXU", page_size=1)["total"], 2)
            self.assertEqual(self.view(stores="ZXU", developers="乙")["total"], 0)
            self.assertEqual(self.view(stores="YAP", search="AX")["total"], 1)
            self.assertEqual(self.save(0, "ZXU-PARENT", zx).status_code, 200)
            yap = self.view(stores="YAP")
            self.assertEqual(yap["rows"][0]["status"], "empty")
            self.assertEqual(yap["rows"][0]["other_parent_skus"],
                             [{"store_code": "ZXU", "parent_sku": "ZXU-PARENT", "matched_child_asins": ["AX", "AY"]}])
            self.assertEqual(self.save(0, "ZXU-PARENT", yap).status_code, 200)
            self.assertTrue(all(group["status"] == "filled" for group in self.view()["rows"]))
            self.assertEqual(self.save(0, "YAP-CUSTOM", self.view(stores="YAP")).status_code, 200)
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["parent_sku"], "ZXU-PARENT")
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["other_parent_skus"][0]["parent_sku"], "YAP-CUSTOM")

    def test_partial_and_dormant_other_store_references_remain_advisory(self):
        operational = self.store_fixture()
        self.current.loc[self.current["MSKU"].eq("YAP002"), "ASIN"] = "AZ"
        with patch.object(variants, "_operational_source", return_value=operational):
            self.assertEqual(self.save(0, "ZXU-SAVED", self.view(stores="ZXU")).status_code, 200)
            yap = self.view(stores="YAP")["rows"][0]
            self.assertEqual(yap["status"], "empty")
            self.assertEqual(yap["other_parent_skus"][0]["matched_child_asins"], ["AX"])
            self.current = self.current[self.current["MSKU"].str.startswith("YAP")]
            self.assertEqual(self.view(stores="YAP")["rows"][0]["other_parent_skus"][0]["parent_sku"], "ZXU-SAVED")
            self.assertEqual(self.save(0, "YAP-OWN", self.view(stores="YAP")).status_code, 200)
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT parent_sku FROM variant_parent_skus WHERE store_code='ZXU'").fetchone()[0], "ZXU-SAVED")

    def test_unconfirmed_legacy_candidates_are_not_confirmed_other_store_references(self):
        operational = self.store_fixture()
        self.add_legacy_assignment()
        with patch.object(variants, "_operational_source", return_value=operational):
            rows = self.view()["rows"]
            self.assertTrue(all(group["status"] == "pending" for group in rows))
            self.assertTrue(all(group["other_parent_skus"] == [] for group in rows))

    def test_legacy_assignments_require_confirmation_across_stores_and_clear_stays_clear(self):
        operational = self.store_fixture()
        self.add_legacy_assignment()
        with patch.object(variants, "_operational_source", return_value=operational):
            zx = self.view(stores="ZXU")
            self.assertEqual(zx["rows"][0]["status"], "pending")
            self.assertTrue(zx["rows"][0]["legacy_assignment"])
            self.assertEqual(zx["rows"][0]["candidate_skus"], ["LEGACY"])
            self.assertEqual(self.save(0, "ZXU-CONFIRMED", zx).status_code, 200)
            yap = self.view(stores="YAP")
            self.assertEqual(yap["rows"][0]["status"], "pending")
            self.assertEqual(self.save(0, "YAP-CONFIRMED", yap).status_code, 200)
            self.assertEqual(self.save(0, "", self.view(stores="YAP")).status_code, 200)
            self.assertEqual(self.view(stores="YAP")["rows"][0]["status"], "empty")
            self.assertEqual(self.view(stores="YAP")["rows"][0]["candidate_skus"], [])
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["parent_sku"], "ZXU-CONFIRMED")
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["other_parent_skus"], [])
            with db.connect() as conn:
                legacy = dict(conn.execute("SELECT * FROM variant_parent_skus WHERE group_key = 'legacy-record'").fetchone())
            self.assertIsNone(legacy["store_code"])
            self.assertEqual(legacy["parent_sku"], "LEGACY")

    def test_unique_legacy_store_inherits_without_get_writes(self):
        operational = self.store_fixture()
        self.current = self.current[self.current["MSKU"].str.startswith("ZXU")]
        self.add_legacy_assignment()
        with db.connect() as conn:
            before = [dict(row) for row in conn.execute("SELECT * FROM variant_parent_skus")]
        with patch.object(variants, "_operational_source", return_value=operational):
            result = self.view(stores="ZXU")
            self.assertEqual(result["rows"][0]["parent_sku"], "LEGACY")
            self.assertEqual(result["rows"][0]["status"], "filled")
        with db.connect() as conn:
            self.assertEqual(before, [dict(row) for row in conn.execute("SELECT * FROM variant_parent_skus")])

    def test_same_store_uniqueness_still_applies(self):
        operational = self.store_fixture()
        self.current = pd.concat([self.current, frame(("ZXU003", "A3", "DE", "P_OTHER", ""),
                                                     ("ZXU004", "A4", "FR", "P_OTHER", ""))], ignore_index=True)
        with patch.object(variants, "_operational_source", return_value=operational):
            self.assertEqual(self.save(0, "PARENT", self.view(stores="ZXU", search="P_SHARED")).status_code, 200)
            self.assertEqual(self.save(0, "parent", self.view(stores="ZXU", search="P_OTHER")).status_code, 409)
            self.assertEqual(self.save(0, "PARENT", self.view(stores="YAP")).status_code, 200)

    def test_virtual_pack_only_second_child_hides_the_family_without_losing_saved_record(self):
        self.current = frame(("ZXU001", "REAL", "DE", "PACK_PARENT", ""),
                             ("VMP_ZXU001_2_PK", "VIRTUAL", "DE", "PACK_PARENT", ""))
        with db.connect() as conn:
            conn.execute("""INSERT INTO variant_parent_skus
                (group_key, parent_sku, parent_asins, child_asins, candidate_skus, needs_confirmation, updated_at)
                VALUES ('pack-history', 'KEEP', '["PACK_PARENT"]', '["REAL","VIRTUAL"]', '[]', 0, '2026-11-01')""")
        self.assertEqual(self.view()["total"], 0)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT parent_sku FROM variant_parent_skus WHERE group_key='pack-history'").fetchone()[0], "KEEP")

    def test_cached_sources_are_reused_across_filters_and_parent_saves(self):
        operational = self.store_fixture()
        with (patch.object(variants, "_operational_source", return_value=operational),
              patch.object(variants, "_operational_metrics", wraps=variants._operational_metrics) as metrics,
              patch.object(variants, "build_store_groups", wraps=variants.build_store_groups) as groups):
            view = self.view(stores="ZXU")
            cached = variants._base_state()
            original_groups = json.dumps(cached.groups, sort_keys=True)
            self.view(status="filled")
            self.view(stores="YAP")
            self.assertEqual(self.save(0, "CACHED-PARENT", view).status_code, 200)
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["parent_sku"], "CACHED-PARENT")
            self.assertEqual(self.view(stores="YAP")["rows"][0]["other_parent_skus"][0]["parent_sku"], "CACHED-PARENT")
            self.assertIs(variants._base_state(), cached)
            self.assertEqual(json.dumps(cached.groups, sort_keys=True), original_groups)
            self.assertEqual(metrics.call_count, 1)
            self.assertEqual(groups.call_count, 1)
            self.assertEqual(self.image_mock.call_count, 1)

    def test_source_changes_invalidate_the_correct_cache_and_stale_edits(self):
        operational = self.store_fixture()
        with (patch.object(variants, "_operational_source", side_effect=lambda: operational.copy()),
              patch.object(variants, "_operational_metrics", wraps=variants._operational_metrics) as metrics,
              patch.object(variants, "build_store_groups", wraps=variants.build_store_groups) as groups):
            old = self.view(stores="ZXU")
            self.source = "new-listing"
            self.assertEqual(self.save(0, "STALE", old).status_code, 409)
            self.view()
            self.assertEqual((metrics.call_count, groups.call_count), (1, 2))
            operational.loc[operational["MSKU"].eq("ZXU001"), "本地SKU名称"] = "替换后的最新品名"
            operational.loc[operational["MSKU"].eq("ZXU001"), "日均销量"] = 99
            self.assertEqual(self.view(stores="ZXU")["rows"][0]["product_name"], "替换后的最新品名")
            self.assertEqual((metrics.call_count, groups.call_count), (2, 3))

    def test_image_changes_refresh_display_without_rebuilding_relations(self):
        self.image_mock.return_value = pd.DataFrame([{"MSKU": "S1", "ASIN": "A1", "图片链接": "https://images.example.com/one.png"}])
        with patch.object(variants, "build_store_groups", wraps=variants.build_store_groups) as groups:
            first = self.view()
            self.assertEqual(first["rows"][0]["children"][0]["image"]["url"], "https://images.example.com/one.png")
            self.image_mock.return_value.loc[0, "图片链接"] = "https://images.example.com/two.png"
            second = self.view()
            self.assertEqual(second["rows"][0]["children"][0]["image"]["url"], "https://images.example.com/two.png")
            self.assertEqual(first["revision"], second["revision"])
            self.assertEqual(groups.call_count, 1)
            self.assertEqual(self.image_mock.call_count, 2)

    def test_source_changes_during_a_cold_build_reject_the_response(self):
        original = variants._source_groups
        def changing_source(revision):
            result = original(revision)
            self.source = "changed-during-read"
            return result
        with patch.object(variants, "_source_groups", side_effect=changing_source):
            response = self.client.get("/api/variants")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.view()["total"], 2)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM variant_parent_skus").fetchone()[0], 0)

    def test_concurrent_cold_reads_share_one_source_build(self):
        original = variants.build_store_groups
        def slow_build(*args):
            time.sleep(0.05)
            return original(*args)
        with patch.object(variants, "build_store_groups", side_effect=slow_build) as groups:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: variants._base_state(), range(2)))
        self.assertIs(results[0], results[1])
        self.assertEqual(groups.call_count, 1)

    def test_source_change_before_commit_rolls_back_parent_sku_write(self):
        view = self.view()
        with db.connect() as conn:
            original = variants._saved_records(conn)
        now = variants.datetime.now
        def change_source(*args):
            self.source = "changed-before-commit"
            return now(*args)
        with patch.object(variants, "datetime") as clock:
            clock.now.side_effect = change_source
            response = self.save(0, "ROLLBACK", view)
        self.assertEqual(response.status_code, 409)
        with db.connect() as conn:
            self.assertEqual(variants._saved_records(conn), original)

    def test_save_edit_clear_unique_and_restart_persistence(self):
        self.assertEqual(self.save(0, " Parent-A ").status_code, 200)
        self.assertEqual(self.view()["rows"][0]["parent_sku"], "Parent-A")
        self.assertEqual(self.save(1, "parent-a").status_code, 409)
        self.assertEqual(self.save(0, "Parent-B").status_code, 200)
        db.initialize_database()
        self.assertEqual(self.view()["rows"][0]["parent_sku"], "Parent-B")
        self.assertEqual(self.save(0, "  ").status_code, 200)
        self.assertEqual(self.view()["rows"][0]["status"], "empty")

    def test_stale_relation_and_assignment_revisions_reject_writes(self):
        view = self.view()
        self.source = "v2"
        self.assertEqual(self.save(0, "STALE", view).status_code, 409)
        view = self.view()
        self.assertEqual(self.save(0, "FRESH", view).status_code, 200)
        self.assertEqual(self.save(1, "STALE", view).status_code, 409)

    def test_algorithm_version_invalidates_edits_from_old_rules(self):
        digest = variants._digest
        def old_digest(value):
            if isinstance(value, list) and value and value[0] == "variants-v4":
                value = ["variants-v3", *value[1:]]
            return digest(value)
        with patch.object(variants, "_digest", side_effect=old_digest):
            previous = self.view()
        self.assertEqual(self.save(0, "STALE", previous).status_code, 409)

    def test_conflicting_merge_remembers_choice_and_later_split_keeps_candidates(self):
        self.save(0, "ONE")
        self.save(1, "TWO")
        self.current = frame(("S1", "A1", "DE", "P1", ""), ("S1B", "A1B", "DE", "P1", ""),
                             ("S2", "A2", "FR", "P2", ""), ("S2B", "A2B", "FR", "P2", ""), ("S1", "A1", "FR", "P2", ""))
        merged = self.view()
        self.assertEqual(merged["total"], 1)
        self.assertEqual(set(merged["rows"][0]["candidate_skus"]), {"ONE", "TWO"})
        self.assertEqual(merged["rows"][0]["status"], "pending")
        self.assertEqual(self.save(0, "ONE", merged).status_code, 200)
        self.assertEqual(self.view()["rows"][0]["status"], "filled")
        self.current = self.current.iloc[:4]
        split = self.view()
        self.assertEqual([group["status"] for group in split["rows"]], ["pending", "pending"])
        self.assertEqual(self.save(0, "ONE", split).status_code, 200)
        after = self.view()
        self.assertEqual(after["rows"][1]["candidate_skus"], ["ONE"])
        self.assertEqual(self.save(1, "ONE", after).status_code, 409)
        self.assertEqual(self.save(1, "", after).status_code, 200)
        self.assertEqual([group["status"] for group in self.view()["rows"]], ["filled", "empty"])

    def test_parent_replacement_inherits_via_child_and_absent_groups_are_retained(self):
        self.save(0, "PARENT")
        self.current = frame(("S1", "A1", "DE", "NEW-PARENT", ""), ("S1B", "A1B", "DE", "NEW-PARENT", ""),
                             ("S3", "A3", "FR", "P3", ""), ("S3B", "A3B", "FR", "P3", ""))
        self.assertEqual(self.view()["rows"][0]["parent_sku"], "PARENT")
        self.current = frame(("S3", "A3", "FR", "P3", ""), ("S3B", "A3B", "FR", "P3", ""))
        self.save(0, "OTHER")
        self.current = frame(("S1", "A1", "DE", "P1", ""), ("S1B", "A1B", "DE", "P1", ""))
        self.assertEqual(self.view()["rows"][0]["parent_sku"], "PARENT")

    def test_search_keeps_whole_family_and_pagination_and_status(self):
        self.current = frame(("S1", "A1", "DE", "P1", ""), ("S2", "A2", "DE", "P1", ""),
                             ("S3", "A3", "FR", "P3", ""), ("S4", "A4", "FR", "P3", ""))
        found = self.view(search="a1")
        self.assertEqual(found["total"], 1)
        self.assertEqual(len(found["rows"][0]["children"]), 2)
        self.save(0, "PARENT", found)
        self.assertEqual(self.view(status="filled")["total"], 1)
        self.assertEqual(self.view(status="empty")["total"], 1)
        self.assertEqual(self.view(page=2, page_size=1)["rows"][0]["parents"][0]["asin"], "P3")
        self.assertEqual(self.client.get("/api/variants", params={"status": "invalid"}).status_code, 422)

    def test_empty_filter_only_keeps_assembled_groups_before_pagination(self):
        standalone = frame(("O1", "OA1", "DE", "", ""), ("O2", "OA2", "FR", "", ""))
        operational = pd.DataFrame([
            {"MSKU": "S1", "ASIN": "A1", "本地SKU名称": "已合成产品", "开发员": "甲"},
            {"MSKU": "O1", "ASIN": "OA1", "本地SKU名称": "手机挂绳-红色-长款", "开发员": "乙"},
            {"MSKU": "O2", "ASIN": "OA2", "本地SKU名称": "手机挂绳-蓝色-长款", "开发员": "乙"},
        ])
        with (patch.object(variants, "_standalone_rows", return_value=standalone),
              patch.object(variants, "_operational_source", return_value=operational)):
            self.assertEqual(self.view()["total"], 3)
            first = self.view(status="empty", page_size=1)
            second = self.view(status="empty", page=2, page_size=1)
            self.assertEqual((first["total"], second["total"]), (2, 2))
            self.assertNotEqual(first["rows"][0]["key"], second["rows"][0]["key"])
            self.assertTrue(all(group["relation_kind"] == "assembled" and group["parent_asins"]
                                and group["status"] == "empty" and not group["parent_sku"]
                                for group in [*first["rows"], *second["rows"]]))
            pending = self.view(status="unassembled")
            self.assertEqual(pending["total"], 1)
            self.assertEqual(pending["rows"][0]["status"], "empty")
            self.assertEqual(self.view(status="empty", search="O1")["total"], 0)
            self.assertEqual(self.view(status="empty", stores="O")["total"], 0)
            self.assertEqual(self.view(status="empty", developers="乙")["total"], 0)
            self.assertEqual(self.view(status="empty", developers="甲")["total"], 1)
            self.assertEqual(self.save(0, "FILLED-PARENT", self.view(status="empty", search="P1")).status_code, 200)
            self.assertEqual(self.view(status="empty")["total"], 1)
            self.assertEqual(self.view(status="unassembled")["total"], 1)

    def test_unassembled_filter_is_independent_of_parent_sku_status_before_pagination(self):
        operational = pd.DataFrame([
            {"MSKU": f"{prefix}{number}", "ASIN": f"{prefix}A{number}", "本地SKU名称": f"候选组{prefix}",
             "开发员": "甲" if prefix != "V" or number == 1 else "乙"}
            for prefix in ("U", "V", "W") for number in (1, 2)
        ])
        standalone = frame(*[(row["MSKU"], row["ASIN"], "DE", "", "") for row in operational.to_dict("records")])
        inferred = variants.build_unassembled_groups(standalone, variants._operational_metrics(operational))
        for group, status in zip(inferred, ("filled", "empty", "pending")):
            group.update(status=status, parent_sku="FILLED" if status == "filled" else "",
                         candidate_skus=["OLD"] if status == "pending" else [])
        assembled = variants.build_variant_groups(self.current)
        for group in assembled:
            group.update(status="pending", parent_sku="", candidate_skus=["ASSEMBLED-OLD"])
        groups = [*assembled, *inferred]
        with (patch.object(variants, "_relation_state", return_value=("2026-11-18", True, groups, [], "test-revision")),
              patch.object(variants, "_display_groups", side_effect=lambda _: {
                  group["key"]: group for group in variants.enrich_groups(groups, operational, {})}),
              patch.object(variants, "_operational_source", return_value=operational)):
            found = self.view(status="unassembled")
            self.assertEqual(found["total"], 3)
            self.assertEqual({group["status"] for group in found["rows"]}, {"filled", "empty", "pending"})
            self.assertTrue(all(group["relation_kind"] == "unassembled" for group in found["rows"]))
            self.assertEqual(self.view(status="all")["total"], 5)
            self.assertEqual(self.view(status="pending")["total"], 3)
            self.assertEqual(self.view(status="empty")["total"], 0)
            first = self.view(status="unassembled", developers="甲", page_size=1)
            second = self.view(status="unassembled", developers="甲", page=2, page_size=1)
            self.assertEqual((first["total"], second["total"]), (3, 3))
            self.assertNotEqual(first["rows"][0]["key"], second["rows"][0]["key"])
            selected = self.view(status="unassembled", developers="甲", search="VA2")
            self.assertEqual(selected["total"], 1)
            self.assertEqual(len(selected["rows"][0]["children"]), 2)
            self.assertEqual({child["developer"] for child in selected["rows"][0]["children"]}, {"甲", "乙"})
            self.assertEqual(self.view(status="unassembled", developers="乙")["total"], 1)
            self.assertEqual(self.view(status="unassembled", developers="乙", search="WA2")["total"], 0)
            self.assertEqual(self.view(status="unassembled", search="NO-MATCH")["total"], 0)

    def test_member_addition_and_single_filled_merge_inherit(self):
        self.save(0, "KEEP")
        self.current = frame(("S1", "A1", "DE", "P1", ""), ("S1B", "A1B", "DE", "P1", ""),
                             ("S2", "A2", "FR", "P2", ""), ("S2B", "A2B", "FR", "P2", ""),
                             ("S1", "A1", "FR", "P2", ""), ("S3", "A3", "FR", "P2", ""))
        group = self.view()["rows"][0]
        self.assertEqual(group["parent_sku"], "KEEP")
        self.assertEqual(group["status"], "filled")
        self.assertEqual(len(group["children"]), 5)

    def test_returning_dormant_sku_collision_requires_confirmation(self):
        self.save(0, "REUSED")
        original = self.current.copy()
        self.current = self.current.iloc[2:]
        self.save(0, "reused")
        self.current = original
        groups = self.view()["rows"]
        self.assertEqual([group["status"] for group in groups], ["pending", "pending"])
        self.assertTrue(all(not group["parent_sku"] for group in groups))

    def test_missing_columns_warning_and_no_get_database_writes(self):
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM variant_parent_skus").fetchone()[0], 0)
        with patch.object(variants, "_source_groups", return_value=("2026-11-06", False, [])):
            missing = self.view()
            self.assertIn("缺少父ASIN或变体属性", missing["warning"])
        self.view()
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM variant_parent_skus").fetchone()[0], 0)

    def test_image_map_can_match_children_missing_from_operational_source(self):
        self.image_mock.return_value = pd.DataFrame([{
            "MSKU": "S1", "ASIN": "A1", "图片链接": "https://images.example.com/1.png"}])
        group = self.view()["rows"][0]
        self.assertEqual(group["children"][0]["image"]["url"], "https://images.example.com/1.png")
        self.assertIsNone(group["children"][0]["daily_sales"])
        self.assertIsNone(group["image"])

    def test_single_asin_is_excluded_even_with_multiple_skus(self):
        self.current = frame(("S1", "A1", "DE", "P1", ""), ("S1B", "A1", "FR", "P2", ""))
        self.assertEqual(self.view()["total"], 0)

    def test_hidden_single_asin_keeps_its_saved_parent_sku_for_reappearance(self):
        self.save(0, "HIDDEN-PARENT")
        original = self.current.copy()
        self.current = self.current.drop(index=1)
        self.assertEqual(self.view()["total"], 1)
        self.save(0, "VISIBLE-PARENT")
        self.current = original
        self.assertEqual(self.view()["rows"][0]["parent_sku"], "HIDDEN-PARENT")

    def test_operational_revision_changes_reject_a_stale_edit(self):
        with patch.object(variants, "_operational_revision", return_value="op-v1"):
            old = self.view()
        with patch.object(variants, "_operational_revision", return_value="op-v2"):
            self.assertEqual(self.save(0, "STALE", old).status_code, 409)

    def test_developer_filter_keeps_whole_group_and_product_names(self):
        operational = pd.DataFrame([
            {"MSKU": "S1", "ASIN": "A1", "开发员": "甲", "本地SKU名称": "1条链子（金）(2.5)"},
            {"MSKU": "S1B", "ASIN": "A1B", "开发员": "乙", "本地SKU名称": "1条链子（银）(4.0)"},
            {"MSKU": "S2", "ASIN": "A2", "开发员": "丙", "本地SKU名称": "1把锁（28mm）"},
        ])
        with patch.object(variants, "_operational_source", return_value=operational):
            result = self.view(developers="甲")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["developers"], ["丙", "乙", "甲"])
            self.assertEqual(len(result["rows"][0]["children"]), 2)
            self.assertEqual(result["rows"][0]["product_name"], "1条链子（金）(2.5)")
            self.assertEqual(result["rows"][0]["children"][0]["product_name"], "1条链子（金）(2.5)")
            self.assertEqual(self.view(search="锁")["total"], 1)

    def test_inferred_split_and_merge_keep_parent_sku_candidates(self):
        standalone = frame(*[(f"S{i:03}", f"OA{i}", "DE", "", "") for i in range(18, 22)])
        operational = pd.DataFrame([{"MSKU": f"S{i:03}", "ASIN": f"OA{i}", "本地SKU名称": "ABCDEFGHIJ"}
                                    for i in range(18, 22)])
        with (patch.object(variants, "_standalone_rows", return_value=standalone),
              patch.object(variants, "_operational_source", side_effect=lambda: operational.copy())):
            original = self.view(search="ABCDEFGHIJ")
            self.assertEqual(self.save(0, "FAMILY", original).status_code, 200)
            operational.loc[2:, "本地SKU名称"] = "MNOPQRSTUV"
            split = self.view(search="OA")
            self.assertEqual(len(split["rows"]), 2)
            self.assertTrue(all(group["status"] == "pending" for group in split["rows"]))
            self.assertTrue(all(group["candidate_skus"] == ["FAMILY"] for group in split["rows"]))
            self.assertEqual(self.save(0, "ONE", split).status_code, 200)
            self.assertEqual(self.save(1, "TWO", self.view(search="OA")).status_code, 200)
            operational["本地SKU名称"] = "ABCDEFGHIJ"
            merged = self.view(search="OA")
            self.assertEqual(len(merged["rows"]), 1)
            self.assertEqual(set(merged["rows"][0]["candidate_skus"]), {"ONE", "TWO"})
            self.assertEqual(merged["rows"][0]["status"], "pending")

    def test_unassembled_assignment_survives_later_real_parent_relationship(self):
        standalone = frame(("O1", "OA1", "DE", "", ""), ("O2", "OA2", "FR", "OA2", ""))
        operational = pd.DataFrame([
            {"MSKU": "O1", "ASIN": "OA1", "本地SKU名称": "1条包包链（金）（80cm）(2.5)", "开发员": "甲"},
            {"MSKU": "O2", "ASIN": "OA2", "本地SKU名称": "1条包包链（银）（100cm）(4.0)", "开发员": "甲"},
        ])
        with patch.object(variants, "_operational_source", return_value=operational):
            self.standalone_patch.stop()
            self.standalone_patch = patch.object(variants, "_standalone_rows", return_value=standalone)
            self.standalone_patch.start()
            inferred = self.view(status="unassembled", search="包包链")
            self.assertEqual(inferred["rows"][0]["relation_kind"], "unassembled")
            self.assertEqual(inferred["rows"][0]["parents"], [])
            self.assertEqual(self.save(0, "ORPHAN-PARENT", inferred).status_code, 200)
            filled = self.view(status="unassembled")
            self.assertEqual(filled["total"], 1)
            self.assertEqual(filled["rows"][0]["status"], "filled")
            self.standalone_patch.stop()
            self.standalone_patch = patch.object(variants, "_standalone_rows", return_value=pd.DataFrame())
            self.standalone_patch.start()
            self.current = frame(("O1", "OA1", "DE", "NEW-PARENT", ""), ("O2", "OA2", "FR", "NEW-PARENT", ""))
            linked = self.view()["rows"][0]
            self.assertEqual(linked["relation_kind"], "assembled")
            self.assertEqual(linked["parent_sku"], "ORPHAN-PARENT")
            self.assertEqual(self.view(status="unassembled")["total"], 0)


class VariantNameTests(unittest.TestCase):
    def test_colour_size_suffixes_and_business_markers(self):
        self.assertEqual(split_variant_name("1条包包链（金）（80cm）【K】(2.5)"), ("1条包包链", "金 / 80cm"))
        self.assertEqual(split_variant_name("(A)1个宠物梳子 蓝色(4.0)"), ("(A)1个宠物梳子", "蓝色"))
        self.assertEqual(split_variant_name("1件蕾丝上衣长袖M码（白色）(2.5)"), ("1件蕾丝上衣长袖", "M码 / 白色"))
        self.assertEqual(split_variant_name("1个耳机海绵套40mm(2.5)"), ("1个耳机海绵套", "40mm"))
        self.assertEqual(common_product_name(["手机挂绳-红色-长款", "手机挂绳-蓝色-长款"]), "手机挂绳-色-长款")

    def test_does_not_strip_models_packaging_or_body_words(self):
        for name in ["2个MC4连接器 IP68", "1套连接件（1J0201550A）", "1个手机支架（T形）", "3个夹子（盒装）", "1条蓝牙线"]:
            self.assertEqual(split_variant_name(name), (unicodedata.normalize("NFKC", name), ""))
        self.assertEqual(common_product_name(["1个锁", "2条链子"]), "")

    def infer(self, skus, names, asins=None):
        asins = asins or [f"A{i}" for i in range(len(skus))]
        source = frame(*[(sku, asin, "DE", "", "") for sku, asin in zip(skus, asins)])
        operational = pd.DataFrame([{"MSKU": sku, "ASIN": asin, "本地SKU名称": name}
                                    for sku, asin, name in zip(skus, asins, names)])
        return variants.build_unassembled_groups(source, variants._operational_metrics(operational))

    def test_contiguous_skus_and_pairwise_similarity_are_required(self):
        skus = ["AEU260301CQT018", "AEU260301CQT019", "AEU260301CQT020"]
        names = ["手机挂绳-红色-长款", "手机挂绳-蓝色-长款", "手机挂绳-黑色-长款"]
        groups = self.infer(skus, names)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["product_name"], "手机挂绳-色-长款")
        self.assertEqual([child["sku"] for child in groups[0]["children"]], skus)
        shuffled = self.infer([skus[2], skus[0], skus[1]], [names[2], names[0], names[1]], ["A2", "A0", "A1"])
        self.assertEqual(groups, shuffled)

    def test_gaps_prefix_width_and_missing_numeric_suffix_break_sequences(self):
        for skus in [("S018", "S020"), ("S018", "T019"), ("S018", "S19"),
                     ("S018-A", "S019-A"), ("S018", "S019B"), ("S099", "S0100")]:
            with self.subTest(skus=skus):
                self.assertEqual(self.infer(skus, ["同一个完整产品名称"] * 2), [])
        self.assertEqual(len(self.infer(["S099", "S100"], ["同一个完整产品名称"] * 2)), 1)

    def test_threshold_is_strict_and_retains_attributes(self):
        self.assertEqual(product_name_similarity("ABCDE", "ABCDX"), 0.8)
        self.assertEqual(self.infer(["S1", "S2"], ["ABCDE", "ABCDX"]), [])
        self.assertEqual(len(self.infer(["S1", "S2"], ["ABCDEF", "ABCDEZ"])), 1)
        self.assertEqual(normalized_product_name("2个MC4连接器 IP68（蓝色40mm）"), "2个MC4连接器 IP68(蓝色40MM)")

    def test_adjacent_similarity_cannot_bridge_dissimilar_endpoints(self):
        groups = self.infer(["S018", "S019", "S020", "S021"],
                            ["ABCDEFGHIJ", "XBCDEFGHIJ", "XBCDEFGHIZ", "XBCDEFGHIZ"])
        self.assertEqual([[child["sku"] for child in group["children"]] for group in groups],
                         [["S018", "S019"], ["S020", "S021"]])

    def test_identical_names_and_marker_only_differences_can_form_groups(self):
        groups = self.infer(["S1", "S2"], ["ＡＢＣ　 ＤＥＦ【K】(2.5)", "abc def(4.0)"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["product_name"], "ABC DEF")
        self.assertEqual(self.infer(["S1", "S2"], ["完整产品名称"] * 2, ["A1", "A1"]), [])

    def test_multiple_skus_for_one_asin_do_not_inflate_variant_count(self):
        groups = self.infer(["S1", "S2", "S3"], ["完整产品名称"] * 3, ["A1", "A2", "A1"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["children"]), 3)
        self.assertEqual(groups[0]["child_asins"], ["A1", "A2"])

    def test_alias_sequences_have_distinct_group_keys(self):
        groups = self.infer(["S1", "S2", "T1", "T2"], ["完整产品名称"] * 4,
                            ["A1", "A2", "A1", "A2"])
        self.assertEqual(len(groups), 2)
        self.assertEqual(len({group["key"] for group in groups}), 2)

    def test_ambiguous_or_missing_sku_names_cannot_join_or_bridge(self):
        groups = self.infer(["S018", "S019", "S019", "S020"],
                            ["完整产品名称", "完整产品名称", "另一种不同产品", "完整产品名称"])
        self.assertEqual(groups, [])
        self.assertEqual(self.infer(["S018", "S019", "S020"], ["完整产品名称", "", "完整产品名称"]), [])
        groups = self.infer(["S018", "S019", "S019"],
                            ["完整产品名称", "完整产品名称【K】", "完整产品名称(2.5)"])
        self.assertEqual(len(groups), 1)

    def test_common_name_preserves_order_repetition_and_cleans_separators(self):
        self.assertEqual(common_product_name(["AB", "BA"]), "A")
        self.assertEqual(common_product_name(["手机挂绳(红)-长款", "手机挂绳(蓝)-长款"]), "手机挂绳-长款")
        self.assertEqual(common_product_name(["--手机手机__挂绳--", "--手机手机__挂绳--"]), "手机手机_挂绳")
        self.assertEqual(common_product_name(["产品((红))", "产品((蓝))"]), "产品")
        self.assertEqual(common_product_name(["手机挂绳", ""]), "")
        self.assertEqual(common_product_name([]), "")

    def test_partial_country_parent_is_not_treated_as_unassembled(self):
        source = frame(("S1", "A1", "DE", "", ""), ("S1", "A1", "FR", "P1", ""), ("S2", "A2", "FR", "A2", ""))
        with patch.object(variants, "_latest_snapshot", return_value=("2026-11-06", True, source)):
            standalone = variants._standalone_rows("test")
        self.assertEqual(set(standalone["ASIN"]), {"A2"})


class VariantListingCompatibilityTests(unittest.TestCase):
    def test_new_columns_preserved_and_old_snapshot_recovers_without_writing(self):
        data = workbook([["sku", "child", "德国", "EUR", 9, 0, 0, 10, 9, "parent", "[color:Noir]"]])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".tmp") as directory:
            root = Path(directory)
            listing.persist_listing_snapshot("Listing20261106.xlsx", data, root)
            source = listing.load_snapshot("2026-11-06", root)
            self.assertEqual(source.loc[0, "父ASIN"], "PARENT")
            csv = root / "listing_prices/2026-11-06.csv"
            source.drop(columns=listing.LISTING_VARIANT_COLUMNS).to_csv(csv, index=False, encoding="utf-8-sig")
            previous = csv.read_bytes()
            recovered = listing.load_snapshot("2026-11-06", root)
            self.assertEqual(recovered.loc[0, "变体属性"], "[color:Noir]")
            self.assertEqual(csv.read_bytes(), previous)
            index_path = root / "listing_prices/index.csv"
            listing.load_listing_index(root).drop(columns=["变体字段齐全"]).to_csv(index_path, index=False, encoding="utf-8-sig")
            with (patch.object(variants, "load_listing_index", side_effect=lambda: listing.load_listing_index(root)),
                  patch.object(variants, "load_snapshot", side_effect=lambda day: listing.load_snapshot(day, root))):
                day, available, groups = variants._source_groups.__wrapped__("legacy")
            self.assertEqual(day, "2026-11-06")
            self.assertTrue(available)
            self.assertEqual(groups[0]["parent_asins"], ["PARENT"])
            self.assertTrue(listing.persist_listing_snapshot("Listing20261106.xlsx", data, root)["idempotent"])

    def test_old_format_still_prices_and_reports_variant_columns_unavailable(self):
        data = workbook([["sku", "child", "DE", "EUR", 9, 0, 0, 10, 9]], False)
        _, normalized, _ = listing.normalize_listing_workbook(data)
        self.assertEqual(normalized.loc[0, "当前实际总价"], 9)
        self.assertFalse(normalized.attrs["variant_columns_available"])
        self.assertEqual(variants.build_variant_groups(normalized), [])


if __name__ == "__main__":
    unittest.main()

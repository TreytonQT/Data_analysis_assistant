"""Current Listing variant families and durable, manually assigned parent SKUs."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, NamedTuple

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.db import connect
from backend.variant_names import common_product_name, normalized_product_name, product_name_similarity, split_variant_name
from backend.listing_prices import (
    LISTING_SNAPSHOT_LOCK,
    _normal_text,
    listing_source_revision,
    load_listing_index,
    load_snapshot,
)

router = APIRouter(prefix="/api/variants", tags=["variants"])
UNKNOWN_STORE = "未识别店铺"
VARIANT_VERSION = "variants-v4"
_RELATION_COLUMNS = ["MSKU", "ASIN", "国家", "父ASIN", "变体属性"]


class VariantBase(NamedTuple):
    source_revision: str
    operational_revision: str
    day: str | None
    available: bool
    operational: pd.DataFrame
    metrics: dict
    groups: list[dict]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def is_virtual_two_pack(sku: str) -> bool:
    return bool(re.fullmatch(r"VMP_.+_2_PK", _normal_text(sku)))


def build_variant_groups(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Build connected components before filtering or joining any metric sources."""
    roots: dict[str, str] = {}

    def find(value: str) -> str:
        roots.setdefault(value, value)
        root = value
        while roots[root] != root:
            root = roots[root]
        while roots[value] != value:
            parent = roots[value]
            roots[value] = root
            value = parent
        return root

    rows = []
    first_parent: dict[str, str] = {}
    for row in frame.to_dict("records"):
        parent, child = _normal_text(row.get("父ASIN")), _normal_text(row.get("ASIN"))
        if not parent or not child or parent == child:
            continue
        sku = _normal_text(row.get("MSKU"))
        if not sku or is_virtual_two_pack(sku):
            continue
        roots[find(parent)] = find(first_parent.setdefault(child, parent))
        rows.append((parent, child, sku, str(row.get("国家") or ""), row.get("变体属性")))
    components: dict[str, list] = {}
    for row in rows:
        components.setdefault(find(row[0]), []).append(row)
    groups = []
    for members in components.values():
        parents: dict[str, set[str]] = {}
        children: dict[tuple[str, str], dict] = {}
        for parent, asin, sku, country, attributes in members:
            parents.setdefault(parent, set()).add(country)
            child = children.setdefault((sku, asin), {"sku": sku, "asin": asin, "sites": []})
            site = {"country": country, "parent_asin": parent,
                    "attributes": "" if pd.isna(attributes) else str(attributes)}
            if site not in child["sites"]:
                child["sites"].append(site)
        parent_asins = sorted(parents)
        child_asins = sorted({asin for _, asin in children})
        for child in children.values():
            child["sites"].sort(key=lambda site: (site["country"], site["parent_asin"]))
        groups.append({
            "key": _digest([parent_asins, child_asins]),
            "parent_asins": parent_asins,
            "child_asins": child_asins,
            "parents": [{"asin": asin, "countries": sorted(parents[asin])} for asin in parent_asins],
            "children": [children[key] for key in sorted(children)],
            "relation_kind": "assembled",
        })
    return sorted(groups, key=lambda group: group["parent_asins"])


@lru_cache(maxsize=4)
def _latest_snapshot(source_revision: str) -> tuple[str | None, bool, pd.DataFrame]:
    del source_revision
    index = load_listing_index()
    if index.empty:
        return None, False, pd.DataFrame()
    record = index.iloc[-1]
    day = str(record["日期"])
    frame = load_snapshot(day)
    marker = record.get("变体字段齐全", "")
    available = marker == "是" if marker else bool(frame.attrs.get("variant_columns_available"))
    return day, available, frame


@lru_cache(maxsize=4)
def _source_groups(source_revision: str) -> tuple[str | None, bool, list[dict]]:
    day, available, frame = _latest_snapshot(source_revision)
    return day, available, build_variant_groups(frame) if available else []


def _standalone_rows(source_revision: str) -> pd.DataFrame:
    _, available, frame = _latest_snapshot(source_revision)
    if not available or frame.empty:
        return pd.DataFrame()
    parents, children = frame["父ASIN"].map(_normal_text), frame["ASIN"].map(_normal_text)
    skus = frame["MSKU"].map(_normal_text)
    linked = set(zip(skus[parents.ne("") & parents.ne(children)], children[parents.ne("") & parents.ne(children)]))
    keep = [not is_virtual_two_pack(sku) and (sku, asin) not in linked for sku, asin in zip(skus, children)]
    return frame.loc[keep, _RELATION_COLUMNS].copy()


def _operational_source() -> pd.DataFrame:
    from backend.dashboard_api import load_source_frame
    from dashboard.report_store import get_latest_source_path

    return load_source_frame("operational_sales", "运营原始表") if get_latest_source_path("operational_sales") else pd.DataFrame()


def _operational_revision() -> str:
    from dashboard.report_store import get_latest_source_path

    path = get_latest_source_path("operational_sales")
    try:
        stat = path.stat() if path else None
        return _digest([str(path), stat.st_size, stat.st_mtime_ns]) if stat else "empty"
    except OSError:
        return "empty"


def _operational_metrics(operational: pd.DataFrame) -> dict[tuple[str, str], dict]:
    metrics = {}
    if not {"MSKU", "ASIN"}.issubset(operational.columns):
        return metrics
    metric_columns = ["MSKU", "ASIN", "日均销量", "开发员", "本地SKU名称"]
    base = operational[[column for column in metric_columns if column in operational.columns]].copy()
    base["MSKU"] = base["MSKU"].map(_normal_text)
    base["ASIN"] = base["ASIN"].map(_normal_text)
    base["日均销量"] = pd.to_numeric(base.get("日均销量", pd.Series(index=base.index, dtype=float)), errors="coerce")
    for key, rows in base.groupby(["MSKU", "ASIN"], sort=False):
        daily = rows["日均销量"].sum(min_count=1)
        developers = sorted({str(value).strip() for value in rows.get("开发员", []) if pd.notna(value) and str(value).strip()})
        names = sorted({str(value).strip() for value in rows.get("本地SKU名称", []) if pd.notna(value) and str(value).strip()})
        metrics[key] = {"daily_sales": None if pd.isna(daily) else float(daily), "developer": "；".join(developers),
                        "developers": developers, "product_name": "；".join(names), "names": names}
    return metrics


def build_unassembled_groups(frame: pd.DataFrame, metrics: dict) -> list[dict]:
    candidates: dict[str, dict] = {}
    for row in frame.to_dict("records"):
        sku, asin = _normal_text(row.get("MSKU")), _normal_text(row.get("ASIN"))
        numbering = re.fullmatch(r"(.*?)([0-9]+)", sku)
        if not numbering or not asin or is_virtual_two_pack(sku):
            continue
        names = metrics.get((sku, asin), {}).get("names", [])
        candidate = candidates.setdefault(sku, {
            "sku": sku, "prefix": numbering[1], "width": len(numbering[2]),
            "number": int(numbering[2]), "names": set(), "children": {},
        })
        candidate["names"].update(normalized_product_name(name) for name in names if name.strip())
        child = candidate["children"].setdefault((sku, asin), {"sku": sku, "asin": asin, "sites": []})
        original = row.get("变体属性")
        attribute = split_variant_name(names[0])[1] if names else ""
        site = {"country": str(row.get("国家") or ""), "parent_asin": "",
                "attributes": attribute if pd.isna(original) or not str(original).strip() else str(original)}
        if site not in child["sites"]:
            child["sites"].append(site)

    sequences: dict[tuple[str, int], list[dict]] = {}
    for candidate in candidates.values():
        if len(candidate["names"]) != 1 or not next(iter(candidate["names"])):
            continue
        candidate["name"] = next(iter(candidate["names"]))
        sequences.setdefault((candidate["prefix"], candidate["width"]), []).append(candidate)

    families = []
    for sequence in (sequences[key] for key in sorted(sequences)):
        family: list[dict] = []
        for candidate in sorted(sequence, key=lambda item: item["number"]):
            if family and (candidate["number"] != family[-1]["number"] + 1
                           or any(product_name_similarity(member["name"], candidate["name"]) <= 0.8 for member in family)):
                families.append(family)
                family = []
            family.append(candidate)
        if family:
            families.append(family)

    groups = []
    for family in families:
        if len(family) < 2:
            continue
        children = [child for member in family for _, child in sorted(member["children"].items())]
        asins = sorted({child["asin"] for child in children})
        if len(asins) < 2:
            continue
        for child in children:
            child["sites"].sort(key=lambda site: site["country"])
        groups.append({"key": _digest(["unassembled", asins, [member["sku"] for member in family]]), "parent_asins": [], "child_asins": asins,
                       "parents": [], "children": children, "relation_kind": "unassembled",
                       "product_name": common_product_name([member["name"] for member in family])})
    return sorted(groups, key=lambda group: (group["product_name"], group["key"]))


def build_store_groups(assembled: list[dict], standalone: pd.DataFrame,
                       operational: pd.DataFrame, metrics: dict) -> list[dict]:
    from dashboard.data_processing import extract_operational_store_codes

    store_lookup: dict[tuple[str, str], set[str]] = {}
    if {"MSKU", "ASIN", "店铺名称"}.issubset(operational.columns):
        for row in operational[["MSKU", "ASIN", "店铺名称"]].to_dict("records"):
            key = (_normal_text(row["MSKU"]), _normal_text(row["ASIN"]))
            codes = {_normal_text(code) for code, _ in extract_operational_store_codes(row["店铺名称"])
                     if code and code != "未识别"}
            store_lookup.setdefault(key, set()).update(codes)

    rows = standalone.reindex(columns=_RELATION_COLUMNS).to_dict("records")
    for group in assembled:
        for child in group["children"]:
            for site in child["sites"]:
                rows.append({"MSKU": child["sku"], "ASIN": child["asin"], "国家": site["country"],
                             "父ASIN": site["parent_asin"], "变体属性": site["attributes"]})
    by_store: dict[str, list[dict]] = {}
    inferred: dict[tuple[str, str], bool] = {}
    for row in rows:
        sku, asin = _normal_text(row.get("MSKU")), _normal_text(row.get("ASIN"))
        if not sku or not asin or is_virtual_two_pack(sku):
            continue
        codes = store_lookup.get((sku, asin), set())
        prefix = re.match(r"([A-Z]+)(?=[0-9])", sku) if not codes else None
        inferred[(sku, asin)] = bool(prefix)
        for code in sorted(codes or {prefix[1] if prefix else UNKNOWN_STORE}):
            by_store.setdefault(code, []).append(row)

    result = []
    for code in sorted(by_store):
        frame = pd.DataFrame(by_store[code], columns=_RELATION_COLUMNS)
        parents, asins = frame["父ASIN"].map(_normal_text), frame["ASIN"].map(_normal_text)
        linked = set(asins[parents.ne("") & parents.ne(asins)])
        groups = [*build_variant_groups(frame), *build_unassembled_groups(frame[~asins.isin(linked)], metrics)]
        for group in groups:
            if len(group["child_asins"]) < 2:
                continue
            result.append({**group, "key": _digest([VARIANT_VERSION, code, group["key"]]), "store_code": code,
                           "store_inferred": any(inferred[(child["sku"], child["asin"])] for child in group["children"])})
    return result


def _record_matches(group: dict, record: dict) -> bool:
    return bool(set(group["parent_asins"]).intersection(json.loads(record["parent_asins"]))
                or set(group["child_asins"]).intersection(json.loads(record["child_asins"])))


def add_other_parent_skus(groups: list[dict], saved: list[dict]) -> list[dict]:
    sources = [{"store_code": group["store_code"], "parent_sku": group["parent_sku"],
                "child_asins": group["child_asins"]} for group in groups if group["status"] == "filled"]
    for record in saved:
        code = record.get("store_code")
        if (code and record["parent_sku"] and not record["needs_confirmation"]
                and not any(group["store_code"] == code and _record_matches(group, record) for group in groups)):
            sources.append({"store_code": code, "parent_sku": record["parent_sku"],
                            "child_asins": json.loads(record["child_asins"])})
    for group in groups:
        hints: dict[tuple[str, str], dict] = {}
        for source in sources:
            code = source["store_code"]
            shared = set(group["child_asins"]).intersection(source["child_asins"])
            if code in {group["store_code"], UNKNOWN_STORE} or not shared:
                continue
            hint = hints.setdefault((code, _normal_text(source["parent_sku"])),
                                    {"store_code": code, "parent_sku": source["parent_sku"], "matched_child_asins": []})
            hint["matched_child_asins"] = sorted(set(hint["matched_child_asins"]).union(shared))
        group["other_parent_skus"] = [hints[key] for key in sorted(hints)]
    return groups


def _saved_records(conn) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM variant_parent_skus ORDER BY group_key")]


def reconcile_assignments(groups: list[dict], saved: list[dict]) -> list[dict]:
    """One-to-one lineage inherits; splits and conflicting merges require a decision."""
    links: dict[int, list[int]] = {}
    for index, record in enumerate(saved):
        parents, children = set(json.loads(record["parent_asins"])), set(json.loads(record["child_asins"]))
        links[index] = [i for i, group in enumerate(groups)
                        if (record.get("store_code") is None or record["store_code"] == group.get("store_code", UNKNOWN_STORE))
                        and (parents.intersection(group["parent_asins"]) or children.intersection(group["child_asins"]))]
    result = []
    for index, group in enumerate(groups):
        matches = [i for i in links if index in links[i]]
        scoped = [i for i in matches if saved[i].get("store_code") is not None]
        if scoped:
            matches = scoped
        candidates: dict[str, str] = {}
        pending = False
        for i in matches:
            record = saved[i]
            values = [record["parent_sku"], *json.loads(record["candidate_skus"])]
            for value in values:
                if value:
                    candidates.setdefault(_normal_text(value), value)
            if record["needs_confirmation"] or (len(links[i]) > 1 and any(values)):
                pending = True
        pending = pending or len(candidates) > 1
        sku = next(iter(candidates.values()), "") if not pending else ""
        result.append({**group, "parent_sku": sku,
                       "status": "pending" if pending else "filled" if sku else "empty",
                       "candidate_skus": list(candidates.values()) if pending else [],
                       "legacy_assignment": bool(matches and not scoped and candidates)})
    # A dormant family may return after its old SKU was reused by another family.
    owners: dict[tuple[str, str], list[dict]] = {}
    for group in result:
        if group["parent_sku"]:
            owners.setdefault((group.get("store_code", UNKNOWN_STORE), _normal_text(group["parent_sku"])), []).append(group)
    for duplicates in owners.values():
        if len(duplicates) > 1:
            for group in duplicates:
                group.update(status="pending", candidate_skus=[group["parent_sku"]], parent_sku="")
    return result


@lru_cache(maxsize=2)
def _cached_operational(operational_revision: str) -> tuple[pd.DataFrame, dict]:
    operational = _operational_source()
    return operational, _operational_metrics(operational)


@lru_cache(maxsize=2)
def _cached_base(source_revision: str, operational_revision: str) -> VariantBase:
    day, available, groups = _source_groups(source_revision)
    operational, metrics = _cached_operational(operational_revision)
    groups = build_store_groups(groups, _standalone_rows(source_revision), operational, metrics) if available else []
    return VariantBase(source_revision, operational_revision, day, available, operational, metrics, groups)


def _assert_base_current(base: VariantBase) -> None:
    if base.operational_revision != _operational_revision():
        raise HTTPException(409, "运营原始表已变化，请刷新后重新确认")
    if base.source_revision != listing_source_revision():
        raise HTTPException(409, "变体关系已变化，请刷新后重新确认")


def _base_state() -> VariantBase:
    # Lock outside the LRU lookup so concurrent cold requests share one build.
    with LISTING_SNAPSHOT_LOCK:
        base = _cached_base(listing_source_revision(), _operational_revision())
        _assert_base_current(base)
        return base


def _image_revision() -> str:
    from dashboard.report_store import get_latest_source_path

    path = get_latest_source_path("sku_image_map")
    try:
        stat = path.stat() if path else None
        return _digest([str(path), stat.st_size, stat.st_mtime_ns]) if stat else "empty"
    except OSError:
        return "empty"


@lru_cache(maxsize=2)
def _cached_display(source_revision: str, operational_revision: str, image_revision: str) -> dict[str, dict]:
    from backend.dashboard_api import _optional_sku_image_map, _sku_image_lookup

    base = _cached_base(source_revision, operational_revision)
    image_map = _optional_sku_image_map()
    image_source = base.operational
    if {"MSKU", "ASIN", "图片链接"}.issubset(image_map.columns):
        image_source = pd.DataFrame([{"MSKU": child["sku"], "ASIN": child["asin"]}
                                     for group in base.groups for child in group["children"]], columns=["MSKU", "ASIN"])
    images = _sku_image_lookup(image_source, image_map)
    return {group["key"]: group for group in enrich_groups(base.groups, base.operational, images, base.metrics)}


def _display_groups(base: VariantBase) -> dict[str, dict]:
    with LISTING_SNAPSHOT_LOCK:
        image_revision = _image_revision()
        display = _cached_display(base.source_revision, base.operational_revision, image_revision)
        _assert_base_current(base)
        if image_revision != _image_revision():
            raise HTTPException(409, "SKU图片映射已变化，请刷新后重试")
        return display


def _relation_state(conn, base: VariantBase | None = None, *, include_references: bool = True
                    ) -> tuple[str | None, bool, list[dict], list[dict], str]:
    if base is None:
        base = _base_state()
    _assert_base_current(base)
    saved = _saved_records(conn)
    revision = _digest([VARIANT_VERSION, base.source_revision, base.operational_revision,
                        [group["key"] for group in base.groups], saved])
    # Reconciliation creates fresh group dictionaries; cached source groups stay unchanged.
    groups = reconcile_assignments(base.groups, saved)
    if include_references:
        groups = add_other_parent_skus(groups, saved)
    return base.day, base.available, groups, saved, revision


def variant_revision() -> str:
    with connect() as conn:
        return _digest([VARIANT_VERSION, _saved_records(conn)])


def enrich_groups(groups: list[dict], operational: pd.DataFrame, image_lookup: dict, metrics: dict | None = None) -> list[dict]:
    from backend.dashboard_api import _sku_image_for_row

    if metrics is None:
        metrics = _operational_metrics(operational)
    result = []
    for group in groups:
        children = [{**child, **metrics.get((child["sku"], child["asin"]), {"daily_sales": None, "developer": "", "developers": [], "product_name": "", "names": []}),
                     "image": _sku_image_for_row(image_lookup, child["sku"], child["asin"])} for child in group["children"]]
        ranked = sorted((child for child in children if child["daily_sales"] is not None),
                        key=lambda child: (-child["daily_sales"], child["sku"], child["asin"]))
        representative = ranked[0] if ranked else None
        name_candidates = [*ranked, *sorted((child for child in children if child["daily_sales"] is None),
                                          key=lambda child: (child["sku"], child["asin"]))]
        product_name = (group.get("product_name", "") if group["relation_kind"] == "unassembled"
                        else next((child["product_name"] for child in name_candidates if child["product_name"]), ""))
        result.append({**group, "children": children,
                       "product_name": product_name,
                       "child_asin_count": len(group["child_asins"]),
                       "developers": sorted({value for child in children for value in child["developers"]}),
                       "image": representative["image"] if representative else None,
                       "representative_sku": representative["sku"] if representative else None})
    return result


@router.get("")
def list_variants(search: str = "", status: str = "all", developers: str = "", stores: str = "", page: int = Query(1, ge=1),
                  page_size: int = Query(50, ge=1, le=200)) -> dict:
    if status not in {"all", "filled", "empty", "pending", "unassembled"}:
        raise HTTPException(422, "变体状态无效")
    try:
        base = _base_state()
        with LISTING_SNAPSHOT_LOCK, connect() as conn:
            day, available, groups, _, revision = _relation_state(conn, base)
        display = _display_groups(base)
        groups = [{**group, **display[group["key"]]} for group in groups]
        operational = base.operational
        options = sorted({value for group in groups for value in group["developers"]})
        store_options = sorted({group.get("store_code", UNKNOWN_STORE) for group in groups})
        selected_stores = {_normal_text(value) for value in stores.split(",") if value.strip()}
        chosen = {value.strip() for value in developers.split(",") if value.strip()}
        query = _normal_text(search)
        matched = [group for group in groups if (status == "all" or
                   (group["relation_kind"] == "unassembled" if status == "unassembled" else group["status"] == status))
                   and (status != "empty" or (group["relation_kind"] == "assembled" and bool(group["parent_asins"])))
                   and (not selected_stores or group.get("store_code", UNKNOWN_STORE) in selected_stores)
                   and (not chosen or chosen.intersection(group["developers"]))
                   and (not query or any(query in _normal_text(value) for value in [
                       group["parent_sku"], *group["candidate_skus"], *group["parent_asins"], *group["child_asins"],
                       group["product_name"], *(child["product_name"] for child in group["children"]),
                       *(child["sku"] for child in group["children"])]))]
        total = len(matched)
        page = min(page, max(1, (total + page_size - 1) // page_size))
        selected = matched[(page - 1) * page_size:page * page_size]
        warning = None
        if not day:
            warning = "请先上传领星产品监控表"
        elif not available:
            warning = "最新原表缺少父ASIN或变体属性，请上传新格式的领星产品监控表"
        elif operational.empty:
            warning = "尚无运营原始表，日均销量和开发员显示缺失"
        elif "本地SKU名称" not in operational.columns:
            warning = "运营原始表缺少本地SKU名称，品名及未合成变体识别暂不可用"
        return {"date": day, "revision": revision, "warning": warning,
                "rows": selected, "total": total, "developers": options, "stores": store_options,
                "page": page, "page_size": page_size}
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(422, f"变体数据读取失败：{exc}") from exc


class ParentSkuInput(BaseModel):
    parent_sku: str
    revision: str


@router.put("/{group_key}/parent-sku")
def save_parent_sku(group_key: str, payload: ParentSkuInput) -> dict:
    base = _base_state()
    with LISTING_SNAPSHOT_LOCK, connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _, _, groups, saved, revision = _relation_state(conn, base, include_references=False)
        if revision != payload.revision:
            raise HTTPException(409, "变体关系或父SKU已变化，请刷新后重新确认")
        target = next((group for group in groups if group["key"] == group_key), None)
        if target is None:
            raise HTTPException(404, "该变体组已不存在，请刷新")
        sku = payload.parent_sku.strip()
        current_store = target["store_code"]
        store_groups = [group for group in groups if group["store_code"] == current_store]
        if sku and any(group["key"] != group_key and _normal_text(group["parent_sku"]) == _normal_text(sku) for group in store_groups):
            raise HTTPException(409, "父SKU已被本店铺其他当前变体组使用")
        target.update(parent_sku=sku, status="filled" if sku else "empty", candidate_skus=[])
        # Materialize all current lineages together so resolving one split keeps the
        # other branch's candidates, while superseded records cannot reintroduce a conflict.
        parents = {value for group in store_groups for value in group["parent_asins"]}
        children = {value for group in store_groups for value in group["child_asins"]}
        for record in saved:
            if record.get("store_code") == current_store and (
                    parents.intersection(json.loads(record["parent_asins"])) or children.intersection(json.loads(record["child_asins"]))):
                conn.execute("DELETE FROM variant_parent_skus WHERE group_key = ?", (record["group_key"],))
        for group in store_groups:
            conn.execute("""INSERT OR REPLACE INTO variant_parent_skus
                (group_key, parent_sku, parent_asins, child_asins, candidate_skus, needs_confirmation, updated_at, store_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                    group["key"], group["parent_sku"], json.dumps(group["parent_asins"]),
                    json.dumps(group["child_asins"]), json.dumps(group["candidate_skus"]),
                    int(group["status"] == "pending"), datetime.now(timezone.utc).isoformat(), current_store))
        _assert_base_current(base)
        return {"saved": True, "parent_sku": sku}

from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Callable

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from dashboard.data_processing import (
    COMMISSION_COLUMNS,
    DEPARTMENT_FEE_COLUMNS,
    METRIC_COLUMNS,
    REPLENISHMENT_COVERAGE_RULE_COLUMNS,
    REPLENISHMENT_PRODUCT_TAG_COLUMNS,
    REPLENISHMENT_SWITCH_COLUMNS,
    REPLENISHMENT_TARGET_COLUMNS,
    STORE_COLUMNS,
    TARGET_COLUMNS,
    build_discovered_commission_config,
    build_discovered_department_fee_config,
    load_metric_config,
    merge_business_config,
    normalize_config_number,
    normalize_commission_config,
    normalize_department_fee_config,
    normalize_month,
    normalize_replenishment_targets,
    normalize_replenishment_coverage_rules,
    normalize_replenishment_product_tags,
    normalize_replenishment_switches,
    normalize_store_config,
    normalize_target_config,
    read_local_table,
    read_upload_table,
)
from dashboard.formula_engine import validate_formula
from dashboard.report_store import load_upload_records
from backend.upload_safety import read_upload_limited

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"
router = APIRouter(prefix="/api", tags=["config"])
CONFIG_MAX_ROWS = 20_000
CONFIG_MAX_COLUMNS = 100
CONFIG_MAX_BYTES = 10 * 1024 * 1024
_CONFIG_WRITE_LOCK = RLock()


@dataclass(frozen=True)
class ConfigDefinition:
    title: str
    description: str
    columns: list[str]
    normalizer: Callable[[pd.DataFrame], pd.DataFrame]
    keys: tuple[str, ...]


def normalize_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in METRIC_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"指标配置缺少列：{', '.join(missing)}")
    names = frame["指标名称"].fillna("").astype(str).str.strip()
    groups = frame["显示分组"].fillna("").astype(str).str.strip()
    if names.eq("").any() or groups.eq("").any():
        raise ValueError("指标名称和显示分组不能为空")
    enabled = frame["是否启用"].fillna("").astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "是", "启用"})
    for row_number, formula in frame.loc[enabled, "公式"].items():
        try:
            validate_formula(str(formula))
        except ValueError as exc:
            raise ValueError(f"第 {row_number + 2} 行公式非法：{exc}") from exc
    allowed_formats = {"金额", "整数", "百分比", "数值", "number", "amount", "percent", "integer"}
    invalid_formats = sorted(set(frame.loc[enabled, "格式"].fillna("").astype(str).str.strip()) - allowed_formats)
    if invalid_formats:
        raise ValueError(f"指标格式非法：{', '.join(invalid_formats)}")
    # Run the production loader as validation while retaining disabled rows in storage.
    class Upload:
        name = "metrics_config.csv"
        def getvalue(self):
            return frame.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    load_metric_config(Upload())
    result = frame[METRIC_COLUMNS].copy().fillna("")
    result["排序"] = pd.to_numeric(result["排序"], errors="coerce").fillna(9999).astype(int)
    return result


CONFIGS: dict[str, ConfigDefinition] = {
    "metrics_config": ConfigDefinition("指标公式配置", "维护指标名称、分组、公式、格式、排序和启用状态。", METRIC_COLUMNS, normalize_metrics, ("指标名称", "显示分组")),
    "store_config": ConfigDefinition("店铺配置", "维护店铺类型、停提款月份和所属部门。", STORE_COLUMNS, normalize_store_config, ("店铺名",)),
    "monthly_targets": ConfigDefinition("目标配置", "每位开发员维护固定月目标和目标毛利率。", TARGET_COLUMNS, normalize_target_config, ("开发员",)),
    "department_fee_config": ConfigDefinition("部门费用率", "按月份和部门维护费用率，可填写 8%、0.08 或 8。", DEPARTMENT_FEE_COLUMNS, normalize_department_fee_config, ("月份", "部门")),
    "commission_config": ConfigDefinition("提成配置", "按月份和开发员维护库存计提、弃置和职位提点。", COMMISSION_COLUMNS, normalize_commission_config, ("月份", "开发员")),
    "replenishment_coverage_rules": ConfigDefinition("库存覆盖规则", "按重量匹配运输方式，并由头程时效、预警天数和补货频次计算库存覆盖天数。", REPLENISHMENT_COVERAGE_RULE_COLUMNS, normalize_replenishment_coverage_rules, ("运输方式", "重量下限")),
    "replenishment_switches": ConfigDefinition("补货开关", "按ASIN控制是否进入补货决策矩阵；关闭补货时必须填写原因。", REPLENISHMENT_SWITCH_COLUMNS, normalize_replenishment_switches, ("ASIN",)),
    "replenishment_product_tags": ConfigDefinition("ASIN产品标签", "按ASIN维护一个或多个产品标签；颜色可留空或填写#RRGGBB。", REPLENISHMENT_PRODUCT_TAG_COLUMNS, normalize_replenishment_product_tags, ("ASIN", "产品标签")),
}


def definition_or_404(name: str) -> ConfigDefinition:
    definition = CONFIGS.get(name)
    if not definition:
        raise HTTPException(404, "未知配置")
    return definition


def config_path(name: str) -> Path:
    definition_or_404(name)
    root = CONFIG_DIR.resolve(strict=False)
    candidate = CONFIG_DIR / f"{name}.csv"
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("配置文件超出 configs 目录") from exc
    return candidate


def read_config(name: str) -> pd.DataFrame:
    definition = definition_or_404(name)
    path = config_path(name)
    if not path.exists():
        return pd.DataFrame(columns=definition.columns)
    try:
        return definition.normalizer(read_local_table(path)).fillna("")
    except Exception as exc:
        raise HTTPException(422, f"{definition.title}读取失败：{exc}") from exc


def records(frame: pd.DataFrame) -> list[dict]:
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _validate_frame_limits(frame: pd.DataFrame) -> None:
    if len(frame) > CONFIG_MAX_ROWS:
        raise ValueError(f"配置行数超过 {CONFIG_MAX_ROWS} 限制")
    if len(frame.columns) > CONFIG_MAX_COLUMNS:
        raise ValueError(f"配置列数超过 {CONFIG_MAX_COLUMNS} 限制")


def _canonical_key(series: pd.Series, column: str) -> pd.Series:
    if column == "月份":
        return series.map(normalize_month).fillna("")
    return series.fillna("").astype(str).str.strip()


def _validate_unique_keys(frame: pd.DataFrame, definition: ConfigDefinition) -> None:
    keyed = pd.DataFrame(index=frame.index)
    for key in definition.keys:
        keyed[key] = _canonical_key(frame[key], key)
    missing = keyed.eq("").any(axis=1)
    if missing.any():
        rows = ", ".join(str(index + 2) for index in keyed.index[missing][:10])
        raise ValueError(f"业务键 {', '.join(definition.keys)} 不能为空（第 {rows} 行）")
    duplicates = keyed.duplicated(subset=list(definition.keys), keep=False)
    if duplicates.any():
        examples = keyed.loc[duplicates, list(definition.keys)].drop_duplicates().head(5).to_dict(orient="records")
        raise ValueError(f"存在重复业务键 {', '.join(definition.keys)}：{examples}")


def _validate_numeric_values(name: str, frame: pd.DataFrame) -> None:
    numeric_columns = {
        "metrics_config": ["排序"],
        "monthly_targets": ["目标业绩", "目标毛利率"],
        "department_fee_config": ["费用率"],
        "commission_config": ["库存计提", "弃置", "职位提点"],
        "replenishment_coverage_rules": ["重量下限", "重量上限", "头程时效", "预警天数", "补货频次"],
    }.get(name, [])
    issues: list[str] = []
    for column in numeric_columns:
        if column not in frame.columns:
            continue
        values = frame[column]
        non_empty = values.notna() & values.astype(str).str.strip().ne("")
        invalid = non_empty & normalize_config_number(values).isna()
        for index in frame.index[invalid][:5]:
            issues.append(f"第 {index + 2} 行 {column}={values.loc[index]!r}")
    if issues:
        raise ValueError("配置包含无法识别的数值：" + "；".join(issues))


def validate_and_normalize_config(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    definition = definition_or_404(name)
    _validate_frame_limits(frame)
    working = frame.copy()
    if name == "replenishment_switches" and "ASIN" not in working.columns and "补货组ID" in working.columns:
        working = working.rename(columns={"补货组ID": "ASIN"})
    for column in definition.columns:
        if column not in working.columns:
            working[column] = pd.NA
    working = working[definition.columns]
    _validate_unique_keys(working, definition)
    _validate_numeric_values(name, working)
    normalized = definition.normalizer(working.copy()).fillna("")
    for column in definition.columns:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[definition.columns]
    _validate_frame_limits(normalized)
    return normalized


def _atomic_write_config(name: str, frame: pd.DataFrame) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    destination = config_path(name)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{name}-",
        suffix=".csv.tmp",
        dir=CONFIG_DIR,
        delete=False,
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _invalidate_dashboard_cache() -> None:
    from backend.dashboard_api import clear_dashboard_caches

    clear_dashboard_caches()


def _invalidate_replenishment_view_cache() -> None:
    from backend.dashboard_api import clear_replenishment_view_cache

    clear_replenishment_view_cache()


def _updated_at(path: Path | None = None) -> str:
    timestamp = datetime.fromtimestamp(path.stat().st_mtime) if path and path.exists() else datetime.now()
    return timestamp.astimezone().isoformat(timespec="seconds")


def upsert_replenishment_switch(
    asin: str,
    is_replenishment: bool,
    close_reason: str,
) -> dict[str, object]:
    normalized_asin = str(asin or "").strip().upper()
    normalized_reason = str(close_reason or "").strip()
    if not normalized_asin:
        raise ValueError("ASIN不能为空")
    if not is_replenishment and not normalized_reason:
        raise ValueError("关闭补货时必须填写关闭原因")

    with _CONFIG_WRITE_LOCK:
        existing = read_config("replenishment_switches")
        existing = existing[~existing["ASIN"].fillna("").astype(str).str.upper().eq(normalized_asin)].copy()
        updated = pd.concat(
            [
                existing,
                pd.DataFrame(
                    [
                        {
                            "ASIN": normalized_asin,
                            "是否补货": is_replenishment,
                            "关闭原因": "" if is_replenishment else normalized_reason,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        normalized = validate_and_normalize_config("replenishment_switches", updated)
        path = _atomic_write_config("replenishment_switches", normalized)
        _invalidate_replenishment_view_cache()
    return {
        "ASIN": normalized_asin,
        "is_replenishment": bool(is_replenishment),
        "close_reason": "" if is_replenishment else normalized_reason,
        "updated_at": _updated_at(path),
    }


def merge_rows(existing: pd.DataFrame, discovered: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    combined = pd.concat([existing, discovered], ignore_index=True)
    for key in keys:
        combined = combined[combined[key].fillna("").astype(str).str.strip().ne("")]
    return combined.drop_duplicates(subset=keys, keep="first").reset_index(drop=True)


def configs_with_discovered_rows() -> dict[str, pd.DataFrame]:
    frames = {name: read_config(name) for name in CONFIGS}
    upload_records = load_upload_records()
    if upload_records.empty:
        return frames
    try:
        from backend.dashboard_api import load_performance_reports

        reports = load_performance_reports()
    except (ValueError, OSError, HTTPException):
        return frames

    stores = reports[["店铺编码"]].dropna().drop_duplicates().rename(columns={"店铺编码": "店铺名"})
    stores["店铺类型"] = ""
    stores["停提款时间"] = ""
    stores["店铺所属部门"] = ""
    frames["store_config"] = merge_rows(frames["store_config"], normalize_store_config(stores), ["店铺名"])

    targets = reports[["销售专员"]].dropna().drop_duplicates().rename(columns={"销售专员": "开发员"})
    targets["目标业绩"] = ""
    targets["目标毛利率"] = ""
    frames["monthly_targets"] = merge_rows(frames["monthly_targets"], normalize_target_config(targets), ["开发员"])

    reports_with_config = merge_business_config(reports, frames["store_config"], frames["monthly_targets"])
    frames["department_fee_config"] = merge_rows(
        frames["department_fee_config"], build_discovered_department_fee_config(reports_with_config), ["月份", "部门"]
    ).sort_values(["月份", "部门"]).reset_index(drop=True)
    frames["commission_config"] = merge_rows(
        frames["commission_config"], build_discovered_commission_config(reports), ["月份", "开发员"]
    ).sort_values(["月份", "开发员"]).reset_index(drop=True)
    return frames


@router.get("/configs")
def list_configs():
    frames = configs_with_discovered_rows()
    return {
        "configs": [
            {
                "name": name,
                "title": definition.title,
                "description": definition.description,
                "columns": definition.columns,
                "rows": records(frames[name]),
                "updated_at": _updated_at(config_path(name)) if config_path(name).exists() else None,
            }
            for name, definition in CONFIGS.items()
        ]
    }


@router.get("/config/{name}")
def get_config(name: str):
    definition = definition_or_404(name)
    frame = configs_with_discovered_rows()[name]
    path = config_path(name)
    return {
        "name": name,
        "title": definition.title,
        "description": definition.description,
        "columns": definition.columns,
        "rows": records(frame),
        "updated_at": _updated_at(path) if path.exists() else None,
    }


@router.put("/config/{name}")
def save_config(name: str, rows: list[dict]):
    definition_or_404(name)
    try:
        with _CONFIG_WRITE_LOCK:
            normalized = validate_and_normalize_config(name, pd.DataFrame(rows))
            path = _atomic_write_config(name, normalized)
            _invalidate_dashboard_cache()
        return {"ok": True, "rows": records(normalized), "updated_at": _updated_at(path)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/config/{name}/upload")
async def upload_config(name: str, file: UploadFile = File(...)):
    definition_or_404(name)
    filename, data = await read_upload_limited(file, fallback_name=f"{name}.csv", max_bytes=CONFIG_MAX_BYTES)

    class Upload:
        def __init__(self):
            self.name = filename
        def getvalue(self):
            return data
    try:
        frame = read_upload_table(Upload())
        with _CONFIG_WRITE_LOCK:
            normalized = validate_and_normalize_config(name, frame)
            path = _atomic_write_config(name, normalized)
            _invalidate_dashboard_cache()
        return {"ok": True, "rows": records(normalized), "updated_at": _updated_at(path)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/config/{name}/download")
def download_config(name: str):
    definition_or_404(name)
    path = config_path(name)
    if path.exists():
        data = path.read_bytes()
    else:
        data = pd.DataFrame(columns=CONFIGS[name].columns).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from dashboard.formula_engine import FormulaContext, FormulaError, evaluate_formula, extract_fields


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "configs"

METRIC_COLUMNS = ["指标名称", "显示分组", "公式", "格式", "排序", "是否启用"]
STORE_COLUMNS = ["店铺名", "店铺类型", "是否计数", "店铺所属部门"]
TARGET_COLUMNS = ["开发员", "目标业绩", "目标毛利率"]


def read_upload_table(uploaded_file, fallback_path: Path | None = None) -> pd.DataFrame:
    if uploaded_file is None:
        if fallback_path is None or not fallback_path.exists():
            return pd.DataFrame()
        return read_local_table(fallback_path)

    name = uploaded_file.name.lower()
    data = uploaded_file.getvalue()
    if name.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(data))
    return read_csv_bytes(data)


def read_local_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path)
    return read_csv_bytes(path.read_bytes())


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    last_error = None
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"CSV 编码无法识别：{last_error}")


def load_metric_config(uploaded_file=None) -> pd.DataFrame:
    df = read_upload_table(uploaded_file, CONFIG_DIR / "metrics_config.csv")
    missing = [col for col in METRIC_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"指标配置缺少列：{', '.join(missing)}")

    df = df[METRIC_COLUMNS].copy()
    df["排序"] = pd.to_numeric(df["排序"], errors="coerce").fillna(9999)
    df["是否启用"] = df["是否启用"].map(is_enabled)
    df = df[df["是否启用"]].sort_values(["显示分组", "排序", "指标名称"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("没有启用的指标")
    return df


def load_business_config(
    store_config: pd.DataFrame | None = None, target_config: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if store_config is None:
        store_config = read_upload_table(None, CONFIG_DIR / "store_config.csv")
    if target_config is None:
        target_config = read_upload_table(None, CONFIG_DIR / "monthly_targets.csv")

    return normalize_store_config(store_config), normalize_target_config(target_config)


def normalize_store_config(store_config: pd.DataFrame) -> pd.DataFrame:
    store_config = store_config.copy()
    aliases = {
        "店铺编码": "店铺名",
        "部门": "店铺所属部门",
    }
    store_config = store_config.rename(columns={old: new for old, new in aliases.items() if old in store_config.columns})

    if store_config.empty:
        store_config = pd.DataFrame(columns=STORE_COLUMNS)
    for col in STORE_COLUMNS:
        if col not in store_config.columns:
            store_config[col] = None
    store_config = store_config[STORE_COLUMNS].copy()
    store_config = store_config[store_config["店铺名"].notna()].drop_duplicates(subset=["店铺名"], keep="first")
    return store_config


def normalize_target_config(target_config: pd.DataFrame) -> pd.DataFrame:
    target_config = target_config.copy()
    aliases = {
        "销售专员": "开发员",
        "销售额目标": "目标业绩",
        "销售目标": "目标业绩",
        "毛利率目标": "目标毛利率",
        "毛利率": "目标毛利率",
    }
    target_config = target_config.rename(columns={old: new for old, new in aliases.items() if old in target_config.columns})
    if target_config.empty:
        target_config = pd.DataFrame(columns=TARGET_COLUMNS)
    for col in TARGET_COLUMNS:
        if col not in target_config.columns:
            target_config[col] = None
    target_config = target_config[TARGET_COLUMNS].copy()
    target_config = target_config[target_config["开发员"].notna()].drop_duplicates(subset=["开发员"], keep="first")
    return target_config


def load_reports(files: Iterable) -> pd.DataFrame:
    frames = []
    for file in files:
        if hasattr(file, "getvalue"):
            frame = read_csv_bytes(file.getvalue()).copy()
            frame["来源文件"] = file.name
        else:
            path = Path(file)
            frame = read_local_table(path).copy()
            frame["来源文件"] = path.name
        frames.append(frame)
    if not frames:
        raise ValueError("没有上传业绩报表")
    df = pd.concat(frames, ignore_index=True)
    required = ["销售专员", "月份", "店铺"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"业绩报表缺少基础列：{', '.join(missing)}")
    return normalize_report(df)


def normalize_report(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["月份"] = result["月份"].map(normalize_month)
    result["店铺编码"] = result["店铺"].map(extract_store_code)
    for col in result.columns:
        if col in {"销售专员", "月份", "国家", "店铺", "店铺编码", "来源文件"}:
            continue
        result[col] = maybe_numeric(result[col])
    return result


def normalize_month(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value)
    match = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if not match:
        return text
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def extract_store_code(value) -> str:
    if pd.isna(value):
        return "未识别"
    text = str(value).strip()
    match = re.search(r"^[^-]+-([A-Za-z0-9]+)", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b([A-Za-z]{2,5})\b", text)
    return match.group(1).upper() if match else text


def maybe_numeric(series: pd.Series) -> pd.Series:
    if series.dtype.kind in "biufc":
        return series
    text = series.astype(str).str.strip()
    percent_mask = text.str.endswith("%")
    cleaned = text.str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    non_empty = text.ne("").sum()
    parsed = numeric.notna().sum()
    if non_empty and parsed / non_empty >= 0.8:
        numeric.loc[percent_mask] = numeric.loc[percent_mask] / 100
        return numeric
    return series


def is_enabled(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "启用"}


def merge_business_config(df: pd.DataFrame, store_config: pd.DataFrame, target_config: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    store_config = store_config.copy()
    store_config = normalize_store_config(store_config)
    store_config["店铺编码"] = store_config["店铺名"].map(extract_store_code)
    store_config = store_config.rename(columns={"店铺所属部门": "部门"})
    if not store_config.empty:
        result = result.merge(store_config[["店铺编码", "店铺类型", "是否计数", "部门"]], on="店铺编码", how="left")

    for col in ["店铺类型", "是否计数", "部门"]:
        if col not in result.columns:
            result[col] = None
    result[["店铺类型", "是否计数", "部门"]] = result[["店铺类型", "是否计数", "部门"]].fillna("未配置")

    target_config = target_config.copy()
    target_config = normalize_target_config(target_config)
    if not target_config.empty:
        target_config = target_config.rename(
            columns={"开发员": "销售专员", "目标业绩": "销售额目标", "目标毛利率": "毛利率目标"}
        )
        target_config["销售额目标"] = maybe_numeric(target_config["销售额目标"])
        target_config["毛利率目标"] = normalize_rate(target_config["毛利率目标"])
        result = result.merge(target_config, on=["销售专员"], how="left")

    for col in ["销售额目标", "毛利率目标"]:
        if col not in result.columns:
            result[col] = pd.NA
    return result


def normalize_rate(series: pd.Series) -> pd.Series:
    numeric = maybe_numeric(series)
    if not hasattr(numeric, "where"):
        return numeric
    return numeric.where(numeric <= 1, numeric / 100)


def compute_metric_table(df: pd.DataFrame, metric_config: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if metric_config.empty:
        return pd.DataFrame()

    validate_metric_fields(df, metric_config)

    rows = []
    if group_cols:
        grouped = df.groupby(group_cols, dropna=False, sort=False)
        for keys, group in grouped:
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = dict(zip(group_cols, keys))
            row.update(compute_metrics_for_frame(group, metric_config))
            rows.append(row)
    else:
        rows.append(compute_metrics_for_frame(df, metric_config))
    return pd.DataFrame(rows)


def validate_metric_fields(df: pd.DataFrame, metric_config: pd.DataFrame) -> None:
    missing_by_metric = []
    columns = set(df.columns)
    for _, metric in metric_config.iterrows():
        missing = [field for field in extract_fields(metric["公式"]) if field not in columns]
        if missing:
            missing_by_metric.append(f"{metric['指标名称']} 缺少字段：{', '.join(missing)}")
    if missing_by_metric:
        raise FormulaError("; ".join(missing_by_metric))


def compute_metrics_for_frame(df: pd.DataFrame, metric_config: pd.DataFrame) -> dict:
    def get_field(name: str):
        if name not in df.columns:
            raise FormulaError(f"字段不存在：{name}")
        return df[name]

    def get_range_sum(start: str, end: str):
        columns = list(df.columns)
        if start not in columns:
            raise FormulaError(f"range_sum() 起始字段不存在：{start}")
        if end not in columns:
            raise FormulaError(f"range_sum() 结束字段不存在：{end}")
        start_idx = columns.index(start)
        end_idx = columns.index(end)
        if start_idx > end_idx:
            raise FormulaError(f"range_sum() 起始字段不能在结束字段之后：{start} > {end}")
        numeric_range = df.loc[:, columns[start_idx : end_idx + 1]].apply(pd.to_numeric, errors="coerce")
        return numeric_range.sum().sum()

    context = FormulaContext(field_getter=get_field, range_sum_getter=get_range_sum)
    row = {}
    for _, metric in metric_config.iterrows():
        value = evaluate_formula(metric["公式"], context)
        if isinstance(value, pd.Series):
            value = pd.to_numeric(value, errors="coerce").sum()
        row[metric["指标名称"]] = value
    return row


def format_display_table(df: pd.DataFrame, metric_lookup: dict) -> pd.DataFrame:
    result = df.copy()
    for col in result.columns:
        fmt = metric_lookup.get(col, {}).get("格式")
        if not fmt:
            continue
        if fmt == "金额":
            result[col] = result[col].map(lambda value: format_number(value, ",.2f"))
        elif fmt == "整数":
            result[col] = result[col].map(lambda value: format_number(value, ",.0f"))
        elif fmt == "百分比":
            result[col] = result[col].map(lambda value: "-" if pd.isna(value) else f"{float(value):.2%}")
        else:
            result[col] = result[col].map(lambda value: format_number(value, ",.2f"))
    return result


def format_number(value, pattern: str) -> str:
    if pd.isna(value):
        return "-"
    try:
        return format(float(value), pattern)
    except (TypeError, ValueError):
        return str(value)


def build_alerts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    alert_rows = []
    for _, row in df.iterrows():
        reasons = []
        if "毛利率" in row and pd.notna(row["毛利率"]) and row["毛利率"] < 0.15:
            reasons.append("毛利率低于 15%")
        if "广告费占比" in row and pd.notna(row["广告费占比"]) and row["广告费占比"] > 0.1:
            reasons.append("广告费占比高于 10%")
        if "目标完成率" in row and pd.notna(row["目标完成率"]) and row["目标完成率"] < 0.9:
            reasons.append("目标完成率低于 90%")
        if reasons:
            item = row.to_dict()
            item["预警原因"] = "；".join(reasons)
            alert_rows.append(item)
    return pd.DataFrame(alert_rows)

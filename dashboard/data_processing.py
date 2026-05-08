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
STORE_COLUMNS = ["店铺名", "店铺类型", "停提款时间", "店铺所属部门"]
TARGET_COLUMNS = ["开发员", "目标业绩", "目标毛利率"]
COMMISSION_COLUMNS = ["月份", "开发员", "库存计提", "弃置", "职位提点"]
DEPARTMENT_FEE_COLUMNS = ["月份", "部门", "费用率"]
OPERATIONAL_SALES_REQUIRED_COLUMNS = [
    "MSKU",
    "店铺名称",
    "7天销量",
    "30天销量",
    "可售",
    "本地库存",
    "昨天销量",
    "前天销量",
    "上前销量",
    "开发员",
    "ASIN",
]
OPERATIONAL_SALES_NUMERIC_COLUMNS = ["7天销量", "30天销量", "可售", "本地库存", "昨天销量", "前天销量", "上前销量"]
OPERATIONAL_SALES_NORMALIZED_COLUMNS = OPERATIONAL_SALES_REQUIRED_COLUMNS + [
    "店铺编码",
    "店铺名称原始",
    "店铺名称展开",
    "店铺类型推断",
    "是否多店铺编码",
    "30天日均",
    "7天日均",
    "是否在售",
    "是否-26",
]
PRODUCT_LEVELS = [
    ("0单", lambda value: value == 0),
    ("0.2单以下", lambda value: 0 < value <= 0.2),
    ("0.2-0.5单", lambda value: 0.2 < value <= 0.5),
    ("0.5-1单", lambda value: 0.5 < value <= 1),
    ("1-2单", lambda value: 1 < value <= 2),
    ("2-3单", lambda value: 2 < value <= 3),
    ("3-5单", lambda value: 3 < value <= 5),
    ("5单以上", lambda value: value > 5),
]
COMMISSION_OUTPUT_COLUMNS = [
    "月份",
    "开发员",
    "营业额",
    "毛利润",
    "毛利率",
    "费用率",
    "库存计提",
    "弃置",
    "职位提点",
    "提成预估",
    "配置状态",
]
STOPPED_COMMISSION_OUTPUT_COLUMNS = [
    "月份",
    "开发员",
    "店铺编码",
    "店铺类型",
    "部门",
    "停提款时间",
    "营业额",
    "毛利润",
    "毛利率",
    "费用率",
    "库存计提分摊",
    "弃置分摊",
    "职位提点",
    "缺提成预估",
    "配置状态",
]


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


def load_commission_config(uploaded_file=None) -> pd.DataFrame:
    return normalize_commission_config(read_upload_table(uploaded_file, CONFIG_DIR / "commission_config.csv"))


def load_department_fee_config(uploaded_file=None) -> pd.DataFrame:
    return normalize_department_fee_config(read_upload_table(uploaded_file, CONFIG_DIR / "department_fee_config.csv"))


def load_operational_sales_source(path_or_file) -> pd.DataFrame:
    return normalize_operational_sales(read_upload_table(path_or_file) if hasattr(path_or_file, "getvalue") else read_local_table(Path(path_or_file)))


def normalize_store_config(store_config: pd.DataFrame) -> pd.DataFrame:
    store_config = store_config.copy()
    aliases = {
        "店铺编码": "店铺名",
        "部门": "店铺所属部门",
        "停提款月份": "停提款时间",
    }
    store_config = store_config.rename(columns={old: new for old, new in aliases.items() if old in store_config.columns})

    if store_config.empty:
        store_config = pd.DataFrame(columns=STORE_COLUMNS)
    for col in STORE_COLUMNS:
        if col not in store_config.columns:
            store_config[col] = None
    store_config = store_config[STORE_COLUMNS].copy()
    store_config["停提款时间"] = store_config["停提款时间"].map(normalize_config_month).fillna("")
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


def normalize_commission_config(commission_config: pd.DataFrame) -> pd.DataFrame:
    commission_config = commission_config.copy()
    aliases = {
        "销售专员": "开发员",
        "月份": "月份",
        "库存": "库存计提",
        "提点": "职位提点",
        "职位提成点": "职位提点",
    }
    commission_config = commission_config.rename(
        columns={old: new for old, new in aliases.items() if old in commission_config.columns}
    )
    if commission_config.empty:
        commission_config = pd.DataFrame(columns=COMMISSION_COLUMNS)
    for col in COMMISSION_COLUMNS:
        if col not in commission_config.columns:
            commission_config[col] = None
    commission_config = commission_config[COMMISSION_COLUMNS].copy()
    commission_config["月份"] = commission_config["月份"].map(normalize_month)
    commission_config = commission_config[
        commission_config["月份"].notna() & commission_config["开发员"].notna()
    ].drop_duplicates(subset=["月份", "开发员"], keep="first")
    commission_config["职位提点"] = normalize_rate(commission_config["职位提点"])
    commission_config["库存计提"] = normalize_config_number(commission_config["库存计提"])
    commission_config["弃置"] = normalize_config_number(commission_config["弃置"])
    return commission_config.reset_index(drop=True)


def normalize_department_fee_config(department_fee_config: pd.DataFrame) -> pd.DataFrame:
    department_fee_config = department_fee_config.copy()
    aliases = {
        "店铺所属部门": "部门",
        "费用部门": "部门",
        "费率": "费用率",
    }
    department_fee_config = department_fee_config.rename(
        columns={old: new for old, new in aliases.items() if old in department_fee_config.columns}
    )
    if department_fee_config.empty:
        department_fee_config = pd.DataFrame(columns=DEPARTMENT_FEE_COLUMNS)
    for col in DEPARTMENT_FEE_COLUMNS:
        if col not in department_fee_config.columns:
            department_fee_config[col] = None
    department_fee_config = department_fee_config[DEPARTMENT_FEE_COLUMNS].copy()
    department_fee_config["月份"] = department_fee_config["月份"].map(normalize_month)
    department_fee_config = department_fee_config[
        department_fee_config["月份"].notna() & department_fee_config["部门"].notna()
    ].drop_duplicates(subset=["月份", "部门"], keep="first")
    department_fee_config["费用率"] = normalize_rate(department_fee_config["费用率"])
    return department_fee_config.reset_index(drop=True)


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
    text = text.strip()
    if not text:
        return None
    chinese_match = re.search(r"(\d{2,4})\s*年\s*(\d{1,2})\s*月", text)
    if chinese_match:
        year = int(chinese_match.group(1))
        if year < 100:
            year += 2000
        return f"{year:04d}-{int(chinese_match.group(2)):02d}"
    match = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if not match:
        return text
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def normalize_config_month(value) -> str | None:
    normalized = normalize_month(value)
    if normalized is None:
        return None
    return normalized if re.fullmatch(r"\d{4}-\d{2}", str(normalized)) else None


def extract_store_code(value) -> str:
    if pd.isna(value):
        return "未识别"
    text = str(value).strip()
    match = re.search(r"^[^-]+-([A-Za-z0-9]+)", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b([A-Za-z]{2,5})\b", text)
    return match.group(1).upper() if match else text


def extract_operational_store_codes(value) -> list[tuple[str, str]]:
    if pd.isna(value):
        return [("未识别", "")]
    text = str(value).strip()
    if not text:
        return [("未识别", "")]

    stores = []
    seen = set()
    for item in [part.strip() for part in text.split(",") if part.strip()]:
        code = extract_store_code(item)
        if code not in seen:
            stores.append((code, item))
            seen.add(code)
    return stores or [("未识别", text)]


def infer_operational_store_type(store_name: str) -> str:
    return "本土" if "本土" in str(store_name) else "中企"


def normalize_operational_sales(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in OPERATIONAL_SALES_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少列：{', '.join(missing)}")

    base = df[OPERATIONAL_SALES_REQUIRED_COLUMNS].copy()
    for col in ["MSKU", "店铺名称", "开发员", "ASIN"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    for col in OPERATIONAL_SALES_NUMERIC_COLUMNS:
        base[col] = normalize_config_number(base[col]).fillna(0)

    rows = []
    for _, row in base.iterrows():
        stores = extract_operational_store_codes(row["店铺名称"])
        is_multi_store_code = len(stores) > 1
        for store_code, store_name in stores:
            item = row.to_dict()
            item["店铺编码"] = store_code
            item["店铺名称原始"] = row["店铺名称"]
            item["店铺名称展开"] = store_name
            item["店铺类型推断"] = infer_operational_store_type(store_name)
            item["是否多店铺编码"] = is_multi_store_code
            item["30天日均"] = item["30天销量"] / 30
            item["7天日均"] = item["7天销量"] / 7
            item["是否在售"] = item["可售"] > 0
            item["是否-26"] = str(item["开发员"]).strip().endswith("-26")
            rows.append(item)
    if not rows:
        return pd.DataFrame(columns=OPERATIONAL_SALES_NORMALIZED_COLUMNS)
    return pd.DataFrame(rows)


def ensure_operational_sales_normalized(df: pd.DataFrame) -> pd.DataFrame:
    if all(col in df.columns for col in OPERATIONAL_SALES_NORMALIZED_COLUMNS):
        return df.copy()
    return normalize_operational_sales(df)


def merge_operational_store_config(df: pd.DataFrame, store_config: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    config = normalize_store_config(store_config).copy()
    if not config.empty:
        config["店铺编码"] = config["店铺名"].map(extract_store_code)
        config = config.drop_duplicates(subset=["店铺编码"], keep="first")
        result = result.merge(config[["店铺编码", "店铺类型"]], on="店铺编码", how="left")
    if "店铺类型" not in result.columns:
        result["店铺类型"] = pd.NA
    result["店铺类型"] = result["店铺类型"].where(result["店铺类型"].notna() & result["店铺类型"].astype(str).str.strip().ne(""), result["店铺类型推断"])
    return result


def safe_ratio(numerator, denominator):
    return numerator / denominator if denominator else 0


def product_level_for_daily_sales(value: float) -> str:
    for label, predicate in PRODUCT_LEVELS:
        if predicate(value):
            return label
    return "未分档"


def build_sales_dashboard_tables(df: pd.DataFrame, store_config: pd.DataFrame) -> dict[str, pd.DataFrame]:
    data = merge_operational_store_config(ensure_operational_sales_normalized(df), store_config)
    if data.empty:
        empty = pd.DataFrame()
        return {"stores": empty, "levels": empty, "date_compare": empty, "type_compare": empty, "source": data}

    store_order = []
    if store_config is not None and not store_config.empty:
        store_order = normalize_store_config(store_config)["店铺名"].map(extract_store_code).dropna().drop_duplicates().tolist()

    data["产品等级"] = data["30天日均"].map(product_level_for_daily_sales)
    total_onsale = data["是否在售"].sum()
    total_30_avg = data["30天日均"].sum()

    store_summary = (
        data.groupby(["店铺编码", "店铺类型"], dropna=False, as_index=False)
        .agg(
            在售个数=("是否在售", "sum"),
            昨日订单=("昨天销量", "sum"),
            前天订单=("前天销量", "sum"),
            上前订单=("上前销量", "sum"),
            **{"-26订单": ("昨天销量", lambda values: values[data.loc[values.index, "是否-26"]].sum())},
            **{"7天日均": ("7天日均", "sum")},
            **{"30天日均": ("30天日均", "sum")},
            总库存=("可售", "sum"),
        )
    )
    store_summary["产品数占比"] = store_summary["在售个数"].map(lambda value: safe_ratio(value, total_onsale))
    store_summary["昨日D值"] = store_summary.apply(lambda row: safe_ratio(row["昨日订单"], row["在售个数"]), axis=1)
    store_summary["7天D值"] = store_summary.apply(lambda row: safe_ratio(row["7天日均"], row["在售个数"]), axis=1)
    order_lookup = {code: idx for idx, code in enumerate(store_order)}
    store_summary["_排序"] = store_summary["店铺编码"].map(order_lookup).fillna(len(order_lookup) + 999)
    store_summary = store_summary.sort_values(["_排序", "店铺编码"]).drop(columns=["_排序"]).reset_index(drop=True)
    store_summary = store_summary[
        ["店铺编码", "店铺类型", "在售个数", "产品数占比", "昨日D值", "7天D值", "昨日订单", "-26订单", "7天日均", "30天日均", "总库存"]
    ]

    level_summary = (
        data.groupby("产品等级", dropna=False, as_index=False)
        .agg(
            在售个数=("是否在售", "sum"),
            昨日订单=("昨天销量", "sum"),
            **{"7天日均": ("7天日均", "sum")},
            **{"30天日均": ("30天日均", "sum")},
        )
    )
    level_summary = pd.DataFrame({"产品等级": [label for label, _ in PRODUCT_LEVELS]}).merge(
        level_summary, on="产品等级", how="left"
    )
    for col in ["在售个数", "昨日订单", "7天日均", "30天日均"]:
        level_summary[col] = level_summary[col].fillna(0)
    level_order = {label: idx for idx, (label, _) in enumerate(PRODUCT_LEVELS)}
    level_summary["_排序"] = level_summary["产品等级"].map(level_order).fillna(999)
    level_summary["产品数占比"] = level_summary["在售个数"].map(lambda value: safe_ratio(value, total_onsale))
    level_summary["30天贡献占比"] = level_summary["30天日均"].map(lambda value: safe_ratio(value, total_30_avg))
    level_summary = level_summary.sort_values("_排序").drop(columns=["_排序"]).reset_index(drop=True)
    total_row = {
        "产品等级": "总计",
        "在售个数": level_summary["在售个数"].sum(),
        "产品数占比": safe_ratio(level_summary["在售个数"].sum(), total_onsale),
        "昨日订单": level_summary["昨日订单"].sum(),
        "7天日均": level_summary["7天日均"].sum(),
        "30天日均": level_summary["30天日均"].sum(),
        "30天贡献占比": safe_ratio(level_summary["30天日均"].sum(), total_30_avg),
    }
    level_summary = pd.concat([level_summary, pd.DataFrame([total_row])], ignore_index=True)
    level_summary = level_summary[["产品等级", "在售个数", "产品数占比", "昨日订单", "7天日均", "30天日均", "30天贡献占比"]]

    type_compare = (
        data.groupby("店铺类型", dropna=False, as_index=False)
        .agg(
            昨天=("昨天销量", "sum"),
            前天=("前天销量", "sum"),
            上前=("上前销量", "sum"),
            **{"7天": ("7天日均", "sum")},
            **{"30天": ("30天日均", "sum")},
        )
        .set_index("店铺类型")
    )
    date_compare = pd.DataFrame(
        [
            {"日期": "昨天", "中企单量": type_compare["昨天"].get("中企", 0), "本土单量": type_compare["昨天"].get("本土", 0)},
            {"日期": "前天", "中企单量": type_compare["前天"].get("中企", 0), "本土单量": type_compare["前天"].get("本土", 0)},
            {"日期": "上前", "中企单量": type_compare["上前"].get("中企", 0), "本土单量": type_compare["上前"].get("本土", 0)},
            {"日期": "7天", "中企单量": type_compare["7天"].get("中企", 0), "本土单量": type_compare["7天"].get("本土", 0)},
            {"日期": "30天", "中企单量": type_compare["30天"].get("中企", 0), "本土单量": type_compare["30天"].get("本土", 0)},
        ]
    )
    date_compare["总计"] = date_compare["中企单量"] + date_compare["本土单量"]

    return {
        "stores": store_summary,
        "levels": level_summary,
        "date_compare": date_compare,
        "source": data,
    }


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
        result = result.merge(store_config[["店铺编码", "店铺类型", "停提款时间", "部门"]], on="店铺编码", how="left")

    for col in ["店铺类型", "停提款时间", "部门"]:
        if col not in result.columns:
            result[col] = None
    result[["店铺类型", "部门"]] = result[["店铺类型", "部门"]].fillna("未配置")
    result["停提款时间"] = result["停提款时间"].fillna("").map(lambda value: normalize_month(value) or "")
    result["是否停提款数据"] = result.apply(
        lambda row: bool(row["停提款时间"]) and str(row["月份"]) >= str(row["停提款时间"]),
        axis=1,
    )

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


def split_counted_and_stopped_data(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data.empty:
        return data.copy(), data.copy()
    if "是否停提款数据" not in data.columns:
        return data.copy(), data.iloc[0:0].copy()
    stopped_mask = data["是否停提款数据"].fillna(False).astype(bool)
    return data[~stopped_mask].copy(), data[stopped_mask].copy()


def normalize_rate(series: pd.Series) -> pd.Series:
    numeric = normalize_config_number(series, percent_to_decimal=True)
    return numeric.where(numeric <= 1, numeric / 100)


def normalize_config_number(series: pd.Series, percent_to_decimal: bool = False) -> pd.Series:
    text = series.astype(str).str.strip()
    text = text.mask(text.isin(["", "nan", "None", "NaN"]))
    percent_mask = text.str.endswith("%", na=False)
    cleaned = text.str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    if percent_to_decimal:
        numeric.loc[percent_mask] = numeric.loc[percent_mask] / 100
    return numeric


def build_discovered_commission_config(reports: pd.DataFrame | None) -> pd.DataFrame:
    if reports is None or reports.empty:
        return normalize_commission_config(pd.DataFrame()).fillna("")
    commission = (
        reports[["月份", "销售专员"]]
        .dropna()
        .drop_duplicates()
        .rename(columns={"销售专员": "开发员"})
        .sort_values(["月份", "开发员"])
    )
    commission["库存计提"] = ""
    commission["弃置"] = ""
    commission["职位提点"] = ""
    return normalize_commission_config(commission).fillna("")


def build_discovered_department_fee_config(reports: pd.DataFrame | None) -> pd.DataFrame:
    if reports is None or reports.empty or "部门" not in reports.columns:
        return normalize_department_fee_config(pd.DataFrame()).fillna("")
    fee_config = (
        reports[["月份", "部门"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["月份", "部门"])
    )
    fee_config["费用率"] = ""
    return normalize_department_fee_config(fee_config).fillna("")


def select_metric_config(metric_config: pd.DataFrame, metric_names: list[str]) -> pd.DataFrame:
    if metric_config.empty:
        raise ValueError("指标配置为空，无法计算提成")
    group_rank = {"开发员分析": 0, "总览": 1, "全部": 2, "趋势": 3, "店铺分析": 4, "开发员店铺分析": 5}
    selected = metric_config[metric_config["指标名称"].isin(metric_names)].copy()
    selected["_metric_order"] = selected["指标名称"].map({name: idx for idx, name in enumerate(metric_names)})
    selected["_group_rank"] = selected["显示分组"].map(group_rank).fillna(99)
    selected = selected.sort_values(["_metric_order", "_group_rank"]).drop_duplicates("指标名称", keep="first")
    missing = [name for name in metric_names if name not in set(selected["指标名称"])]
    if missing:
        raise ValueError(f"提成计算缺少指标公式：{', '.join(missing)}")
    return selected.drop(columns=["_metric_order", "_group_rank"])


def compute_commission_table(
    df: pd.DataFrame,
    metric_config: pd.DataFrame,
    commission_config: pd.DataFrame,
    department_fee_config: pd.DataFrame,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=COMMISSION_OUTPUT_COLUMNS)

    metrics = select_metric_config(metric_config, ["销售额", "毛利润", "毛利率"])
    base = compute_metric_table(df, metrics, ["月份", "销售专员", "部门"]).rename(
        columns={"销售专员": "开发员", "销售额": "营业额"}
    )
    if base.empty:
        return pd.DataFrame(columns=COMMISSION_OUTPUT_COLUMNS)

    fee_config = normalize_department_fee_config(department_fee_config).copy()
    fee_config["__has_department_fee_config"] = True
    base = base.merge(fee_config, on=["月份", "部门"], how="left")
    if "__has_department_fee_config" not in base.columns:
        base["__has_department_fee_config"] = False
    base["__has_department_fee_config"] = base["__has_department_fee_config"].fillna(False)
    base["__部门费用额"] = base["营业额"] * base["费用率"]
    base["__部门提成前利润"] = base["营业额"] * (base["毛利率"] - base["费用率"])

    has_department_fee = base["__has_department_fee_config"].fillna(False).astype(bool) & base["费用率"].notna()
    dept_missing = (
        base[~has_department_fee]
        .groupby(["月份", "开发员"], dropna=False)
        .size()
        .rename("__缺部门费用率数")
        .reset_index()
    )
    base_summary = (
        base.groupby(["月份", "开发员"], dropna=False, as_index=False)
        .agg(
            营业额=("营业额", "sum"),
            毛利润=("毛利润", "sum"),
            __部门费用额=("__部门费用额", "sum"),
            __部门提成前利润=("__部门提成前利润", "sum"),
        )
        .merge(dept_missing, on=["月份", "开发员"], how="left")
    )
    base_summary["__缺部门费用率数"] = base_summary["__缺部门费用率数"].fillna(0)
    base_summary["毛利率"] = base_summary.apply(
        lambda row: row["毛利润"] / row["营业额"] if pd.notna(row["营业额"]) and row["营业额"] else pd.NA,
        axis=1,
    )
    base_summary["费用率"] = base_summary.apply(
        lambda row: row["__部门费用额"] / row["营业额"] if pd.notna(row["营业额"]) and row["营业额"] else pd.NA,
        axis=1,
    )

    config = normalize_commission_config(commission_config).copy()
    config["__has_commission_config"] = True
    merged = base_summary.merge(config, on=["月份", "开发员"], how="left")
    if "__has_commission_config" not in merged.columns:
        merged["__has_commission_config"] = False
    merged["__has_commission_config"] = merged["__has_commission_config"].fillna(False)

    param_cols = ["库存计提", "弃置", "职位提点"]
    has_all_params = (
        merged["__has_commission_config"]
        & merged[param_cols].notna().all(axis=1)
        & merged["__缺部门费用率数"].eq(0)
    )
    merged["配置状态"] = has_all_params.map(lambda value: "已配置" if value else "缺配置")
    merged["提成预估"] = pd.NA
    merged.loc[has_all_params, "提成预估"] = (
        (merged.loc[has_all_params, "__部门提成前利润"] - merged.loc[has_all_params, "库存计提"] - merged.loc[has_all_params, "弃置"])
        * merged.loc[has_all_params, "职位提点"]
    )
    return merged[COMMISSION_OUTPUT_COLUMNS].sort_values(["月份", "开发员"]).reset_index(drop=True)


def compute_stopped_commission_table(
    df: pd.DataFrame,
    metric_config: pd.DataFrame,
    commission_config: pd.DataFrame,
    department_fee_config: pd.DataFrame,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=STOPPED_COMMISSION_OUTPUT_COLUMNS)

    metrics = select_metric_config(metric_config, ["销售额", "毛利润", "毛利率"])
    group_cols = ["月份", "销售专员", "店铺编码", "店铺类型", "部门", "停提款时间"]
    base = compute_metric_table(df, metrics, group_cols).rename(
        columns={"销售专员": "开发员", "销售额": "营业额"}
    )
    if base.empty:
        return pd.DataFrame(columns=STOPPED_COMMISSION_OUTPUT_COLUMNS)

    fee_config = normalize_department_fee_config(department_fee_config).copy()
    fee_config["__has_department_fee_config"] = True
    base = base.merge(fee_config, on=["月份", "部门"], how="left")
    if "__has_department_fee_config" not in base.columns:
        base["__has_department_fee_config"] = False
    base["__has_department_fee_config"] = base["__has_department_fee_config"].fillna(False)

    config = normalize_commission_config(commission_config).copy()
    config["__has_commission_config"] = True
    merged = base.merge(config, on=["月份", "开发员"], how="left")
    if "__has_commission_config" not in merged.columns:
        merged["__has_commission_config"] = False
    merged["__has_commission_config"] = merged["__has_commission_config"].fillna(False)

    merged["__月开发员停提款营业额"] = merged.groupby(["月份", "开发员"])["营业额"].transform("sum")
    merged["__分摊比例"] = merged.apply(
        lambda row: row["营业额"] / row["__月开发员停提款营业额"] if row["__月开发员停提款营业额"] else 0,
        axis=1,
    )
    merged["库存计提分摊"] = merged["库存计提"] * merged["__分摊比例"]
    merged["弃置分摊"] = merged["弃置"] * merged["__分摊比例"]

    param_cols = ["库存计提", "弃置", "职位提点"]
    has_all_params = (
        merged["__has_commission_config"]
        & merged[param_cols].notna().all(axis=1)
        & merged["__has_department_fee_config"].fillna(False).astype(bool)
        & merged["费用率"].notna()
    )
    merged["配置状态"] = has_all_params.map(lambda value: "已配置" if value else "缺配置")
    merged["缺提成预估"] = pd.NA
    merged.loc[has_all_params, "缺提成预估"] = (
        (
            merged.loc[has_all_params, "营业额"] * (merged.loc[has_all_params, "毛利率"] - merged.loc[has_all_params, "费用率"])
            - merged.loc[has_all_params, "库存计提分摊"]
            - merged.loc[has_all_params, "弃置分摊"]
        )
        * merged.loc[has_all_params, "职位提点"]
    )
    return merged[STOPPED_COMMISSION_OUTPUT_COLUMNS].sort_values(["月份", "开发员", "店铺编码"]).reset_index(drop=True)


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

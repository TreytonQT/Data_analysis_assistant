from __future__ import annotations

import io
import calendar
import re
import unicodedata
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
REPLENISHMENT_TARGET_COLUMNS = ["ASIN", "目标可售天数"]
DEFAULT_REPLENISHMENT_TARGET_DAYS = 70
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
OPERATIONAL_SALES_NUMERIC_COLUMNS = [
    "7天销量",
    "30天销量",
    "可售",
    "本地库存",
    "昨天销量",
    "前天销量",
    "上前销量",
]
OPERATIONAL_SALES_DERIVED_COLUMNS = ["占用资金"]
OPERATIONAL_SALES_NORMALIZED_COLUMNS = OPERATIONAL_SALES_REQUIRED_COLUMNS + OPERATIONAL_SALES_DERIVED_COLUMNS + [
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
AGING_STOCK_COLUMNS = [
    "91-180天库存数",
    "181-330天库存数",
    "331-365天库存数",
    "366-455天库存数",
    "456天以上库存数",
]
AGING_CAPITAL_COLUMNS = [
    "91-180天占用资金",
    "181-330天占用资金",
    "331-365天占用资金",
    "366-455天占用资金",
    "456天占用资金",
]
OPERATIONAL_AGING_REQUIRED_COLUMNS = ["MSKU", "开发员", "ASIN"] + AGING_STOCK_COLUMNS + AGING_CAPITAL_COLUMNS
REPLENISHMENT_STOCK_COMPONENT_COLUMNS = ["可售", "待入库", "采购在途", "本地库存", "在途", "计划入库"]
AVAILABLE_INVENTORY_STOCK_COLUMNS = [
    "可售",
    "待调仓",
    "调仓中",
    "待入库",
    "采购在途",
    "本地库存",
    "在途",
    "计划入库",
]
AVAILABLE_INVENTORY_REQUIRED_COLUMNS = ["开发员", "日均销量"] + AVAILABLE_INVENTORY_STOCK_COLUMNS
AVAILABLE_INVENTORY_SUMMARY_COLUMNS = ["开发员"] + AVAILABLE_INVENTORY_STOCK_COLUMNS + [
    "库存总数",
    "日均单量",
    "总可售天数",
]
AVAILABLE_INVENTORY_MONITOR_COLUMNS = ["开发员", "库存总数", "日均订单", "总可售天数"]
SALES_VOLUME_DETAIL_REQUIRED_COLUMNS = ["msku", "店铺", "开发专员"]
SALES_AMOUNT_DETAIL_REQUIRED_COLUMNS = ["msku", "店铺", "开发专员"]
DEPARTMENT_PERFORMANCE_FIXED_COLUMNS = [
    "开发员",
    "在售产品数",
    "销售额贡献占比",
    "近7天日均订单",
    "近7天日均销售额（元）",
    "预估本月销售额（元）",
]
DEPARTMENT_PERFORMANCE_BOARDS = [
    ("运营20部", "20"),
    ("联合部门", "union"),
    ("人员业绩贡献总计", "all"),
]
REPLENISHMENT_OPERATIONAL_REQUIRED_COLUMNS = [
    "ASIN",
    "MSKU",
    "店铺名称",
    "开发员",
    "日均销量",
    "单品重量(g)",
] + REPLENISHMENT_STOCK_COMPONENT_COLUMNS + AGING_STOCK_COLUMNS
DISCARD_THRESHOLD_SEGMENTS = {
    "90天以上": ["91-180", "181-330", "331-365", "366-455", "456天以上"],
    "180天以上": ["181-330", "331-365", "366-455", "456天以上"],
    "365天以上": ["366-455", "456天以上"],
}
PRODUCT_COUNTRIES = ["德国", "法国", "西班牙", "意大利"]
PRODUCT_OPERATIONAL_REQUIRED_COLUMNS = [
    "ASIN",
    "MSKU",
    "可售",
    "可售天数",
    "日均销量",
    "昨天销量",
    "前天销量",
    "上前销量",
    "7天销量",
    "14天销量",
    "30天销量",
    "90天销量",
]
PRODUCT_OPERATIONAL_SUM_COLUMNS = [
    "可售数量",
    "日均销量",
    "昨天销量",
    "前天销量",
    "上前销量",
    "7天销量",
    "14天销量",
    "30天销量",
    "90天销量",
]
GROSS_PROFIT_VOLUME_COLUMNS = ["销量--FBA销量", "销量--FBM销量", "销量--多渠道销量"]
REPLENISHMENT_GROSS_RATIO_COLUMNS = ["广告费占比", "退款占比", "FBA发货费占比"]
REPLENISHMENT_GROSS_REQUIRED_COLUMNS = [
    "ASIN",
    "MSKU",
    "国家",
    "销售额--FBA销售额",
    "COD",
    "毛利润",
] + GROSS_PROFIT_VOLUME_COLUMNS + REPLENISHMENT_GROSS_RATIO_COLUMNS
GROSS_PROFIT_AD_COLUMNS = [
    "广告费-SD广告",
    "广告费-SP广告",
    "广告费-SB广告",
    "广告费-SBV广告",
    "广告费--差异分摊",
]
GROSS_PROFIT_REQUIRED_COLUMNS = [
    "ASIN",
    "MSKU",
    "国家",
    "销售额--FBA销售额",
    "COD",
    "毛利润",
] + GROSS_PROFIT_VOLUME_COLUMNS + GROSS_PROFIT_AD_COLUMNS
RATING_REQUIRED_COLUMNS = ["ASIN", "国家", "Rating总数", "评分"]
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
LOW_MARGIN_PRODUCT_THRESHOLD = 0.15
LOW_MARGIN_PRODUCT_MIN_SALES = 5
LOW_MARGIN_PRODUCT_COLUMNS = ["SKU", "ASIN", "国家", "开发员", "销量", "销售额", "毛利润", "毛利率"]
GROSS_PROFIT_DEVELOPER_COLUMNS = ["开发员", "开发人员", "销售专员", "销售"]
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
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(data), engine="xlrd", engine_kwargs={"ignore_workbook_corruption": True})
    return read_csv_bytes(data)


def read_local_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path)
    if path.suffix.lower() == ".xls":
        return pd.read_excel(path, engine="xlrd", engine_kwargs={"ignore_workbook_corruption": True})
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
    capital_cols = operational_sales_capital_columns(df)
    for col in capital_cols:
        base[col] = normalize_config_number(df[col]).fillna(0)
    base["占用资金"] = base[capital_cols].sum(axis=1) if capital_cols else 0
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


def operational_sales_capital_columns(df: pd.DataFrame) -> list[str]:
    return [
        col
        for col in df.columns
        if re.fullmatch(r"\d+(?:-\d+)?天(?:以上)?占用资金", str(col).strip())
    ]


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
            占用资金=("占用资金", "sum"),
        )
    )
    store_summary["产品数占比"] = store_summary["在售个数"].map(lambda value: safe_ratio(value, total_onsale))
    store_summary["昨日D值"] = store_summary.apply(lambda row: safe_ratio(row["昨日订单"], row["在售个数"]), axis=1)
    store_summary["7天D值"] = store_summary.apply(lambda row: safe_ratio(row["7天日均"], row["在售个数"]), axis=1)
    order_lookup = {code: idx for idx, code in enumerate(store_order)}
    store_summary["_排序"] = store_summary["店铺编码"].map(order_lookup).fillna(len(order_lookup) + 999)
    store_summary = store_summary.sort_values(["_排序", "店铺编码"]).drop(columns=["_排序"]).reset_index(drop=True)
    store_summary = store_summary[
        [
            "店铺编码",
            "店铺类型",
            "在售个数",
            "产品数占比",
            "昨日D值",
            "7天D值",
            "昨日订单",
            "-26订单",
            "7天日均",
            "30天日均",
            "总库存",
            "占用资金",
        ]
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


def normalize_operational_aging(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in OPERATIONAL_AGING_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少库龄列：{', '.join(missing)}")

    result = df[OPERATIONAL_AGING_REQUIRED_COLUMNS].copy()
    for col in ["MSKU", "开发员", "ASIN"]:
        result[col] = result[col].fillna("").astype(str).str.strip()
    for col in AGING_STOCK_COLUMNS + AGING_CAPITAL_COLUMNS:
        result[col] = normalize_config_number(result[col]).fillna(0)
    return result


def build_slow_moving_inventory_table(df: pd.DataFrame, discard_threshold: str = "90天以上") -> pd.DataFrame:
    if discard_threshold not in DISCARD_THRESHOLD_SEGMENTS:
        raise ValueError(f"未知弃置费阈值：{discard_threshold}")

    data = normalize_operational_aging(df)
    if data.empty:
        return pd.DataFrame()

    agg = {col: (col, "sum") for col in AGING_STOCK_COLUMNS + AGING_CAPITAL_COLUMNS}
    base = data.groupby("MSKU", dropna=False, as_index=False).agg(
        开发员=("开发员", lambda values: "；".join(sorted({str(value) for value in values if str(value).strip()}))),
        ASIN=("ASIN", lambda values: "；".join(sorted({str(value) for value in values if str(value).strip()}))),
        **agg,
    )

    stock_90_plus = base[AGING_STOCK_COLUMNS].sum(axis=1)
    capital_90_plus = base[AGING_CAPITAL_COLUMNS].sum(axis=1)
    base = base[stock_90_plus.gt(0)].copy()
    if base.empty:
        return pd.DataFrame(columns=slow_moving_inventory_columns())

    base["90天以上库存数合计"] = base[AGING_STOCK_COLUMNS].sum(axis=1)
    base["90天以上占用资金合计"] = base[AGING_CAPITAL_COLUMNS].sum(axis=1)
    base["库存计提"] = (
        base["91-180天占用资金"] * 0.05
        + (base["181-330天占用资金"] + base["331-365天占用资金"]) * 0.08
        + (base["366-455天占用资金"] + base["456天占用资金"]) * 0.12
    )

    segment_to_stock = {
        "91-180": "91-180天库存数",
        "181-330": "181-330天库存数",
        "331-365": "331-365天库存数",
        "366-455": "366-455天库存数",
        "456天以上": "456天以上库存数",
    }
    segment_to_capital = {
        "91-180": "91-180天占用资金",
        "181-330": "181-330天占用资金",
        "331-365": "331-365天占用资金",
        "366-455": "366-455天占用资金",
        "456天以上": "456天占用资金",
    }
    segments = DISCARD_THRESHOLD_SEGMENTS[discard_threshold]
    discard_stock = base[[segment_to_stock[segment] for segment in segments]].sum(axis=1)
    discard_capital = base[[segment_to_capital[segment] for segment in segments]].sum(axis=1)
    base["弃置费"] = discard_stock * 6 + discard_capital * 1.5

    base = base.rename(columns={"MSKU": "SKU"})
    return base[slow_moving_inventory_columns()].sort_values("90天以上占用资金合计", ascending=False).reset_index(drop=True)


def slow_moving_inventory_columns() -> list[str]:
    return [
        "SKU",
        "开发员",
        "ASIN",
        "90天以上库存数合计",
        "90天以上占用资金合计",
        "库存计提",
        "弃置费",
        "91-180天库存数",
        "181-330天库存数",
        "331-365天库存数",
        "366-455天库存数",
        "456天以上库存数",
        "91-180天占用资金",
        "181-330天占用资金",
        "331-365天占用资金",
        "366-455天占用资金",
        "456天占用资金",
    ]


def normalize_available_inventory_monitor(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in AVAILABLE_INVENTORY_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少可售监控列：{', '.join(missing)}")

    base = df[AVAILABLE_INVENTORY_REQUIRED_COLUMNS].copy()
    base["开发员"] = base["开发员"].fillna("").astype(str).str.strip()
    base = base[base["开发员"].ne("")].copy()
    for col in ["日均销量"] + AVAILABLE_INVENTORY_STOCK_COLUMNS:
        base[col] = normalize_config_number(base[col]).fillna(0)

    if base.empty:
        return pd.DataFrame(columns=AVAILABLE_INVENTORY_SUMMARY_COLUMNS)

    grouped = (
        base.groupby("开发员", dropna=False, sort=True)[["日均销量"] + AVAILABLE_INVENTORY_STOCK_COLUMNS]
        .sum()
        .reset_index()
    )
    grouped["库存总数"] = grouped[AVAILABLE_INVENTORY_STOCK_COLUMNS].sum(axis=1)
    grouped["日均单量"] = grouped["日均销量"]
    grouped["总可售天数"] = grouped.apply(lambda row: safe_blank_ratio(row["库存总数"], row["日均单量"]), axis=1)
    return grouped[AVAILABLE_INVENTORY_SUMMARY_COLUMNS].reset_index(drop=True)


def build_available_inventory_monitor_table(df: pd.DataFrame) -> pd.DataFrame:
    summary = normalize_available_inventory_monitor(df)
    if summary.empty:
        return pd.DataFrame(columns=AVAILABLE_INVENTORY_MONITOR_COLUMNS)

    result = summary[["开发员", "库存总数", "日均单量", "总可售天数"]].rename(columns={"日均单量": "日均订单"})
    return result[AVAILABLE_INVENTORY_MONITOR_COLUMNS].reset_index(drop=True)


def sales_detail_date_columns(df: pd.DataFrame, suffix: str) -> list[str]:
    pattern = re.compile(r"^\d{2}-\d{2}" + re.escape(suffix) + r"$")
    return [col for col in df.columns if pattern.fullmatch(str(col).strip())]


def normalize_sales_volume_detail(df: pd.DataFrame) -> pd.DataFrame:
    return normalize_sales_metric_detail(df, SALES_VOLUME_DETAIL_REQUIRED_COLUMNS, "销量")


def normalize_sales_amount_detail(df: pd.DataFrame) -> pd.DataFrame:
    return normalize_sales_metric_detail(df, SALES_AMOUNT_DETAIL_REQUIRED_COLUMNS, "销售额")


def normalize_sales_metric_detail(df: pd.DataFrame, required_columns: list[str], suffix: str) -> pd.DataFrame:
    missing = [col for col in required_columns if col not in df.columns]
    date_columns = sales_detail_date_columns(df, suffix)
    if missing:
        raise ValueError(f"{suffix}明细缺少列：{', '.join(missing)}")
    if not date_columns:
        raise ValueError(f"{suffix}明细缺少 MM-DD{suffix} 日期列")

    result = df[required_columns + date_columns].copy()
    for col in required_columns:
        result[col] = result[col].fillna("").astype(str).str.strip()
    result["msku"] = result["msku"].str.replace(r"^\t+", "", regex=True)
    result["人员"] = result["开发专员"].map(normalize_department_person_name)
    result["店铺前缀"] = result["店铺"].map(extract_department_store_prefix)
    for col in date_columns:
        result[col] = normalize_config_number(result[col]).fillna(0)
    return result


def normalize_department_person_name(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text == "--":
        return ""
    text = re.sub(r"^运营[一二三四五六七八九十百千万0-9]+部-", "", text)
    text = re.sub(r"-26$", "", text)
    return text.strip()


def extract_department_store_prefix(value) -> str:
    match = re.match(r"^\s*(\d+)-", str(value).strip())
    return match.group(1) if match else ""


def department_scope_mask(df: pd.DataFrame, scope: str) -> pd.Series:
    if scope == "20":
        return df["店铺前缀"].eq("20")
    if scope == "union":
        return df["店铺前缀"].isin(["6", "7"])
    return pd.Series(True, index=df.index)


def department_metric_columns_for_dates(dates: list[pd.Timestamp], suffix: str) -> list[str]:
    return [f"{date.strftime('%m-%d')}{suffix}" for date in dates]


def department_month_dates(today: pd.Timestamp) -> list[pd.Timestamp]:
    month_start = today.replace(day=1)
    if today.day == 1:
        return []
    return list(pd.date_range(month_start, today - pd.Timedelta(days=1), freq="D"))


def department_performance_daily_columns(dates: list[pd.Timestamp]) -> list[str]:
    columns = []
    for date in dates:
        label = f"{date.month}月{date.day}日"
        columns.extend([f"{label}销量", f"{label}销售额（元）"])
    return columns


def department_performance_columns(dates: list[pd.Timestamp]) -> list[str]:
    return DEPARTMENT_PERFORMANCE_FIXED_COLUMNS + department_performance_daily_columns(dates)


def build_department_performance_tables(
    operational_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    amount_df: pd.DataFrame,
    today=None,
) -> dict[str, pd.DataFrame]:
    today_ts = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.today().normalize()
    window_dates = [today_ts - pd.Timedelta(days=offset) for offset in range(1, 8)]
    volume = normalize_sales_volume_detail(volume_df)
    amount = normalize_sales_amount_detail(amount_df)
    volume_date_cols = department_metric_columns_for_dates(window_dates, "销量")
    amount_date_cols = department_metric_columns_for_dates(window_dates, "销售额")
    missing_volume = [col for col in volume_date_cols if col not in volume.columns]
    missing_amount = [col for col in amount_date_cols if col not in amount.columns]
    if missing_volume:
        raise ValueError(f"销量明细缺少近7天日期列：{', '.join(missing_volume)}")
    if missing_amount:
        raise ValueError(f"销售额明细缺少近7天日期列：{', '.join(missing_amount)}")

    month_dates = department_month_dates(today_ts)
    month_amount_cols = [col for col in department_metric_columns_for_dates(month_dates, "销售额") if col in amount.columns]
    remaining_days = calendar.monthrange(today_ts.year, today_ts.month)[1] - today_ts.day + 1
    onsale_counts = build_department_onsale_counts(operational_df)
    tables = {}
    for title, scope in DEPARTMENT_PERFORMANCE_BOARDS:
        volume_scope = volume[department_scope_mask(volume, scope)].copy()
        amount_scope = amount[department_scope_mask(amount, scope)].copy()
        tables[title] = build_department_performance_table_for_scope(
            title,
            scope,
            volume_scope,
            amount_scope,
            window_dates,
            volume_date_cols,
            amount_date_cols,
            month_amount_cols,
            remaining_days,
            onsale_counts,
        )
    return tables


def build_department_performance_table_for_scope(
    title: str,
    scope: str,
    volume: pd.DataFrame,
    amount: pd.DataFrame,
    window_dates: list[pd.Timestamp],
    volume_date_cols: list[str],
    amount_date_cols: list[str],
    month_amount_cols: list[str],
    remaining_days: int,
    onsale_counts: dict[tuple[str, str | None], int],
) -> pd.DataFrame:
    people = sorted({person for person in volume["人员"].tolist() + amount["人员"].tolist() if person})
    summary = build_department_performance_row(
        title,
        scope,
        None,
        volume,
        amount,
        window_dates,
        volume_date_cols,
        amount_date_cols,
        month_amount_cols,
        remaining_days,
        onsale_counts,
    )
    denominator = summary["近7天日均销售额（元）"]
    rows = [summary]
    person_rows = []
    for person in people:
        person_rows.append(
            build_department_performance_row(
                person,
                scope,
                person,
                volume[volume["人员"].eq(person)].copy(),
                amount[amount["人员"].eq(person)].copy(),
                window_dates,
                volume_date_cols,
                amount_date_cols,
                month_amount_cols,
                remaining_days,
                onsale_counts,
            )
        )
    person_rows = sorted(person_rows, key=lambda row: row["近7天日均销售额（元）"], reverse=True)
    rows.extend(person_rows)
    result = pd.DataFrame(rows)
    result["销售额贡献占比"] = result["近7天日均销售额（元）"].map(lambda value: safe_blank_ratio(value, denominator))
    return result[department_performance_columns(window_dates)].reset_index(drop=True)


def build_department_performance_row(
    label: str,
    scope: str,
    person: str | None,
    volume: pd.DataFrame,
    amount: pd.DataFrame,
    window_dates: list[pd.Timestamp],
    volume_date_cols: list[str],
    amount_date_cols: list[str],
    month_amount_cols: list[str],
    remaining_days: int,
    onsale_counts: dict[tuple[str, str | None], int],
) -> dict:
    total_volume_7 = volume[volume_date_cols].sum().sum() if not volume.empty else 0
    total_amount_7 = amount[amount_date_cols].sum().sum() if not amount.empty else 0
    month_amount = amount[month_amount_cols].sum().sum() if month_amount_cols and not amount.empty else 0
    row = {
        "开发员": label,
        "在售产品数": onsale_counts.get((scope, person), 0),
        "销售额贡献占比": 0,
        "近7天日均订单": total_volume_7 / 7,
        "近7天日均销售额（元）": total_amount_7 / 7,
        "预估本月销售额（元）": month_amount + (total_amount_7 / 7) * remaining_days,
    }
    for date, volume_col, amount_col in zip(window_dates, volume_date_cols, amount_date_cols):
        label_prefix = f"{date.month}月{date.day}日"
        row[f"{label_prefix}销量"] = volume[volume_col].sum() if not volume.empty else 0
        row[f"{label_prefix}销售额（元）"] = amount[amount_col].sum() if not amount.empty else 0
    return row


def build_department_onsale_counts(operational_df: pd.DataFrame) -> dict[tuple[str, str | None], int]:
    required = ["MSKU", "店铺名称", "开发员", "可售"]
    missing = [col for col in required if col not in operational_df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少部门监控在售列：{', '.join(missing)}")

    counts: dict[tuple[str, str | None], set[str]] = {}
    base = operational_df[required].copy()
    base["MSKU"] = base["MSKU"].fillna("").astype(str).str.strip()
    base["开发员"] = base["开发员"].map(normalize_department_person_name)
    base["可售"] = normalize_config_number(base["可售"]).fillna(0)
    base = base[base["MSKU"].ne("") & base["可售"].gt(0)].copy()
    for _, row in base.iterrows():
        scopes = department_scopes_for_store_names(row["店铺名称"])
        scopes.add("all")
        for scope in scopes:
            counts.setdefault((scope, None), set()).add(row["MSKU"])
            if row["开发员"]:
                counts.setdefault((scope, row["开发员"]), set()).add(row["MSKU"])
    return {key: len(value) for key, value in counts.items()}


def department_scopes_for_store_names(value) -> set[str]:
    scopes = set()
    for item in [part.strip() for part in str(value).split(",") if part.strip()]:
        prefix = extract_department_store_prefix(item)
        if prefix == "20":
            scopes.add("20")
        elif prefix in {"6", "7"}:
            scopes.add("union")
    return scopes


def normalize_replenishment_targets(targets: pd.DataFrame | None) -> pd.DataFrame:
    if targets is None or targets.empty:
        return pd.DataFrame(columns=REPLENISHMENT_TARGET_COLUMNS)

    data = targets.copy()
    for col in REPLENISHMENT_TARGET_COLUMNS:
        if col not in data.columns:
            data[col] = pd.NA
    data = data[REPLENISHMENT_TARGET_COLUMNS].copy()
    data["ASIN"] = data["ASIN"].fillna("").astype(str).str.strip()
    data["目标可售天数"] = normalize_config_number(data["目标可售天数"]).round()
    data = data[data["ASIN"].ne("") & data["目标可售天数"].notna()].copy()
    data["目标可售天数"] = data["目标可售天数"].clip(lower=0).astype(int)
    return data.drop_duplicates(subset=["ASIN"], keep="last").reset_index(drop=True)


def normalize_replenishment_operational(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REPLENISHMENT_OPERATIONAL_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少补货管理列：{', '.join(missing)}")

    base = df[REPLENISHMENT_OPERATIONAL_REQUIRED_COLUMNS].copy()
    for col in ["ASIN", "MSKU", "店铺名称", "开发员"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    base = base[base["ASIN"].ne("")].copy()
    for col in REPLENISHMENT_STOCK_COMPONENT_COLUMNS + AGING_STOCK_COLUMNS + ["日均销量", "单品重量(g)"]:
        base[col] = normalize_config_number(base[col]).fillna(0)
    return base


def build_replenishment_operational_summary(df: pd.DataFrame) -> pd.DataFrame:
    operational = normalize_replenishment_operational(df)
    if operational.empty:
        return pd.DataFrame(columns=replenishment_operational_columns())

    grouped = (
        operational.groupby("ASIN", dropna=False, sort=False)
        .agg(
            MSKU=("MSKU", join_non_empty_values),
            店铺编码=("店铺名称", join_operational_store_codes),
            开发员=("开发员", join_non_empty_values),
            **{"亚马逊可售库存数量": ("可售", "sum")},
            待入库=("待入库", "sum"),
            采购在途=("采购在途", "sum"),
            本地库存=("本地库存", "sum"),
            在途=("在途", "sum"),
            计划入库=("计划入库", "sum"),
            **{"库龄超90天库存数": (AGING_STOCK_COLUMNS[0], "sum")},
            日均销量=("日均销量", "sum"),
            重量=("单品重量(g)", "max"),
        )
        .reset_index()
    )
    grouped["库龄超90天库存数"] = operational.groupby("ASIN", sort=False)[AGING_STOCK_COLUMNS].sum().sum(axis=1).to_numpy()
    grouped["总库存数量"] = grouped[
        ["亚马逊可售库存数量", "待入库", "采购在途", "本地库存", "在途", "计划入库"]
    ].sum(axis=1)
    grouped["建议补货方式"] = grouped["重量"].map(lambda value: "卡航" if value > 100 else "空运")
    return grouped[replenishment_operational_columns()].reset_index(drop=True)


def join_operational_store_codes(values: pd.Series) -> str:
    codes = []
    seen = set()
    for value in values:
        for code, _ in extract_operational_store_codes(value):
            if code and code not in seen:
                codes.append(code)
                seen.add(code)
    return "；".join(codes)


def replenishment_operational_columns() -> list[str]:
    return [
        "ASIN",
        "MSKU",
        "店铺编码",
        "开发员",
        "亚马逊可售库存数量",
        "总库存数量",
        "库龄超90天库存数",
        "日均销量",
        "重量",
        "建议补货方式",
    ]


def normalize_replenishment_gross_profit_source(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in REPLENISHMENT_GROSS_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"毛利原始表缺少补货管理列：{', '.join(missing)}")
    sales_columns = columns_between(df, "销售额--FBA销售额", "COD")

    base = df[["ASIN", "MSKU", "国家", "毛利润"] + GROSS_PROFIT_VOLUME_COLUMNS + sales_columns + REPLENISHMENT_GROSS_RATIO_COLUMNS].copy()
    for col in ["ASIN", "MSKU", "国家"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    for col in set(["毛利润"] + GROSS_PROFIT_VOLUME_COLUMNS + sales_columns):
        base[col] = normalize_config_number(base[col]).fillna(0)
    for col in REPLENISHMENT_GROSS_RATIO_COLUMNS:
        base[col] = normalize_rate(base[col]).fillna(0)
    base["销量"] = base[GROSS_PROFIT_VOLUME_COLUMNS].sum(axis=1)
    base["销售额"] = base[sales_columns].sum(axis=1)
    return base[
        ["ASIN", "MSKU", "国家", "销量", "销售额", "毛利润"] + REPLENISHMENT_GROSS_RATIO_COLUMNS
    ]


def build_replenishment_gross_summary(df: pd.DataFrame) -> pd.DataFrame:
    gross_profit = normalize_replenishment_gross_profit_source(df)
    if gross_profit.empty:
        return pd.DataFrame(columns=["ASIN"] + replenishment_gross_columns())

    country_data = gross_profit[gross_profit["国家"].isin(PRODUCT_COUNTRIES)].copy()
    if country_data.empty:
        return pd.DataFrame(columns=["ASIN"] + replenishment_gross_columns())

    grouped = (
        country_data.groupby(["ASIN", "国家"], dropna=False, sort=False)
        .agg(单量=("销量", "sum"), 销售额=("销售额", "sum"), 毛利润=("毛利润", "sum"))
        .reset_index()
    )
    grouped["毛利率"] = grouped.apply(lambda row: safe_blank_ratio(row["毛利润"], row["销售额"]), axis=1)
    result = grouped[["ASIN"]].drop_duplicates().copy()

    for country in PRODUCT_COUNTRIES:
        subset = grouped[grouped["国家"].eq(country)][["ASIN", "单量", "毛利率"]].copy()
        subset = subset.rename(columns={"单量": f"{country}单量", "毛利率": f"{country}毛利率"})
        result = result.merge(subset, on="ASIN", how="left")

    reason_wide = build_replenishment_reason_columns(country_data)
    result = result.merge(reason_wide, on="ASIN", how="left")
    for col in replenishment_gross_columns():
        if col not in result.columns:
            result[col] = pd.NA if not col.endswith("原因") else ""
    return result[["ASIN"] + replenishment_gross_columns()]


def build_replenishment_reason_columns(gross_profit: pd.DataFrame) -> pd.DataFrame:
    if gross_profit.empty:
        return pd.DataFrame(columns=["ASIN"] + replenishment_reason_columns())

    rows = []
    grouped = gross_profit.groupby(["ASIN", "国家", "MSKU"], dropna=False, sort=False)
    for (asin, country, msku), group in grouped:
        if country not in PRODUCT_COUNTRIES or not str(msku).strip():
            continue
        reasons = []
        if group["广告费占比"].max() > 0.15:
            reasons.append("广告炸")
        if group["退款占比"].max() > 0.08:
            reasons.append("退货多")
        if group["FBA发货费占比"].max() > 0.60:
            reasons.append("FBA配送费炸")
        if reasons:
            rows.append({"ASIN": asin, "国家": country, "MSKU原因": f"{msku}: {'、'.join(reasons)}"})

    if not rows:
        return pd.DataFrame(columns=["ASIN"] + replenishment_reason_columns())

    reason_data = pd.DataFrame(rows)
    grouped_reasons = (
        reason_data.groupby(["ASIN", "国家"], dropna=False, sort=False)
        .agg(原因=("MSKU原因", lambda values: "；".join(values)))
        .reset_index()
    )
    result = grouped_reasons[["ASIN"]].drop_duplicates().copy()
    for country in PRODUCT_COUNTRIES:
        subset = grouped_reasons[grouped_reasons["国家"].eq(country)][["ASIN", "原因"]].copy()
        subset = subset.rename(columns={"原因": f"{country}原因"})
        result = result.merge(subset, on="ASIN", how="left")
    for col in replenishment_reason_columns():
        if col not in result.columns:
            result[col] = ""
    return result[["ASIN"] + replenishment_reason_columns()]


def replenishment_gross_columns() -> list[str]:
    columns = []
    for country in PRODUCT_COUNTRIES:
        columns.extend([f"{country}单量", f"{country}毛利率", f"{country}原因"])
    return columns


def replenishment_reason_columns() -> list[str]:
    return [f"{country}原因" for country in PRODUCT_COUNTRIES]


def build_replenishment_rating_summary(df: pd.DataFrame) -> pd.DataFrame:
    rating = normalize_rating_source(df)
    if rating.empty:
        return pd.DataFrame(columns=["ASIN", "产品评分"])

    data = rating[rating["国家"].isin(PRODUCT_COUNTRIES)].copy()
    if data.empty:
        return pd.DataFrame(columns=["ASIN", "产品评分"])
    country_order = {country: index for index, country in enumerate(PRODUCT_COUNTRIES)}
    data["_国家排序"] = data["国家"].map(country_order).fillna(len(country_order))
    data = data.sort_values(["ASIN", "Rating总数", "_国家排序"], ascending=[True, False, True], kind="stable")
    best = data.drop_duplicates(subset=["ASIN"], keep="first").copy()
    best["产品评分"] = best.apply(format_product_rating, axis=1)
    return best[["ASIN", "产品评分"]].reset_index(drop=True)


def build_replenishment_management_tables(
    operational_df: pd.DataFrame,
    gross_profit_df: pd.DataFrame,
    rating_df: pd.DataFrame,
    target_config: pd.DataFrame | None = None,
    only_needed: bool = True,
) -> dict[str, pd.DataFrame]:
    operational = build_replenishment_operational_summary(operational_df)
    gross_profit = build_replenishment_gross_summary(gross_profit_df)
    rating = build_replenishment_rating_summary(rating_df)
    targets = normalize_replenishment_targets(target_config)

    if operational.empty:
        empty_detail = pd.DataFrame(columns=replenishment_management_columns())
        return {"detail": empty_detail, "store_distribution": pd.DataFrame(columns=["店铺编码", "需补货ASIN数"])}

    result = operational.merge(targets, on="ASIN", how="left")
    result["目标可售天数"] = result["目标可售天数"].fillna(DEFAULT_REPLENISHMENT_TARGET_DAYS).astype(int)
    raw_replenishment_quantity = (
        result["日均销量"] * result["目标可售天数"] - result["总库存数量"]
    ).clip(lower=0)
    result["建议补货数量"] = (raw_replenishment_quantity // 10) * 10
    result = result.merge(gross_profit, on="ASIN", how="left").merge(rating, on="ASIN", how="left")
    for col in replenishment_management_columns():
        if col not in result.columns:
            result[col] = pd.NA

    result = result[replenishment_management_columns()].copy()
    if only_needed:
        result = result[pd.to_numeric(result["建议补货数量"], errors="coerce").fillna(0).gt(0)].copy()
    result = result.sort_values(["建议补货数量", "ASIN"], ascending=[False, True], kind="stable").reset_index(drop=True)
    return {"detail": result, "store_distribution": build_replenishment_store_distribution(result)}


def build_replenishment_store_distribution(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty or "店铺编码" not in detail.columns:
        return pd.DataFrame(columns=["店铺编码", "需补货ASIN数"])
    rows = []
    for _, row in detail.iterrows():
        asin = str(row.get("ASIN", "")).strip()
        for store_code in [code.strip() for code in str(row.get("店铺编码", "")).split("；") if code.strip()]:
            rows.append({"ASIN": asin, "店铺编码": store_code})
    if not rows:
        return pd.DataFrame(columns=["店铺编码", "需补货ASIN数"])
    data = pd.DataFrame(rows).drop_duplicates(subset=["ASIN", "店铺编码"])
    return (
        data.groupby("店铺编码", dropna=False, as_index=False)
        .agg(需补货ASIN数=("ASIN", "nunique"))
        .sort_values(["需补货ASIN数", "店铺编码"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )


def replenishment_management_columns() -> list[str]:
    base_columns = [
        "ASIN",
        "MSKU",
        "店铺编码",
        "目标可售天数",
        "亚马逊可售库存数量",
        "总库存数量",
        "库龄超90天库存数",
        "日均销量",
        "重量",
        "建议补货方式",
        "建议补货数量",
    ]
    return base_columns + replenishment_gross_columns() + ["产品评分"]


def normalize_product_operational(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in PRODUCT_OPERATIONAL_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"运营原始表缺少产品管理列：{', '.join(missing)}")

    base = df[PRODUCT_OPERATIONAL_REQUIRED_COLUMNS].copy()
    for col in ["ASIN", "MSKU"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    base = base[base["MSKU"].ne("")].copy()
    for col in PRODUCT_OPERATIONAL_REQUIRED_COLUMNS:
        if col in {"ASIN", "MSKU"}:
            continue
        base[col] = normalize_config_number(base[col]).fillna(0)
    base = base.rename(columns={"MSKU": "SKU", "可售": "可售数量"})
    if base.empty:
        return pd.DataFrame(columns=["ASIN", "SKU", "可售天数"] + PRODUCT_OPERATIONAL_SUM_COLUMNS)

    grouped = (
        base.groupby(["ASIN", "SKU"], dropna=False, sort=False)
        .agg(
            可售数量=("可售数量", "sum"),
            可售天数=("可售天数", "first"),
            日均销量=("日均销量", "sum"),
            昨天销量=("昨天销量", "sum"),
            前天销量=("前天销量", "sum"),
            上前销量=("上前销量", "sum"),
            **{
                "7天销量": ("7天销量", "sum"),
                "14天销量": ("14天销量", "sum"),
                "30天销量": ("30天销量", "sum"),
                "90天销量": ("90天销量", "sum"),
            },
        )
        .reset_index()
    )
    return grouped[["ASIN", "SKU", "可售数量", "可售天数"] + [col for col in PRODUCT_OPERATIONAL_SUM_COLUMNS if col != "可售数量"]]


def normalize_gross_profit_source(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in GROSS_PROFIT_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"毛利原始表缺少列：{', '.join(missing)}")
    sales_columns = columns_between(df, "销售额--FBA销售额", "COD")

    base = df[["ASIN", "MSKU", "国家", "毛利润"] + GROSS_PROFIT_VOLUME_COLUMNS + GROSS_PROFIT_AD_COLUMNS + sales_columns].copy()
    for col in ["ASIN", "MSKU", "国家"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    for col in set(["毛利润"] + GROSS_PROFIT_VOLUME_COLUMNS + GROSS_PROFIT_AD_COLUMNS + sales_columns):
        base[col] = normalize_config_number(base[col]).fillna(0)
    base["销量"] = base[GROSS_PROFIT_VOLUME_COLUMNS].sum(axis=1)
    base["销售额"] = base[sales_columns].sum(axis=1)
    base["广告支出净额"] = base[GROSS_PROFIT_AD_COLUMNS].sum(axis=1)
    return base[["ASIN", "MSKU", "国家", "销量", "销售额", "毛利润", "广告支出净额"]]


def normalize_rating_source(df: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in RATING_REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Rating缺少列：{', '.join(missing)}")
    base = df[RATING_REQUIRED_COLUMNS].copy()
    for col in ["ASIN", "国家"]:
        base[col] = base[col].fillna("").astype(str).str.strip()
    base["Rating总数"] = normalize_config_number(base["Rating总数"]).fillna(0)
    base["评分"] = normalize_config_number(base["评分"])
    return base


def build_product_management_table(
    operational_df: pd.DataFrame, gross_profit_df: pd.DataFrame, rating_df: pd.DataFrame
) -> pd.DataFrame:
    operational = normalize_product_operational(operational_df)
    gross_profit = normalize_gross_profit_source(gross_profit_df)
    rating = normalize_rating_source(rating_df)
    if operational.empty:
        return pd.DataFrame(columns=product_management_all_columns())

    result = operational.copy()
    result["_sort_order"] = range(len(result))
    sku_gross = build_product_gross_columns(gross_profit, ["ASIN", "MSKU"]).rename(columns={"MSKU": "SKU"})
    rating_wide = build_product_rating_columns(rating)

    result = result.merge(sku_gross, on=["ASIN", "SKU"], how="left").merge(rating_wide, on="ASIN", how="left")
    for col in product_management_all_columns():
        if col not in result.columns:
            result[col] = pd.NA
    return result[product_management_all_columns()].sort_values("_sort_order", kind="stable").reset_index(drop=True)


def build_low_margin_product_table(
    gross_profit_df: pd.DataFrame,
    threshold: float = LOW_MARGIN_PRODUCT_THRESHOLD,
    min_sales: float = LOW_MARGIN_PRODUCT_MIN_SALES,
    developers: Iterable[str] | None = None,
) -> pd.DataFrame:
    gross_profit = normalize_low_margin_gross_profit_source(gross_profit_df)
    if developers:
        selected_developers = {str(developer).strip() for developer in developers if str(developer).strip()}
        gross_profit = gross_profit[gross_profit["开发员"].isin(selected_developers)].copy()
    if gross_profit.empty:
        return pd.DataFrame(columns=LOW_MARGIN_PRODUCT_COLUMNS)

    grouped = (
        gross_profit.rename(columns={"MSKU": "SKU"})
        .groupby(["ASIN", "SKU", "国家"], dropna=False, sort=False)
        .agg(
            开发员=("开发员", join_non_empty_values),
            销量=("销量", "sum"),
            销售额=("销售额", "sum"),
            毛利润=("毛利润", "sum"),
        )
        .reset_index()
    )
    grouped["毛利率"] = grouped.apply(lambda row: safe_blank_ratio(row["毛利润"], row["销售额"]), axis=1)
    grouped = grouped[
        (pd.to_numeric(grouped["销量"], errors="coerce") >= min_sales)
        & (pd.to_numeric(grouped["毛利率"], errors="coerce") < threshold)
    ].copy()

    if grouped.empty:
        return pd.DataFrame(columns=LOW_MARGIN_PRODUCT_COLUMNS)

    grouped = grouped.sort_values(["毛利率", "SKU", "国家"], ascending=[False, True, True], kind="stable")
    return grouped[LOW_MARGIN_PRODUCT_COLUMNS].reset_index(drop=True)


def normalize_low_margin_gross_profit_source(df: pd.DataFrame) -> pd.DataFrame:
    gross_profit = normalize_gross_profit_source(df)
    developer_col = first_existing_column(df, GROSS_PROFIT_DEVELOPER_COLUMNS)
    if developer_col is None:
        gross_profit["开发员"] = ""
        return gross_profit

    gross_profit["开发员"] = df[developer_col].fillna("").astype(str).str.strip().reset_index(drop=True)
    return gross_profit


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def join_non_empty_values(values: pd.Series) -> str:
    return "；".join(sorted({str(value).strip() for value in values if str(value).strip()}))


def sort_key_series(series: pd.Series) -> pd.Series:
    non_empty = series.notna() & series.astype(str).str.strip().ne("")
    numeric = normalize_config_number(series)
    if non_empty.any() and numeric.notna().sum() / non_empty.sum() >= 0.8:
        return numeric
    return series.map(normalize_sort_text)


def normalize_sort_text(value) -> str:
    if pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def sort_product_management_table(df: pd.DataFrame, sort_column: str | None = None, ascending: bool = True) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    result = df.copy()
    if not sort_column or sort_column == "默认排序" or sort_column not in result.columns:
        if "_sort_order" in result.columns:
            return result.sort_values("_sort_order", kind="stable").reset_index(drop=True)
        return result.reset_index(drop=True)
    order_col = "_sort_order" if "_sort_order" in result.columns else sort_column
    return result.sort_values(
        [sort_column, order_col],
        ascending=[ascending, True],
        na_position="last",
        kind="stable",
        key=sort_key_series,
    ).reset_index(drop=True)


def build_product_gross_columns(gross_profit: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if gross_profit.empty:
        return pd.DataFrame(columns=group_cols + product_gross_columns())

    totals = (
        gross_profit.groupby(group_cols, dropna=False, sort=False)
        .agg(销售额=("销售额", "sum"), 毛利润=("毛利润", "sum"))
        .reset_index()
    )
    totals["毛利率"] = totals.apply(lambda row: safe_blank_ratio(row["毛利润"], row["销售额"]), axis=1)

    country_data = gross_profit[gross_profit["国家"].isin(PRODUCT_COUNTRIES)].copy()
    if country_data.empty:
        for col in product_country_gross_columns():
            totals[col] = pd.NA
        return totals[group_cols + product_gross_columns()]

    country_grouped = (
        country_data.groupby(group_cols + ["国家"], dropna=False, sort=False)
        .agg(销量=("销量", "sum"), 销售额=("销售额", "sum"), 毛利润=("毛利润", "sum"), 广告支出净额=("广告支出净额", "sum"))
        .reset_index()
    )
    country_grouped["毛利率"] = country_grouped.apply(lambda row: safe_blank_ratio(row["毛利润"], row["销售额"]), axis=1)
    country_grouped["广告费占比"] = country_grouped.apply(
        lambda row: safe_blank_ratio(abs(row["广告支出净额"]), row["销售额"]),
        axis=1,
    )

    wide = totals
    for country in PRODUCT_COUNTRIES:
        subset = country_grouped[country_grouped["国家"].eq(country)][group_cols + ["销量", "毛利率", "广告费占比"]].copy()
        subset = subset.rename(
            columns={
                "销量": f"{country}销量",
                "毛利率": f"{country}毛利率",
                "广告费占比": f"{country}广告费占比",
            }
        )
        wide = wide.merge(subset, on=group_cols, how="left")
    for col in product_gross_columns():
        if col not in wide.columns:
            wide[col] = pd.NA
    return wide[group_cols + product_gross_columns()]


def build_product_rating_columns(rating: pd.DataFrame) -> pd.DataFrame:
    if rating.empty:
        return pd.DataFrame(columns=["ASIN"] + product_rating_columns())
    base = rating[rating["国家"].isin(PRODUCT_COUNTRIES)].copy()
    if base.empty:
        return pd.DataFrame(columns=["ASIN"] + product_rating_columns())
    grouped = (
        base.groupby(["ASIN", "国家"], dropna=False, sort=False)
        .agg(Rating总数=("Rating总数", "max"), 评分=("评分", "mean"))
        .reset_index()
    )
    country_order = {country: idx for idx, country in enumerate(PRODUCT_COUNTRIES)}
    grouped["_国家排序"] = grouped["国家"].map(country_order).fillna(len(country_order))
    best = grouped.sort_values(
        ["ASIN", "Rating总数", "_国家排序"],
        ascending=[True, False, True],
        kind="stable",
    ).drop_duplicates("ASIN", keep="first")
    best["Rating"] = best.apply(format_product_rating, axis=1)
    return best[["ASIN"] + product_rating_columns()].reset_index(drop=True)


def columns_between(df: pd.DataFrame, start: str, end: str) -> list[str]:
    columns = list(df.columns)
    if start not in columns or end not in columns:
        missing = [col for col in [start, end] if col not in columns]
        raise ValueError(f"毛利原始表缺少销售额区间列：{', '.join(missing)}")
    start_index = columns.index(start)
    end_index = columns.index(end)
    if start_index > end_index:
        raise ValueError(f"毛利原始表销售额区间列顺序异常：{start} 在 {end} 之后")
    return columns[start_index : end_index + 1]


def safe_blank_ratio(numerator, denominator):
    return numerator / denominator if pd.notna(denominator) and denominator else pd.NA


def format_product_rating(row) -> str:
    count = row["Rating总数"]
    score = row["评分"]
    if pd.isna(count):
        return ""
    count_text = str(int(round(float(count))))
    if pd.isna(score):
        return count_text
    return f"{count_text}({float(score):.1f})"


def product_country_gross_columns() -> list[str]:
    columns = []
    for country in PRODUCT_COUNTRIES:
        columns.extend([f"{country}销量", f"{country}毛利率", f"{country}广告费占比"])
    return columns


def product_gross_columns() -> list[str]:
    return product_country_gross_columns() + ["销售额", "毛利润", "毛利率"]


def product_rating_columns() -> list[str]:
    return ["Rating"]


def product_management_columns() -> list[str]:
    return [
        "SKU",
        "ASIN",
        "可售数量",
        "可售天数",
        "日均销量",
        "昨天销量",
        "前天销量",
        "上前销量",
        "7天销量",
        "14天销量",
        "30天销量",
        "90天销量",
    ] + product_gross_columns() + product_rating_columns()


def product_management_internal_columns() -> list[str]:
    return ["_sort_order"]


def product_management_all_columns() -> list[str]:
    return product_management_columns() + product_management_internal_columns()


def product_management_display_table(df: pd.DataFrame) -> pd.DataFrame:
    display_columns = [col for col in product_management_columns() if col in df.columns]
    return df[display_columns].copy()


def maybe_numeric(series: pd.Series) -> pd.Series:
    if series.dtype.kind in "biufc":
        return series
    text = normalized_numeric_text(series)
    percent_mask = text.str.endswith("%", na=False)
    cleaned = text.str.replace("%", "", regex=False)
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    non_empty = (text.notna() & text.ne("")).sum()
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
    text = normalized_numeric_text(series)
    percent_mask = text.str.endswith("%", na=False)
    cleaned = text.str.replace("%", "", regex=False)
    numeric = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    if percent_to_decimal:
        numeric.loc[percent_mask] = numeric.loc[percent_mask] / 100
    return numeric


def normalized_numeric_text(series: pd.Series) -> pd.Series:
    return series.map(clean_numeric_text)


def clean_numeric_text(value) -> str | None:
    if pd.isna(value):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if text.lower() in {"", "nan", "none", "null", "nat", "-", "--", "—", "–", "未配置"}:
        return None

    is_parenthesized_negative = text.startswith("(") and text.endswith(")")
    if is_parenthesized_negative:
        text = text[1:-1].strip()

    text = (
        text.replace("\u00a0", "")
        .replace("\u2007", "")
        .replace("\u202f", "")
        .replace("\u3000", "")
        .replace(" ", "")
        .replace("\t", "")
        .replace(",", "")
        .replace("，", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
    )
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    if is_parenthesized_negative and text and not text.startswith("-"):
        text = "-" + text
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)%?", text):
        match = re.match(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)%?", text)
        if match:
            text = match.group(0)
    return text


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
        return maybe_numeric(df[name])

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
        numeric_range = df.loc[:, columns[start_idx : end_idx + 1]].apply(normalize_config_number)
        return numeric_range.sum().sum()

    context = FormulaContext(field_getter=get_field, range_sum_getter=get_range_sum)
    row = {}
    for _, metric in metric_config.iterrows():
        value = evaluate_formula(metric["公式"], context)
        if isinstance(value, pd.Series):
            value = normalize_config_number(value).sum()
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

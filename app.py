from __future__ import annotations

import hashlib
import html
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from dashboard.data_processing import (
    DEFAULT_REPLENISHMENT_TARGET_DAYS,
    build_available_inventory_monitor_table,
    build_department_performance_tables,
    build_discovered_commission_config,
    build_discovered_department_fee_config,
    build_alerts,
    build_low_margin_product_table,
    build_product_management_table,
    build_replenishment_management_tables,
    build_sales_dashboard_tables,
    build_slow_moving_inventory_table,
    compute_commission_table,
    compute_metric_table,
    compute_stopped_commission_table,
    load_commission_config,
    load_department_fee_config,
    load_business_config,
    load_metric_config,
    load_operational_sales_source,
    merge_business_config,
    normalize_commission_config,
    normalize_department_fee_config,
    normalize_gross_profit_source,
    normalize_rating_source,
    normalize_replenishment_targets,
    normalize_sales_amount_detail,
    normalize_sales_volume_detail,
    normalize_store_config,
    normalize_target_config,
    product_management_columns,
    product_management_display_table,
    read_upload_table,
    read_local_table,
    select_metric_config,
    split_counted_and_stopped_data,
)
from dashboard.display import SIDEBAR_BANNER_PATH, month_label
from dashboard.filters import apply_home_filters
from dashboard.report_store import (
    delete_upload_record,
    get_latest_source_path,
    get_operational_sales_source_path,
    load_latest_source_record,
    load_operational_sales_source_record,
    load_reports_from_records,
    load_upload_records,
    persist_latest_source,
    persist_operational_sales_source,
    persist_uploaded_reports,
)


st.set_page_config(page_title="开发员销售数据看板", layout="wide")

CONFIG_DIR = Path(__file__).resolve().parent / "configs"
COMPONENT_DIR = Path(__file__).resolve().parent / "dashboard" / "components"
METRIC_CONFIG_PATH = CONFIG_DIR / "metrics_config.csv"
STORE_CONFIG_PATH = CONFIG_DIR / "store_config.csv"
TARGET_CONFIG_PATH = CONFIG_DIR / "monthly_targets.csv"
COMMISSION_CONFIG_PATH = CONFIG_DIR / "commission_config.csv"
DEPARTMENT_FEE_CONFIG_PATH = CONFIG_DIR / "department_fee_config.csv"
REPLENISHMENT_TARGET_PATH = CONFIG_DIR / "replenishment_targets.csv"
REPLENISHMENT_COLUMN_ORDER_PATH = CONFIG_DIR / "replenishment_column_order.csv"
replenishment_column_order_component = components.declare_component(
    "replenishment_column_order",
    path=str(COMPONENT_DIR / "column_order"),
)


NAV_ITEMS = {
    "首页": "📊 首页",
    "销量看板": "📦 销量看板",
    "滞销提醒": "⏳ 滞销提醒",
    "产品管理": "🧾 产品管理",
    "部门监控": "📍 部门监控",
    "补货管理": "🚚 补货管理",
    "上传中心": "⬆️ 上传中心",
    "配置中心": "⚙️ 配置中心",
}


def inject_sidebar_styles():
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            background: linear-gradient(
                180deg,
                color-mix(in srgb, var(--secondary-background-color) 92%, var(--background-color)) 0%,
                var(--background-color) 100%
            );
            border-right: 1px solid color-mix(in srgb, var(--text-color) 14%, transparent);
        }
        section[data-testid="stSidebar"] > div {
            padding-top: 1.5rem;
        }
        section[data-testid="stSidebar"] img {
            border-radius: 14px;
            border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
            background: var(--secondary-background-color);
            box-shadow: 0 10px 24px color-mix(in srgb, var(--text-color) 12%, transparent);
            margin-bottom: 0.8rem;
        }
        .sidebar-brand {
            padding: 0.2rem 0 0.9rem 0;
            border-bottom: 1px solid color-mix(in srgb, var(--text-color) 14%, transparent);
            margin-bottom: 0.9rem;
        }
        .sidebar-brand-title {
            font-size: 1.42rem;
            line-height: 1.15;
            font-weight: 800;
            color: var(--text-color);
            letter-spacing: 0;
        }
        .sidebar-brand-caption {
            margin-top: 0.35rem;
            color: color-mix(in srgb, var(--text-color) 62%, transparent);
            font-size: 0.78rem;
            line-height: 1.4;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] {
            gap: 0.35rem;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label {
            background: color-mix(in srgb, var(--secondary-background-color) 82%, transparent);
            border: 1px solid color-mix(in srgb, var(--text-color) 14%, transparent);
            border-radius: 10px;
            padding: 0.58rem 0.65rem;
            margin: 0.18rem 0;
            transition: all 120ms ease;
            color: var(--text-color);
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label p,
        section[data-testid="stSidebar"] [role="radiogroup"] label span {
            color: var(--text-color) !important;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: color-mix(in srgb, var(--secondary-background-color) 66%, var(--primary-color));
            border-color: color-mix(in srgb, var(--primary-color) 52%, var(--text-color));
            transform: translateX(2px);
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: color-mix(in srgb, var(--primary-color) 22%, var(--secondary-background-color));
            border-color: color-mix(in srgb, var(--primary-color) 74%, var(--text-color));
            box-shadow: inset 3px 0 0 var(--primary-color);
            font-weight: 700;
        }
        section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p,
        section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) span {
            color: var(--text-color) !important;
            font-weight: 700;
        }
        section[data-testid="stSidebar"] [data-testid="stRadio"] > label {
            color: color-mix(in srgb, var(--text-color) 66%, transparent);
            font-size: 0.8rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }
        html[data-theme="dark"] section[data-testid="stSidebar"] img,
        body[data-theme="dark"] section[data-testid="stSidebar"] img,
        [data-theme="dark"] section[data-testid="stSidebar"] img {
            filter: brightness(0.76) saturate(0.92);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_navigation():
    inject_sidebar_styles()
    with st.sidebar:
        if SIDEBAR_BANNER_PATH.exists():
            st.image(str(SIDEBAR_BANNER_PATH), use_container_width=True)
        st.markdown(
            """
            <div class="sidebar-brand">
              <div class="sidebar-brand-title">开发员销售看板</div>
              <div class="sidebar-brand-caption">业绩上传 · 目标配置 · 销售分析</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        selected = st.radio(
            "导航",
            list(NAV_ITEMS.keys()),
            index=0,
            format_func=lambda item: NAV_ITEMS[item],
            label_visibility="visible",
        )
    return selected


def metric_lookup_from_config(metric_config_df):
    return (
        metric_config_df.drop_duplicates(subset=["指标名称"], keep="first")
        .set_index("指标名称")
        .to_dict(orient="index")
    )


def metrics_for_group(metric_config_df, group_name: str, fallback_to_overview: bool = True):
    selected = metric_config_df[metric_config_df["显示分组"].isin([group_name, "全部"])].copy()
    if selected.empty and fallback_to_overview:
        selected = metric_config_df[metric_config_df["显示分组"].isin(["总览", "全部"])].copy()
    return selected.drop_duplicates(subset=["指标名称"], keep="first")


def show_metric_cards(summary_table, metric_config):
    if summary_table.empty:
        return

    row = summary_table.iloc[0]
    cols = st.columns(min(6, max(1, len(summary_table.columns))))
    display_metrics = [
        name
        for name in summary_table.columns
        if name not in {"月份", "销售专员", "店铺", "店铺编码", "店铺类型", "停提款时间", "是否停提款数据", "部门"}
    ]

    for idx, metric_name in enumerate(display_metrics[:6]):
        fmt = metric_config.get(metric_name, {}).get("格式", "数字")
        cols[idx % len(cols)].metric(metric_name, format_display_value(row[metric_name], fmt))


def format_display_value(value, fmt: str) -> str:
    if value is None:
        return "-"
    try:
        if fmt == "金额":
            return f"{float(value):,.2f}"
        if fmt == "整数":
            return f"{float(value):,.0f}"
        if fmt == "百分比":
            return f"{float(value):.2%}"
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def metric_column_config(metric_lookup: dict, columns) -> dict:
    config = {}
    for col in columns:
        fmt = metric_lookup.get(col, {}).get("格式")
        if fmt == "金额":
            config[col] = st.column_config.NumberColumn(col, format="%.2f")
        elif fmt == "整数":
            config[col] = st.column_config.NumberColumn(col, format="%d")
        elif fmt == "百分比":
            config[col] = st.column_config.NumberColumn(col, format="percent")
        elif fmt:
            config[col] = st.column_config.NumberColumn(col, format="%.2f")
    return config


def render_metric_dataframe(df: pd.DataFrame, metric_lookup: dict):
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=metric_column_config(metric_lookup, df.columns),
    )


def default_chen_developers(options: list[str]) -> list[str]:
    matched = [option for option in options if "陈千潼" in str(option)]
    return matched or options


def chart_if_available(df, x, y, color=None, title=None, kind="bar"):
    if df.empty or x not in df.columns or y not in df.columns:
        return
    if kind == "line":
        fig = px.line(df, x=x, y=y, color=color, markers=True, title=title)
    else:
        fig = px.bar(df, x=x, y=y, color=color, title=title)
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=45, b=10))
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=df[x].tolist())
    st.plotly_chart(fig, use_container_width=True)


def sales_metric_lookup():
    return {
        "在售个数": {"格式": "整数"},
        "昨日订单": {"格式": "整数"},
        "前天订单": {"格式": "整数"},
        "上前订单": {"格式": "整数"},
        "-26订单": {"格式": "整数"},
        "总库存": {"格式": "整数"},
        "占用资金": {"格式": "金额"},
        "产品数占比": {"格式": "百分比"},
        "30天贡献占比": {"格式": "百分比"},
        "昨日D值": {"格式": "数字"},
        "7天D值": {"格式": "数字"},
        "7天日均": {"格式": "数字"},
        "30天日均": {"格式": "数字"},
        "中企单量": {"格式": "数字"},
        "本土单量": {"格式": "数字"},
        "总计": {"格式": "数字"},
    }


def slow_moving_metric_lookup():
    result = {
        "滞销SKU数": {"格式": "整数"},
        "90天以上库存数合计": {"格式": "整数"},
        "90天以上占用资金合计": {"格式": "数字"},
        "库存计提": {"格式": "数字"},
        "弃置费": {"格式": "数字"},
    }
    for col in ["91-180天库存数", "181-330天库存数", "331-365天库存数", "366-455天库存数", "456天以上库存数"]:
        result[col] = {"格式": "整数"}
    for col in ["91-180天占用资金", "181-330天占用资金", "331-365天占用资金", "366-455天占用资金", "456天占用资金"]:
        result[col] = {"格式": "数字"}
    return result


def slow_moving_column_config():
    stock_columns = [
        "91-180天库存数",
        "181-330天库存数",
        "331-365天库存数",
        "366-455天库存数",
        "456天以上库存数",
        "90天以上库存数合计",
    ]
    amount_columns = [
        "91-180天占用资金",
        "181-330天占用资金",
        "331-365天占用资金",
        "366-455天占用资金",
        "456天占用资金",
        "90天以上占用资金合计",
        "库存计提",
        "弃置费",
    ]
    config = {col: st.column_config.NumberColumn(col, format="%d") for col in stock_columns}
    config.update({col: st.column_config.NumberColumn(col, format="%.2f") for col in amount_columns})
    return config


def available_inventory_monitor_column_config(df: pd.DataFrame):
    return {
        "库存总数": st.column_config.NumberColumn("库存总数", format="%.2f"),
        "日均订单": st.column_config.NumberColumn("日均订单", format="%.2f"),
        "总可售天数": st.column_config.NumberColumn("总可售天数", format="%.2f"),
    }


def available_inventory_monitor_styler(df: pd.DataFrame):
    def style_row(row):
        styles = []
        for col, value in row.items():
            style = ""
            if col == "总可售天数":
                numeric = pd.to_numeric(value, errors="coerce")
                if pd.notna(numeric) and numeric > 120:
                    style = "background-color: #fecaca; color: #7f1d1d; font-weight: 700;"
                elif pd.notna(numeric) and numeric > 90:
                    style = "background-color: #fef3c7; color: #78350f; font-weight: 700;"
            styles.append(style)
        return styles

    return df.style.apply(style_row, axis=1)


def department_performance_column_config(df: pd.DataFrame):
    config = {
        "在售产品数": st.column_config.NumberColumn("在售产品数", format="%d"),
        "销售额贡献占比": st.column_config.NumberColumn("销售额贡献占比", format="percent"),
        "近7天日均订单": st.column_config.NumberColumn("近7天日均订单", format="%.2f"),
        "近7天日均销售额（元）": st.column_config.NumberColumn("近7天日均销售额（元）", format="%.2f"),
        "预估本月销售额（元）": st.column_config.NumberColumn("预估本月销售额（元）", format="%.2f"),
    }
    for col in df.columns:
        if col.endswith("销量"):
            config[col] = st.column_config.NumberColumn(col, format="%d")
        elif col.endswith("销售额（元）"):
            config[col] = st.column_config.NumberColumn(col, format="%.2f")
    return config


def department_performance_styler(df: pd.DataFrame):
    numeric_formats = {}
    for col in df.columns:
        if col == "销售额贡献占比":
            numeric_formats[col] = "{:.2%}"
        elif col == "在售产品数" or col.endswith("销量"):
            numeric_formats[col] = "{:.0f}"
        elif col in {"近7天日均订单", "近7天日均销售额（元）", "预估本月销售额（元）"} or col.endswith("销售额（元）"):
            numeric_formats[col] = "{:.2f}"

    def highlight_summary(row):
        if row.name == 0:
            return ["background-color: #fde68a; color: #111827; font-weight: 700;" for _ in row]
        return ["" for _ in row]

    return df.style.format(numeric_formats, na_rep="").apply(highlight_summary, axis=1)


def compact_amount(value) -> str:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return ""
    if abs(numeric) >= 10000:
        return f"{numeric / 10000:.1f}万"
    return f"{numeric:.0f}" if float(numeric).is_integer() else f"{numeric:.1f}"


def compact_number(value, decimals: int = 0) -> str:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return ""
    if decimals:
        return f"{numeric:.{decimals}f}"
    return f"{numeric:.0f}"


def compact_percent(value) -> str:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return ""
    if abs(numeric - 1) < 0.000001:
        return "100%"
    return f"{numeric:.1%}"


def department_performance_compact_html(title: str, df: pd.DataFrame) -> str:
    date_labels = []
    for col in df.columns:
        if col.endswith("销量") and "月" in col:
            label = col.removesuffix("销量")
            amount_col = f"{label}销售额（元）"
            if amount_col in df.columns:
                date_labels.append(label)

    fixed_headers = [
        ("开发员", "开发员"),
        ("在售产品数", "在售<br>产品数"),
        ("销售额贡献占比", "销售额<br>贡献占比"),
        ("近7天日均订单", "近7天<br>日均订单"),
        ("近7天日均销售额（元）", "近7天日均<br>销售额"),
        ("预估本月销售额（元）", "预估本月<br>销售额"),
    ]
    colspan = len(fixed_headers) + len(date_labels) * 2
    parts = [
        """
        <style>
        .dept-perf-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            margin: 0.25rem 0 1rem 0;
            font-size: 0.76rem;
            line-height: 1.15;
            background: #f8fafc;
            color: #050505;
        }
        .dept-perf-table th,
        .dept-perf-table td {
            border: 1px solid #1f2937;
            padding: 0.22rem 0.25rem;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: clip;
        }
        .dept-perf-table .title {
            background: #c7ece9;
            font-size: 1.05rem;
            font-weight: 800;
            padding: 0.38rem;
        }
        .dept-perf-table .fixed-head,
        .dept-perf-table .date-head,
        .dept-perf-table .sub-head {
            background: #d8f1ef;
            font-weight: 800;
        }
        .dept-perf-table .summary td {
            background: #fff200;
            font-weight: 800;
        }
        .dept-perf-table .metric {
            background: #fff7d6;
        }
        .dept-perf-table .name-col { width: 5.6%; }
        .dept-perf-table .small-col { width: 5.1%; }
        .dept-perf-table .mid-col { width: 6.1%; }
        .dept-perf-table .daily-col { width: 4.45%; }
        </style>
        """,
        '<table class="dept-perf-table">',
        f'<thead><tr><th class="title" colspan="{colspan}">{html.escape(title)}业绩排行榜</th></tr>',
        "<tr>",
    ]
    for idx, (_, label) in enumerate(fixed_headers):
        cls = "name-col" if idx == 0 else ("mid-col" if idx >= 3 else "small-col")
        parts.append(f'<th class="fixed-head {cls}" rowspan="2">{label}</th>')
    for label in date_labels:
        parts.append(f'<th class="date-head" colspan="2">{html.escape(label)}</th>')
    parts.append("</tr><tr>")
    for _ in date_labels:
        parts.append('<th class="sub-head daily-col">销量</th><th class="sub-head daily-col">销售额</th>')
    parts.append("</tr></thead><tbody>")

    for row_index, row in df.iterrows():
        row_class = ' class="summary"' if row_index == 0 else ""
        parts.append(f"<tr{row_class}>")
        parts.append(f"<td>{html.escape(str(row['开发员']))}</td>")
        parts.append(f"<td class=\"metric\">{compact_number(row.get('在售产品数'))}</td>")
        parts.append(f"<td class=\"metric\">{compact_percent(row.get('销售额贡献占比'))}</td>")
        parts.append(f"<td class=\"metric\">{compact_number(row.get('近7天日均订单'), 0)}</td>")
        parts.append(f"<td class=\"metric\">{compact_amount(row.get('近7天日均销售额（元）'))}</td>")
        parts.append(f"<td class=\"metric\">{compact_amount(row.get('预估本月销售额（元）'))}</td>")
        for label in date_labels:
            parts.append(f"<td>{compact_number(row.get(f'{label}销量'))}</td>")
            parts.append(f"<td>{compact_amount(row.get(f'{label}销售额（元）'))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def plot_sales_bar(df, x, y, title):
    if df.empty or x not in df.columns or y not in df.columns:
        return
    chart_data = df[df[y].fillna(0).ne(0)].copy()
    if chart_data.empty:
        return
    fig = px.bar(chart_data, x=x, y=y, title=title)
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=45, b=10))
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=chart_data[x].tolist())
    st.plotly_chart(fig, use_container_width=True)


def commission_metric_lookup(metric_lookup):
    result = metric_lookup.copy()
    result.update(
        {
            "营业额": {"格式": "金额"},
            "毛利润": {"格式": "金额"},
            "毛利率": {"格式": "百分比"},
            "费用率": {"格式": "百分比"},
            "库存计提": {"格式": "金额"},
            "弃置": {"格式": "金额"},
            "职位提点": {"格式": "百分比"},
            "提成预估": {"格式": "金额"},
            "库存计提分摊": {"格式": "金额"},
            "弃置分摊": {"格式": "金额"},
            "缺提成预估": {"格式": "金额"},
            "缺配置月份数": {"格式": "整数"},
        }
    )
    return result


def render_commission_dashboard(counted, stopped, metric_config_df, commission_config_df, department_fee_config_df, metric_lookup):
    st.subheader("提成预估")
    commission_lookup = commission_metric_lookup(metric_lookup)
    try:
        detail = compute_commission_table(counted, metric_config_df, commission_config_df, department_fee_config_df)
    except Exception as exc:
        st.error(f"提成预估无法计算：{exc}")
        return

    if detail.empty:
        st.info("当前计入范围内暂无可计算的提成数据。")
    else:
        missing = detail[detail["配置状态"].ne("已配置")]
        if not missing.empty:
            labels = [f"{month_label(row['月份'])} - {row['开发员']}" for _, row in missing.head(12).iterrows()]
            suffix = " 等" if len(missing) > 12 else ""
            st.warning("以下月份和开发员缺少完整提成配置，暂不计算提成：" + "；".join(labels) + suffix)

        numeric_detail = detail.copy()
        for col in ["营业额", "毛利润", "毛利率", "费用率", "库存计提", "弃置", "职位提点", "提成预估"]:
            numeric_detail[col] = pd.to_numeric(numeric_detail[col], errors="coerce")
        numeric_detail["_缺配置"] = numeric_detail["配置状态"].ne("已配置")

        summary = (
            numeric_detail.groupby("开发员", dropna=False, as_index=False)
            .agg(
                营业额=("营业额", "sum"),
                毛利润=("毛利润", "sum"),
                提成预估=("提成预估", lambda values: values.sum(min_count=1)),
                缺配置月份数=("_缺配置", "sum"),
            )
            .sort_values("提成预估", ascending=False, na_position="last")
        )
        summary["毛利率"] = summary.apply(
            lambda row: row["毛利润"] / row["营业额"] if pd.notna(row["营业额"]) and row["营业额"] else pd.NA,
            axis=1,
        )
        summary = summary[["开发员", "营业额", "毛利润", "毛利率", "提成预估", "缺配置月份数"]]

        chart_data = summary.dropna(subset=["提成预估"])
        if not chart_data.empty:
            chart_if_available(chart_data, "开发员", "提成预估", title="开发员提成预估")
        render_metric_dataframe(summary, commission_lookup)

        detail_display = detail.copy()
        detail_display["月份"] = detail_display["月份"].map(month_label)
        render_metric_dataframe(detail_display, commission_lookup)

    st.markdown("**停提款店铺缺提成**")
    try:
        stopped_detail = compute_stopped_commission_table(stopped, metric_config_df, commission_config_df, department_fee_config_df)
    except Exception as exc:
        st.error(f"停提款店铺缺提成无法计算：{exc}")
        return
    if stopped_detail.empty:
        st.info("当前筛选范围内没有停提款店铺数据。")
        return
    stopped_missing = stopped_detail[stopped_detail["配置状态"].ne("已配置")]
    if not stopped_missing.empty:
        labels = [f"{month_label(row['月份'])} - {row['开发员']}" for _, row in stopped_missing.head(12).iterrows()]
        suffix = " 等" if len(stopped_missing) > 12 else ""
        st.warning("以下停提款店铺缺少完整提成配置，暂不计算缺提成：" + "；".join(labels) + suffix)
    stopped_display = stopped_detail.copy()
    stopped_display["月份"] = stopped_display["月份"].map(month_label)
    stopped_display["停提款时间"] = stopped_display["停提款时间"].map(month_label)
    render_metric_dataframe(stopped_display, commission_lookup)


def render_developer_store_type_pies(filtered, metric_config_df):
    try:
        sales_metric = select_metric_config(metric_config_df, ["销售额"])
        store_type_table = compute_metric_table(filtered, sales_metric, ["销售专员", "店铺类型"])
    except Exception as exc:
        st.warning(f"店铺类型占比无法计算：{exc}")
        return

    if store_type_table.empty or "销售额" not in store_type_table.columns:
        return
    totals = store_type_table.groupby("销售专员", as_index=False)["销售额"].sum().sort_values("销售额", ascending=False)
    developers = totals["销售专员"].tolist()
    for offset in range(0, len(developers), 3):
        cols = st.columns(3)
        for col, developer in zip(cols, developers[offset : offset + 3]):
            chart_data = store_type_table[store_type_table["销售专员"].eq(developer)].copy()
            chart_data = chart_data[chart_data["销售额"].fillna(0).ne(0)]
            if chart_data.empty:
                continue
            fig = px.pie(chart_data, names="店铺类型", values="销售额", title=str(developer), hole=0.35)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=45, b=10), showlegend=True)
            col.plotly_chart(fig, use_container_width=True)


def add_month_display(df):
    result = df.copy()
    if "月份" in result.columns:
        result["月份显示"] = result["月份"].map(month_label)
    return result


def render_config_template(title: str, path: Path, description: str, file_name: str):
    st.caption(description)
    try:
        template_bytes = path.read_text(encoding="utf-8").encode("utf-8-sig")
        template_df = read_local_table(path).head(6).fillna("")
    except Exception as exc:
        st.warning(f"{title}模板读取失败：{exc}")
        return

    st.download_button(
        f"下载{title}模板 CSV",
        data=template_bytes,
        file_name=file_name,
        mime="text/csv",
        key=f"download_{file_name}",
        use_container_width=True,
    )
    with st.expander(f"查看{title}模板字段/示例", expanded=False):
        st.dataframe(template_df, use_container_width=True, hide_index=True)


def load_local_config(path: Path, normalizer):
    try:
        return normalizer(read_local_table(path)).fillna("")
    except Exception:
        return normalizer(pd.DataFrame()).fillna("")


def merge_config_rows(existing, discovered, key_col):
    combined = pd.concat([existing, discovered], ignore_index=True)
    combined = combined[combined[key_col].astype(str).str.strip().ne("")]
    return combined.drop_duplicates(subset=[key_col], keep="first").reset_index(drop=True)


def merge_config_rows_by_keys(existing, discovered, key_cols):
    combined = pd.concat([existing, discovered], ignore_index=True)
    for key_col in key_cols:
        combined = combined[combined[key_col].astype(str).str.strip().ne("")]
    return combined.drop_duplicates(subset=key_cols, keep="first").reset_index(drop=True)


def prepare_commission_editor_df(commission_config):
    editor_df = commission_config.copy()
    for col in ["月份", "开发员", "库存计提", "弃置", "职位提点"]:
        if col in editor_df.columns:
            editor_df[col] = editor_df[col].fillna("").astype(str)
    return editor_df


def commission_editor_column_config(reports):
    month_options = [""] + sorted(reports["月份"].dropna().unique().tolist()) if reports is not None and not reports.empty else [""]
    return {
        "月份": st.column_config.SelectboxColumn(
            "月份",
            options=month_options,
            format_func=lambda value: "" if not value else month_label(value),
            required=True,
        ),
        "开发员": st.column_config.TextColumn("开发员", required=True),
        "库存计提": st.column_config.TextColumn("库存计提"),
        "弃置": st.column_config.TextColumn("弃置"),
        "职位提点": st.column_config.TextColumn("职位提点", help="可填 8%、0.08 或 8。"),
    }


def prepare_department_fee_editor_df(department_fee_config):
    editor_df = department_fee_config.copy()
    for col in ["月份", "部门", "费用率"]:
        if col in editor_df.columns:
            editor_df[col] = editor_df[col].fillna("").astype(str)
    return editor_df


def prepare_target_editor_df(target_config):
    editor_df = target_config.copy()
    for col in ["开发员", "目标业绩", "目标毛利率"]:
        if col in editor_df.columns:
            editor_df[col] = editor_df[col].fillna("").astype(str)
    return editor_df


def target_editor_column_config():
    return {
        "开发员": st.column_config.TextColumn("开发员", required=True),
        "目标业绩": st.column_config.TextColumn("目标业绩"),
        "目标毛利率": st.column_config.TextColumn("目标毛利率", help="可填 22%、0.22 或 22。"),
    }


def build_discovered_store_config(reports):
    if reports is None or reports.empty:
        return normalize_store_config(pd.DataFrame()).fillna("")
    stores = (
        reports[["店铺编码"]]
        .dropna()
        .drop_duplicates()
        .rename(columns={"店铺编码": "店铺名"})
        .sort_values("店铺名")
    )
    stores["店铺类型"] = ""
    stores["停提款时间"] = ""
    stores["店铺所属部门"] = ""
    return normalize_store_config(stores).fillna("")


def build_discovered_target_config(reports):
    if reports is None or reports.empty:
        return normalize_target_config(pd.DataFrame()).fillna("")
    developers = (
        reports[["销售专员"]]
        .dropna()
        .drop_duplicates()
        .rename(columns={"销售专员": "开发员"})
        .sort_values("开发员")
    )
    developers["目标业绩"] = ""
    developers["目标毛利率"] = ""
    return normalize_target_config(developers).fillna("")


def render_business_config_editors(reports=None):
    local_store = load_local_config(STORE_CONFIG_PATH, normalize_store_config)
    local_target = load_local_config(TARGET_CONFIG_PATH, normalize_target_config)
    local_commission = load_local_config(COMMISSION_CONFIG_PATH, normalize_commission_config)
    local_department_fee = load_local_config(DEPARTMENT_FEE_CONFIG_PATH, normalize_department_fee_config)
    store_config = merge_config_rows(local_store, build_discovered_store_config(reports), "店铺名")
    target_config = merge_config_rows(local_target, build_discovered_target_config(reports), "开发员")
    reports_with_store = None
    if reports is not None and not reports.empty:
        reports_with_store = merge_business_config(reports, store_config, target_config)
    department_fee_config = merge_config_rows_by_keys(
        local_department_fee, build_discovered_department_fee_config(reports_with_store), ["月份", "部门"]
    ).sort_values(["月份", "部门"])
    commission_config = merge_config_rows_by_keys(
        local_commission, build_discovered_commission_config(reports), ["月份", "开发员"]
    ).sort_values(["月份", "开发员"])

    st.caption("报表里出现的新店铺和开发员会自动补到表格中，点击保存后写入本地配置。")
    st.markdown("**店铺配置**")
    edited_store = st.data_editor(
        store_config,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="store_config_editor",
        column_config={
            "店铺类型": st.column_config.SelectboxColumn("店铺类型", options=["", "中企", "本土", "其他"]),
            "停提款时间": st.column_config.SelectboxColumn(
                "停提款时间",
                options=[""] + sorted(reports["月份"].dropna().unique().tolist()) if reports is not None and not reports.empty else [""],
                format_func=lambda value: "" if not value else month_label(value),
            ),
        },
    )
    if st.button("保存店铺配置", use_container_width=True):
        saved = normalize_store_config(edited_store).fillna("")
        saved.to_csv(STORE_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("店铺配置已保存。")

    st.markdown("**目标配置**")
    edited_target = st.data_editor(
        prepare_target_editor_df(target_config),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="target_config_editor",
        column_config=target_editor_column_config(),
    )
    if st.button("保存目标配置", use_container_width=True):
        saved = normalize_target_config(edited_target).fillna("")
        saved.to_csv(TARGET_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("目标配置已保存。")

    st.markdown("**部门费用率配置**")
    st.caption("按月份和店铺所属部门维护费用率；可填 8%、0.08 或 8。提成计算会按店铺所属部门套用对应费用率。")
    edited_department_fee = st.data_editor(
        prepare_department_fee_editor_df(department_fee_config),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="department_fee_config_editor",
        column_config={
            "月份": st.column_config.SelectboxColumn(
                "月份",
                options=[""] + sorted(reports["月份"].dropna().unique().tolist()) if reports is not None and not reports.empty else [""],
                format_func=lambda value: "" if not value else month_label(value),
            ),
        },
    )
    if st.button("保存部门费用率配置", use_container_width=True):
        saved = normalize_department_fee_config(edited_department_fee).fillna("")
        saved.to_csv(DEPARTMENT_FEE_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("部门费用率配置已保存。")

    st.markdown("**提成配置**")
    st.caption("按月份和开发员维护库存计提、弃置和职位提点；职位提点可填 8%、0.08 或 8。")
    edited_commission = st.data_editor(
        prepare_commission_editor_df(commission_config),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="commission_config_editor",
        column_config=commission_editor_column_config(reports),
    )
    if st.button("保存提成配置", use_container_width=True):
        saved = normalize_commission_config(edited_commission).fillna("")
        saved.to_csv(COMMISSION_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("提成配置已保存。")

    return (
        normalize_store_config(edited_store),
        normalize_target_config(edited_target),
        normalize_commission_config(edited_commission),
    )


def process_report_uploads(report_files):
    if not report_files:
        return
    processed = st.session_state.setdefault("processed_report_uploads", set())
    pending = []
    for uploaded_file in report_files:
        data = uploaded_file.getvalue()
        fingerprint = f"{uploaded_file.name}:{len(data)}:{hashlib.sha256(data).hexdigest()}"
        if fingerprint not in processed:
            pending.append((uploaded_file, fingerprint))
    if not pending:
        return
    results = persist_uploaded_reports([uploaded_file for uploaded_file, _ in pending])
    for _, fingerprint in pending:
        processed.add(fingerprint)
    for result in results:
        action = "已替换" if result.replaced else "已保存"
        st.success(f"{action} {result.month}：{result.original_name}")


def process_operational_sales_upload(uploaded_file):
    if uploaded_file is None:
        return
    data = uploaded_file.getvalue()
    fingerprint = f"{uploaded_file.name}:{len(data)}:{hashlib.sha256(data).hexdigest()}"
    if st.session_state.get("processed_operational_sales_upload") == fingerprint:
        return
    load_operational_sales_source(uploaded_file)
    persist_operational_sales_source(uploaded_file)
    st.session_state["processed_operational_sales_upload"] = fingerprint
    st.success(f"已保存运营原始表：{uploaded_file.name}")


def process_latest_source_upload(uploaded_file, source_key: str, display_name: str, validator):
    if uploaded_file is None:
        return
    data = uploaded_file.getvalue()
    fingerprint = f"{uploaded_file.name}:{len(data)}:{hashlib.sha256(data).hexdigest()}"
    state_key = f"processed_{source_key}_upload"
    if st.session_state.get(state_key) == fingerprint:
        return
    validator(read_upload_table(uploaded_file))
    persist_latest_source(uploaded_file, source_key, display_name)
    st.session_state[state_key] = fingerprint
    st.success(f"已保存{display_name}：{uploaded_file.name}")


def render_operational_sales_source_record():
    render_latest_source_record("运营原始表", load_operational_sales_source_record())


def render_latest_source_record(title: str, record: pd.DataFrame):
    st.subheader(f"已上传{title}")
    if record.empty:
        st.info(f"暂无已保存的{title}。上传 XLS/XLSX 后刷新或重新打开也会保留。")
        return

    display = record.copy()
    display["文件大小"] = pd.to_numeric(display["文件大小"], errors="coerce").map(
        lambda value: "-" if pd.isna(value) else f"{value / 1024:.1f} KB"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_upload_records(records):
    st.subheader("已上传报表记录")
    if records.empty:
        st.info("暂无已保存的业绩报表。上传 CSV 后刷新或重新打开也会保留。")
        return

    display = records.copy()
    display["月份"] = display["月份"].map(month_label)
    display["文件大小"] = pd.to_numeric(display["文件大小"], errors="coerce").map(
        lambda value: "-" if pd.isna(value) else f"{value / 1024:.1f} KB"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)

    months = records["月份"].tolist()
    month_to_delete = st.selectbox(
        "删除上传记录",
        [""] + months,
        format_func=lambda value: "请选择要删除的月份" if not value else month_label(value),
    )
    if st.button("删除所选月份记录", disabled=not month_to_delete):
        delete_upload_record(month_to_delete)
        st.success(f"已删除 {month_label(month_to_delete)} 上传记录。")
        st.rerun()


def load_dashboard_data(records):
    if records.empty:
        return None
    reports = load_reports_from_records(records)
    store_config, target_config = load_business_config()
    return merge_business_config(reports, store_config, target_config)


def render_home_filters(data):
    st.markdown(
        """
        <style>
        .st-key-home_filter_bar {
            position: sticky;
            top: 0;
            z-index: 999;
            background: color-mix(in srgb, var(--background-color) 94%, transparent);
            border: 1px solid color-mix(in srgb, var(--text-color) 14%, transparent);
            border-radius: 8px;
            padding: 0.75rem 0.75rem 0.25rem 0.75rem;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.16);
            backdrop-filter: blur(10px);
        }
        .st-key-home_filter_bar * {
            color: var(--text-color);
        }
        .st-key-home_filter_bar [data-baseweb="tag"] span {
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="home_filter_bar"):
        st.markdown("**筛选条件**")
        col1, col2, col3, col4 = st.columns(4)
        months = sorted(data["月份"].dropna().unique().tolist()) if "月份" in data.columns else []
        developers = sorted(data["销售专员"].dropna().unique().tolist()) if "销售专员" in data.columns else []
        departments = sorted(data["部门"].dropna().unique().tolist()) if "部门" in data.columns else []
        store_types = sorted(data["店铺类型"].dropna().unique().tolist()) if "店铺类型" in data.columns else []

        selected_months = col1.multiselect("月份", months, default=[], format_func=month_label)
        selected_developers = col2.multiselect("开发员", developers, default=default_chen_developers(developers))
        selected_departments = col3.multiselect("店铺所属部门", departments, default=departments)
        selected_store_types = col4.multiselect("店铺类型", store_types, default=store_types)

    return apply_home_filters(data, selected_months, selected_developers, selected_departments, selected_store_types)


def validate_metric_formulas(filtered, metric_config_df):
    errors = []
    for _, metric in metric_config_df.iterrows():
        try:
            compute_metric_table(filtered, metric_config_df[metric_config_df["指标名称"] == metric["指标名称"]], [])
        except Exception as exc:
            errors.append(f"{metric['指标名称']}：{exc}")
    return errors


def render_home_page(data, metric_config_df, metric_lookup, commission_config_df, department_fee_config_df):
    st.title("首页")
    if data is None or data.empty:
        st.info("暂无可分析的业绩报表，请先到“上传中心”上传 CSV。")
        return

    filtered = render_home_filters(data)
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return
    counted, stopped = split_counted_and_stopped_data(filtered)
    if counted.empty:
        st.warning("当前筛选条件下的常规看板没有计入数据；如存在停提款店铺数据，可在提成预估板块查看。")

    errors = validate_metric_formulas(counted, metric_config_df) if not counted.empty else []
    if errors:
        st.error("部分公式无法计算：\n\n" + "\n".join(f"- {e}" for e in errors))
        return

    overview_metrics = metrics_for_group(metric_config_df, "总览", fallback_to_overview=False)
    overview = compute_metric_table(counted, overview_metrics, [])
    st.subheader("总览 KPI")
    show_metric_cards(overview, metric_lookup)

    trend_metrics = metrics_for_group(metric_config_df, "趋势")
    trend = compute_metric_table(counted, trend_metrics, ["月份"])
    trend = trend.sort_values("月份") if "月份" in trend.columns else trend
    trend_chart = add_month_display(trend)
    trend_display = trend_chart.drop(columns=["月份"], errors="ignore")

    st.subheader("月度趋势")
    if "销售额" in trend.columns:
        chart_if_available(trend_chart, "月份显示", "销售额", title="月度销售额趋势", kind="line")
    render_metric_dataframe(trend_display, metric_lookup)

    developer_metrics = metrics_for_group(metric_config_df, "开发员分析")
    developer_table = compute_metric_table(counted, developer_metrics, ["销售专员"])
    developer_table = developer_table.sort_values(by="销售额", ascending=False) if "销售额" in developer_table.columns else developer_table

    st.subheader("开发员分析")
    if "销售额" in developer_table.columns:
        chart_if_available(developer_table.head(15), "销售专员", "销售额", title="开发员销售额排行")
    render_developer_store_type_pies(counted, metric_config_df)
    render_metric_dataframe(developer_table, metric_lookup)

    render_commission_dashboard(counted, stopped, metric_config_df, commission_config_df, department_fee_config_df, metric_lookup)

    store_metrics = metrics_for_group(metric_config_df, "店铺分析")
    store_table = compute_metric_table(counted, store_metrics, ["部门", "店铺编码", "店铺类型"])
    store_table = store_table.sort_values(by="销售额", ascending=False) if "销售额" in store_table.columns else store_table

    st.subheader("店铺分析")
    if "销售额" in store_table.columns:
        chart_if_available(store_table.head(20), "店铺编码", "销售额", color="部门", title="店铺销售额排行")
    render_metric_dataframe(store_table, metric_lookup)

    developer_store_metrics = metrics_for_group(metric_config_df, "开发员店铺分析")
    developer_store_table = compute_metric_table(counted, developer_store_metrics, ["店铺编码", "店铺类型"])
    if "销售额" in developer_store_table.columns:
        developer_store_table = developer_store_table.sort_values(by="销售额", ascending=False)
        total_sales = developer_store_table["销售额"].sum()
        developer_store_table["销售额占比"] = developer_store_table["销售额"] / total_sales if total_sales else 0
        metric_lookup["销售额占比"] = {"格式": "百分比"}

    st.subheader("开发员 + 店铺分析")
    if "销售额" in developer_store_table.columns:
        chart_if_available(developer_store_table.head(20), "店铺编码", "销售额", color="店铺类型", title="所选范围店铺销售额排行")
    render_metric_dataframe(developer_store_table, metric_lookup)

    alerts = build_alerts(developer_store_table)
    st.subheader("异常预警")
    if alerts.empty:
        st.success("当前筛选范围内未发现默认预警项。")
    else:
        render_metric_dataframe(alerts, metric_lookup)

    csv = developer_store_table.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出开发员+店铺明细 CSV",
        data=csv,
        file_name="developer_store_dashboard.csv",
        mime="text/csv",
    )


def render_sales_dashboard_page():
    st.title("销量看板")
    source_path = get_operational_sales_source_path()
    if source_path is None:
        st.info("暂无可分析的运营原始表，请先到“上传中心”上传运营原始表 XLS/XLSX。")
        return

    try:
        operational_data = load_operational_sales_source(source_path)
        store_config, _ = load_business_config()
        tables = build_sales_dashboard_tables(operational_data, store_config)
    except Exception as exc:
        st.error(f"销量看板无法读取或计算：{exc}")
        return

    developer_options = sorted(
        operational_data.loc[operational_data["开发员"].astype(str).str.strip().ne(""), "开发员"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )
    if developer_options:
        with st.container(key="sales_filter_bar"):
            selected_developers = st.multiselect("开发员", developer_options, default=default_chen_developers(developer_options))
        if not selected_developers:
            st.warning("请选择至少一个开发员。")
            return
        operational_data = operational_data[operational_data["开发员"].isin(selected_developers)].copy()
        try:
            tables = build_sales_dashboard_tables(operational_data, store_config)
        except Exception as exc:
            st.error(f"销量看板无法按筛选条件计算：{exc}")
            return

    source = tables["source"]
    stores = tables["stores"]
    levels = tables["levels"]
    date_compare = tables["date_compare"]
    metric_lookup = sales_metric_lookup()

    if source.empty or stores.empty:
        st.warning("运营原始表中没有可展示的数据。")
        return

    multi_store_count = source.loc[source["是否多店铺编码"], "MSKU"].nunique()
    if multi_store_count:
        st.warning(f"检测到 {multi_store_count} 个 MSKU 同时关联多个不同店铺编码，已按店铺编码分别计入。")

    total_onsale = stores["在售个数"].sum()
    total_yesterday = stores["昨日订单"].sum()
    total_26_orders = stores["-26订单"].sum()
    total_7_avg = stores["7天日均"].sum()
    total_30_avg = stores["30天日均"].sum()
    total_stock = stores["总库存"].sum()
    kpi_cols = st.columns(6)
    kpi_cols[0].metric("在售个数", f"{total_onsale:,.0f}")
    kpi_cols[1].metric("昨日订单", f"{total_yesterday:,.0f}")
    kpi_cols[2].metric("-26订单", f"{total_26_orders:,.0f}")
    kpi_cols[3].metric("7天日均", f"{total_7_avg:,.2f}")
    kpi_cols[4].metric("30天日均", f"{total_30_avg:,.2f}")
    kpi_cols[5].metric("总库存", f"{total_stock:,.0f}")

    chart_cols = st.columns(3)
    with chart_cols[0]:
        plot_sales_bar(stores, "店铺编码", "昨日订单", "昨日店铺订单量")
    with chart_cols[1]:
        plot_sales_bar(stores, "店铺编码", "-26订单", "-26订单量")
    with chart_cols[2]:
        plot_sales_bar(stores, "店铺编码", "30天日均", "30天店铺日均订单量")

    table_cols = st.columns([1.15, 0.85])
    with table_cols[0]:
        st.subheader("店铺明细")
        render_metric_dataframe(stores, metric_lookup)
    with table_cols[1]:
        st.subheader("产品等级")
        render_metric_dataframe(levels, metric_lookup)
        st.subheader("日期对比")
        render_metric_dataframe(date_compare, metric_lookup)

    csv = stores.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出销量看板店铺明细 CSV",
        data=csv,
        file_name="sales_dashboard_store_detail.csv",
        mime="text/csv",
    )


def render_slow_moving_inventory_page():
    st.title("滞销提醒")
    source_path = get_operational_sales_source_path()
    if source_path is None:
        st.info("暂无可分析的运营原始表，请先到“上传中心”上传运营原始表 XLS/XLSX。")
        return

    try:
        operational_data = read_local_table(source_path)
    except Exception as exc:
        st.error(f"运营原始表读取失败：{exc}")
        return

    developer_options = sorted(
        operational_data.loc[operational_data["开发员"].astype(str).str.strip().ne(""), "开发员"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    ) if "开发员" in operational_data.columns else []

    with st.container(key="slow_moving_filter_bar"):
        col1, col2 = st.columns([2, 1])
        selected_developers = col1.multiselect("开发员", developer_options, default=default_chen_developers(developer_options))
        discard_threshold = col2.selectbox("弃置费阈值", ["90天以上", "180天以上", "365天以上"], index=0)

    if developer_options and not selected_developers:
        st.warning("请选择至少一个开发员。")
        return
    if selected_developers:
        operational_data = operational_data[operational_data["开发员"].astype(str).isin(selected_developers)].copy()

    try:
        detail = build_slow_moving_inventory_table(operational_data, discard_threshold)
    except Exception as exc:
        st.error(f"滞销提醒无法计算：{exc}")
        return

    if detail.empty:
        st.info("当前筛选条件下没有 90 天以上库龄库存的 SKU。")
        return

    metric_lookup = slow_moving_metric_lookup()
    kpi_cols = st.columns(5)
    kpi_cols[0].metric("滞销SKU数", f"{len(detail):,.0f}")
    kpi_cols[1].metric("90天以上库存数", f"{detail['90天以上库存数合计'].sum():,.0f}")
    kpi_cols[2].metric("90天以上占用资金", f"{detail['90天以上占用资金合计'].sum():,.2f}")
    kpi_cols[3].metric("库存计提", f"{detail['库存计提'].sum():,.2f}")
    kpi_cols[4].metric("弃置费", f"{detail['弃置费'].sum():,.2f}")

    st.subheader("滞销 SKU 明细")
    st.dataframe(
        detail,
        use_container_width=True,
        hide_index=True,
        column_config=slow_moving_column_config(),
    )

    csv = detail.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出滞销SKU表格 CSV",
        data=csv,
        file_name=f"slow_moving_inventory_{discard_threshold}.csv",
        mime="text/csv",
    )


def render_department_monitor_page():
    st.title("部门监控")
    source_path = get_latest_source_path("operational_sales")
    if source_path is None:
        st.info("请先到“上传中心”上传运营原始表。")
        return

    try:
        operational_data = read_local_table(source_path)
    except Exception as exc:
        st.error(f"运营原始表读取失败：{exc}")
        return

    performance_paths = {
        "销量明细": get_latest_source_path("sales_volume_detail"),
        "销售额明细": get_latest_source_path("sales_amount_detail"),
    }
    missing_performance = [name for name, path in performance_paths.items() if path is None]
    if missing_performance:
        st.info("请先到“上传中心”上传：" + "、".join(missing_performance))
    else:
        try:
            volume_data = read_local_table(performance_paths["销量明细"])
            amount_data = read_local_table(performance_paths["销售额明细"])
            performance_tables = build_department_performance_tables(operational_data, volume_data, amount_data)
        except Exception as exc:
            st.error(f"部门业绩看板无法读取或计算：{exc}")
            performance_tables = {}

        for title, table in performance_tables.items():
            if table.empty:
                st.info(f"{title} 暂无可展示数据。")
                continue
            st.markdown(department_performance_compact_html(title, table), unsafe_allow_html=True)
            st.download_button(
                f"导出{title} CSV",
                data=table.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"department_performance_{title}.csv",
                mime="text/csv",
            )

    st.divider()
    st.subheader("可售天数监控")
    try:
        monitor_table = build_available_inventory_monitor_table(operational_data)
    except Exception as exc:
        st.error(f"可售天数监控无法计算：{exc}")
        return

    if monitor_table.empty:
        st.warning("当前运营原始表没有可展示的开发员可售天数监控数据。")
        return

    days_values = pd.to_numeric(monitor_table["总可售天数"], errors="coerce")
    kpi_cols = st.columns(3)
    kpi_cols[0].metric("开发员数", f"{len(monitor_table):,.0f}")
    kpi_cols[1].metric(">90天开发员", f"{days_values.gt(90).sum():,.0f}")
    kpi_cols[2].metric(">120天开发员", f"{days_values.gt(120).sum():,.0f}")

    st.caption("库存总数 = 可售 + 待调仓 + 调仓中 + 待入库 + 采购在途 + 本地库存 + 在途 + 计划入库；总可售天数 = 库存总数 / 日均订单。")
    st.dataframe(
        available_inventory_monitor_styler(monitor_table),
        use_container_width=True,
        hide_index=True,
        column_config=available_inventory_monitor_column_config(monitor_table),
    )

    csv = monitor_table.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出可售天数监控 CSV",
        data=csv,
        file_name="available_inventory_monitor.csv",
        mime="text/csv",
    )


def product_management_column_config():
    int_columns = ["可售数量", "昨天销量", "前天销量", "上前销量", "7天销量", "14天销量", "30天销量", "90天销量"]
    decimal_columns = ["可售天数", "日均销量", "销售额", "毛利润"]
    country_volume_columns = [f"{country}销量" for country in ["德国", "法国", "西班牙", "意大利"]]
    config = {col: st.column_config.NumberColumn(col, format="%d") for col in int_columns + country_volume_columns}
    config.update({col: st.column_config.NumberColumn(col, format="%.2f") for col in decimal_columns})
    return config


def low_margin_product_column_config():
    return {
        "销量": st.column_config.NumberColumn("销量", format="%d"),
        "销售额": st.column_config.NumberColumn("销售额", format="%.2f"),
        "毛利润": st.column_config.NumberColumn("毛利润", format="%.2f"),
    }


def product_management_percent_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    margin_columns = [col for col in df.columns if "毛利率" in str(col)]
    ad_columns = [col for col in df.columns if "广告费占比" in str(col)]
    return margin_columns, ad_columns


def product_management_percent_styler(df: pd.DataFrame):
    margin_columns, ad_columns = product_management_percent_columns(df)
    percent_columns = margin_columns + ad_columns

    def format_percent(value):
        if pd.isna(value):
            return ""
        try:
            return f"{float(value):.2%}"
        except (TypeError, ValueError):
            return str(value)

    def style_percent_cells(data: pd.DataFrame):
        styles = pd.DataFrame("", index=data.index, columns=data.columns)
        for col in margin_columns:
            numeric = pd.to_numeric(data[col], errors="coerce")
            styles.loc[numeric < 0.12, col] = "background-color: #fee2e2; color: #991b1b;"
            styles.loc[(numeric >= 0.12) & (numeric <= 0.20), col] = "background-color: #fef3c7; color: #92400e;"
            styles.loc[numeric > 0.20, col] = "background-color: #dcfce7; color: #166534;"
        for col in ad_columns:
            numeric = pd.to_numeric(data[col], errors="coerce")
            styles.loc[numeric > 0.10, col] = "background-color: #fee2e2; color: #991b1b;"
        return styles

    formatters = {col: format_percent for col in percent_columns}
    return df.style.format(formatters, na_rep="").apply(style_percent_cells, axis=None)


def load_replenishment_target_config() -> pd.DataFrame:
    if not REPLENISHMENT_TARGET_PATH.exists():
        return normalize_replenishment_targets(pd.DataFrame())
    return normalize_replenishment_targets(read_local_table(REPLENISHMENT_TARGET_PATH))


def save_replenishment_target_config(targets: pd.DataFrame):
    normalized = normalize_replenishment_targets(targets)
    REPLENISHMENT_TARGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(REPLENISHMENT_TARGET_PATH, index=False, encoding="utf-8-sig")


def load_replenishment_column_order() -> pd.DataFrame:
    if not REPLENISHMENT_COLUMN_ORDER_PATH.exists():
        return pd.DataFrame(columns=["列名", "排序"])
    data = read_local_table(REPLENISHMENT_COLUMN_ORDER_PATH)
    for col in ["列名", "排序"]:
        if col not in data.columns:
            data[col] = pd.NA
    data = data[["列名", "排序"]].copy()
    data["列名"] = data["列名"].fillna("").astype(str).str.strip()
    data["排序"] = pd.to_numeric(data["排序"], errors="coerce")
    data = data[data["列名"].ne("")].copy()
    return data.drop_duplicates(subset=["列名"], keep="last").reset_index(drop=True)


def save_replenishment_column_order(order_config: pd.DataFrame):
    config = normalize_replenishment_column_order(order_config, list(order_config["列名"]))
    REPLENISHMENT_COLUMN_ORDER_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.to_csv(REPLENISHMENT_COLUMN_ORDER_PATH, index=False, encoding="utf-8-sig")


def replenishment_column_order_from_columns(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"列名": list(columns), "排序": list(range(1, len(columns) + 1))},
        columns=["列名", "排序"],
    )


def normalize_replenishment_column_order(order_config: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    existing = order_config.copy() if order_config is not None else pd.DataFrame(columns=["列名", "排序"])
    for col in ["列名", "排序"]:
        if col not in existing.columns:
            existing[col] = pd.NA
    existing = existing[["列名", "排序"]].copy()
    existing["列名"] = existing["列名"].fillna("").astype(str).str.strip()
    existing["排序"] = pd.to_numeric(existing["排序"], errors="coerce")
    existing = existing[existing["列名"].isin(columns)].drop_duplicates(subset=["列名"], keep="last")
    order_lookup = existing.set_index("列名")["排序"].to_dict()
    rows = []
    for default_index, column in enumerate(columns, start=1):
        order_value = order_lookup.get(column)
        rows.append({"列名": column, "排序": default_index if pd.isna(order_value) else int(order_value)})
    return pd.DataFrame(rows).sort_values(["排序", "列名"], kind="stable").reset_index(drop=True)


def apply_replenishment_column_order(df: pd.DataFrame, order_config: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    normalized = normalize_replenishment_column_order(order_config, list(df.columns))
    ordered_columns = [col for col in normalized["列名"].tolist() if col in df.columns]
    remaining_columns = [col for col in df.columns if col not in ordered_columns]
    return df[ordered_columns + remaining_columns].copy()


def render_replenishment_column_order_editor(detail: pd.DataFrame) -> pd.DataFrame:
    saved_order = load_replenishment_column_order()
    normalized_order = normalize_replenishment_column_order(saved_order, list(detail.columns))
    with st.expander("列顺序配置"):
        st.caption("拖拽列名调整补货明细显示顺序，保存后刷新页面仍按该顺序显示。")
        available_columns = list(detail.columns)
        current_columns = normalized_order["列名"].tolist()
        preview_columns = st.session_state.get("replenishment_column_order_preview")
        if isinstance(preview_columns, list):
            preview_columns = [str(column) for column in preview_columns if str(column) in available_columns]
            if preview_columns:
                current_columns = normalize_replenishment_column_order(
                    replenishment_column_order_from_columns(preview_columns),
                    available_columns,
                )["列名"].tolist()
        dragged_columns = replenishment_column_order_component(
            columns=current_columns,
            key="replenishment_column_order_dragger",
            height=180,
            default=current_columns,
        )
        if isinstance(dragged_columns, list):
            column_names = {str(column) for column in available_columns}
            dragged_columns = [str(column) for column in dragged_columns if str(column) in column_names]
            st.session_state["replenishment_column_order_preview"] = dragged_columns
        else:
            dragged_columns = current_columns
        preview_order = normalize_replenishment_column_order(
            replenishment_column_order_from_columns(dragged_columns),
            available_columns,
        )
        col1, col2, _ = st.columns([1, 1, 4])
        if col1.button("保存列顺序", use_container_width=True):
            save_replenishment_column_order(preview_order)
            st.session_state.pop("replenishment_column_order_preview", None)
            st.success("列顺序已保存。")
            st.rerun()
        if col2.button("恢复默认顺序", use_container_width=True):
            if REPLENISHMENT_COLUMN_ORDER_PATH.exists():
                REPLENISHMENT_COLUMN_ORDER_PATH.unlink()
            st.session_state.pop("replenishment_column_order_preview", None)
            st.success("已恢复默认列顺序。")
            st.rerun()
    return preview_order


def merge_replenishment_target_config(base: pd.DataFrame, overrides: pd.DataFrame | None) -> pd.DataFrame:
    frames = [normalize_replenishment_targets(base)]
    if overrides is not None and not overrides.empty:
        frames.append(normalize_replenishment_targets(overrides))
    return normalize_replenishment_targets(pd.concat(frames, ignore_index=True))


def replenishment_targets_from_detail(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty or "ASIN" not in detail.columns or "目标可售天数" not in detail.columns:
        return normalize_replenishment_targets(pd.DataFrame())
    return normalize_replenishment_targets(detail[["ASIN", "目标可售天数"]])


def replenishment_targets_changed(previous: pd.DataFrame, current: pd.DataFrame) -> bool:
    previous_targets = replenishment_targets_from_detail(previous).set_index("ASIN")
    current_targets = replenishment_targets_from_detail(current).set_index("ASIN")
    if set(previous_targets.index) != set(current_targets.index):
        return True
    if previous_targets.empty and current_targets.empty:
        return False
    aligned_previous = previous_targets.sort_index()["目标可售天数"]
    aligned_current = current_targets.sort_index()["目标可售天数"]
    return not aligned_previous.equals(aligned_current)


def replenishment_column_config(editable: bool = False):
    int_columns = ["目标可售天数", "亚马逊可售库存数量", "总库存数量", "库龄超90天库存数"]
    decimal_columns = ["日均销量", "重量", "建议补货数量"]
    country_volume_columns = [f"{country}单量" for country in ["德国", "法国", "西班牙", "意大利"]]
    margin_columns = [f"{country}毛利率" for country in ["德国", "法国", "西班牙", "意大利"]]
    config = {col: st.column_config.NumberColumn(col, format="%d") for col in int_columns + country_volume_columns}
    config.update({col: st.column_config.NumberColumn(col, format="%.2f") for col in decimal_columns})
    config.update({col: st.column_config.NumberColumn(col, format="percent") for col in margin_columns})
    if editable:
        config["目标可售天数"] = st.column_config.NumberColumn(
            "目标可售天数",
            min_value=0,
            step=1,
            format="%d",
            help=f"缺失时默认 {DEFAULT_REPLENISHMENT_TARGET_DAYS} 天。",
        )
    return config


def replenishment_margin_styler(df: pd.DataFrame):
    margin_columns = [col for col in df.columns if "毛利率" in str(col)]

    def style_margin_cells(data: pd.DataFrame):
        styles = pd.DataFrame("", index=data.index, columns=data.columns)
        for col in margin_columns:
            numeric = pd.to_numeric(data[col], errors="coerce")
            styles.loc[numeric > 0.20, col] = "background-color: #dcfce7; color: #166534;"
            styles.loc[(numeric > 0.13) & (numeric < 0.20), col] = "background-color: #fef3c7; color: #92400e;"
            styles.loc[numeric < 0.13, col] = "background-color: #fee2e2; color: #991b1b;"
        return styles

    return df.style.apply(style_margin_cells, axis=None)


def render_replenishment_management_page():
    st.title("补货管理")
    source_paths = {
        "运营原始表": get_latest_source_path("operational_sales"),
        "毛利原始表": get_latest_source_path("gross_profit"),
        "Rating": get_latest_source_path("rating"),
    }
    missing = [name for name, path in source_paths.items() if path is None]
    if missing:
        st.info("请先到“上传中心”上传：" + "、".join(missing))
        return

    try:
        operational_data = read_local_table(source_paths["运营原始表"])
        gross_profit_data = read_local_table(source_paths["毛利原始表"])
        rating_data = read_local_table(source_paths["Rating"])
        saved_targets = load_replenishment_target_config()
        session_targets = st.session_state.get("replenishment_target_overrides")
        target_config = merge_replenishment_target_config(saved_targets, session_targets)

        if "开发员" in operational_data.columns:
            developer_series = operational_data["开发员"].fillna("").astype(str).str.strip()
            developer_options = sorted(developer_series[developer_series.ne("")].drop_duplicates().tolist())
            with st.container(key="replenishment_filter_bar"):
                selected_developers = st.multiselect("开发员", developer_options, default=default_chen_developers(developer_options))
            if developer_options and not selected_developers:
                st.warning("请选择至少一个开发员。")
                return
            if selected_developers:
                operational_data = operational_data[developer_series.isin(selected_developers)].copy()
        else:
            st.warning("运营原始表缺少“开发员”列，当前补货管理表无法按开发员筛选。")

        tables = build_replenishment_management_tables(operational_data, gross_profit_data, rating_data, target_config)
    except Exception as exc:
        st.error(f"补货管理无法读取或计算：{exc}")
        return

    detail = tables["detail"]
    store_distribution = tables["store_distribution"]
    if detail.empty:
        st.info("当前筛选条件下没有需要补货的 ASIN。")
        return

    total_replenishment = pd.to_numeric(detail["建议补货数量"], errors="coerce").fillna(0).sum()
    kpi_cols = st.columns(3)
    kpi_cols[0].metric("需补货ASIN数", f"{detail['ASIN'].nunique():,.0f}")
    kpi_cols[1].metric("预计补货总库存数", f"{total_replenishment:,.2f}")
    kpi_cols[2].metric("涉及店铺数", f"{store_distribution['店铺编码'].nunique() if not store_distribution.empty else 0:,.0f}")

    if not store_distribution.empty:
        plot_sales_bar(store_distribution, "店铺编码", "需补货ASIN数", "需补货 ASIN 店铺分布")
        st.dataframe(
            store_distribution,
            use_container_width=True,
            hide_index=True,
            column_config={"需补货ASIN数": st.column_config.NumberColumn("需补货ASIN数", format="%d")},
        )

    st.subheader("补货明细")
    column_order = render_replenishment_column_order_editor(detail)
    display_detail = apply_replenishment_column_order(detail, column_order)
    disabled_columns = [col for col in display_detail.columns if col != "目标可售天数"]
    edited_detail = st.data_editor(
        replenishment_margin_styler(display_detail),
        use_container_width=True,
        hide_index=True,
        disabled=disabled_columns,
        column_config=replenishment_column_config(editable=True),
        key="replenishment_target_editor",
    )
    if replenishment_targets_changed(display_detail, edited_detail):
        st.session_state["replenishment_target_overrides"] = merge_replenishment_target_config(
            target_config,
            replenishment_targets_from_detail(edited_detail),
        )
        st.rerun()

    save_cols = st.columns([1, 4])
    if save_cols[0].button("保存目标可售天数", use_container_width=True):
        save_replenishment_target_config(target_config)
        st.session_state.pop("replenishment_target_overrides", None)
        st.success("目标可售天数已保存。")
        st.rerun()

    csv = display_detail.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出补货管理表 CSV",
        data=csv,
        file_name="replenishment_management.csv",
        mime="text/csv",
    )


def render_product_management_page():
    st.title("产品管理")
    source_paths = {
        "运营原始表": get_latest_source_path("operational_sales"),
        "毛利原始表": get_latest_source_path("gross_profit"),
        "Rating": get_latest_source_path("rating"),
    }
    missing = [name for name, path in source_paths.items() if path is None]
    if missing:
        st.info("请先到“上传中心”上传：" + "、".join(missing))
        return

    try:
        operational_data = read_local_table(source_paths["运营原始表"])
        gross_profit_data = read_local_table(source_paths["毛利原始表"])
        rating_data = read_local_table(source_paths["Rating"])
        selected_developers = None
        if "开发员" in operational_data.columns:
            developer_series = operational_data["开发员"].fillna("").astype(str).str.strip()
            developer_options = sorted(developer_series[developer_series.ne("")].drop_duplicates().tolist())
            with st.container(key="product_management_filter_bar"):
                selected_developers = st.multiselect("开发员", developer_options, default=default_chen_developers(developer_options))
            if developer_options and not selected_developers:
                st.warning("请选择至少一个开发员。")
                return
            if selected_developers:
                operational_data = operational_data[developer_series.isin(selected_developers)].copy()
        else:
            st.warning("运营原始表缺少“开发员”列，当前产品管理表无法按开发员筛选。")
        product_table = build_product_management_table(operational_data, gross_profit_data, rating_data)
        low_margin_table = build_low_margin_product_table(gross_profit_data, developers=selected_developers)
    except Exception as exc:
        st.error(f"产品管理表无法读取或计算：{exc}")
        return

    if product_table.empty:
        st.warning("当前数据源没有可展示的产品管理数据。")
        return

    display_table = product_management_display_table(product_table)

    asin_count = display_table["ASIN"].nunique()
    sku_count = len(display_table)
    kpi_cols = st.columns(5)
    kpi_cols[0].metric("ASIN数", f"{asin_count:,.0f}")
    kpi_cols[1].metric("SKU数", f"{sku_count:,.0f}")
    kpi_cols[2].metric("可售数量", f"{pd.to_numeric(display_table['可售数量'], errors='coerce').sum():,.0f}")
    kpi_cols[3].metric("日均销量", f"{pd.to_numeric(display_table['日均销量'], errors='coerce').sum():,.2f}")
    kpi_cols[4].metric("30天销量", f"{pd.to_numeric(display_table['30天销量'], errors='coerce').sum():,.0f}")

    st.subheader("低毛利率 SKU")
    if low_margin_table.empty:
        st.info("当前毛利原始表中没有毛利率低于 15% 且出单数不少于 5 单的 SKU。")
    else:
        low_margin_sales = pd.to_numeric(low_margin_table["销售额"], errors="coerce").sum()
        low_margin_profit = pd.to_numeric(low_margin_table["毛利润"], errors="coerce").sum()
        low_margin_rate = low_margin_profit / low_margin_sales if low_margin_sales else pd.NA
        low_margin_kpis = st.columns(3)
        low_margin_kpis[0].metric("合计销售额", f"{low_margin_sales:,.2f}")
        low_margin_kpis[1].metric("合计毛利润", f"{low_margin_profit:,.2f}")
        low_margin_kpis[2].metric("合计毛利率", "-" if pd.isna(low_margin_rate) else f"{low_margin_rate:.2%}")

        st.dataframe(
            product_management_percent_styler(low_margin_table),
            use_container_width=True,
            hide_index=True,
            column_config=low_margin_product_column_config(),
        )
        low_margin_csv = low_margin_table.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "导出低毛利率表格 CSV",
            data=low_margin_csv,
            file_name="low_margin_products.csv",
            mime="text/csv",
        )

    st.subheader("产品管理明细")
    st.dataframe(
        product_management_percent_styler(display_table),
        use_container_width=True,
        hide_index=True,
        column_config=product_management_column_config(),
    )

    csv = display_table.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出产品管理表 CSV",
        data=csv,
        file_name="product_management.csv",
        mime="text/csv",
    )


def render_upload_center(records):
    st.title("上传中心")
    st.subheader("个人监控数据源")
    personal_cols = st.columns(2)
    with personal_cols[0]:
        operational_file = st.file_uploader("运营原始表 XLS/XLSX", type=["xls", "xlsx"], accept_multiple_files=False)
        try:
            process_operational_sales_upload(operational_file)
        except Exception as exc:
            st.error(f"运营原始表保存失败：{exc}")
        render_operational_sales_source_record()

    with personal_cols[1]:
        report_files = st.file_uploader("业绩报表 CSV", type=["csv"], accept_multiple_files=True)
        try:
            process_report_uploads(report_files)
        except Exception as exc:
            st.error(f"业绩报表保存失败：{exc}")
        render_upload_records(load_upload_records())

    personal_cols = st.columns(2)
    with personal_cols[0]:
        gross_profit_file = st.file_uploader("毛利原始表 CSV/XLS/XLSX", type=["csv", "xls", "xlsx"], accept_multiple_files=False, key="gross_profit_upload")
        try:
            process_latest_source_upload(gross_profit_file, "gross_profit", "毛利原始表", normalize_gross_profit_source)
        except Exception as exc:
            st.error(f"毛利原始表保存失败：{exc}")
        render_latest_source_record("毛利原始表", load_latest_source_record("gross_profit"))

    with personal_cols[1]:
        rating_file = st.file_uploader("Rating XLS/XLSX", type=["xls", "xlsx"], accept_multiple_files=False, key="rating_upload")
        try:
            process_latest_source_upload(rating_file, "rating", "Rating", normalize_rating_source)
        except Exception as exc:
            st.error(f"Rating保存失败：{exc}")
        render_latest_source_record("Rating", load_latest_source_record("rating"))

    st.divider()
    st.subheader("部门监控数据源")
    department_cols = st.columns(2)
    with department_cols[0]:
        sales_volume_file = st.file_uploader("销量明细 CSV", type=["csv"], accept_multiple_files=False, key="sales_volume_detail_upload")
        try:
            process_latest_source_upload(sales_volume_file, "sales_volume_detail", "销量明细", normalize_sales_volume_detail)
        except Exception as exc:
            st.error(f"销量明细保存失败：{exc}")
        render_latest_source_record("销量明细", load_latest_source_record("sales_volume_detail"))

    with department_cols[1]:
        sales_amount_file = st.file_uploader("销售额明细 CSV", type=["csv"], accept_multiple_files=False, key="sales_amount_detail_upload")
        try:
            process_latest_source_upload(sales_amount_file, "sales_amount_detail", "销售额明细", normalize_sales_amount_detail)
        except Exception as exc:
            st.error(f"销售额明细保存失败：{exc}")
        render_latest_source_record("销售额明细", load_latest_source_record("sales_amount_detail"))


def render_config_center(metric_config_df, records):
    st.title("配置中心")
    st.subheader("指标公式配置")
    metric_file = st.file_uploader("指标公式配置 CSV/XLSX", type=["csv", "xlsx"])
    render_config_template(
        "指标公式配置",
        METRIC_CONFIG_PATH,
        "维护看板指标名称、显示分组、计算公式、格式、排序和启用状态。",
        "指标公式配置模板.csv",
    )
    if metric_file is not None:
        try:
            load_metric_config(metric_file)
            if st.button("保存上传的指标公式配置", use_container_width=True):
                METRIC_CONFIG_PATH.write_bytes(metric_file.getvalue())
                st.success("指标公式配置已保存。")
                st.rerun()
        except Exception as exc:
            st.error(f"上传的指标公式配置无效：{exc}")
    with st.expander("当前启用的指标公式", expanded=True):
        st.dataframe(metric_config_df, use_container_width=True, hide_index=True)

    reports = None
    if not records.empty:
        try:
            reports = load_reports_from_records(records)
        except Exception as exc:
            st.warning(f"读取已上传报表用于补全配置失败：{exc}")

    st.subheader("业务配置")
    render_business_config_editors(reports)


def main():
    page = render_sidebar_navigation()

    try:
        metric_config_df = load_metric_config()
        metric_lookup = metric_lookup_from_config(metric_config_df)
    except Exception as exc:
        st.error(f"指标公式配置读取失败：{exc}")
        return
    try:
        commission_config_df = load_commission_config()
    except Exception as exc:
        st.error(f"提成配置读取失败：{exc}")
        return
    try:
        department_fee_config_df = load_department_fee_config()
    except Exception as exc:
        st.error(f"部门费用率配置读取失败：{exc}")
        return

    records = load_upload_records()
    data = None
    if not records.empty:
        try:
            data = load_dashboard_data(records)
        except Exception as exc:
            st.error(f"数据读取失败：{exc}")
            data = None

    if page == "首页":
        render_home_page(data, metric_config_df, metric_lookup, commission_config_df, department_fee_config_df)
    elif page == "销量看板":
        render_sales_dashboard_page()
    elif page == "滞销提醒":
        render_slow_moving_inventory_page()
    elif page == "产品管理":
        render_product_management_page()
    elif page == "部门监控":
        render_department_monitor_page()
    elif page == "补货管理":
        render_replenishment_management_page()
    elif page == "上传中心":
        render_upload_center(records)
    else:
        render_config_center(metric_config_df, records)


main()

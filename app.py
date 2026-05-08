from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.data_processing import (
    build_alerts,
    compute_metric_table,
    format_display_table,
    load_business_config,
    load_metric_config,
    merge_business_config,
    normalize_store_config,
    normalize_target_config,
    read_local_table,
)
from dashboard.display import SIDEBAR_BANNER_PATH, month_label
from dashboard.filters import apply_home_filters
from dashboard.report_store import (
    delete_upload_record,
    load_reports_from_records,
    load_upload_records,
    persist_uploaded_reports,
)


st.set_page_config(page_title="开发员销售数据看板", layout="wide")

CONFIG_DIR = Path(__file__).resolve().parent / "configs"
METRIC_CONFIG_PATH = CONFIG_DIR / "metrics_config.csv"
STORE_CONFIG_PATH = CONFIG_DIR / "store_config.csv"
TARGET_CONFIG_PATH = CONFIG_DIR / "monthly_targets.csv"


NAV_ITEMS = {
    "首页": "📊 首页",
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
        if name not in {"月份", "销售专员", "店铺", "店铺编码", "店铺类型", "是否计数", "部门"}
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
    stores["是否计数"] = "是"
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
    store_config = merge_config_rows(local_store, build_discovered_store_config(reports), "店铺名")
    target_config = merge_config_rows(local_target, build_discovered_target_config(reports), "开发员")

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
            "是否计数": st.column_config.SelectboxColumn("是否计数", options=["是", "否"]),
        },
    )
    if st.button("保存店铺配置", use_container_width=True):
        saved = normalize_store_config(edited_store).fillna("")
        saved.to_csv(STORE_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("店铺配置已保存。")

    st.markdown("**目标配置**")
    edited_target = st.data_editor(
        target_config,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="target_config_editor",
    )
    if st.button("保存目标配置", use_container_width=True):
        saved = normalize_target_config(edited_target).fillna("")
        saved.to_csv(TARGET_CONFIG_PATH, index=False, encoding="utf-8-sig")
        st.success("目标配置已保存。")

    return normalize_store_config(edited_store), normalize_target_config(edited_target)


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
        selected_developers = col2.multiselect("开发员", developers, default=[])
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


def render_home_page(data, metric_config_df, metric_lookup):
    st.title("首页")
    if data is None or data.empty:
        st.info("暂无可分析的业绩报表，请先到“上传中心”上传 CSV。")
        return

    filtered = render_home_filters(data)
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    errors = validate_metric_formulas(filtered, metric_config_df)
    if errors:
        st.error("部分公式无法计算：\n\n" + "\n".join(f"- {e}" for e in errors))
        return

    overview_metrics = metrics_for_group(metric_config_df, "总览", fallback_to_overview=False)
    overview = compute_metric_table(filtered, overview_metrics, [])
    st.subheader("总览 KPI")
    show_metric_cards(overview, metric_lookup)

    trend_metrics = metrics_for_group(metric_config_df, "趋势")
    trend = compute_metric_table(filtered, trend_metrics, ["月份"])
    trend = trend.sort_values("月份") if "月份" in trend.columns else trend
    trend_chart = add_month_display(trend)
    trend_display = format_display_table(trend_chart.drop(columns=["月份"], errors="ignore"), metric_lookup)

    st.subheader("月度趋势")
    if "销售额" in trend.columns:
        chart_if_available(trend_chart, "月份显示", "销售额", title="月度销售额趋势", kind="line")
    st.dataframe(trend_display, use_container_width=True, hide_index=True)

    developer_metrics = metrics_for_group(metric_config_df, "开发员分析")
    developer_table = compute_metric_table(filtered, developer_metrics, ["销售专员"])
    developer_table = developer_table.sort_values(by="销售额", ascending=False) if "销售额" in developer_table.columns else developer_table

    st.subheader("开发员分析")
    if "销售额" in developer_table.columns:
        chart_if_available(developer_table.head(15), "销售专员", "销售额", title="开发员销售额排行")
    st.dataframe(format_display_table(developer_table, metric_lookup), use_container_width=True, hide_index=True)

    store_metrics = metrics_for_group(metric_config_df, "店铺分析")
    store_table = compute_metric_table(filtered, store_metrics, ["部门", "店铺编码", "店铺类型"])
    store_table = store_table.sort_values(by="销售额", ascending=False) if "销售额" in store_table.columns else store_table

    st.subheader("店铺分析")
    if "销售额" in store_table.columns:
        chart_if_available(store_table.head(20), "店铺编码", "销售额", color="部门", title="店铺销售额排行")
    st.dataframe(format_display_table(store_table, metric_lookup), use_container_width=True, hide_index=True)

    developer_store_metrics = metrics_for_group(metric_config_df, "开发员店铺分析")
    developer_store_table = compute_metric_table(filtered, developer_store_metrics, ["店铺编码", "店铺类型"])
    if "销售额" in developer_store_table.columns:
        developer_store_table = developer_store_table.sort_values(by="销售额", ascending=False)
        total_sales = developer_store_table["销售额"].sum()
        developer_store_table["销售额占比"] = developer_store_table["销售额"] / total_sales if total_sales else 0
        metric_lookup["销售额占比"] = {"格式": "百分比"}

    st.subheader("开发员 + 店铺分析")
    if "销售额" in developer_store_table.columns:
        chart_if_available(developer_store_table.head(20), "店铺编码", "销售额", color="店铺类型", title="所选范围店铺销售额排行")
    st.dataframe(format_display_table(developer_store_table, metric_lookup), use_container_width=True, hide_index=True)

    alerts = build_alerts(developer_store_table)
    st.subheader("异常预警")
    if alerts.empty:
        st.success("当前筛选范围内未发现默认预警项。")
    else:
        st.dataframe(format_display_table(alerts, metric_lookup), use_container_width=True, hide_index=True)

    csv = developer_store_table.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "导出开发员+店铺明细 CSV",
        data=csv,
        file_name="developer_store_dashboard.csv",
        mime="text/csv",
    )


def render_upload_center(records):
    st.title("上传中心")
    report_files = st.file_uploader("业绩报表 CSV", type=["csv"], accept_multiple_files=True)
    try:
        process_report_uploads(report_files)
    except Exception as exc:
        st.error(f"业绩报表保存失败：{exc}")
    render_upload_records(load_upload_records())


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

    records = load_upload_records()
    data = None
    if not records.empty:
        try:
            data = load_dashboard_data(records)
        except Exception as exc:
            st.error(f"数据读取失败：{exc}")
            data = None

    if page == "首页":
        render_home_page(data, metric_config_df, metric_lookup)
    elif page == "上传中心":
        render_upload_center(records)
    else:
        render_config_center(metric_config_df, records)


main()

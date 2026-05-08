from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.data_processing import (
    compute_metric_table,
    load_business_config,
    load_metric_config,
    merge_business_config,
    normalize_report,
    read_local_table,
)


def main() -> None:
    files = sorted(Path("D:/").glob("业绩报表_2026-*.csv"))
    if not files:
        raise SystemExit("D:/ 下没有找到 业绩报表_2026-*.csv")

    frames = []
    for path in files:
        frame = read_local_table(path).copy()
        frame["来源文件"] = path.name
        frames.append(frame)

    reports = normalize_report(pd.concat(frames, ignore_index=True))
    metrics = load_metric_config()
    store_config, target_config = load_business_config()
    data = merge_business_config(reports, store_config, target_config)

    print(f"files={len(files)} rows={len(data)} months={sorted(data['月份'].dropna().unique().tolist())}")

    overview = compute_metric_table(data, metrics[metrics["显示分组"].eq("总览")], [])
    developer = compute_metric_table(data, metrics[metrics["显示分组"].eq("开发员分析")], ["销售专员"])
    store = compute_metric_table(data, metrics[metrics["显示分组"].eq("店铺分析")], ["店铺编码", "店铺类型"])
    selected_developers = ["运营二十部-陈千潼", "运营二十部-陈千潼-26"]
    developer_store_source = data[data["销售专员"].isin(selected_developers)]
    developer_store = compute_metric_table(
        developer_store_source,
        metrics[metrics["显示分组"].eq("开发员店铺分析")],
        ["店铺编码", "店铺类型"],
    )
    if "销售额" in developer_store.columns:
        developer_store = developer_store.sort_values("销售额", ascending=False)
        developer_store["销售额占比"] = developer_store["销售额"] / developer_store["销售额"].sum()

    print("overview")
    print(overview.to_string(index=False))
    print(f"developer_rows={len(developer)} store_rows={len(store)} selected_developer_store_rows={len(developer_store)}")
    print("developer_head")
    print(developer.head().to_string(index=False))
    print("selected_developer_store_head")
    print(developer_store.head().to_string(index=False))


if __name__ == "__main__":
    main()

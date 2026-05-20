# 开发员销售数据看板

本项目是一个本地 Streamlit 数据看板，用来上传和维护多类销售原始表，并按开发员、月份、店铺、产品、库存库龄等维度生成经营分析。它不是通用 BI 工具，核心目标是把固定格式的业务报表清洗、合并、计算并展示成可筛选、可导出的看板。

## 快速启动

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

如果只想验证数据处理逻辑：

```powershell
python -m unittest discover -s tests
```

## 主要页面

- `首页`：上传的业绩报表分析入口，包含总览 KPI、月度趋势、开发员分析、店铺分析、开发员+店铺分析、异常预警和提成预估。
- `销量看板`：基于运营原始表，按店铺和产品等级展示在售数、订单量、日均、库存等指标。
- `滞销提醒`：基于运营原始表中的库龄列，计算 90 天以上库存、占用资金、库存计提和弃置费。
- `产品管理`：合并运营原始表、毛利原始表和 Rating，生成 SKU 级产品管理明细，并单独列出低毛利率 SKU。
- `补货管理`：合并运营原始表、毛利原始表和 Rating，按 ASIN 计算建议补货数量、异常原因、店铺分布和补货方式。
- `上传中心`：上传业绩报表、运营原始表、毛利原始表和 Rating。上传后的文件保存在 `data/` 下，刷新页面后仍可继续分析。
- `配置中心`：维护指标公式、店铺配置、目标配置、提成配置和部门费用率配置，保存后写回 `configs/`。

## 数据来源

- 业绩报表 CSV：用于首页和提成预估，必须包含 `销售专员`、`月份`、`店铺`，其余指标通过公式配置引用。
- 运营原始表 XLS/XLSX：用于销量看板、滞销提醒和产品管理，关键列包括 `MSKU`、`店铺名称`、销量、库存、开发员和 ASIN。
- 毛利原始表 CSV/XLS/XLSX：用于产品管理和低毛利率 SKU，关键列包括 ASIN、MSKU、国家、销售额区间列、销量列、毛利润和广告费列。
- Rating XLS/XLSX：用于产品管理，关键列包括 ASIN、国家、Rating 总数和评分。

上传文件由 `dashboard/report_store.py` 管理。多月份业绩报表会按月份记录，重复月份会替换旧记录；运营、毛利、Rating 属于“最新文件”类型，同类只保留最近一次上传。

## 配置文件

配置文件默认存放在 `configs/`：

- `metrics_config.csv`：首页指标公式配置，字段为 `指标名称`、`显示分组`、`公式`、`格式`、`排序`、`是否启用`。
- `store_config.csv`：店铺配置，字段为 `店铺名`、`店铺类型`、`停提款时间`、`店铺所属部门`。
- `monthly_targets.csv`：开发员目标配置，字段为 `开发员`、`目标业绩`、`目标毛利率`。
- `commission_config.csv`：提成配置，字段为 `月份`、`开发员`、`库存计提`、`弃置`、`职位提点`。
- `department_fee_config.csv`：部门费用率配置，字段为 `月份`、`部门`、`费用率`。
- `replenishment_targets.csv`：补货目标配置，字段为 `ASIN`、`目标可售天数`；缺失 ASIN 默认按 70 天计算。

`停提款时间` 为空表示店铺一直计入首页常规看板；填写月份后，从该月份开始含当月的数据不计入常规看板，只在提成预估中的“停提款店铺缺提成”单独展示。

补货管理按 ASIN 汇总运营库存，`总库存数量 = 可售 + 待入库 + 采购在途 + 本地库存 + 在途 + 计划入库`，`建议补货数量 = max(日均销量 * 目标可售天数 - 总库存数量, 0)`。毛利异常原因按 MSKU 判断后合并到 ASIN 行，德法西意分别展示；Rating 取四站点中 Rating 总数最多的站点展示为 `数量(评分)`。

## 指标公式

公式引擎位于 `dashboard/formula_engine.py`，计算入口在 `dashboard/data_processing.py` 的 `compute_metric_table()`。公式只支持安全白名单能力：

- 字段引用：`[字段名]`
- 四则运算、括号、比较和布尔运算
- 函数：`sum()`、`mean()`、`min()`、`max()`、`count()`、`nunique()`、`abs()`、`round()`、`safe_divide()`、`if()`、`range_sum()`
- 字符串比较：`[店铺类型] == "本土"`

示例：

```text
range_sum("销售额--FBA销售额", "COD")
safe_divide(sum([毛利润]), range_sum("销售额--FBA销售额", "COD"))
if(safe_divide(sum([毛利润]), sum([销售额--FBA销售额])) < 0.15, 1, 0)
```

## 代码结构

- `app.py`：Streamlit 页面、筛选控件、图表和表格展示。
- `dashboard/data_processing.py`：数据读取、清洗、合并、汇总、提成、销量、滞销和产品管理核心逻辑。
- `dashboard/formula_engine.py`：安全公式解析和执行。
- `dashboard/report_store.py`：上传文件持久化、上传记录维护和最新原始表管理。
- `dashboard/filters.py`：首页筛选逻辑。
- `dashboard/display.py`：展示辅助函数和静态资源路径。
- `tests/`：数据处理、公式、筛选、上传记录和辅助函数测试。

## 维护要点

- 原始表中的数值可能来自 Excel 公式、复制粘贴或不同区域格式，可能出现全角数字、中文逗号、不换行空格、货币符号、百分号或会计负数。新增数值列时，应优先复用 `normalize_config_number()` 或现有 normalize 函数，避免直接按字符串排序或求和。
- 展示层应尽量保留数值列类型，再用 Streamlit `column_config` 控制格式；不要为了显示千分位或百分比把表格数据整体转成字符串，否则用户点击列头排序会变成文本排序。
- 新页面如果依赖上传文件，优先通过 `read_local_table()` / `read_upload_table()` 读取，保持 CSV 编码和 XLS/XLSX 兼容策略一致。
- 新业务指标优先放入 `metrics_config.csv` 公式配置；只有跨表、分摊或需要特殊业务规则的逻辑才写入 Python。

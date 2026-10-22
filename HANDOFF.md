# HANDOFF — 本地销售数据分析助手

> 发布补注（2026-10-22）：本工作区现整理为 `v2.2.0 · 新品与价格监控`。以下为 2026-09-20 起积累的历史开发记录，其中“未发布”“待回归”和本机数据计数不代表当前状态；当前功能、升级规则和发布内容以 README.md、CHANGELOG.md、DEPLOYMENT.md 及实际 Release 为准。

> 核对日期：2026-09-20。依据当前工作区代码、配置、已有文档、Git 和本机数据结构；不是仅依据 README。路径均相对项目根目录。本文记录可继续开发的上下文，不替代源码。
> 基线：HEAD `a0c183d`（2026-09-04，v2.1.0）；当前有大量原有未提交修改及新增文件，尤其 `backend/pricing.py`、`frontend/src/PricingPanels.tsx`、`departmentRatio.ts`。这些已纳入本文，不能按 HEAD 覆盖。编写前根目录没有 HANDOFF、PRD、TODO、coding_rules 文件。

## 1. 项目一句话说明

面向单人、本机桌面使用的跨境电商销售分析工具：手工导入 ERP/Amazon 导出的 CSV/Excel，集中查看经营业绩、SKU 利润、滞销、补货和新品批次。React 展示，FastAPI/pandas 计算，原始文件、CSV 配置和 SQLite 在本机保存；没有 ERP 在线同步或 AI 模型调用。当前主要工作是稳定已有业务口径，并完成 v2.1.0 之后调价/促销拆分、Listing 价格观察、部门预测及销量画像等改动的回归收尾。

## 2. 当前项目状态

| 方面 | 当前真实状态 |
| --- | --- |
| 阶段 | 已有 Windows 便携版发布与完整本机应用；当前工作区处于发布后功能迭代，不是空白 MVP |
| 已实现 | 9 个主页面、文件上传/替换/预览/下载、配置编辑、经营计算、服务端分页排序/导出、ASIN 补货、首批货件监控、待办、主题/标签页、系统重启退出 |
| 当前新增实现 | 长期调价事件/累乘/幂等/作废/审计；限时活动稳定 ID 与重叠校验；Listing 快照与实际价格观察；销售额按日历史；共享本土考核比例；补货四站销量改读最新销量明细；滞销库存覆盖天数 |
| 尚未收尾 | 本轮代码与定向回归已更新，完整后端回归、Docker/Windows 打包和浏览器端到端验收仍待执行；工作区改动尚未发布。 |
| 可运行性 | 本次 TypeScript + Vite 生产构建通过，后端 API 测试可执行；不能宣称全部功能验收通过。未重新运行 Windows 打包、Docker 或浏览器端到端验收 |
| 首要目标 | 保留当前业务数据和未提交实现，修复/校准失败回归及跨页面刷新，再决定下一版本发布 |

**2026-09-20 验证快照**（各测试/构建子进程设 85 秒硬超时，无安装）：

- 本轮前端回归：10 个文件、72 项通过；后端定向覆盖数据库、Parquet 缓存、促销分页/搜索/排序/复制/CSV、补货站点销量、任务周期、批次到货与看板契约，相关测试通过。完整后端回归尚未作为验收结论。
- 本轮 `npm.cmd test -- --run`：10 个文件、72 项通过，约 22 秒。
- 本轮 `npm.cmd run build`：通过，约 8 秒；主 JS chunk 约 824 kB，存在大包警告。
- 验证环境为已有 `.venv` Python **3.14.3**、Node **24.14.0**；文档建议及发布 CI 使用 Python **3.12**。不要把本机版本当成新的最低版本要求。

**本机数据快照，仅用于理解现状，不能当作新部署种子数据**：业绩月份 2026-01～09；往月销量 2025-09～2026-08 连续 12 个月；运营和销量/销售额明细更新于 09-16，后两者范围 08-18～09-16。只读查询确认 SQLite 有 96 批次、2662 批次 SKU、3606 首次货件 SKU、2422 开售价 SKU、27 待办、618 调价事件；`sku_promotions` 当前 0 行，最近登记快照 395 行。调价拆分迁移标记 `2026-09-separate-price-adjustments-v1` 已于 09-15 写入，**本机不是等待首次迁移的旧库**。这些计数会随使用变化。

## 3. 技术栈

| 层 | 实际技术 |
| --- | --- |
| 前端 | React 19、TypeScript 5.7 系列（strict）、Ant Design 5、Ant Design Icons、dayjs；Vite 6（本次构建 6.4.3） |
| 状态/路由 | React hooks/ref；自建 URL query + History API 导航，无 React Router/Redux；图表使用 SVG/CSS，无 ECharts |
| 后端 | Python、FastAPI 0.139.0、Uvicorn 0.46.0、Pydantic 请求模型、python-multipart 0.0.27 |
| 数据处理 | pandas 3.0.2；openpyxl 3.1.5 读写 xlsx；xlrd 2.0.2 读 xls；pyarrow 24.0.0 处理 Parquet |
| 持久化 | 原始 CSV/XLS/XLSX + CSV 索引/配置 + 标准库 sqlite3；没有 ORM、IndexedDB 或远程数据库 |
| 浏览器存储 | localStorage 仅主题和考核比例；sessionStorage 保存最近访问标签页，业务数据不存浏览器 |
| 测试/发布 | unittest + FastAPI TestClient/httpx 0.28.1；Vitest 4、Testing Library、jsdom；PyInstaller 6.21.0 + GitHub Actions |

Python 精确依赖见 `requirements*.txt`；前端 package.json 使用版本范围，复现安装以 `package-lock.json` 为准。

## 4. 项目目录结构

```text
app_paths.py                 源码/便携版路径与环境变量，所有存储层应依赖它
backend/                     HTTP 路由、SQLite、系统控制
├── main.py                  注册路由、初始化数据库、静态 SPA、HTTP 中间件
├── dashboard_api.py         看板聚合、缓存、分页、图片/促销/批次关联与导出
├── reports_api.py           上传及原文件管理 → dashboard/report_store.py
├── config_api.py            配置白名单、校验、原子保存
├── promotions.py / pricing.py 限时促销 / 长期调价
├── batch_monitor.py         批次、首次货件、开售价、历史导入 CLI
├── tasks.py / db.py          待办生命周期 / 全库建表迁移
└── app_revisions.py、system_*、server_runtime.py
dashboard/                  可复用数据层（不再是 Streamlit 页面目录）
├── data_processing.py       标准化及核心业务计算，最大且最关键的模块
├── formula_engine.py        AST 白名单公式解释器
├── report_store.py          原始文件、索引、滚动月份、销售额历史
├── parquet_cache.py         可重建磁盘缓存与内存缓存
└── promotions.py            SKU 标准化、促销候选规则（不同于 backend 同名文件）
frontend/src/                页面组件平铺，无 pages/stores/services 分层
├── main.tsx / navigation.ts 应用壳、导航、标签页与数据域刷新
├── api.ts                   fetch 封装、请求/返回类型及兼容处理
├── *Page.tsx、*Board.tsx     业务页面
├── DashboardDecisionMatrices.tsx、SkuImagePreview.tsx、feedback.ts
└── styles.css、*.test.tsx、test/setup.ts
configs/                     业务配置 CSV（有实际业务值，不全是演示配置）
data/                        运行数据，Git 忽略；详见第 6 节
scripts/                     桌面启动器、快捷方式、数据检查/性能基准/旧待办导入
packaging/                   Windows 便携入口、PyInstaller spec、使用说明
.github/workflows/           windows-release.yml：测试、打包、发布
tests/                      后端业务、API、安全、迁移与存储回归
README.md / CHANGELOG.md / DEPLOYMENT.md / AGENTS.md
```

依赖主线：`前端 api.ts → backend 路由 → dashboard 计算/存储 + db.py`；`dashboard_api.py` 额外关联批次、促销、调价。存在为避免循环导入使用的局部 import，拆模块时先核对依赖。

## 5. 核心模块

以下均已有实现；“风险”是后续修改时应先检查的边界，详细规则见第 7 节。

| 模块 / 入口 | 输入 → 核心流程 → 输出 | 关键依赖 / 状态与风险 |
| --- | --- | --- |
| 上传 / UploadCenter | 原文件 → 大小/格式/字段/数字校验 → 全批次预检 → 原文件+索引原子保存 → 缓存失效 → 上传记录/预览 | reports_api、report_store、upload_safety；原文件是权威。只保留最新源或按月覆盖，不是任意追加 |
| 经营首页 / DashboardPage | 月业绩+店铺/目标/公式/提成/费用率 → 配置合并、筛选、公式计算 → 指标/趋势/排行/异常/提成 | `_build_overview`、`compute_metric_table`；首页财务含停提款店铺，提成另分口径 |
| 销量看板 | 运营原始表+店铺配置 → 店铺拆分、等级归类 → 店铺/等级销量和在售库存统计 | `build_sales_dashboard_tables`；一行多店铺会完整复制指标，不能套用其他页面的汇总方式 |
| 产品/低毛利 | 运营为主 + 毛利/Rating/图片 + SQLite 开售价/到货/当前促销/调价 → ASIN+SKU 行 → 决策矩阵 | `build_product_management_table`、`_build_products`；不把同 SKU 多开发员扩成重复产品行 |
| 滞销 | 排除停提款运营行 → 按 MSKU 聚合库龄/资金/日均/库存覆盖 → 计提和弃置 → 图片及最近限时快照/调价 | `build_slow_moving_inventory_table`、`_build_slow_moving`；缺失与零不能混同 |
| 调价与促销 | 运营+店铺 → 候选；人工登记 → 两套 SQLite 事件 → 当前汇总/批次/历史/矩阵附加字段 | dashboard/promotions、backend/promotions、pricing；仅登记，不调用平台改价。相关定向回归已通过，完整后端与端到端验收仍待执行 |
| 部门监控 | 业绩视图：两类日明细+运营+按日销售额历史；提成/考核：月业绩报表 → 开发员/部门/店铺汇总 | `build_department_performance_tables`、`build_department_commission_monitor`、`build_department_assessment_report`；两种考核系数公式不同 |
| 补货 | 运营+覆盖规则/开关/标签 → SKU 校准销量/库存 → ASIN 聚合 → 建议量；附加毛利/Rating/图片/促销/日明细/历史 | `build_replenishment_management_tables`、`_replenishment_tables`；附加参考数据不改变建议量。基础计算缓存与开关筛选分开 |
| 批次监控 | 批次 xlsx+货件 CSV → 固定批次成员/首次绑定 → 美工/到货 → 进度、未归属清单、产品开售信息 | batch_monitor + SQLite；当前新成员范围硬编码为开发员含“陈千潼”，历史已确认成员保留 |
| 待办 / 顶栏抽屉 | 手工/JSON → SQLite → 状态流转/排序/按访问更新周期 → 列表和通知 | tasks、todo_import；前端轮询，无后台定时调度/系统级通知 |
| 配置/系统 | CSV 编辑→校验/保存；本机控制→优雅退出/重启 | ConfigCenter、SystemControls；开发模式直接 uvicorn 不提供受控重启 |

## 6. 数据结构、字段与存储

### 6.1 文件与路径

`app_paths.py`：源码下 APP_ROOT=项目根；便携版 APP_ROOT=exe 所在目录、RESOURCE_ROOT=PyInstaller 资源目录。`DATA_ANALYSIS_ASSISTANT_DATA_DIR`、`DATA_ANALYSIS_ASSISTANT_CONFIG_DIR` 可覆盖数据/配置路径；环境变量须在 import 前设置。前端资源位于 RESOURCE_ROOT/frontend/dist，PID/日志位于 APP_ROOT/.tmp。缓存与批次附件均使用 DATA_DIR；路径安全边界仍见第 13 节。

| 路径（默认） | 数据与主键 / 写入方式 |
| --- | --- |
| `data/reports/YYYY-MM.csv` + `data/upload_records.csv` | 月业绩原字节；索引列：月份、原始文件名、保存文件名、上传时间、文件大小。月份唯一，同月整体替换 |
| `data/sources/{key}.{csv,xls,xlsx}` + `{key}_source.csv` | 每种最新数据源；索引首列为“数据源”，其他列同上。保存后删除旧扩展名版本 |
| `data/sales_history/YYYY-MM.csv` + `data/sales_history_records.csv` | 连续 12 个月销量原字节与月份索引；同月替换，新月滚动淘汰 |
| `data/department_sales_amount_history.csv` | 日期+开发专员+店铺，值为原始销售额（元）；重传按**整天**替换，保留其他日期 |
| `data/listing_prices/` | 按日 Listing 原始/标准化快照与索引；用于实际价格观察，按日期保留 |
| `data/app.db` | 待办、批次、首批货件、开售价、促销快照、调价与审计 |
| `data/batch_monitor/uploads/` | 批次/货件导入附件归档 |
| `data/cache/` | schema version `6`、源文件指纹决定的 Parquet；可重建，不是备份 |

### 6.2 输入字段与关联键

字段名大小写与中文标点有业务意义，接口不是统一英文 Product 模型。

| 数据源 key | 核心字段 / 映射 / 关联 |
| --- | --- |
| performance（月业绩） | `月份,销售专员,店铺` + 财务字段。月份归一 YYYY-MM；销售专员关联配置“开发员”；店铺提取店铺编码关联 store_config |
| operational_sales | `MSKU→SKU`、`ASIN`、`开发员`、`店铺名称`；`本地SKU→库存SKU`，MSKU 同时作图片“虚拟SKU”。销量：昨天/前天/上前、7/14/30/90天销量、日均销量、可售天数；`上架时间,单品重量(g)` |
| 运营库存列 | `可售,待调仓,调仓中,待入库,采购在途,本地库存,在途,计划入库` 八列；库龄库存：91-180、181-330、331-365、366-455、456天以上库存数；对应资金末列是 **456天占用资金**，不是“456天以上占用资金” |
| gross_profit | `ASIN,MSKU,国家,毛利润`；销量为 `销量--FBA销量/FBM销量/多渠道销量`；销售额取 `销售额--FBA销售额` 至 `COD` 按物理列顺序的闭区间；广告 SD/SP/SB/SBV/差异分摊；补货原因另需广告费占比/退款占比/FBA发货费占比 |
| rating | `ASIN,国家,Rating总数,评分`；四国名称德国/法国/西班牙/意大利对应 DE/FR/ES/IT |
| sales_volume_detail / sales_amount_detail | 小写 `msku`、`店铺,开发专员` + `MM-DD销量` / `MM-DD销售额` 日期列。补货站点统计额外依赖小写 `asin` 和 `国家`，普通上传校验不强制这两列 |
| 往月销量 CSV | 小写 `asin,msku`、`国家,小计`、该月份所有 `MM-DD销量` 列；文件名必须含完整自然月 `YYYY-MM-DD ~ YYYY-MM-DD`；ASIN 汇总前会标准化大写 |
| sku_image_map | `库存SKU,虚拟SKU,库存图片链接`（表头去空格、SKU 大小写兼容）；按运营 `(本地SKU,MSKU)` 精确匹配，键 trim+uppercase，不按 ASIN 猜图片 |
| 批次 xlsx | 某一 Sheet 的 `SKU,DE_PRICE,FR_PRICE,ES_PRICE,IT_PRICE`；恰好一个匹配 Sheet。SKU trim+uppercase，四站开售价为数值，不随调价登记自动重算 |
| 首批货件 CSV | `货件单号,MSKU,ASIN`；MSKU→sku，ASIN 要求 10 位字母数字；一个 SKU 只绑定首次货件 |

月历史每日值必须非负且与小计一致（容差1e-6）；空ASIN且整月零销量行跳过，空ASIN有销量则拒绝。CSV依次尝试utf-8-sig/gb18030/utf-8，Excel一般读取首个Sheet（批次/旧历史导入器另有专门Sheet规则）。

上传校验器：`backend/reports_api.py` 的 SOURCE_DEFINITIONS/各 `_validate_*`，字段集合及 normalizer 在 `dashboard/data_processing.py`。非空非法数字先拒绝，不允许坏值默默落盘后变 0。

### 6.3 CSV 配置

| 文件（configs/） | 键及字段 / 说明 |
| --- | --- |
| metrics_config.csv | `(指标名称,显示分组)`；公式、格式、排序、是否启用；分组总览/趋势/开发员/店铺等 |
| store_config.csv | `店铺名` 实际是代码；店铺类型、停提款时间、店铺所属部门；兼容旧“店铺编码/部门/停提款月份” |
| monthly_targets.csv | **仅开发员为键，无月份列**；目标业绩、目标毛利率；合并后名为销售额目标、毛利率目标 |
| commission_config.csv | `(月份,开发员)`；库存计提、弃置、职位提点 |
| department_fee_config.csv | `(月份,部门)`；费用率 |
| replenishment_coverage_rules.csv | 运输方式、重量下限、重量上限、头程时效、预警天数、补货频次、是否启用；启用区间不得重叠 |
| replenishment_switches.csv | `ASIN`；是否补货、关闭原因；兼容旧补货组ID，关闭必须有原因 |
| replenishment_product_tags.csv | `(ASIN,产品标签)`；标签颜色（可选 #RRGGBB）、是否启用、备注 |
| replenishment_targets.csv | **遗留文件**；仍有兼容 normalizer，但当前补货不读取它计算目标/装箱量，也不在配置 API 白名单 |

配置读取可把报表发现的新店铺/人员/月份合并为待配置行，但 GET 不自动保存；通用 PUT 接受整张行数组并替换整个文件。提成/费用率当前从部门提成行展开编辑，配置中心菜单仅展示其余 6 类。

### 6.4 SQLite 核心表

无独立 migrations 文件夹，建表/兼容迁移见 `backend/db.py`；pricing schema 在 `pricing.ensure_schema`。

| 表 | 主键 / 关键字段 / 关系 |
| --- | --- |
| tasks | `id` UUID；title,notes,status,due_at,remind_at,recurrence_type,recurrence_days(JSON),next_reminder_at,notification_read_at,created_at,updated_at,completed_at,sort_order |
| sku_promotions | `id` UUID；sku,activity_id,promotion_name,asin_snapshot,developer_snapshot,discount_percent,rule_key,start_date,end_date,created_at,updated_at；同一次活动共享 activity_id，SKU 可有多个不重叠活动 |
| sku_last_promotions | `sku`；promotion_id,promotion_name,discount_percent,start_date,end_date,updated_at；最近**登记**快照，不等同最近生效活动，不是级联删除关系 |
| price_adjustments | `id`；batch_id,batch_name,sku,discount_percent,effective_date,created_at,migration_source,voided_at,void_reason；UNIQUE(batch_id,sku) |
| pricing_requests | `request_id`；payload_hash,batch_id；登记幂等凭据 |
| pricing_audit | 整数 id；kind,source_id,payload(JSON),recorded_at,migration_key；迁移、编辑、删除、作废审计 |
| batch_monitor_batches | `batch_no`；artwork_completed_date,source_file_name,source_file_hash,created_at,updated_at |
| batch_monitor_skus | `sku`；batch_no→批次，de/fr/es/it_price,developer_snapshot,monitor_basis,created_at；SKU 不跨批次 |
| sku_first_shipments | `sku`；shipment_no,asin,arrival_date,updated_at；可先导入货件后归属批次 |
| sku_launch_prices | `sku`；de/fr/es/it_price,source_file_hash,updated_at；无批次历史开售价补充表 |
| batch_monitor_imports / batch_monitor_meta | file_hash 导入幂等/统计；key/value/updated_at 域版本 |
| app_migrations | `migration_key`、applied_at；已执行迁移账本 |

SQLite 连接上下文负责 commit/rollback；关键批量操作 `BEGIN IMMEDIATE`。当前未启用 ORM、WAL 或统一 foreign_keys PRAGMA，不能仅凭声明的外键假设级联行为。

### 6.5 API 契约

- `GET /api/dashboard/{page}`：`title,has_data,message,filters,selected,metrics,sections,updated_at`（可有 warnings/commission_config）。section 为 `key,title,columns,rows`，可带 chart、summary、page/page_size/total/paginated；columns 含 key/label/type/format/unit/precision/sortable。
- `GET /api/dashboard/{page}/sections/{section}`：筛选+search+sort_by+sort_order+page+page_size；默认首屏 50、上限 200。`…/export.csv` 导出全部匹配结果，UTF-8 BOM，不局限当前页。
- 补货 section 另有 `group_rows`：`group_id,identity,countries,inventory,trend,promotion,history,recommendation`；详情返回 group/sku_rows/sales_history。空值 JSON null 与实际 0 必须保留。Excel `/api/dashboard/replenishment/export.xlsx` 两张表；跟随开发员、min_qty、搜索和排序，导出全部匹配行，不限当前页。
- `GET /api/reports`；Listing 价格快照使用 `/api/reports/listing-prices` 上传、预览和下载，实际观察使用 `/api/pricing/observations`，服务端分页。`POST /api/reports/performance|sales-history`（files）；`POST /api/reports/source/{key}`（file）；对应 preview/download/delete。历史只能整体清空，单月可下载/替换。
- `GET /api/configs`、`GET/PUT /api/config/{name}`、POST upload、GET download；部门提成专用接口见 dashboard_api 和 api.ts。
- `/api/promotions`：overview、candidates/{5|8|10}（含 skus.txt/export.csv）、records、last-promotions、manual、activities 删除、按 ID 编辑/删除。
- `/api/pricing`：adjustments/preview、adjustments POST、adjustments/{id}/void POST、adjustment-batches、history。history 当前一次性返回，前端分页。
- `/api/batch-monitor`：batches 列表/创建/详情、美工、shipments 上传/到货、skus 到货、orphans、copy-lists；请求/返回精确定义在 api.ts。
- `/api/tasks`、`/api/notifications`；`/api/app-revisions` 返回 dashboard/promotions/reports/configs/batch_monitor 五域版本；`/api/system/*` 受控运行状态/重启/退出；health 返回 `{ok:true}`。
- 常见错误：422 校验/计算错误，409 日期重叠或状态冲突，404 缺文件/对象；api.ts 统一处理 detail，并兼容旧 section/columns/chart 结构。

## 7. 核心业务规则

### 7.1 通用、金额和店铺

- 财务销量 = FBA+FBM+多渠道；销售额按 FBA销售额～COD **列位置区间**求和。不要排序/裁剪原表列后再调用 `range_sum`。毛利率=汇总毛利润/汇总销售额，不是各行百分比平均。
- 广告费=SD+SP+SB+SBV+差异分摊汇总后取绝对值，不是逐行 abs。普通率字段内部为 0～1；促销/调价 discount_percent 是 1～99 的整数百分点。API 金额原单位元，很多前端显示除 10000 成“万”；CSV 保留原单位/精度。
- 店铺编码优先提取首个连字符后的字母数字段，fallback 为短字母代码，转大写。人员显示归并用 NFKC、统一横杠、去运营部门前缀和 -26 后缀；配置键仍用原始开发员名，不要按显示姓名覆盖多行配置。
- **停提款口径不统一且有意按场景处理**：月业绩从配置月份起拆分计提/停提款数据，首页总经营财务仍包含停提款；运营销量在售数排除有停提款配置的店铺；滞销/促销若原行任一逗号店铺有停提款月份则整行排除（不比较未来/当前月份）；补货保留库存并标记店铺状态。
- 销量看板 `normalize_operational_sales` 拆逗号店铺，每个店铺保留原行**全部数值**，不按店数平分；产品/部门/促销/补货使用未展开原行，避免重复放大。
- 产品等级按 30天销量/30：0、(0,.2]、(.2,.5]、(.5,1]、(1,2]、(2,3]、(3,5]、>5。店铺 D=订单/有效在售；分母零返回 0。-26 在售 SKU 是可售>0 的非空 MSKU 去重，特殊计数不按停提款排除。

### 7.2 产品、Rating、滞销

- 产品按 ASIN+SKU 聚合，同 SKU 多开发员去重后用分号展示；运营可售天数取原字段代表值，不等同滞销覆盖天数。当前四站毛利/销量来自毛利表，整体收益可含其他国家。
- 低毛利筛选：当前运营 SKU 范围内、站点销量≥5、毛利率<15%；默认最差优先。Rating：产品先在 ASIN+国家内取评价数最大、评分平均，再选评价数最多的国家；并列 DE→FR→ES→IT。补货从原 Rating 行选最多评价数，别误用产品的评分平均。0 条评价即便有评分也显示缺失色。
- 产品“开售时间”取首批货件到货日期，不是运营“上架时间”；开售价优先批次 SKU，缺失时 fallback `sku_launch_prices`，不是当前平台售价。
- 滞销按 MSKU 聚合且要求 90+库存>0。日均销量缺失保持 NA，真实 0 保留；库存覆盖天数=八项总库存/聚合日均销量，日均≤0/缺库存则 NA。这里待入库只算一次。
- 计提=91–180资金×5% +181–365资金×8% +366+资金×12%。弃置费=所选库龄库存×6 +所选库龄资金×1.5；90+/180+/365+切换改变弃置计算，不改变默认90+入选标准。

### 7.3 补货（改动前必须读对应回归）

1. 按 ASIN 汇总所有 SKU；空 ASIN 保留异常分组。原 SKU 取最早有效上架日期，再按 MSKU 决胜，其余为跟卖。日期兼容 Excel 序号、日期字符串、日/月/年及 MET/MEST/CET/CEST/GMT 后缀；不做导致日期前移的 UTC 转换。
2. SKU 校准日销：上架<90天为 `(7天/7)×.9 +(14天/14)×.09 +(30天/30)×.01`；≥90天权重 `.6/.3/.1`。必要输入缺失使该组异常、建议 NA，不能补零后算“正常”。T值=`7天/7−30天/30`。
3. **SKU总库存 = 可售+待调仓+调仓中+2×待入库+采购在途+本地库存+在途+计划入库**。待入库重复计入是 Excel 兼容口径，有测试保护；亚马逊可售=前四项各一次。不要“修正”为八项各一次。
4. ASIN 库存/日销求和，重量取最大。覆盖规则区间左闭右开；当前 <100g 空运=30+40+10=80天，≥100g 卡航=40+40+10=90天。
5. 目标库存=校准日销×覆盖天数；测算量=`max(按 Excel ROUND 四舍五入((目标库存−总库存)/10)×10,0)`，不是向上取整，也不读取遗留目标天数/装箱量。关闭补货：官方建议0，测算仍保留；矩阵和导出排除关闭 ASIN，重新开启去配置中心。
6. 页面/API 默认 `min_qty=30`，会隐藏低建议及 NA 异常；排查异常先选“全部”(0)。筛选后的指标随之变化。关闭操作要求原因，并仅失效开关视图缓存，不重跑昂贵基础计算。
7. 毛利原因：广告费占比>.15、退款占比>.08、FBA发货费占比>.60；毛利/Rating/T值/促销/历史销量仅辅助判断，不据此自动阻断补货或改建议数量。
8. 销量画像三种来源：近3日/周期销量来自运营；四站销量来自**最新 sales_volume_detail 的日列**、按 ASIN+国家汇总所有 SKU/店铺、完整重复行去重；旺销月份来自往月12个月。日期范围优先原始文件名，fallback 上传日期推断年份。源缺失/缺关联列/ASIN未匹配显示 null；已匹配的无销量站点可为 0，不能 fallback 旧年累计或毛利单量。
9. 月历史在 ASIN 四站日汇总后识别连续≥10天零销量，整段剔除（跨月和边界也算）；其他零天仍计入分母。月校准日均=月销量/计入天数，保留两位。旺销前6月先按月销量、再日均排序。

### 7.4 部门业绩、考核和提成

- 日报参考日 T=销量/销售额两表共有的最新日期；MM-DD 用参考年推断跨年。近7日取 T−1～T−7，不含 T。日明细仅完全相同行去重，原上传文件保留并提醒。
- 预估月度采用“自然月结算区间前移7天”：完成日期实际额 + 近7日日均×剩余天数。销售额历史保留此前完整日期；已完成日期缺失会报错，不用日均伪造。上传覆盖某日期时删除历史中**该日期所有人员/店铺**再写入，不能把局部名单当增量文件传。
- 业绩排行销售额：原始店铺名含“本土”按1，其余按.8；库存八项各一次，在售按可售>0 的 MSKU 去重；部门前缀6/7归联合部门、20归运营二十部，店铺排行限定20前缀。
- **两种考核不要合并**：日明细“预估考核销售额”=`中企原始预估×.8 + 本土原始预估×x`；月业绩“考核销售额”=`中企原始销售额 + 本土原始销售额×x`，后者不乘.8。两页共享浏览器 localStorage 中 x，范围0～1、默认1，跨已挂载页/浏览器 storage 事件同步；不写配置 CSV。
- 月开发员提成=`[Σ各部门(营业额×(毛利率−费用率))−库存计提−弃置]×职位提点`，负值保留。费用率按月份+部门，计提/弃置/提点按月份+原开发员。任何必要配置缺失则该明细提成 NA；汇总可能仅包含已配置部分，必须同时看配置状态。
- 部门提成将原开发员归并显示人员，展开行编辑原始配置；无开发员/无销售员等占位标“无需配置”。停提款提成另按店铺分组，并按同月同开发员停提款营业额占比分摊固定成本。目标配置无月份，跨月汇总按所选月份数扩展目标。

### 7.5 长期调价与限时促销

- normalize_promotion_sku 做 NFKC+trim，**保留大小写**，不等于图片/批次 SKU 的 uppercase。候选优先：可售≥20且90天销量≤10→降10%；(10,20]→8%；(20,30]→5%；未命中且90+库存>0→5%兜底。已有未结束（含待开始）活动的 SKU 从候选排除。
- 限时活动新建必须名称、起止日、1～99整数优惠；结束当天仍 active。“今日结束”次日才结束。同 SKU 日期闭区间重叠整批409拒绝，不能覆盖。手工登记允许不在运营源的 SKU，保留空快照并标源缺失。
- 每次新建写入活动及 SKU 最近登记快照；编辑日期/名称和删除活动**不改/不删登记快照**。activity_id 标识一次活动，不按名称删除；跨日期同名活动可并存。当前实时活动、最近登记快照、历史审计是三个不同对象。
- 长期调价是追加事件：累计降幅=`100×(1−Π(1−每次降幅/100))`，连续两次10%得到19%。只计已生效且未作废事件；未来事件不影响当前。限时额外优惠再作用于调价后的价格，不能把百分比相加；无实际绝对售价和平台改价动作。
- 登记先预览再确认；request_id+payload_hash 保证相同请求重放不重复记账，内容变化同 ID 返回409。纠错仅作废并填原因，保留审计，不删除事件。
- 汇总销量按长期/限时有效 SKU 并集去重；`daily_lift` 实际为7天日均−30天日均，可负，**不能宣称因果促销增量**。
- `migrate_legacy(path,backup_path)` 为显式一次性迁移，启动仅 ensure_schema。严格校验两组长期名单388+230个不同SKU、10%及原日期，并校验两组限时170+123；先 SQLite backup，再事务迁移/审计/清理长期快照。名单不符中止，禁止放宽条件强迁。本机迁移已完成；别删除 app_migrations 标记重跑。

### 7.6 批次和待办

- 新建批次批次号3～32位大写字母数字/下划线/连字符；SKU限定有效标识。只导入当前运营开发员含“陈千潼”的 SKU，随后固化 `developer_snapshot/monitor_basis`，后续运营人员变化不让旧批次消失。历史导入的 historical_confirmed 成员同样保留。
- 批次 xlsx 跳过全空和五字段均137的模板行；同文件重复SKU、跨批次SKU整批拒绝；纳入范围的四站价格须>0，历史未维护价格可 null。不能把缺失价格显示0。
- 首次货件绑定永久保留：同文件同SKU冲突拒绝，重复同内容合并；后续导入冲突警告但不覆盖已有首次绑定。整票到货只更新尚无日期的SKU；完成=美工图已完成且所有SKU已绑定并已到货。
- 历史批次 CLI `python -m backend.batch_monitor import-history <xlsx>` 读货件/美工图和开售价两表，要求初始批次/货件表为空，文件hash幂等；`import-launch-prices` 只补历史开售价，不创建虚假批次。
- 待办状态 todo/current/in_progress/snoozed/completed；UTC时间保存、前端本地显示。GET tasks/notifications 会执行生命周期写入：到期待办转current、周期完成项到下一期重开，非周期旧完成项自动清理。
- 重复 daily/weekly/monthly；星期0=周一，月度取配置首个日期并截到当月末，多选日期不代表月内执行多次。清理基准是 `COALESCE(remind_at,due_at,completed_at)` 早于7天，不一定是完成后7天。UI JSON导入新建UUID，重复导入会重复；旧待办脚本另有保留ID/幂等/备份逻辑。前端打开抽屉时60秒轮询，不是后台通知服务。

## 8. 完整数据流与缓存

```text
ERP CSV/Excel → UploadCenter → reports_api 校验 → report_store 原文件+索引
  ├─ 月业绩 + configs → normalize_report/merge_business_config → formula_engine → 首页/提成/考核
  ├─ 运营 → 销量/产品/滞销/补货主数据 ← 毛利、Rating、图片、配置
  ├─ 日销量+日销售额 → 日销售额历史 → 部门实际与月度预估
  └─ 往月CSV → 连续12个月 → ASIN四站按日合计/剔除长零段 → 补货旺销月份
SQLite 批次/首次货件/开售价 → 产品开售信息
SQLite 限时活动/登记快照/长期调价 → 促销页、产品/滞销、补货参考
各派生 DataFrame → Parquet/LRU → dashboard API section/group_rows → api.ts → 矩阵/表格/SVG/导出
```

原文件指纹包含路径、size、mtime_ns、SHA256及 CACHE_SCHEMA_VERSION。修改派生结构/算法要检查是否提升 schema 或调整失效，不只改 React。上传/配置会清缓存；补货开关只清视图层。前端保留已访问页面挂载，以 active/routeVersion/refreshVersion 控制刷新；切换时比较五域 revisions，不是每次重建页面。后端 products revision含批次+促销，slow-moving含促销；补货及前端产品刷新链尚有缺口，见第13节。

## 9. 页面与功能关系

真实路由是 `/?page=...`，不是 `/dashboard`；导航权威为 `navigation.ts`。

| page / 子参数 | 页面组件 | 数据/模块 |
| --- | --- | --- |
| overview（缺省） | DashboardPage | 月业绩/公式/配置经营汇总 |
| sales | DashboardPage | 运营销量店铺/等级 |
| products&tab=detail 或 low-margin | DashboardPage + DashboardDecisionMatrices | 产品/站点毛利/图片/批次/促销/调价 |
| slow-moving&tab=details | SlowMovingPage → DashboardPage | 滞销库龄/资金/覆盖天数 |
| slow-moving&tab=promotion | SlowMovingPage → PromotionBoard + PricingPanels | promotion_view=records/adjustments/history/last-promotions/candidates-10/-8/-5 |
| department&tab=performance/commission/assessment | DashboardPage | 日报预测 / 月报提成行内配置 / 月报考核 |
| replenishment | ReplenishmentPage | ASIN主行，展开SKU计算与历史；独立页内筛选状态 |
| batch-monitor | BatchMonitorPage | 批次、首批货件、到货及复制清单 |
| uploads&tab=daily/weekly/monthly | UploadCenter | 当前 UI：每日运营/毛利/销量/销售额；每周 Rating+业绩；每月图片+历史 |
| config&config_tab=配置文件名不含.csv | ConfigCenter | 6个可见配置页；编辑草稿为组件状态，保存后才写CSV |
| 顶栏待办/通知/系统操作 | TaskBoard / SystemControls | SQLite 待办、受控服务状态 |

筛选如 developers/months/month/departments/store_types/threshold 部分保存在 URL；不是所有页面的搜索/展开/分页都会跨刷新保存。快速标签存在 sessionStorage `sales-dashboard-quick-tabs-v1`，首页不可关闭；主题键 `dashboard-theme`，比例键 `department-assessment-local-ratio`。页面自己的跳转需发 `sales-dashboard-route-change` 并兼容 popstate。

## 10. 关键文件索引（按任务直接打开）

| 文件 | 首看函数/责任 |
| --- | --- |
| app_paths.py | 数据/配置/资源/运行目录 |
| backend/main.py | 应用注册、导入时建库、静态资源、中间件 |
| backend/dashboard_api.py | `_build_*`、`_bundle/_page_revision`、section查询/导出、补货group_rows、矩阵关联 |
| dashboard/data_processing.py | `normalize_*`、`build_*`、`compute_commission_table`，大部分业务规则 |
| dashboard/formula_engine.py | 公式编译/字段提取/AST执行，禁止任意eval |
| dashboard/report_store.py | `persist_*`、latest source、滚动history、销售额历史与失败回滚 |
| dashboard/parquet_cache.py | `revision_digest/load_or_build_parquet`、CACHE_SCHEMA_VERSION |
| backend/reports_api.py | 数据源定义、上传全量校验、预览下载删除 |
| backend/upload_safety.py | 扩展名/文件名/字节/zip炸弹/路径边界 |
| backend/config_api.py | 配置白名单、unique keys、normalizer、原子保存、发现行 |
| dashboard/promotions.py | 促销 SKU 标准化、候选与日均计算 |
| backend/promotions.py | 日期/冲突、activity_id、最近快照、汇总与CSV |
| backend/pricing.py | ensure_schema、migrate_legacy、adjustment_state、幂等/预览/作废/审计 |
| backend/db.py | SQLite上下文、建表、旧库迁移及备份 |
| backend/batch_monitor.py | 新批次/货件/到货/历史价格CLI、revision |
| backend/tasks.py | 待办状态、排序、周期、通知与访问时清理 |
| backend/todo_import.py | 旧待办格式、时区与ID迁移 |
| backend/app_revisions.py | 五个数据域版本依赖 |
| backend/server_runtime.py | 受控uvicorn运行、PID、退出后重启 |
| backend/system_control.py / backend/system_api.py | 重启退出状态机、回环+请求头校验 |
| scripts/dashboard_launcher.py / start_dashboard.bat | 源码桌面启动检查、后台进程、health等待 |
| frontend/src/main.tsx / navigation.ts | 页面挂载、菜单/标签、URL、域级刷新 |
| frontend/src/api.ts | API类型、错误和兼容数据转换 |
| frontend/src/DashboardPage.tsx | 通用看板、SVG排行/图表、提成编辑、部门考核 |
| frontend/src/DashboardDecisionMatrices.tsx | 产品/低毛利/滞销矩阵及业务状态色 |
| frontend/src/ReplenishmentPage.tsx | 补货矩阵、阈值、SKU明细、关闭及Excel导出 |
| frontend/src/PromotionBoard.tsx / PricingPanels.tsx | 限时/候选/登记快照，调价预览/批次/历史/作废 |
| frontend/src/BatchMonitorPage.tsx | 批次/整票和单SKU到货交互 |
| frontend/src/UploadCenter.tsx / ConfigCenter.tsx | 分组上传、配置草稿/保存 |
| frontend/src/departmentRatio.ts | 两页共享比例、预估考核列与导出 |
| frontend/src/SkuImagePreview.tsx / feedback.ts | 图片加载重试/预览；统一操作反馈/下载/复制 |
| frontend/src/TaskBoard.tsx / SystemControls.tsx | 顶栏抽屉任务、重启等待 |
| frontend/src/styles.css | 全局布局、深色、矩阵和尺寸断点 |
| tests/test_data_processing.py | 业务边界的主要事实依据 |
| tests/test_dashboard_contract_api.py / test_report_store.py | 分页/排序/导出一致性、存储原子性 |
| tests/test_pricing.py / test_replenishment_site_sales.py | 新调价及四站销量回归；对应前端 *.test.tsx |
| packaging/DataAnalysisAssistant.spec / windows_launcher.py | 便携资源与本机启动 |
| .github/workflows/windows-release.yml | 标签v*发布、测试、打包与数据排除 |

## 11. 已确定的设计决策

| 决策（证据） | 原因/约束；不要随意改成 |
| --- | --- |
| 单人本机，默认127.0.0.1（README、启动器） | 没有认证/权限/多租户；局域网和云协作不是现有范围 |
| 原始文件+索引是权威，Parquet可重建（report_store/DEPLOYMENT） | 保留原始上传可下载/重算/恢复；不要只留清洗后缓存，也不要迁入浏览器localStorage |
| CSV配置+SQLite交互数据（实际实现） | 配置可导出编辑，任务/批次/调价有稳定身份；不随意改存储体系。选择此组合的更早设计讨论待确认 |
| SKU产品视图、ASIN补货视图并存（代码/测试） | 汇总粒度服务不同业务，不能为了复用强行统一 |
| 补货Excel公式、缺失保持NA（测试） | 双计待入库、ROUND到10、重量边界均已有回归；改变要先确认业务口径 |
| 原始多店铺复制仅用于销量看板（代码/测试） | 其他模块使用未展开数据，防止库存/销售重复计算 |
| 首次货件永久绑定+批次成员固化（批次代码/测试） | 新源文件不能覆盖首发事实或移除历史成员 |
| 调价追加可作废、限时独立、登记快照独立（pricing/promotions测试） | 累计降幅与短期优惠不能混存；删除/结束限时不取消长期调价，不复活已删除活动 |
| 公式AST白名单（formula_engine） | 支持 [字段]、range_sum、sum/mean/min/max/count/nunique、safe_divide、if_/abs/round及有限运算；禁止换成不受限eval |
| 便携版业务数据放exe旁，发布包不带data（app_paths/CI） | 升级手工迁移data+configs；不写入_MEIPASS临时资源目录 |
| 页面保留挂载+按数据域刷新（main/navigation） | 保留筛选/滚动及减少计算；改页面时必须维护active/revision链 |

## 12. 项目编码与执行规范

- **AGENTS.md 是明确执行约束**：每条安装/构建/测试命令≤90秒，到时终止；安装失败最多重试一次，第二次失败停止并记录；失败/超时先告知用户，再做不依赖它的工作；大依赖分批安装，frontend同样适用。工具提前返回session不等于命令有硬超时。
- Python 文件/函数 snake_case，React组件 PascalCase、工具 camelCase；沿用模块现有风格，不做无关格式化。当前无独立 coding_rules/统一 lint 配置，不能虚构规范。
- TS strict：变更接口同步 api.ts、后端序列化、页面和相关测试；业务DataFrame中文字段保持一致。金额/率/折扣的单位契约见第7节。
- 上传先完整校验再提交；使用现有 filename/path allowlist、原子文件替换、事务/回滚；不要把 UI 校验当后端保障。
- 修改计算同步覆盖主表、汇总、详情、搜索/排序、CSV/Excel；禁止仅修改显示使两条数据流口径不同。用原字段/明确label，不把中间辅助列意外导出。
- 前端统一使用 feedback.ts 的 message/download/copy，保留可重试错误、请求竞态保护和重复提交锁；部分旧页尚未完全统一，不据此删保护。
- CSS 全局按页面/组件前缀组织、补齐 `.dark-mode`；桌面由 `.route-pane` 管滚动、导航固定。已有小屏断点不等于承诺手机端适配。
- 测试用临时数据和配置目录；import backend.main 就会 initialize_database，禁止为只读分析随手导入真实库。改迁移先使用数据库副本并检查app_migrations。
- 保留用户未提交修改；不要重置、覆盖业务配置或用测试样例替换真实 data。

## 13. 已知问题 / 技术债 / 文档差异

### 本轮已同步的回归契约

- `tests/test_db.py` 已改为显式列名插入，兼容含 `activity_id` 的 `sku_promotions` 新结构；本轮定向迁移测试通过。
- 看板导出契约已按字段名核对，不再依赖固定列下标；补货站点销量测试保留完整月份字段。
- `tests/test_promotions_api.py` 已同步当前 CSV 文案“近7天与近30天日均差”；前端促销表单测试在弹窗范围内定位日期输入。
- 本轮已验证前端 10 个文件、72 项测试通过；后端定向覆盖数据库、Parquet 缓存、促销、补货站点销量、任务周期、批次到货和看板契约，并在最新改动后分别复跑任务 11 项、批次 13 项、看板契约 16 项，均通过。
- 完整后端回归、Docker/Windows 打包和浏览器端到端验收仍待执行；未把定向通过扩大解释为全量验收。

### 代码确认的缺口（未做生产端到端复现）

- **Docker/路径问题已修复但未做镜像验收**：Dockerfile 已复制 `app_paths.py`；缓存和批次附件已切换到 DATA_DIR，仍需在干净镜像中验证。
- **路径安全边界需验收**：CACHE_DIR 已限制在 DATA_DIR 下，批次附件也已使用 DATA_DIR；需补自定义目录和越界路径测试。
- **缓存刷新链需浏览器验收**：产品前端、补货页面和后端页面版本已纳入促销域/本地日变化；仍需验证登记、作废、Listing 上传、到货更新及跨日后的列表、详情和导出。
- **老库活动删除兼容**：普通ensure_schema只加空activity_id，旧活动汇总生成legacy合成ID，但活动删除直接按DB activity_id等值查询；未执行特定迁移的旧库存在404风险。当前本机无实时促销行，不据此推断其他旧库已安全。
- **到货日期校验已统一**：整票和单 SKU 接口均禁止未来日期；尚未做浏览器端端到端验收。
- **多文件一致性**：部门提成保存分别写费用率/提成CSV，不是跨两文件事务；批次DB提交与附件归档也不是统一事务。
- **CI依赖已补齐但未远程运行**：windows-release 已安装 requirements-dev 并加入 pip 缓存键；仍需等待 CI 或干净环境验证。

### 技术债与未实现范围

- data_processing/dashboard_api和几个页面较大；pricing/history无服务端分页，主前端chunk偏大。适合有回归保护后按业务边界拆分，不作为先重写理由。
- 2025/12-sheet历史汇总、replenishment_targets等兼容代码仍在；当前主流程是逐月CSV，不以遗留函数名判断功能状态。
- 删除最新销售额源不会清除已积累按日历史；这是当前行为，UI尚无独立历史管理入口。需要明确删除语义时再改，不直接清历史。
- 待办已按周期校验：每天不提交日期、每周仅0～6、每月单日期；已完成任务不再自动清理，用户从列表逐条删除。旧库月多日期读取时取最小日期，保存后规范化。
- 无账户、远程同步、自动ERP抓取、平台实际改价、独立后台提醒；这些未实现不等于已排期。
- 原README“每日上传”含业绩，当前UI放每周；README说配置中心维护提成/费用率，当前导航移至部门提成行内编辑；CHANGELOG只到v2.1.0，缺后续调价/按日历史/新画像规则。以本文及代码为准。

## 14. 下一步开发任务（基于现状的建议优先级）

**P0 — 完成当前迭代闭环**

1. 运行完整后端回归、Docker/Windows 打包和浏览器端到端验收；保留新的 activity_id、导出字段及趋势非因果命名。
2. 验证“登记/作废→切页→矩阵刷新”、Listing 上传、到货更新、午夜上架天数及缓存导出一致性。
3. 检查待提交新文件是否完整纳入版本管理；确认已迁移数据可备份恢复，再准备版本说明。没有授权不自动提交/发布或重跑真实库迁移。

**P1 — 运行与数据一致性**

1. 在干净环境验证 Docker、CI 依赖和 DATA_DIR 隔离。
2. 旧activity_id迁移兼容、两CSV保存失败回滚、批次附件归档失败恢复。
3. 为到货日期、待办周期和导出筛选补充更多回归及浏览器交互测试。
4. 同步README上传分组/配置入口和CHANGELOG新行为。

**P2 — 按实际瓶颈优化**

1. pricing/history服务端分页；用benchmark_dashboard定位慢请求再优化/拆模块。
2. 前端依赖chunk优化；按需改样式和响应式，不扩大为手机项目。
3. 清理已经不需兼容的旧历史/目标代码前先确认历史数据用途，避免删迁移能力。

## 15. 容易踩坑的地方

- **SKU不是库存SKU，ASIN不是SKU**；促销大小写保留，图片/批次通常大写；关联前使用各自normalizer，不能全局一刀切。
- 运营“上架时间”用于补货新品权重；产品“开售时间”来自首批到货；“最近登记限时”可能未来/已删除，不能当当前折扣。
- 毛利表站点单量、最新日明细四站销量、往月12个月画像不是一个统计窗口；接口字段 `countries.units` 与 `history.site_sales` 不可互换。
- 缺失null不是0；Rating零评价不是零分；rate小数与discount整数百分点不同；开售价不除10000。
- 补货双算待入库和滞销单算八项库存均有回归；默认min_qty30会把异常藏起来。
- 最新源替换只留一份，但销售额日历史会保留；往月历史必须完整连续12个月，不能按销售额日历史的追加逻辑实现。
- 往月初次上传验证连续12个月已结束自然月，不强制一定截至今天上个月；后续需向前相邻续月，旧窗外月份不能回插。整批最多24文件；不要用旧12-sheet导入器替换当前入口。
- 图片映射要求public HTTPS、无空键/冲突；完全重复合并，空链接跳过并警告；一个库存SKU/虚拟SKU多向冲突拒绝。浏览器直接加载外部图，网络失败有占位与有限重试，不代表数据丢失。
- 通用源上限50MB；月文件单个20MB、批次总100MB/最多24个；配置10MB；表格/zip另有限额。先检查upload_safety，不能只改前端accept。
- main导入有数据库迁移副作用；旧促销名称迁移曾备份并清理当时活动，有一次性标记。只读检查SQLite用mode=ro，不借启动应用完成。
- Vite `publicDir:false`、`emptyOutDir:false`及prepare-build为Windows文件锁问题保留；旧hash产物可能累积，别随意恢复自动清目录后导致Windows构建失效。
- 新接口静态子路径应在动态 `/{id}` 路由前注册；同名 backend/promotions.py 与 dashboard/promotions.py职责不同。

## 16. 项目运行与验证

**当前已有依赖和构建时最短运行**：根目录执行 `.\start_dashboard.bat`，访问 `http://127.0.0.1:8000`。启动器检查依赖、dist和端口，后台运行，不依赖终端；`.tmp/dashboard.pid`、`dashboard.stdout.log`、`dashboard.stderr.log` 用于定位。8000被占用先确认进程，不盲目终止。当前普通源码入口与便携exe的控制台生命周期不同。

**新环境**：建议Python3.12、Node24（CI用24，README写20+）；创建 `.venv`，按requirements精确版本安装，再frontend执行npm ci/build。代理执行下面所有安装/构建/测试都必须带外部≤90秒硬超时；依赖大批次拆开、失败最多重试一次，命令示例本身不实现超时。

```powershell
py -3.12 -m venv .venv
# 分批安装：Web层、数据层；版本来源 requirements.txt
.venv\Scripts\python.exe -m pip install fastapi==0.139.0 uvicorn[standard]==0.46.0 python-multipart==0.0.27
.venv\Scripts\python.exe -m pip install pandas==3.0.2 pyarrow==24.0.0
.venv\Scripts\python.exe -m pip install openpyxl==3.1.5 xlrd==2.0.2
.venv\Scripts\python.exe -m pip install httpx==0.28.1
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\start_dashboard.bat
```

`npm ci`是锁文件完整安装；若超时不能无限重试或改锁文件强拆，先记录环境问题，复用可用依赖或另行解决安装，再做独立代码工作。

**开发模式两终端**：根目录 `.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload`；frontend下 `npm.cmd run dev`（Vite `/api`代理8000）。直接uvicorn未绑定SystemController，页面重启/退出不可用是预期；需要此功能使用 `python -m backend.server_runtime`/桌面启动器。生产页面前端修改后需重建dist。

**验证**（在所改模块范围优先，必要时全套）：

```powershell
# 隔离main导入时的建库；不要用真实DB跑探索性测试
$env:DATA_ANALYSIS_ASSISTANT_DATA_DIR = Join-Path (Get-Location) '.tmp\test-data'
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe -m unittest discover -s tests
Remove-Item Env:\DATA_ANALYSIS_ASSISTANT_DATA_DIR
cd frontend
npm.cmd test
npm.cmd run build
cd ..
```

DATA_DIR环境覆盖尚未隔离全部附件/缓存，涉及这些模块仍应patch各路径；临时测试配置勿覆盖configs。定向unittest使用 `discover -s tests -p test_pricing.py` 等，前端 `npm.cmd test -- src/具体.test.tsx`。真实数据性能可运行 `scripts/benchmark_dashboard.py`（也要限时），不把临时空数据测试当业务验收。

首次启动创建数据库，无业务种子；保留configs后通过上传中心录入各源，历史首次传12个月。升级/数据迁移前停服务，备份data原件/索引/app.db/附件/日历史及configs；cache可重建。便携版通过PyInstaller spec和CI打包，发布包不含data，但会复制configs中的当前业务配置。Docker 已补齐入口文件，但未完成镜像构建验收；不按 DEPLOYMENT 直接断言可用。

## 17. 最近重要变更

| 基线 / 范围 | 对下一轮开发的意义 |
| --- | --- |
| v2.0.1（2026-08-10，相关a3c5b17） | React+FastAPI替代Streamlit；ASIN补货/批次/日明细/滚动历史/Windows便携版成为主架构 |
| v2.1.0（2026-09-04，a0c183d） | 多级导航/标签、域刷新、系统重启退出、部门考核、图片映射、促销关联、补货门槛30和关闭原因 |
| 当前未提交：pricing + promotions/db/main + PricingPanels | 长期调价与限时拆分；稳定 activity_id、登记快照语义、累乘/幂等/作废、迁移审计；本轮补充 Listing 观察分页和用户反馈；本机09-15已迁移 |
| 当前未提交：report_store/reports_api/data_processing | 日销售额跨上传持久化、按日期覆盖；当前月未完整业绩可用；历史零销量空ASIN处理及相关规则已有测试 |
| 当前未提交：dashboard_api/ReplenishmentPage及新site-sales测试 | 四站销量从最新销量明细计算，带时间窗口，不依赖历史12个月是否存在 |
| 当前未提交：departmentRatio/DashboardPage/navigation | 两处考核比例共享、开发员预估考核列及CSV、部门提成行内配置 |
| 当前未提交：矩阵/滞销/图片/配置 | 滞销覆盖天数和调价字段、图片重试、业务配置更新；本轮已同步补货筛选导出、待办周期和复制反馈；发布前仍需完整验收 |

不要把工作区已存在实现重新当作待新增功能，也不要把上述所有改动宣称已发布。后续更新本文应替换失效段落，不无限追加日志。

## 18. 本轮导航与补货加载优化（2026-09-20）

- 产品管理和实际价格的页内重复标签已移除；侧栏仍保留原路由，products 的 tab 与 promotion_view=actual-prices 旧参数继续驱动正确视图。实际价格路由只渲染“实际价格观察”，不再加载促销概览。
- 顶部最近访问标签保留经营首页不可关闭，并新增“关闭其他”“关闭右侧”；标签标题使用单行截断和原文提示。重启、退出收进系统菜单，原确认和状态遮罩仍在 frontend/src/main.tsx、frontend/src/SystemControls.tsx。
- 导航切换先激活页面，/api/app-revisions 在后台检查；请求序号忽略过期版本结果，避免切页被版本检查阻塞。
- 补货接口支持 include_pricing=false：核心矩阵先返回，当前页价格通过 /api/dashboard/replenishment/pricing 批量补齐，最多 MAX_PAGE_SIZE 个补货组。backend/listing_prices.py 的 cached_listing_bundle 按 Listing 文件、数据库修改时间和业务日期建立最多 8 组内存缓存；补货组装按 ASIN、SKU、站点建立索引。
- 本轮验证：前端构建通过；导航、促销、系统控件 14 项测试通过；补货页面 19 项测试通过；后端目标文件 py_compile 通过。当前环境缺少 pytest 与 FastAPI，后端回归和浏览器深色/宽度验收未完成，性能基线尚未在临时数据目录实测，不宣称达到 30%/50% 目标。
- 直接相关文件：frontend/src/main.tsx、frontend/src/SystemControls.tsx、frontend/src/DashboardPage.tsx、frontend/src/PromotionBoard.tsx、frontend/src/ReplenishmentPage.tsx、frontend/src/api.ts、backend/dashboard_api.py、backend/listing_prices.py。保留旧路由和默认 include_pricing=true 接口兼容，未迁移业务数据、未发布。
## 19. 本轮批次监控到货与状态筛选修复（2026-09-22）

- 批次进度矩阵的未完成、全部、已完成切换改为由 view/search/page 状态统一触发服务端请求；旧请求仍由请求序号保护，避免快速点击时旧结果覆盖新视图。
- 整票到货保存成功后立即关闭弹窗加载态并显示新增 SKU 数量，批次列表与复制清单改为后台刷新；刷新失败会保留“已登记到货，但页面刷新失败”的提示。
- backend/batch_monitor.py 的整票到货响应只聚合受影响批次，不再更新后扫描全部批次；批次列表复用 Listing 派生缓存，并直接统计原始变价事件，避免每次切换标签逐事件查询调价/促销记录。
- 批次详情继续使用 Listing 缓存；相关批次文件、SQLite 结构和业务规则未迁移，未发布。
- 验证：frontend 的 npx vitest run src/BatchMonitorPage.test.tsx 为 6 项通过，npm run build 通过，python -m py_compile backend/batch_monitor.py 通过。后端 API 回归未执行成功，当前环境缺少 fastapi；未宣称真实数据下的耗时目标达成。
- 直接相关文件：frontend/src/BatchMonitorPage.tsx、frontend/src/BatchMonitorPage.test.tsx、backend/batch_monitor.py。


## 20. 批次保存提速与手动完成（2026-10-09）

- 根因：`GET /api/batch-monitor/batches` 默认同步附加 Listing 价格指标，前端首屏和状态写入后的列表刷新因此等待价格派生；批次新建与货件上传的异步路由也直接运行 pandas/Excel/CSV 解析，占用事件循环。业务状态写入本身是较小事务。
- 前端改用 `include_price_metrics=false` 获取核心矩阵，三个价格指标通过 `/api/batch-monitor/price-metrics` 独立加载、局部失败可重试；旧列表接口默认仍返回价格指标。开发员映射和价格指标按版本缓存，Listing 历史/事件与开售价依赖拆分，批次摘要支持限定批次聚合。
- 创建批次和货件 CSV 解析/落库移至工作线程。保存接口返回规范批次摘要与业务版本；前端按批次锁定提交，局部更新后立即结束保存态，再合并刷新列表/复制清单。列表、复制清单请求合并同条件并发，详情请求按最新批次摘要合并，旧响应不能覆盖状态。
- 批次新增可空 `manual_completed_at`，旧库通过可重复执行的 `ALTER TABLE` 兼容。手动完成不补美工图、货件或到货事实；保留实际计数及日期，允许继续改进度；撤销只清标记，真实进度已齐时仍自动完成。手动完成批次从未完成统计和两个待办复制清单排除；价格指标仍含全部批次成员。
- 临时 SQLite/合成 Listing 基准：100 批次、3000 SKU、2000 货件，运营范围计算使用空映射、Listing 指标使用合成 DataFrame。保存加完整价格指标列表 5 次中位数 169.66ms；保存加核心列表中位数 22.72ms，下降 86.6%。独立价格指标冷读约 147.66ms、同版本命中约 2.30ms。临时缓存检查确认：只改手动完成标记时三个 Listing 派生缓存均未重建；改开售价时仅当前 Listing 视图重建。该基准覆盖服务函数和临时数据，不是浏览器端到端；未用真实业务数据。
- 验证：批次测试只组装批次路由，先切换临时 `DB_PATH` 再初始化；`.venv` 下 `python -m unittest tests.test_batch_monitor` 15 项通过、1 项用户本机文件验收跳过；批次页面 Vitest 7 项通过；`npm run build` 和 `python -m py_compile backend/batch_monitor.py backend/listing_prices.py backend/db.py` 通过。导入 `backend.main` 的旧夹具会提前初始化数据库，已移除该导入；检查到 `data/app.db` 写入时间早于本轮测试，真实库未改动。pytest 不在现有虚拟环境，Listing pytest 文件未执行；浏览器端到端未验收。生产构建仍提示主 chunk 超过 500KB，与本轮无关。
- 直接相关文件：`backend/batch_monitor.py`、`backend/db.py`、`backend/listing_prices.py`、`frontend/src/BatchMonitorPage.tsx`、`frontend/src/BatchMonitorPage.test.tsx`、`frontend/src/api.ts`、`frontend/src/styles.css`、`tests/test_batch_monitor.py`、`README.md`、`CHANGELOG.md`。未对业务库执行升级或改数，未发布。

# 新 Codex 对话启动指南

如果你是一个刚刚接手项目的 Codex：

1. 首先阅读本 HANDOFF.md。
2. 不要立即全量扫描整个项目。
3. 根据当前任务，只打开 HANDOFF 中对应的关键文件。
4. 如果 HANDOFF 与实际代码冲突，以实际代码为准。
5. 修改代码前，先确认是否存在相关设计决策。
6. 修改完成后，同步更新 HANDOFF.md 中受影响的部分。
## 21. 批次监控移除价格指标（2026-10-09）

- 按用户确认，批次监控不再显示或监控“无当前价 SKU”“低于开售价 SKU”“近7日变价 SKU”。列表响应只保留未完成批次、待美工、待发货 SKU、待到货 SKU 四项进度统计。
- 删除批次专用 Listing 指标扫描、`/api/batch-monitor/price-metrics` 路由及前端请求状态；批次页不再为这三项读取全量批次 SKU 或加载 Listing 价格历史。其它页面的 Listing 价格服务和批次详情中的价格展示未改。
- 第20节保存后完整指标列表的耗时对比属于移除这三项之前的历史基准；本次移除后未重新声称端到端性能提升。
- 验证（2026-10-09）：批次后端 unittest 15 项运行、1 项按已有文件验收规则跳过；批次页面 Vitest 7 项通过；后端 py_compile、前端生产构建和 git diff --check 通过。未做浏览器实机验收，也未在本次移除 KPI 后重新测量端到端耗时。
## 22. 批次监控列表故障修复（2026-10-10）

- 真实服务日志确认列表 500 的原因：`_cached_operational_developer_maps` 使用字符串作为版本缓存键，却直接将其交给要求 `Path` 的 `read_local_table`，冷读运营原始表时触发 `AttributeError: 'str' object has no attribute 'suffix'`。复制清单不经过该读取，因此会出现清单有内容、列表和指标加载失败的现象。
- 缓存函数内部恢复 `Path(path_text)`，Parquet 源依赖和读取器共用该对象；保留原开发员筛选口径及版本失效规则。
- 新增 `test_list_reads_real_operational_sources_and_invalidates_scope_cache`：真实临时 CSV/Excel、临时数据库和缓存，不替换开发员映射计算；验证三个状态视图、未归属数量、同版本复用及源文件替换后重新读取。修复前两种文件均复现同一异常；修复后批次 unittest 16 项运行、15 项通过、1 项外部文件验收跳过（85 秒外层硬超时，测试耗时 79.093 秒）。git diff --check 通过。
- 已通过项目系统接口重启本机服务加载修复。重启前在真实数据库的临时副本执行初始化，确认无需结构升级且内容不变；未提交真实批次状态变更，未发布。收尾全库指纹与重启前不同，期间待办表出现新的更新时间，不能宣称全库前后一致；批次表、货件表和批次版本的最新修改时间仍在 2026-10-09 或更早。
- 本机只读验证：未完成、全部、已完成列表均 HTTP 200，进度统计和未归属数量恢复；一键完成 PUT 路由出现在当前 OpenAPI。浏览器工具连续启动失败（Windows sandbox setup refresh 错误），页面视觉与点击验收未完成，不能据此宣称已验收。
- 直接相关文件：`backend/batch_monitor.py`、`tests/test_batch_monitor.py`、`CHANGELOG.md`、`HANDOFF.md`。

## 23. 新品监控（2026-10-13）

- 新品监控位于“产品管理”组下，路由为 ?page=new-products；核心数据来自运营原始表和首批货件开售日期。
- 新品范围为开售0～100天（含边界）。覆盖天数=可售/运营日均销量；可售>0且覆盖<5建议涨价，覆盖>90建议降价；有库存且日均为0的 SKU 开售满7天后进入降价清单。零库存单列，核心缺失/无效值及SKU-ASIN冲突不进入清单。重复SKU先聚合、合并开发员并检测冲突，再筛选开发员。
- dashboard/data_processing.py 的 build_new_product_monitor_table 保留核心缺失值，数值列用向量化 sum(min_count=1) 汇总。backend/dashboard_api.py 按运营表、毛利、Rating、图片映射及其上传索引、批次版本与北京时间日期缓存全量新品基础表；同版本并发冷请求合并为一次计算，筛选缓存只处理已计算的新品行。版本检查不再扫描Listing、历史销量等无关源。
- 页面使用 GET /api/dashboard/new-products/view 一次返回概览、完整copy_lists和指定页明细，支持开发员、开售阶段、SKU/ASIN搜索、状态、分页和排序。保留原 /new-products、/new-products/copy-lists、/new-products/sections/detail 与CSV导出接口。复制清单和概览忽略状态和分页，复制清单按开发员、阶段、搜索过滤。状态只影响明细与导出；源上传、到货变更、手动刷新、跨北京时间午夜保持更新。
- 前端页为 frontend/src/NewProductMonitorPage.tsx；请求序号及AbortController保护快速筛选，加载期间禁止复制旧清单。毛利、Rating和图片仍为可选字段。表格翻页不会触发排序处理或重置回第一页。
- 2026-10-13性能复测：真实本机源数据包含824个新品SKU；同一进程新筛选条件、未启用剖析器的后端组装耗时，首次全部从3875.89ms降至1209.88ms，开发员（464行）从3627.36ms降至24.44ms，涨价状态（9行）从3618.06ms降至26.10ms。这是后端函数耗时，不是浏览器端到端时间。
- 验证：新品后端unittest 12项通过，页面Vitest 5项通过，TypeScript/Vite生产构建通过（仍有主chunk超过500KB的既有警告）。回归覆盖原窗口与库存阈值、空值及冲突、分页/CSV/完整复制清单、同版本并发复用、上传/到货/跨日失效、开发员和搜索单次请求、快速筛选旧响应保护。
- 本机服务已通过现有系统重启接口加载优化。只读实服HTTP验证：首次view 1518.81ms，开发员筛选44.74ms，涨价状态41.28ms，SKU搜索34.22ms；全部824行、选定开发员464行、涨价9行，完整复制清单和CSV导出与筛选一致。这是单次本机接口样本，未声称浏览器端到端耗时。


## 24. 全板块加载提速与筛选统一（2026-10-13）

- 实际价格 `/api/pricing/observations` 先按日期、站点、类型和关键词筛选并分页，再核验当前页及计算销量响应；验证/登记信息和开售价索引按 SQLite/WAL 文件版本缓存，销量响应源按相关源版本缓存并预转换数值列。提供状态筛选时仍先对所有基础匹配项核验再分页，以保持状态筛选结果和总数正确。原始响应结构和 SKU 优先、ASIN 回退及前后时间窗口径不变。
- 部门监控增加 `view=performance|commission`：业绩视图复用标准化后的业绩输入和当前版本统计表；提成视图仅组装所选月份；考核继续独立加载。产品接口增加 `view=detail|low-margin`，并复用当前价格、毛利、Rating、图片索引；当前价读取避免加载完整 Listing 历史。
- 经营首页、销量、滞销、促销、批次等热点源按源文件/数据库版本及业务日期缓存，减少筛选请求的全历史版本扫描与重复标准化。部门业绩配置数值解析和金额历史合并使用向量化路径。补货的参考价格继续按展开/当前页单独加载。
- 前端全局筛选使用 `ConfirmFilterSelect`：草稿在弹层内暂存，点击“确定”只提交该字段；多选支持搜索、全选当前搜索结果、清空及已选数量，空选择代表全部。文字搜索仅在 Enter/搜索图标后提交，确认下拉不提交未搜索的文字。重置恢复各视图默认值并回第一页；排序和分页即时应用于已确认条件。保留独立表格搜索自身范围、配置未保存保护和业务编辑操作。
- 导出按钮统一为“导出筛选结果”；新品清单继续覆盖全部匹配项并忽略状态、分页，页面说明清单范围。其他复制/导出使用已应用条件，加载期间禁用旧清单复制。请求序号、AbortController 和相同条件请求合并覆盖主要异步看板；隐藏页面只在激活时加载。
- 实服基准（2026-10-13，HTTP 200，每个接口同条件采样9次；首个样本含服务内缓存冷读，热请求P95为8个后续样本的实测最大值）：

| 页面/视图 | 首次请求 ms | 热请求 P95 ms |
| --- | ---: | ---: |
| 实际价格 | 1421.5 | 169.9 |
| 部门业绩 | 1980.4 | 22.3 |
| 部门提成 | 364.3 | 41.7 |
| 产品明细 | 603.8 | 44.0 |
| 低毛利 SKU | 349.8 | 33.8 |
| 销量看板 | 810.2 | 61.2 |
| 滞销提醒 | 282.8 | 19.1 |
| 经营首页 | 987.6 | 37.1 |
| 补货管理 | 169.0 | 77.6 |
| 新品监控 | 793.4 | 43.1 |

  实际价格和部门业绩的数值为最后一次服务重启后的复测；其余视图在最终服务重启前采样，最终改动只涉及实际价格缓存。此前计划中的旧样本：部门监控切月7.44秒、实际价格超过15秒未返回、产品切开发员1.96秒、销量1.23秒、经营首页0.75秒、滞销0.63秒。新旧样本机器状态和缓存热度不同，仅作接口层参考，不是浏览器端到端结果。
- 验证：后端相关 API unittest 57项通过、1项按已有外部文件条件跳过；数据处理定向测试85项通过，实际价格新增分页/状态/响应窗口测试3项通过；前端测试79项通过、生产构建通过；相关 Python 模块 py_compile 和 `git diff --check` 通过。构建仍显示主 JS chunk 超过500KB警告。
- 最终代码已通过现有本机系统接口重启加载。重启后实际价格9次请求首个1421.5ms、热请求P50 166.5ms/P95 169.9ms；部门业绩首个1980.4ms、热请求P50 18.1ms/P95 22.3ms。所有上述热请求P95低于500ms，实际价格低于200ms。
- 浏览器工具初始化两次均被 Windows sandbox 的 `helper_unknown_error: setup refresh had errors` / kernel exit 阻断；因此无法完成全部22个叶子的浏览器视觉、深浅主题、点击及端到端加载验收。接口样本覆盖本轮识别的10个热点视图，不把它们表述成22个页面的浏览器验收。未安装依赖、未改数据库结构、未发布。
- 直接相关文件：`backend/listing_prices.py`、`backend/dashboard_api.py`、`backend/promotions.py`、`backend/batch_monitor.py`、`backend/app_revisions.py`、`dashboard/data_processing.py`、`dashboard/parquet_cache.py`、`dashboard/report_store.py`、`frontend/src/FilterActions.tsx`、`frontend/src/DashboardPage.tsx`、`frontend/src/DashboardDecisionMatrices.tsx`、`frontend/src/PromotionBoard.tsx`、`frontend/src/ReplenishmentPage.tsx`、`frontend/src/BatchMonitorPage.tsx`、`frontend/src/NewProductMonitorPage.tsx`、`frontend/src/api.ts`、相关测试。

## 25. 全局筛选框统一改造（2026-10-21）

- 所有全局筛选下拉统一使用 `frontend/src/ConfirmFilterSelect.tsx`：32px 紧凑触发器显示全部、单项或已选数量；主题色跟随 Ant Design token，选项区可滚动，长名称自动换行。弹层含搜索、（多选时）全选当前搜索结果及固定清空/取消/确定操作。
- 搜索只过滤候选项，不提交条件；多选全选仅作用于当前搜索结果并保留其他已选项。勾选不会请求；确定立即提交单个条件，语义无变化则不请求；取消、Esc 和外部关闭丢弃草稿。多选空值代表全部，单选清空由页面恢复其业务默认值。
- 接入看板开发员、月份、部门、店铺类型、库龄、矩阵排序字段，考核监控开发员/月，促销候选及记录页开发员/状态，新品开发员/阶段/提醒状态，补货开发员/门槛/排序和批次状态。编辑表单、配置单元格、补货行内操作、上传操作及导航标签保留原交互。
- 全局筛选移除“应用筛选”和未应用提示；搜索框统一使用 Enter/搜索图标单独提交，文字草稿不随下拉确认提交。重置按钮保留各视图默认值和默认排序；确认条件后回第一页并保留排序。刷新、分页、导出和复制仍使用已确认条件，独立表格搜索继续限制在当前表格。
- 本轮仅修改前端，不改接口、数据库或统计口径。页面沿用现有请求序号和取消机制；新品页面继续在加载时禁止使用旧复制清单。
- 验证：共享筛选组件、Dashboard 决策矩阵/考核、新品、补货、批次及促销共6个相关 Vitest 文件61项通过；`npm.cmd run build` 中 TypeScript 检查与 Vite 生产构建通过；`git diff --check` 通过。构建仍提示主 JS chunk 超过500KB。
- 本轮未重启后端或改本机业务数据。浏览器页面和深浅主题的人工视觉验收待完成；computer-use 初始化时 trusted Node 进程连续两次意外退出，未能打开页面检查。
- 直接相关文件：`frontend/src/ConfirmFilterSelect.tsx`、`frontend/src/FilterActions.tsx`、`frontend/src/DashboardPage.tsx`、`frontend/src/DashboardDecisionMatrices.tsx`、`frontend/src/PromotionBoard.tsx`、`frontend/src/ReplenishmentPage.tsx`、`frontend/src/BatchMonitorPage.tsx`、`frontend/src/NewProductMonitorPage.tsx`、`frontend/src/styles.css`、相关前端测试。

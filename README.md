# 本地销售数据分析助手

当前版本：`v2.4.0` · 产品经营与变体管理

这是一个面向单人、本机桌面使用的销售数据分析应用。React 负责界面，FastAPI 负责数据读取、校验、计算、缓存与导出；项目不包含登录、权限体系和手机端适配，也不再使用 Streamlit。

服务默认只监听 `127.0.0.1:8000`，不会主动暴露到局域网。

## 下载 Windows 便携版

发布审计通知：v2.0.0～v2.3.0 便携包已撤为草稿，不再公开下载；相关分支和标签已清理误发布文件。v2.4.0 只携带 `config_templates/` 空白配置结构及通用指标公式，不含真实 `configs/`、内部交接或业务数据。旧 SHA 缓存及他人副本不属于新版本内容，不能保证已收回。

不需要配置 Python、Node.js 或 Docker，可直接从 [GitHub Releases](https://github.com/TreytonQT/Data_analysis_assistant/releases/latest) 下载 `DataAnalysisAssistant-windows-x64-v2.4.0.zip`：

1. 完整解压到固定目录，不要直接在压缩包内运行。
2. 双击 `DataAnalysisAssistant.exe`。
3. 程序就绪后会自动打开 `http://127.0.0.1:8000`。
4. 保留启动窗口；关闭窗口即停止程序。

发布包不包含业务数据、上传文件、SQLite 数据库或缓存。升级前请先关闭旧程序并备份旧目录中的 `data/` 和 `configs/`，再将它们复制到新版本目录。压缩包同时提供 SHA-256 校验文件。

## 主要功能

- **经营首页**：按月份、开发员、部门和店铺类型查看经营指标、趋势、排行、异常预警与提成预估。
- **销量看板**：按店铺和产品等级分析在售数、订单、日均销量及库存表现，并支持服务端排序和完整 CSV 导出。
- **产品经营**：经营诊断分为积压清仓、利润风险和新品低销，统一 SKU 处理队列、详情、勾选复制及按范围导出。清仓提供日均销量和可售天数；新品使用开售 0～99 天及可配置销量区间。
- **涨降价追踪**：分开查看最新实际涨价、降价，按每 5 个百分点分档，并用当前 7／30 天销量趋势 T 排名。站点证据按 SKU＋ASIN＋国家精确匹配，运营 SKU 汇总仅作独立参考，不混入站点统计。
- **统一 SKU 详情**：展示全部 ASIN、库存、资金、分国财务和价格，以及 30／90／180 天销量／价格曲线；已下架身份可进入只读历史。旧长期调价和限时促销历史及后端接口保留兼容，新页面不自动执行 ERP 改价。
- **变体管理**：按店铺识别真实父体和待合成组，保留多国语言属性；支持父 SKU 行内编辑、冲突确认、跨店参考以及状态／店铺／开发员筛选，重复加载复用源缓存。
- **部门监控**：提供统计报表业绩、月业绩报表提成和考核三个视图；按日历史支持前移 7 天的月度业绩预测，共享本土考核比例，并可在提成行展开维护提成与部门费用配置。
- **补货管理**：以 ASIN 为主行展示德/法/西/意站点毛利、库存矩阵、趋势测算、12 个月销量画像、库存图片和建议补货数量；支持搜索、开发员批量筛选、最低补货量、排序、分页、Excel 导出、产品标签和带原因的不补货操作。
- **批次监控**：创建和导入批次，维护美工图、开售价、首次货件绑定与到货状态；可一键完成或撤销手动完成，自动更新待办统计和 SKU/货件复制清单。
- **上传中心**：领星产品监控表每日同时更新价格、变体和 Rating，不再单独上传评分；管理业绩、运营／毛利、图片、销量明细及滚动 12 个月销量原始表，支持预览、下载、替换和删除。
- **配置中心**：维护指标公式、店铺、目标、库存覆盖规则、补货开关和 ASIN 产品标签；提成与费用率在部门提成监控中维护。
- **待办提醒**：创建、排序、流转、重复提醒、导入和导出本地待办事项；每月重复选择单个日期，已完成任务保留至手动删除。

界面使用多级菜单和最近访问标签页组织业务视图，支持浏览器前进/后退恢复页面与筛选状态。保存、上传、下载、复制、删除等操作会显示统一的进行中、成功或失败反馈。

## 本地源码运行

首次克隆后，先执行 `Copy-Item config_templates configs -Recurse` 初始化配置，再按需在配置中心填写。已有 `configs/` 时请保留原目录，不执行覆盖。模板不含人员、店铺、提成金额、目标和具体运输规则。

建议使用 Python 3.12 和 Node.js 20 或更高版本。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

安装并构建完成后，双击 `start_dashboard.bat`，或在终端运行：

```powershell
.\start_dashboard.bat
```

启动脚本会调用独立桌面启动器，检查 Python 依赖、React 构建产物和 `8000` 端口，在后台启动 FastAPI，等待 `/api/health` 就绪后再打开浏览器。运行日志和进程号保存在 `.tmp/`。

停止由启动脚本创建的服务：

```powershell
Stop-Process -Id (Get-Content .tmp\dashboard.pid)
```

首次部署后，可运行 powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_desktop_shortcut.ps1 创建桌面“销售数据看板”快捷方式。该快捷方式启动的服务不依赖 Codex 或启动终端保持打开。

看板右上角的“系统”菜单提供“重启系统”和“退出系统”。重启会恢复当前页面，退出后请使用桌面快捷方式重新启动。

## 开发模式

先安装开发依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

分别启动后端和前端：

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
cd frontend
npm.cmd run dev
```

Vite 开发服务器会把 `/api` 请求代理到本机 FastAPI。生产构建由 FastAPI 直接提供，因此修改前端后需要重新执行 `npm.cmd run build`。

## 数据与更新频率

| 频率 | 数据源 | 主要用途 |
| --- | --- | --- |
| 每日 | 运营原始表、毛利原始表、销量明细、销售额明细、领星产品监控表（价格／变体／Rating） | 产品经营、部门、补货及价格追踪 |
| 每周 | 业绩报表 | 月度经营、提成与考核 |
| 每月 | 往月销量原始表、SKU 图片映射表 | 补货页滚动 12 个月销量画像（首次上传必须包含连续 12 个月）；矩阵库存图片 |

- `data/` 保存原始文件、上传记录和 `app.db`。原始文件是权威数据，不能用 Parquet 替代。
- `configs/` 保存指标、店铺、目标、提成、部门费用率和补货业务配置；部门提成与考核比例也可在部门监控页面维护。
- `data/listing_prices/` 保存按日 Listing 快照与索引；`data/cache/` 是根据源文件指纹与 schema 版本生成的可重建 Parquet 缓存，不属于备份内容。

升级、迁移或批量导入前，应停止程序并同时备份 `data/` 和 `configs/`。上传失败不会以缓存文件作为恢复来源。
## 导航、筛选与加载

- 工作台采用统一浅色/深色主题、小水怪品牌图和公共组件；经营首页分组呈现指标、趋势、利润、广告与开发员概览，全部配置指标及原始区块仍可在明细中查看。
- 全局筛选支持“仅筛选此项”，立即以当前候选替换该字段；普通勾选仍仅修改草稿，确定后生效。
- 折线、分组柱图、补货月销量及价格阶梯图支持横坐标吸附、数值浮层、键盘和触屏操作；页面动效尊重系统减少动态效果偏好。
- 补货默认最低数量为 0，可自行提高门槛；产品名称取原 SKU 名称，缺失时回退组内名称，支持名称搜索与导出。

- 产品经营侧栏提供经营诊断、涨价追踪、降价追踪，变体管理为独立一级入口；旧产品／滞销／新品／价格书签会映射到对应新视图。
- 顶部最近访问标签支持关闭其他、关闭右侧；经营首页始终保留。重启和退出位于系统菜单。
- 补货页面先显示核心矩阵，再按当前页补齐价格与趋势；价格区域支持失败重试。四站点销量来自最新销量明细，滚动 12 个月画像独立展示，附加价格与站点数据不改变基础建议量。
- 批次监控只展示进度与待办统计，不加载无当前价、低于开售价、近7日变价三项价格指标；新建、状态更新、到货和一键完成成功后立即反馈并更新当前数据，必要的列表与复制清单在后台刷新。未完成批次可一键结束监控，实际美工图、发货与到货进度保持原样；可撤销手动完成，手动完成批次退出待办统计和复制清单。

## 新增数据与计算口径

- SKU 图片映射推荐列为 `MSKU、ASIN、图片链接`，按两项标识精确关联，不会按 MSKU 单独回退到其他 ASIN 图片；兼容旧 `库存SKU、虚拟SKU、库存图片链接` 格式。链接必须为有效公网 HTTPS URL，重复相同记录合并，冲突拒绝，空链接跳过并提示。

- 领星工作簿文件名须包含 `ListingYYYYMMDD`，恰好一个工作表包含 `MSKU、ASIN、国家、币种、售价(总价)、运费、积分、价格、优惠价、Rating总数、评分`；变体另需父 ASIN 及属性。快照保留 180 个日历日，同日替换，旧格式历史仍可读取，详见 [统一上传](docs/LISTING_RATING_UPLOAD.md)。
- 新品开售日期来自首次到货／开售数据，默认可售库存大于 0、90 天销量小于 5，缺失不当零。清仓日均按上架年龄校准 7／14／30 天销量，可售天数使用完整 SKU 补货口径库存，详见 [产品经营](docs/PRODUCT_OPERATIONS.md)。
- 部门业绩预测需要销售额明细与按日历史。考核页采用 `中企销售额 + x × 本土销售额`，预测考核采用 `中企原始预估 × 0.8 + 本土原始预估 × x`；`x` 在当前浏览器保存并跨相关视图同步。
- 长期调价与限时活动分表保存，调价不会改写最初开售价；旧版开放结束日期记录不会在启动时被自动重新归类，迁移前请先备份并核对业务含义，详见 [部署与升级说明](DEPLOYMENT.md)。

## 测试与构建检查

```powershell
# 每个测试文件独立运行，兼容 unittest 类与 pytest 函数，并限制单命令时长
Get-ChildItem tests\test_*.py | ForEach-Object {
  .venv\Scripts\python.exe scripts\run_bounded.py --timeout 85 -- .venv\Scripts\python.exe -m pytest -q $_.FullName
  if ($LASTEXITCODE -ne 0) { throw "后端回归失败：$($_.Name)" }
}

cd frontend
..\.venv\Scripts\python.exe ..\scripts\run_bounded.py --timeout 85 -- cmd.exe /d /c npm.cmd test
..\.venv\Scripts\python.exe ..\scripts\run_bounded.py --timeout 85 -- cmd.exe /d /c npm.cmd run build
```

使用当前工作区数据执行一次冷请求和五次热请求性能基准：

```powershell
.venv\Scripts\python.exe scripts\benchmark_dashboard.py
```

自动化代理运行安装、构建或测试命令时须遵循 [AGENTS.md](AGENTS.md) 中的 90 秒上限、有限重试和分批安装规则。

## 代码结构

- `backend/`：FastAPI 路由、看板接口、配置、上传、批次和本地 SQLite 功能
- `frontend/`：React 桌面端界面
- `dashboard/`：数据标准化、公式、业务计算、文件存储和 Parquet 缓存
- `config_templates/`：可公开的配置表头和通用指标公式
- `configs/`：本机业务配置（不提交）
- `data/`：本地原始数据、缓存和数据库（不提交到 Git）
- `packaging/`：PyInstaller Windows 便携版入口与打包配置
- `.github/workflows/`：标签触发的 Windows 测试、打包和 Release 发布流程
- `tests/`：后端业务与 API 回归测试

版本更新记录见 [CHANGELOG.md](CHANGELOG.md)，本机和 Docker 部署细节见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 专项说明与独立工具

- [产品经营与价格追踪](docs/PRODUCT_OPERATIONS.md)、[变体管理](docs/VARIANT_MANAGEMENT.md)、[领星统一上传](docs/LISTING_RATING_UPLOAD.md)。
- [独立亚马逊跟卖表格助手](follow_sell/README.md) 的源码及测试随仓库提供；它有独立资源和启动入口，不包含在本 Release 的看板 EXE 中。业务原表及完整参考工作簿不随源码公开，独立便携包需按其说明另外构建。


## UI 与开发一致性规范

前端沿用现有Ant Design工作台、深浅主题与业务决策矩阵。Design Tokens、基础组件API、筛选/表单/上传/反馈约定及代码组织要求见 [UI、代码与组件复用规范](docs/UI_CODE_STANDARDS.md)。

内部实施记录、代理指令和本机交接材料仅在本地保留，不作为公开项目文档。后续开发不改动业务计算和存储契约来迁就界面。

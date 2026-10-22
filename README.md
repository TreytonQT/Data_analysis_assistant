# 本地销售数据分析助手

当前版本：`v2.2.0` · 新品与价格监控

这是一个面向单人、本机桌面使用的销售数据分析应用。React 负责界面，FastAPI 负责数据读取、校验、计算、缓存与导出；项目不包含登录、权限体系和手机端适配，也不再使用 Streamlit。

服务默认只监听 `127.0.0.1:8000`，不会主动暴露到局域网。

## 下载 Windows 便携版

不需要配置 Python、Node.js 或 Docker，可直接从 [GitHub Releases](https://github.com/TreytonQT/Data_analysis_assistant/releases/latest) 下载 `DataAnalysisAssistant-windows-x64-v2.2.0.zip`：

1. 完整解压到固定目录，不要直接在压缩包内运行。
2. 双击 `DataAnalysisAssistant.exe`。
3. 程序就绪后会自动打开 `http://127.0.0.1:8000`。
4. 保留启动窗口；关闭窗口即停止程序。

发布包不包含业务数据、上传文件、SQLite 数据库或缓存。升级前请先关闭旧程序并备份旧目录中的 `data/` 和 `configs/`，再将它们复制到新版本目录。压缩包同时提供 SHA-256 校验文件。

## 主要功能

- **经营首页**：按月份、开发员、部门和店铺类型查看经营指标、趋势、排行、异常预警与提成预估。
- **销量看板**：按店铺和产品等级分析在售数、订单、日均销量及库存表现，并支持服务端排序和完整 CSV 导出。
- **滞销提醒**：计算库龄库存、占用资金、计提、弃置费用和库存覆盖天数；关联图片、最近一次限时促销和累计调价，并提供“调价与促销”“实际价格”入口。
- **调价与促销**：分别登记长期调价和限时活动；长期调价按生效日期累乘计算降幅，支持批次、登记预览、重复请求保护、作废纠错和审计，限时活动支持同 SKU 时间重叠校验。
- **实际价格**：上传按日 Listing 价格快照，查看德/法/西/意站点实际售价、价格历史、变价事件、登记生效观察与销量趋势参考。调价登记和监控用于本地分析，平台改价仍需在业务系统中完成。
- **产品管理**：合并运营、毛利、Rating、批次、图片和当前促销数据，以决策矩阵查看 SKU 级产品表现与低毛利异常。
- **新品监控**：在产品管理下查看开售 0～100 天的 SKU，按可售库存、日均销量和覆盖天数提示涨价、降价、断货或观察中；支持确认后筛选、排序分页、建议 SKU 复制和 CSV 导出。
- **部门监控**：提供统计报表业绩、月业绩报表提成和考核三个视图；按日历史支持前移 7 天的月度业绩预测，共享本土考核比例，并可在提成行展开维护提成与部门费用配置。
- **补货管理**：以 ASIN 为主行展示德/法/西/意站点毛利、库存矩阵、趋势测算、12 个月销量画像、库存图片和建议补货数量；支持搜索、开发员批量筛选、最低补货量、排序、分页、Excel 导出、产品标签和带原因的不补货操作。
- **批次监控**：创建和导入批次，维护美工图、开售价、首次货件绑定与到货状态；可一键完成或撤销手动完成，自动更新待办统计和 SKU/货件复制清单。
- **上传中心**：按每日、每周、每月分组管理业绩报表、运营/毛利原始表、Rating、SKU 图片映射表、Listing 价格快照、销量/销售额明细和滚动 12 个月销量原始表，支持预览、下载、替换和删除。
- **配置中心**：维护指标公式、店铺、目标、库存覆盖规则、补货开关和 ASIN 产品标签；提成与费用率在部门提成监控中维护。
- **待办提醒**：创建、排序、流转、重复提醒、导入和导出本地待办事项；每月重复选择单个日期，已完成任务保留至手动删除。

界面使用多级菜单和最近访问标签页组织业务视图，支持浏览器前进/后退恢复页面与筛选状态。保存、上传、下载、复制、删除等操作会显示统一的进行中、成功或失败反馈。

## 本地源码运行

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
| 每日 | 业绩报表、运营原始表、毛利原始表、销量明细、销售额明细、Listing价格快照 | 经营、销量、滞销、产品、部门、补货和实际价格观察 |
| 每周 | Rating | 产品与补货的站点评分、评价数量 |
| 每月 | 往月销量原始表、SKU 图片映射表 | 补货页滚动 12 个月销量画像（首次上传必须包含连续 12 个月）；矩阵库存图片 |

- `data/` 保存原始文件、上传记录和 `app.db`。原始文件是权威数据，不能用 Parquet 替代。
- `configs/` 保存指标、店铺、目标、提成、部门费用率和补货业务配置；部门提成与考核比例也可在部门监控页面维护。
- `data/listing_prices/` 保存按日 Listing 快照与索引；`data/cache/` 是根据源文件指纹与 schema 版本生成的可重建 Parquet 缓存，不属于备份内容。

升级、迁移或批量导入前，应停止程序并同时备份 `data/` 和 `configs/`。上传失败不会以缓存文件作为恢复来源。
## 导航、筛选与加载

- 产品管理明细、低毛利率 SKU 和实际价格均以侧栏为入口；旧 URL 参数仍兼容。实际价格观察只读取价格观察数据，不加载调价与促销概览。
- 顶部最近访问标签支持关闭其他、关闭右侧；经营首页始终保留。重启和退出位于系统菜单。
- 补货页面先显示核心矩阵，再按当前页补齐价格与趋势；价格区域支持失败重试。四站点销量来自最新销量明细，滚动 12 个月画像独立展示，附加价格与站点数据不改变基础建议量。
- 批次监控只展示进度与待办统计，不加载无当前价、低于开售价、近7日变价三项价格指标；新建、状态更新、到货和一键完成成功后立即反馈并更新当前数据，必要的列表与复制清单在后台刷新。未完成批次可一键结束监控，实际美工图、发货与到货进度保持原样；可撤销手动完成，手动完成批次退出待办统计和复制清单。

## 新增数据与计算口径

- Listing 工作簿文件名须包含 `ListingYYYYMMDD`（例如 `Listing20261022.xlsx`），且恰好一个工作表包含 `MSKU、ASIN、国家、币种、售价(总价)、运费、积分、价格、优惠价`。同一天上传整体替换该日快照；价格缺失、跨日间隔和异常会显式展示。
- 新品开售日期来自首次到货/开售数据：覆盖不足 5 天提示涨价，超过 90 天提示降价；有库存但零销量时，未满 7 天继续观察，满 7 天提示降价。缺失或冲突数据会标识异常，涨降价清单按已应用筛选生成，不受表格分页影响。
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
- `configs/`：默认业务配置
- `data/`：本地原始数据、缓存和数据库（不提交到 Git）
- `packaging/`：PyInstaller Windows 便携版入口与打包配置
- `.github/workflows/`：标签触发的 Windows 测试、打包和 Release 发布流程
- `tests/`：后端业务与 API 回归测试

版本更新记录见 [CHANGELOG.md](CHANGELOG.md)，本机和 Docker 部署细节见 [DEPLOYMENT.md](DEPLOYMENT.md)。

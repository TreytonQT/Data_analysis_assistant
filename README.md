# 本地销售数据分析助手

当前版本：`v2.0.1`

这是一个面向单人、本机桌面使用的销售数据分析应用。React 负责界面，FastAPI 负责数据读取、校验、计算、缓存与导出；项目不包含登录、权限体系和手机端适配，也不再使用 Streamlit。

服务默认只监听 `127.0.0.1:8000`，不会主动暴露到局域网。

## 下载 Windows 便携版

不需要配置 Python、Node.js 或 Docker，可直接从 [GitHub Releases](https://github.com/TreytonQT/Data_analysis_assistant/releases/latest) 下载 `DataAnalysisAssistant-windows-x64-v2.0.1.zip`：

1. 完整解压到固定目录，不要直接在压缩包内运行。
2. 双击 `DataAnalysisAssistant.exe`。
3. 程序就绪后会自动打开 `http://127.0.0.1:8000`。
4. 保留启动窗口；关闭窗口即停止程序。

发布包不包含业务数据、上传文件、SQLite 数据库或缓存。升级前请先关闭旧程序并备份旧目录中的 `data/` 和 `configs/`，再将它们复制到新版本目录。压缩包同时提供 SHA-256 校验文件。

## 主要功能

- **经营首页**：按月份、开发员、部门和店铺类型查看经营指标、趋势、排行、异常预警与提成预估。
- **销量看板**：按店铺和产品等级分析在售数、订单、日均销量及库存表现。
- **滞销提醒**：计算库龄库存、占用资金、计提与弃置费用；按动销策略生成促销候选、复制 SKU、记录促销周期并跟踪日均销量提升。
- **产品管理**：合并运营、毛利、Rating 和批次数据，查看 SKU 级产品表现与低毛利异常。
- **部门监控**：按开发员、部门和店铺汇总在售 SKU、库存总数、占用资金、近 7 天订单与销售额。
- **补货管理**：以 ASIN 为主行展示德/法/西/意站点毛利、库存矩阵、趋势测算、12 个月销量画像和建议补货数量；支持搜索、排序、分页、Excel 导出、产品标签和补货开关，并可展开查看 SKU 级站点毛利与促销信息。
- **批次监控**：创建和导入批次，维护美工图、上架售价、货件绑定与到货状态，并识别未绑定或未归属批次的 SKU。
- **上传中心**：按每日、每周、每月分组管理业绩报表、运营原始表、毛利原始表、Rating、销量/销售额明细和滚动 12 个月销量原始表，支持预览、下载、替换和删除。
- **配置中心**：维护指标公式、店铺、目标、提成、部门费用率、库存覆盖规则、补货开关和 ASIN 产品标签。
- **待办提醒**：创建、排序、流转、重复提醒、导入和导出本地待办事项。

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

启动脚本会检查 Python 依赖、React 构建产物和 `8000` 端口，后台启动 FastAPI，等待 `/api/health` 就绪后再打开浏览器。运行日志和进程号保存在 `.tmp/`。

停止由启动脚本创建的服务：

```powershell
Stop-Process -Id (Get-Content .tmp\dashboard.pid)
```

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
| 每日 | 业绩报表、运营原始表、毛利原始表、销量明细、销售额明细 | 经营、销量、滞销、产品、部门和补货计算 |
| 每周 | Rating | 产品与补货的站点评分、评价数量 |
| 每月 | 往月销量原始表 | 补货页滚动 12 个月销量画像；首次上传必须包含连续 12 个月 |

- `data/` 保存原始文件、上传记录和 `app.db`。原始文件是权威数据，不能用 Parquet 替代。
- `configs/` 保存指标、店铺、目标、提成、部门费用率和补货业务配置。
- `data/cache/` 是根据源文件指纹与 schema 版本生成的可重建 Parquet 缓存，不属于备份内容。

升级、迁移或批量导入前，应停止程序并同时备份 `data/` 和 `configs/`。上传失败不会以缓存文件作为恢复来源。

## 测试与构建检查

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests

cd frontend
npm.cmd test
npm.cmd run build
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

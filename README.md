# 本地销售数据分析助手

这是一个仅供单人、本机桌面使用的销售数据看板。React 负责界面，FastAPI 负责数据读取、校验、计算、缓存与导出；项目不包含登录、权限体系和手机端适配，也不再使用 Streamlit。

服务默认只监听 `127.0.0.1:8000`，不会主动暴露到局域网。

## 首次安装

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

Vite 开发服务器会把 `/api` 请求代理到本机的 FastAPI 服务。生产构建由 FastAPI 直接提供，因此修改前端后需要重新执行 `npm.cmd run build`。

## 数据与缓存

- `data/` 保存上传的原始 CSV/XLS/XLSX、上传记录和 `app.db`。原始文件是权威数据，不能用 Parquet 替代。
- `configs/` 保存指标公式、店铺、月目标、提成、部门费率和补货等业务配置。
- `data/cache/` 只保存根据源文件指纹和 schema 版本生成的 Parquet 缓存。缓存损坏或版本变化时会自动重建；应用停止后可安全删除整个缓存目录。

升级或批量导入前，应同时备份 `data/`、`configs/` 和 `data/app.db`。上传失败不会以缓存文件作为恢复来源。

## 主要功能

- 经营总览、销售、滞销、产品、部门和补货看板
- 滞销页内的促销提醒：按动销策略自动分档、复制 SKU、标记促销周期并统计日均销量提升
- 按月份、开发员、部门、店铺类型等条件筛选
- 大表分页、搜索、排序和 CSV 导出
- 业绩及运营/毛利/Rating 数据源上传与下载
- 指标公式、店铺、目标、提成、费用率和补货配置维护
- 现有待办功能保持原状，本轮未扩展

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

- `backend/`：FastAPI 路由、看板接口、配置、上传和本地 SQLite 功能
- `frontend/`：React 桌面端界面
- `dashboard/`：共享的数据标准化、公式、业务计算、文件存储和 Parquet 缓存
- `configs/`：本地业务配置
- `data/`：本地原始数据、缓存和数据库（不提交到 Git）
- `tests/`：后端业务与 API 回归测试

Docker 是可选运行方式，详见 [DEPLOYMENT.md](DEPLOYMENT.md)。

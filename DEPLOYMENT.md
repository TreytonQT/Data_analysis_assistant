# React + FastAPI 本地运行与 Docker 说明

本项目面向单人、本机桌面使用。普通 Windows 用户推荐使用 GitHub Release 便携版；源码环境的正式入口是 `start_dashboard.bat`，Docker 只是可选方案。所有方式都应只从 `127.0.0.1` 访问，不提供登录或局域网公开服务。

## Windows 便携版（推荐）

从 [GitHub Releases](https://github.com/TreytonQT/Data_analysis_assistant/releases/latest) 下载 `DataAnalysisAssistant-windows-x64-v2.0.1.zip` 和对应的 `.sha256.txt`：

1. 可选：使用 `Get-FileHash` 核对压缩包 SHA-256。
2. 将压缩包完整解压到固定目录，不要直接在压缩包中运行。
3. 双击 `DataAnalysisAssistant.exe`；就绪后会自动打开 `http://127.0.0.1:8000`。
4. 保留启动窗口；关闭窗口或按 `Ctrl+C` 即停止程序。

```powershell
Get-FileHash .\DataAnalysisAssistant-windows-x64-v2.0.1.zip -Algorithm SHA256
```

便携版内置前端和 Python 运行环境，不要求另行安装 Python、Node.js 或 Docker。首次运行会在程序目录旁创建 `data/` 和空数据库，默认配置位于 `configs/`。

升级便携版时，先关闭旧程序并备份旧目录中的 `data/` 与 `configs/`，完整解压新版后再将备份复制到新版目录。不要直接用新版空目录覆盖唯一的数据副本。

## 本机源码运行

首次安装：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

之后运行：

```powershell
.\start_dashboard.bat
```

脚本按以下顺序启动：

1. 检查 `.venv` 和 Python 运行依赖。
2. 检查 `frontend/dist/index.html` 是否存在。
3. 检查本机 `8000` 端口是否空闲。
4. 以 `127.0.0.1:8000` 启动 FastAPI。
5. 最多等待 30 秒，只有健康检查成功后才打开浏览器。

标准输出、错误日志和进程号分别位于：

- `.tmp/dashboard.stdout.log`
- `.tmp/dashboard.stderr.log`
- `.tmp/dashboard.pid`

停止后台服务：

```powershell
Stop-Process -Id (Get-Content .tmp\dashboard.pid)
```

## Docker（可选）

Docker 镜像只复制 React 构建所需文件、`backend/`、`dashboard/` 和固定版本的 Python 依赖。镜像不包含本地 `data/`、`configs/`、虚拟环境、Git 历史、测试目录或 `node_modules`。

Compose 会把已有目录挂载进容器：

- `./data` → `/app/data`
- `./configs` → `/app/configs`

因此在迁移到另一台电脑时，应先完整复制这两个目录，再启动容器。不要用空的 `configs/` 覆盖已有业务配置。

```powershell
docker compose up --build -d
docker compose ps
```

访问 `http://127.0.0.1:8000`。Compose 端口明确绑定到宿主机回环地址；容器内部监听 `0.0.0.0` 仅用于 Docker 端口转发。运行进程使用非 root 用户，并带有 `/api/health` 健康检查。

查看日志或停止：

```powershell
docker compose logs -f dashboard
docker compose down
```

## 数据备份与恢复

执行版本升级、配置批量修改或大批量上传之前，停止服务并备份：

- `data/` 下所有原始 CSV/XLS/XLSX 和上传记录
- `data/app.db`
- `configs/` 下所有配置 CSV

`data/cache/` 是可重建的 Parquet 加速层，不是备份。服务停止后可以删除该目录；下次读取源文件时会自动补建。恢复时以原始文件、上传记录、配置 CSV 和 SQLite 数据库为准。

## 常见问题

### 提示 8000 端口被占用

```powershell
netstat -ano | findstr :8000
```

确认进程后再停止它，或先停止已运行的 Docker Compose 服务。启动脚本不会覆盖或复用未知进程。

### 找不到 React 构建产物

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
```

### 健康检查超时

先查看 `.tmp/dashboard.stderr.log`。也可在前台运行后端以获得完整错误：

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 验证服务状态

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

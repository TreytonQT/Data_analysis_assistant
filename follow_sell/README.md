# 独立亚马逊跟卖表格助手

Python处理与服务入口位于本目录，独立前端位于 `frontend/src/followSell/`，Vite入口为 `frontend/follow-sell.html`。不注册到现有工作台，不导入 `backend.main`，不使用真实SQLite、data或configs。

## 规则

- OA：使用已核对的102列表头及中文说明行，新SKU按映射顺序输出；`LENGTH → LENGHT`。德法西意领星价格优先，缺失回退OA并告警，两处都缺失则阻断。其他字段复制OA。
- 马帮：`新虚拟SKU → 映射表原SKU → 原马帮虚拟SKU`精确匹配。分号分隔的多个新SKU必须归于同一原SKU。只覆盖processor中12个业务字段，保护两个新SKU标识，保留其他列、样式及工作表。缺少的源业务列不更新，空白覆盖为空白。
- 新SKU唯一，原SKU可复用。相关来源键歧义、冲突售价、空键或未匹配记录整批阻断；同SKU同国家同价重复可合并。零售价与空售价不同。
- 所有POST要求本次启动生成的会话token并检查Origin；仅接受本机Host。结果只在内存缓存最近12批，保存采用独占创建并在当前预览内幂等；不覆盖输入。
- 只接受xlsx，每文件50MB，解压后200MB上限；说明行仅存在于OA输出模板，不会把源文件中的任意备注当作指令执行。

## 独立接口

- `GET /api/settings`：默认输出目录与会话token；变更接口通过 `X-Follow-Sell-Token` 传入。
- `POST /api/process/oa`：multipart字段mapping、oa、prices。
- `POST /api/process/mabang`：multipart字段mapping、generated、original。
- 成功返回result_id、summary、columns、rows、warnings、filename；422返回detail.message/count/issues，issue包含file/sheet/row/sku/message。
- `POST /api/results/{id}/save`：JSON output_dir，返回实际path；重复请求返回首次保存路径。`GET /api/results/{id}/download`下载副本。
- `GET /api/templates/{1..5}`、`POST /api/choose-directory`、`POST /api/shutdown`、`GET /api/health`。

## 资源与构建

沿用项目现有Python、前端及PyInstaller依赖，无新增UI库。所有构建、测试经 `scripts/run_bounded.py --timeout 85 -- ...` 执行；失败先报告，安装最多重试一次。

1. `python -m follow_sell.prepare_assets --source <参考文件目录> --output <交付根目录>` 只提取5份模板的表头和一条样本、OA表头/说明、原始文件校验和。7份完整参考文件不会进入资源包。
2. 用捆绑的artifact-tool Node运行时执行 `build_assets.mjs <交付根目录> <1|2|3|4|5|oa>`，每份独立运行；脚本旁需要能解析 `@oai/artifact-tool` 的node_modules。生成资源在交付目录work/resources，预览在work，5份模板在模板子目录。首次表格创作前按spreadsheets技能执行一次创作标记。
3. 当前版本号由 `follow_sell/__init__.py` 的VERSION统一维护（目前1.0.1）。从frontend目录执行 `node node_modules/vite/bin/vite.js build --config vite.follow-sell.config.ts`，设置 `FOLLOW_SELL_WEB_OUT=<交付目录>/work/v1.0.1/web`。将生成的follow-sell.html复制为同目录index.html。
4. 设置 `FOLLOW_SELL_RESOURCES=<交付目录>/work/resources`、`FOLLOW_SELL_WEB=<交付目录>/work/v1.0.1/web`，执行 `python -m PyInstaller --noconfirm --workpath <交付目录>/work/v1.0.1/pyinstaller --distpath <交付目录>/work/v1.0.1/dist follow_sell/AmazonFollowSell.spec`。
5. `python -m follow_sell.assemble --output <交付根目录>` 从对应版本的dist复制EXE、_internal、5份模板与使用说明，生成版本化便携目录、ZIP和SHA256，保留旧版本。不将开发日志、测试输出、原始表或验收表打进便携包。

源码运行：设置上述资源/网页环境变量后，`python -m follow_sell.launcher`。默认随机本机端口，测试可传 `--port 8876 --no-browser`。源码模式的FOLLOW_SELL_HOME默认是D盘交付目录，冻结模式使用EXE所在目录。上传可能使用的临时文件限定在程序work/tmp，日志在work/logs；构建时将PYINSTALLER_CONFIG_DIR指定到交付目录work/pyinstaller-cache。

## 验证

- 逻辑/接口：`python -m unittest follow_sell.test_processor -v`，夹具在D盘work/tests临时目录，不初始化现有业务库。
- 实际样本：`python -m follow_sell.verify_samples --source <原表目录> --output <交付根目录>`，逐单元格对比修正错位的OA例表与马帮例表，仅允许约定的19处0恢复空白，并检查7份原表校验和、5份红字模板。
- 前端：现有Vitest运行 `src/followSell/App.test.tsx`，覆盖文件替换、旧响应、错误、重复保存与失败重试；现有tsconfig执行无输出检查。
- UI沿用DesignSystemProvider、designTokens、PageHeading、PageState、feedback及apiErrors。CSS仅使用follow前缀及已定义token。独立入口无需改动既有工作台路由和共享组件。
- OA和马帮标题下提供输出文件提示；公开源码的马帮图片使用通用文件名示例，原始店铺文件名截图仅在本地保留。资源经Vite import内置，不依赖临时目录或网络。

内部验收材料和业务参考工作簿不随源码公开。真实浏览器测试与组件测试分别记录；已有机器上的EXE复测不等于全新Windows机器验证。本项目看板Release不附带此工具的独立EXE或模板资源，需要按上述步骤自行准备并构建。

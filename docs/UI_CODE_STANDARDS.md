# UI、代码与组件复用规范

本规范基于项目当前 React + Ant Design 桌面工作台，适用于新增及修改代码。2026-10-29 已落地的公共入口以本文件为准；不要求为格式统一重写存量业务模块。

## 工作边界

- 保持现有业务规则、计算、字段、API响应、CSV/Excel导出和存储结构。
- 产品/滞销按SKU，补货按ASIN，批次有独立进度语义；不要合并成一个万能表格。
- 保留已访问页面挂载、active/revision刷新、AbortController/请求序号、批次局部合并、补货价格分阶段加载。
- 原始文件是权威数据，缓存可重建；不要测试或迁移真实业务库。import backend.main会初始化数据库，后端测试必须先隔离data/config路径。
- 修改前查看git状态，保留当前未提交内容。按模块小步修改和验证，不整库格式化或搬迁文件。

## Design Tokens与主题

唯一的基础值来源是 `frontend/src/designTokens.ts`：

| 类型 | 现行值/规则 |
| --- | --- |
| 数据强调色 | #3b82f6；主按钮使用中性黑/白，风险色保留业务含义 |
| 页面背景 | light #f5f5f7；dark #0b0b0d |
| 卡片/浮层 | light白色；dark #171719 / #222225 |
| 正文 | light #1d1d1f；dark #f5f5f7 |
| 次要文字 | light #626268；dark #b4b4b8 |
| 边框 | light #e5e5e9；dark #303034；控件边框单独使用controlBorder |
| 字体 | Inter及系统/PingFang SC/Microsoft YaHei回退；不额外加载网络字体 |
| 内容宽度 | 最大1800px，侧栏240px，顶栏56px |
| 间距 | 控件8、卡片16、区块18、标题24、页面28；窄布局页面18 |
| 圆角 | 紧凑筛选4、图片/图表浮层6、矩阵8、普通卡片10 |
| 层级 | sticky5、工具栏10、筛选/自写图表浮层1200、系统状态2200 |
| 操作提示 | top24、maxCount3、默认成功2.5秒；警告/错误沿用6秒 |

`appTheme(dark)`提供Ant配置，`appCssVariables(dark)`提供手写CSS变量。`DesignSystemProvider`负责中文locale/表单校验/日期语言，并在html安装变量和dark-mode类，使body下的Modal/Drawer/Popover/自写Portal也能匹配主题。

- CSS使用 `--app-color-*`、`--app-space-*`、`--app-radius-*`、`--app-layer-*` 等变量，不引用未启用的 `--ant-*` 变量。
- 新增主题值必须在token映射中同时定义light/dark。不要只在一个页面追加近似颜色或一段暗色补丁。
- 自定义Portal需要主题状态时使用 `useDarkTheme()`，不要查询 `.app-shell.dark-mode` 推断状态。
- 颜色表达业务含义。价格涨跌、毛利风险、库龄、建议补货数量不能机械共用“正数绿色、负数红色”。业务标签自定义色、SVG坐标、图表动态宽度仍可保留内联。
- 当前矩阵共用青绿色表头和边框token，保持现有结构。部门SVG仍是固定纸张式报表，是明确保留的展示例外；改变其配色/结构需浏览器对照验收。

## 公共组件使用

新增公共UI放在 `frontend/src/components/`；现有成熟组件不为目录整齐而全量搬迁。

| 用途 | 必须优先复用 | API/边界 |
| --- | --- | --- |
| 页面标题 | PageHeading | title、description、actions、density；使用语义h1，工作台默认28px，销量用compact，保留页面操作回调 |
| KPI | MetricCard | 复用Ant Card+Statistic；variant=plain供分组指标使用，默认card；title/value/precision/suffix、有限tone；显示格式留给领域适配器 |
| 首屏加载 | PageLoading | label、compact；独立Spin不使用无效tip，文字单独展示 |
| 区块失败 | SectionError | title、error、onRetry；保留已成功加载内容，不把整个页面一并清空 |
| 区块空态 | SectionEmpty | description；只表示无数据/无匹配，不代替错误和加载 |
| 有提交的弹窗 | MutationModal | 基于Ant Modal；busy统一loading、禁关闭/取消/重复触发；onOk保留业务校验、ref锁和请求幂等 |
| 全局筛选 | ConfirmFilterSelect | value/options/mode/onConfirm；selectionUnit显式传“人/项”，不要从ariaLabel推断业务 |
| 筛选重置 | FilterActions | onReset恢复各页业务默认值和排序 |
| SKU图片 | SkuImagePreview | 已有占位、失败重试、lazy、预览；36px用于紧凑新品表，48px用于矩阵 |
| 图表定位与浮层 | useChartAxisTooltip / ChartAxisTooltip | 共用横轴命中、键盘/触屏与Portal定位；调用图表提供位置、格式化数值行及业务说明，不接管计算或请求 |
| 提示/下载/复制 | feedback.ts | feedbackMessage、runOperation、downloadWithFeedback、copyWithFeedback；全部转发应用注入的message |

页面顶层沿用Card工作台结构，主页面按标题、错误/警告、筛选、KPI、数据区组织。批次的全局复制清单等业务例外保留并说明范围。

PageHeading默认底距24；使用父grid gap的页面（当前批次页）由页面栈管理段间距，不能与标题margin重复叠加。默认KPI数值24px，销量compact22px；批次彩色顶边是同一组件的tone变体。

MutationModal不接管业务提交/校验，只负责忙碌态交互。只读预览和系统控制确认继续使用Ant Modal；有两步预览、原因输入、删除后果的内容保持独立。保存期间字段也应disabled，保留失败后继续纠正的能力。

## 筛选、表格与操作

- 工具栏使用默认32px控件；small用于表内动作和筛选弹层页脚。同一工具栏不混24/32px操作高度。
- 数据记录表默认small。销量compact保留更紧凑padding；上传Dragger卡本身保持常规密度。
- 页面正文按Ant默认，紧凑表12px；已有矩阵极小字号不在未实测时批量放大，新内容避免小于10px。SKU/ASIN单行并支持看完整值，原因/说明按空间允许有限换行。
- 默认Card圆角10、矩阵8。不要将所有控件强行改成同一个圆角。
- 普通操作用默认按钮；主提交用primary；danger用于删除、作废、关闭补货等有后果操作，复制涨价名单不使用danger。
- 筛选草稿不请求；确定提交当前字段；取消、Esc、外点丢弃草稿。多选空代表全部，单选清空恢复页面默认。
- ConfirmFilterSelect的每个候选项提供“仅筛选此项”：立即以该项替换当前字段的选择并收起弹层，不保留该字段其他勾选或草稿，不改变其他字段。单选、多选均支持，沿用默认值归一化和相同条件不重复提交；鼠标悬停或键盘焦点进入该行时显示，触屏常显。
- 搜索仅Enter/搜索图标提交，确认下拉不得顺带提交未搜索文字。筛选/搜索/页大小变更回第一页；排序、分页、导出使用已应用条件。
- 导出命名“导出筛选结果”，不改变导出范围或字段。新品复制清单仍忽略提醒状态和分页；批次清单仍是全局业务范围，不能改成当前矩阵页。
- 不为外观统一更改页大小、服务端上限和排序。主表50、新品/促销可选20/50/100/200、价格30、批次20、上传8/12、配置15等现行场景继续保留。
- rowKey优先业务稳定键，避免让Ant Table通过已弃用的第二个index参数生成身份。动态旧表兼容键在调用前计算；未来新增明细应有稳定键。
- 初始加载、后台刷新、空结果、失败分别呈现。持久错误可重试；写入成功但刷新失败显示warning，不能提示“保存失败”引导重复提交。
- 保留键盘焦点，禁止清除outline却不提供替代可见焦点。断点沿用Ant lg(991/992)、矩阵1440边界及现有900/720/640例外，不承诺手机端适配。

## 图表交互

- 折线、价格阶梯和纵向分组柱图统一按最近横坐标定位，显示竖向定位线与选中点/分组；数值放在浮层，保留坐标刻度和图例。横向排行条形图保留当前展示。
- 浮层标题为月份、日期或分类，列出该项全部已绘制系列的色标、名称与格式化数值。金额/比例、零/缺失及月销量计入天数、价格促销/异常等语义由原图负责；不能根据图上坐标反推业务数值。
- 共用实现位于`components/ChartAxisTooltip.tsx`：Hook接收SVG坐标点、viewBox宽高和数据revision；浮层接收标题、已格式化items、footer与屏幕锚点。命中计算考虑SVG变换与缩放，浮层通过body Portal及现有主题变量显示，以实际尺寸翻转并限制在视口8px内边距。
- 鼠标按横向位置吸附，触屏点选后保留且不禁止页面滚动；外点、鼠标离开、取消、滚动/缩放、数据更新、路由切换时清理。键盘聚焦首项，左右键与Home/End切换，Esc/失焦关闭；图表Enter/空格不触发父级业务行展开。
- 横轴定位即时更新，不增加跟随动画、不触发请求。`chartLine`和`chartComparison` token沿用补货图既有蓝/橙系列，深浅主题与Portal共用；新图表继续使用同一入口，不复制定位和浮层代码。

## API、展示与状态组织

- 页面网络请求通过 `api.ts`。报告上传用uploadReports，配置导入用uploadConfig；multipart不手设Content-Type边界。
- `apiErrors.ts`唯一维护结构化detail解析，`api.ts`保留兼容导出；下载共用同一解析，不在页面重复拼count/examples。
- `formatters.ts`维护完全相同的展示工具，现有formatAmountInWan只返回除10000后的格式文本，单位由调用方附加。不要混淆元/万、0–1比例与0–100百分数。
- `productPresentation.ts`维护四站映射和现行毛利/Rating显示分档，保持原阈值；它不计算补货、提成或促销业务结果。
- `PageLifecycleProps`统一active/routeVersion/refreshVersion。生命周期仍由main/navigation控制，不把局部编辑草稿提升为全局store。
- 新URL写入优先使用navigation现有helper并维护自定义路由事件和popstate；不要把所有局部搜索/分页强制写入URL。
- 保留unknown直到边界校验；不要为了统一类型将中文业务字段全量改名。interface和type均可，复杂Props用具名类型，枚举场景复用PageKey等联合。

## 代码与CSS书写

- TS/TSX用2空格、单引号、分号；组件PascalCase，函数/变量camelCase，Hook以use开头。Python4空格，模块/函数snake_case、类PascalCase。
- import按外部依赖、项目内部两组组织；仅整理本次修改区域，不为排序改变副作用初始化顺序。
- 公共展示组件、纯工具、API、页面业务各司其职。禁止新建万能Table/Filter/Form配置引擎替代业务清晰的独立实现。
- 新CSS类必须有组件/页面前缀；不继续新增无命名空间的margin-/recommendation-业务类。
- 不新增无原因!important。存量覆盖先验证优先级再逐项清理，不能整文件删除。
- 不新增近似同用途色值；动态位置/尺寸和业务标签色允许内联；CSS拆文件时先保持加载顺序。
- `.editorconfig`约束编码、行尾与缩进；本轮未安装新的lint/formatter依赖，不宣称有ESLint/Stylelint门禁。现有严格类型、回归、构建继续作为实际检查入口。

## 每模块验证与交接

所有安装、测试、构建命令≤90秒，推荐现有run_bounded.py的85秒硬限制；失败先说明原因再修正，安装失败最多重试一次。测试与构建分开执行，避免CPU争用造成无意义超时。

```powershell
.venv/Scripts/python.exe scripts/run_bounded.py --timeout 85 -- node frontend/node_modules/typescript/bin/tsc --noEmit --project frontend/tsconfig.json
.venv/Scripts/python.exe scripts/run_bounded.py --timeout 85 -- cmd.exe /d /c npm.cmd --prefix frontend test -- --maxWorkers=2 --testTimeout=10000
.venv/Scripts/python.exe scripts/run_bounded.py --timeout 85 -- cmd.exe /d /c npm.cmd --prefix frontend run build
```

模块开发先运行相关测试，全部接入后跑全量前端回归。表单/请求改动需覆盖慢请求、失败重试、草稿保留、并发保护和原请求参数；低影响纯排版不添加照抄实现的测试。

有浏览器时对照light/dark和1920/1440/1366/1024桌面宽度，关注Portal、筛选、表格滚动、长文本和焦点；写操作使用隔离fixture。不可用时明确写“未完成真实浏览器视觉验收”，组件测试不代替截图。

交接时更新HANDOFF和实施记录，列出本轮文件、检查结果、失败原因及待验收项；不把既有工作区改动算作自己的修改。

## Apple风格工作台（2026-11-03）

- 视觉方案已获用户授权落地。`workspace.css`在原`styles.css`后加载，集中管理应用壳、标题、表格、经营首页和新品监控展示；不替换业务矩阵与部门SVG的结构。
- 品牌图使用用户提供的原始`assets/water-monster.jpg`，通过Vite import打包，不使用桌面绝对路径或外链，保留`alt=小水怪`。
- `OverviewBoard`是经营首页专用布局。六项常见指标分组展示；新增配置指标和API返回区块必须继续显示。所有原始表格、搜索、导出在明细标签内保留，访问过的标签不销毁。
- 新品使用一个指标带及两套独立复制清单；SKU、ASIN和提醒状态固定列，其余字段继续横向滚动，保留日期、销量窗口和行展开详情。
- `useWorkspaceMotion.ts`使用GSAP，仅处理页面切换220ms和筛选弹层280ms的transform/opacity反馈；清单沿用Ant展开动画320ms。首次进入不表演数字动画，不延迟业务请求。
- 动效受`prefers-reduced-motion`约束；切页、关弹层和卸载时清理GSAP上下文与待执行帧，避免旧动画污染已保留的页面。
- 详细实施与真实浏览器验收边界见`docs/APPLE_UI_REDESIGN.md`。隔离验收使用生产构建及临时接口夹具，不导入`backend.main`或操作真实业务数据库。

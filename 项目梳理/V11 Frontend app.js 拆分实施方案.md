# V11 Frontend `app.js` 拆分实施方案

## 1. 目标与边界

当前 `frontend/app.js` 约 73KB，同时负责路由、全局状态、API 请求、Analyze、Benchmark、Error Analysis、Fallback Promotions、渲染、图表、弹窗和事件绑定。

本方案只整理代码结构，不改变业务行为：

- 保留 API 路径、返回字段、前端日志和页面交互。
- 保留当前页面来源作为默认 API 地址。
- 不修改后端，不引入 React/Vue，不引入构建工具。
- 不把 LangGraph 放入前端。

## 2. 当前职责与目标归属

| 当前职责 | 代表函数 | 目标模块 |
|---|---|---|
| 路由 | `routes`、`setRoute`、`loadRouteData` | `config/routes.js`、`router.js` |
| 全局状态 | `state` | `state/store.js` |
| API | `apiUrl`、`fetchJson`、`checkHealth` | `api/client.js` |
| Analyze | `runAnalyze`、`runDiagnosis`、`renderAnalyze` | `pages/analyze.js` |
| Benchmark | `loadBenchmark`、`uploadBenchmarkFile`、`renderBenchmark` | `pages/benchmark_overview.js` |
| Error Analysis | `loadErrors`、`renderErrors` | `pages/error_analysis.js` |
| 错误饼图 | `renderFailureTypePie`、`ringSlices` | `components/failure_pie.js` |
| Triage | `parseTriageCards`、`renderTriageCards` | `utils/triage_parser.js`、`components/triage_report.js` |
| Promotions | `loadPromotions`、`applyPromotions`、`renderPromotions` | `pages/fallback_promotions.js` |
| 通用展示 | `escapeHtml`、`percent`、`jsonBlock`、`table` | `utils/format.js`、`components/table.js` |
| 页面外壳 | `renderShell`、`navIcon`、`bindRouteEvents` | `components/shell.js`、`router.js` |

## 3. 目标目录

```text
frontend/
├─ index.html
├─ app.js                         # 入口和总协调
├─ styles.css
├─ api/client.js                  # 统一 HTTP 请求
├─ config/routes.js               # 路由元信息
├─ state/store.js                 # 全局状态
├─ router.js                      # 路由切换
├─ pages/
│  ├─ analyze.js
│  ├─ benchmark_overview.js
│  ├─ error_analysis.js
│  └─ fallback_promotions.js
├─ components/
│  ├─ shell.js
│  ├─ triage_report.js
│  ├─ failure_pie.js
│  ├─ progress_status.js
│  ├─ modal.js
│  └─ table.js
├─ utils/
│  ├─ frontend_logger.js
│  ├─ format.js
│  ├─ result_format.js
│  └─ triage_parser.js
└─ assets/
```

## 4. 依赖规则

```text
app.js -> router.js -> pages/*
pages/* -> api/client.js、state/store.js、components/*、utils/*
components/* 不直接调用 fetch
api/client.js 不操作 DOM
utils/* 不修改全局 state
页面之间不互相 import
```

`frontend_logger.js` 继续通过 `window.frontendLogger` 提供日志，避免改变现有日志协议。

## 5. 分阶段实施

### Phase 0：建立基线

先创建 Git 快照，记录四个页面截图、Network 请求、Console 日志和当前 `node --check frontend/app.js` 结果。拆分期间保留原 `app.js` 作为回滚版本。

### Phase 1：抽取无状态工具

先迁移 `escapeHtml`、`percent`、`jsonBlock`、`mappingSet`、`formatMappings`、`entityToConcept`、`promotionKey`。不读取 DOM、不读取全局状态，输入输出必须保持不变。

### Phase 2：抽取 API client 和 state

新建 `frontend/api/client.js`，集中处理 `apiUrl`、`fetchJson`、健康检查、Analyze、Benchmark、Error Analysis、Promotions 请求。

新建 `frontend/state/store.js`，迁移 `state` 中的 route、text、health、analyzeResult、benchmark、errors、promotions、进度、弹窗和 triage 筛选状态。初期只使用 `getState()`、`setState()`、`resetPageState()`，不引入状态管理库。

### Phase 3：拆分业务页面

新建 `frontend/pages/analyze.js`，迁移 Analyze 请求、渲染、诊断、Raw JSON 和单个 fallback 写入。

新建 `frontend/pages/benchmark_overview.js`，迁移 Benchmark 加载、上传、进度、统计和失败案例渲染。

新建 `frontend/pages/error_analysis.js`，迁移错误分桶、筛选、报告加载和页面渲染。

新建 `frontend/pages/fallback_promotions.js`，迁移候选加载、批量/单个写入、确认弹窗、进度条和完成动画。

### Phase 4：拆分图表、Triage 和通用组件

迁移错误饼图到 `components/failure_pie.js`，Markdown 解析到 `utils/triage_parser.js`，人话报告卡片到 `components/triage_report.js`，弹窗/进度/表格分别进入对应 components 文件。

### Phase 5：收敛入口和外壳

将 `renderShell`、`navIcon`、`bindRouteEvents` 放入 `components/shell.js` 和 `router.js`。最终 `app.js` 只负责导入模块、初始化 store、启动 router 和首次 render。

## 6. 加载方式

拆分后使用浏览器原生 ES Module，不增加构建系统：

```html
<script src="/frontend/utils/frontend_logger.js?v=..."></script>
<script type="module" src="/frontend/app.js?v=..."></script>
```

日志文件必须先加载，后端现有 JS 修改时间版本号逻辑继续保留。Docker 仍只需复制 `frontend/`。

## 7. 事件和异步规则

每个页面提供自己的 `bindAnalyzeEvents`、`bindBenchmarkEvents`、`bindErrorAnalysisEvents`、`bindPromotionEvents`。页面重渲染后不得重复绑定；必须防止重复上传、重复写入和旧请求结果覆盖新页面状态。

## 8. 回滚方案

每个阶段单独提交。验证期间可使用 `app.modular.js` 作为新入口；出现异常时恢复 `index.html` 对旧 `app.js` 的引用。全部页面通过验证后，才正式替换入口文件。

## 9. 验证方案

静态检查：

```powershell
node --check frontend/app.js
node --check frontend/api/client.js
node --check frontend/pages/analyze.js
```

功能检查：

```text
Analyze：输入 SOB/CP，查看扩写、诊断、Raw JSON 和 fallback 写入。
Benchmark：上传 50/60 条 JSON，查看进度和统计。
Error Analysis：点击错误类型，查看对应 LLM 解释。
Fallback Promotions：批量写入，检查进度条和完成动画。
```

日志检查：确认 `ui.app.load`、`ui.analyze.click`、`api.request_start`、`api.request_ok`、`api.request_error`、`ui.analyze.result_ok` 仍然存在，并确认 `window.frontendLogger.print()` 可用。

Docker 检查：

```powershell
docker compose build api
docker compose up -d api
Invoke-WebRequest http://127.0.0.1:8000/app -UseBasicParsing
```

浏览器 Network 中不得出现 `app.js`、`api/client.js`、页面模块或 `frontend_logger.js` 的 404。

## 10. 完成标准

```text
app.js 只负责入口和总协调
API 请求集中在 api/client.js
四个业务页面有独立模块
组件不包含后端请求
日志和 API 协议不变
页面交互不变
Docker /app 正常打开
所有模块无 404
静态检查和手动验收通过
```

本轮不拆 CSS、不改后端、不改变业务数据结构，目标是降低维护复杂度而不是重写前端。

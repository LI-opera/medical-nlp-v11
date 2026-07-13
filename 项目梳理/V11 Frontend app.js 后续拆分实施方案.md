# V11 Frontend `app.js` 后续拆分实施方案

## 1. 当前状态与目标

第一批已完成：`frontend/api/client.js`、`frontend/utils/format.js`，并将 `app.js` 改为 ES Module。当前四个页面业务仍集中在 `app.js`。

本轮继续拆分，但不改变业务行为：不修改后端 API、前端日志协议、页面文本、布局、颜色、交互，也不引入 React/Vue 或构建工具。

目标结构：

```text
frontend/
├─ app.js
├─ api/client.js
├─ state/store.js
├─ router.js
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
│  └─ triage_parser.js
└─ styles.css
```

## 2. 模块边界

```text
app.js -> router.js -> pages/*
pages/* -> api/client.js、state/store.js、components/*、utils/*
components/* 不直接调用 fetch
api/client.js 不操作 DOM
utils/* 不修改全局 state
页面之间不互相 import
```

`frontend_logger.js` 继续通过 `window.frontendLogger` 提供日志。

## 3. Batch 1：抽取全局状态

新增：

```text
frontend/state/store.js
```

迁移当前 `state` 中的 route、tab、text、apiBase、health、Analyze 结果、Benchmark 结果、Error Analysis、Promotions、上传进度、写入进度、弹窗和 triage 筛选状态。

提供最小接口：

```text
getState()
setState(patch)
resetAnalyzeState()
resetBenchmarkState()
resetPromotionState()
```

不引入状态管理库，先使用普通对象和显式更新。

验收：初始空状态、示例按钮、清空文本、页面切换、进度和弹窗状态都不变。

## 4. Batch 2：拆分 Analyze

新增：

```text
frontend/pages/analyze.js
```

迁移：

```text
runAnalyze
runDiagnosis
renderAnalyze
renderSingleDiagnosis
renderSinglePromotionStatus
renderConceptSummary
renderRawJsonDisclosure
buildSinglePromotionItem
canPromoteSingleCandidate
```

页面模块只负责读取状态、调用 API、生成 Analyze HTML 和绑定 Analyze 事件。它不能包含通用 HTTP、全局路由或其他页面逻辑。

验收：SOB/CP 扩写、XYZ 失败、LLM 诊断、Raw JSON、fallback 写入 primary 全部保持正常。

## 5. Batch 3：拆分 Benchmark Overview

新增：

```text
frontend/pages/benchmark_overview.js
```

迁移：

```text
loadBenchmark
uploadBenchmarkFile
renderBenchmark
renderBenchmarkUploadStatus
renderBenchmarkFailedCases
renderCategoryStackedBars
```

验收：初始无旧数据、上传 50/60 条 JSON、进度更新、total/correct/failed/accuracy、动态分类和失败案例全部正常。前端不重新定义 benchmark 统计口径。

## 6. Batch 4：拆分 Error Analysis

新增：

```text
frontend/pages/error_analysis.js
frontend/components/failure_pie.js
frontend/components/triage_report.js
frontend/utils/triage_parser.js
```

迁移错误分桶、饼图、Markdown Triage 解析和筛选渲染函数：`loadErrors`、`renderErrors`、`buildFailureBuckets`、`renderFailureTypePie`、`parseTriageCards`、`renderTriageCards`、`renderFilteredTriage`、`extractMarkdownBetween`、`extractCaseMarkdown`。

验收：饼图点击筛选、LLM 人话解释、错误卡片“情况/可能原因/下一步建议”、空状态全部保持不变。

## 7. Batch 5：拆分 Fallback Promotions

新增：

```text
frontend/pages/fallback_promotions.js
frontend/components/progress_status.js
frontend/components/modal.js
```

迁移候选加载、批量/单个写入、确认弹窗、进度条和完成动画。验收已有候选不显示写入按钮，批量写入和单个写入均保持正常。

## 8. Batch 6：拆分路由和外壳

新增：

```text
frontend/router.js
frontend/components/shell.js
```

迁移 `routes`、`navIcon`、`setRoute`、`loadRouteData`、`renderShell`、`bindRouteEvents`。

最终 `app.js` 只负责导入模块、初始化 logger/store、启动 router 和首次 render，目标控制在约 150 行以内。

## 9. 加载与事件规则

继续使用浏览器原生 ES Module：`index.html` 保持 logger 普通脚本先加载，`app.js` 使用 `type="module"`。后端注入的 JS 版本号继续保留。

每个页面提供自己的事件绑定函数：`bindAnalyzeEvents`、`bindBenchmarkEvents`、`bindErrorAnalysisEvents`、`bindPromotionEvents`。必须防止重复绑定、重复上传、重复写入，以及旧异步请求覆盖新页面状态。

## 10. 每批验证

静态检查：

```powershell
node --check frontend/app.js
node --check frontend/api/client.js
node --check frontend/state/store.js
node --check frontend/pages/analyze.js
```

浏览器检查：刷新后确认 Network 中新模块无 404，Console 无 import/未定义变量错误，`window.frontendLogger.print()` 仍可用。

功能检查：Analyze 输入 SOB/CP；Benchmark 上传样例；Error Analysis 点击错误类型；Fallback Promotions 执行批量和单条写入。

Docker 检查使用 `docker compose build api`、`docker compose up -d api`，然后访问 `http://127.0.0.1:8000/app`，确认页面和所有模块正常加载。

## 11. 回滚策略

每个 Batch 单独提交。出现异常时先恢复 `index.html` 对旧 `app.js` 的引用，检查 Git diff，再根据快照回退；不得覆盖用户未确认的其他修改。

## 12. 完成标准

```text
app.js 只负责入口和总协调
四个页面有独立模块
API 请求统一由 client.js 处理
全局状态统一由 store.js 管理
组件不直接请求后端
日志和 API 协议不变
页面交互不变
Docker /app 正常打开
所有模块无 404
静态检查和手动验收通过
```

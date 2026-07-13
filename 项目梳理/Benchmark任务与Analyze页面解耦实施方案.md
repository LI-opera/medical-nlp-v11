# Benchmark 任务与 Analyze 页面解耦实施方案

## 1. 目标

解决从 Overview 上传 benchmark cases 后，Analyze 页面 primary 写入弹窗持续频闪的问题，并明确 benchmark 任务运行期间各页面的刷新边界。

目标行为：

```text
上传 benchmark
    -> 只更新 Overview 的任务进度
    -> Analyze 保持当前界面和当前分析结果
    -> 用户仍可执行单条 fallback 候选写入 primary

benchmark 完成
    -> 刷新 Overview
    -> 重新读取 Error Analysis
    -> 重新读取 Fallback Promotions
    -> 不重置 Analyze 当前内容
```

本方案只调整前端状态和渲染边界，不改变 benchmark 业务计算、primary 写入规则和后端接口协议。

## 2. 当前问题

当前调用链为：

```text
Overview 上传
  -> benchmark_overview.js 轮询任务
  -> 每轮更新 state
  -> 调用全局 render()
  -> shell.js 重建整个 app.innerHTML
  -> Analyze 弹窗被重新生成
  -> CSS 入场动画反复播放
```

因此频闪不是 primary 写入按钮重复发送请求，而是 benchmark 轮询触发了全局页面重绘。

当前还有两个并发风险：

1. 离开 Overview 后，旧 benchmark 轮询仍可能继续更新全局页面。
2. benchmark 生成 promotion 结果时，用户可能同时在 Analyze 写入了相同候选，导致页面显示的 `already_exists` 状态过期。

## 3. 设计原则

### 3.1 Analyze 是独立交互上下文

Analyze 的以下状态在 benchmark 期间保持不变：

```text
输入文本
分析结果
扩写文本
当前单句诊断
LLM 诊断结果
primary 单条写入弹窗
```

benchmark 上传不会清空或重建这些内容。

### 3.2 Overview 任务状态局部更新

benchmark 上传期间只更新：

```text
上传按钮状态
进度条
当前阶段
当前 case / 总 case
上传错误
上传完成提示
```

优先使用 Overview 自己的状态节点或局部 DOM 更新，不调用会重建整个应用的全局 `render()`。

### 3.3 Benchmark 完成后再刷新分析页面数据

以下数据只在 benchmark 任务完成后重新读取：

```text
benchmark_results.json
error_analysis_report.json
error_triage_report.md
fallback_candidate_promotions.json
```

刷新 Error Analysis 和 Fallback Promotions 的数据状态即可，不需要强制切换页面，也不需要重建 Analyze。

## 4. 实施范围

### 4.1 前端状态拆分

在 `frontend/state/store.js` 中保持三类状态边界：

```text
analyze state
  text / analyzeResult / diagnosis / promotion modal

benchmark job state
  benchmarkUploading / benchmarkUploadJob / progress / result / error

benchmark derived reports
  benchmark / errors / triage / promotions
```

benchmark job 的变化不能触发 Analyze 状态重置。

### 4.2 Benchmark 轮询控制器

在 `frontend/pages/benchmark_overview.js` 中增加本地任务控制：

```text
activeJobId
pollTimer 或可取消轮询句柄
isMounted / route ownership 判断
```

要求：

1. 新上传任务开始时记录新的 `job_id`。
2. 只有当前任务的轮询结果可以更新 Overview。
3. 旧任务结果、过期任务结果不能覆盖新任务状态。
4. 离开 Overview 时停止或失效当前轮询。
5. 任务结束、失败或取消时清理轮询句柄。

### 4.3 局部渲染

建议给 Overview 上传区域增加稳定容器，例如：

```html
<div id="benchmarkUploadStatus"></div>
```

轮询期间只更新该容器：

```text
renderBenchmarkUploadStatus()
    -> benchmarkUploadStatus.innerHTML = ...
```

不得在每次轮询时调用 `shell.render()`。

如果当前页面切换机制暂时无法支持局部渲染，则至少保证：

```text
只有 state.route === "benchmarkOverview" 时更新 Overview DOM
Analyze 页面不被重新挂载
```

但最终仍应采用稳定容器方案。

### 4.4 页面完成后的数据刷新

benchmark 任务完成后执行：

```text
1. 更新 Overview 当前 benchmark summary
2. 清空 errors / triage / promotions 的旧内存缓存
3. 标记三个报告为 stale 或重新加载
4. 如果用户当前位于对应页面，局部刷新该页面数据
5. 如果用户当前位于 Analyze，不切换页面、不重建 Analyze
```

页面下次进入时，如果数据标记为 stale，再重新请求对应接口。

## 5. primary 并发与重复候选

### 5.1 用户写入优先保持可用

benchmark 运行期间，Analyze 中的单条 primary 写入按钮仍可用。它只修改候选词典，不修改 benchmark 当前运行结果。

### 5.2 Promotion 数据重新核验

benchmark 完成后，Fallback Promotions 必须基于最新 primary 词典重新判断：

```text
候选唯一键 = normalized_abbreviation
             + normalized_expansion
             + normalized_domain
```

判断规则：

```text
完全相同 -> already_exists，禁止重复写入
同一缩写、不同扩写 -> 保留为不同候选
同一缩写、相同扩写、不同 domain -> 按项目现有 domain 规则处理，不能静默覆盖
```

前端显示的 `new` / `already_exists` 只能作为提示，最终去重必须由后端写入逻辑保证幂等。

### 5.3 竞态处理

如果 benchmark promotion 结果生成期间发生 primary 写入：

```text
1. benchmark 结果仍然可以完成
2. promotion 页面刷新时重新读取最新词典
3. 确认写入时后端再次做幂等去重
4. 页面显示最终新增数量，不相信旧的预览数量
```

不建议为了这个场景锁住整个 Analyze 页面，也不建议阻塞 benchmark 任务。

## 6. 推荐执行顺序

### P1：修复全局重绘触发

修改 `benchmark_overview.js`，让轮询只更新上传进度区域。

验收：

```text
上传 benchmark 后切换 Analyze
打开 primary 写入弹窗
弹窗不频闪、不自动关闭、不重复播放动画
```

### P2：增加任务过期保护

加入 `job_id` 校验和轮询清理机制。

验收：

```text
连续上传两个文件
旧任务不能覆盖新任务进度
离开 Overview 后旧轮询不再触发页面更新
```

### P3：完成后刷新报告缓存

benchmark 完成后只让 Overview、Error Analysis、Fallback Promotions 的数据失效或刷新。

验收：

```text
Overview 数字更新
Error Analysis 显示新 benchmark 的报告
Fallback Promotions 显示新 benchmark 的候选
Analyze 当前输入和结果不丢失
```

### P4：确认 primary 幂等行为

验证单条写入和批量写入对相同候选的处理一致。

验收：

```text
重复写入同一 abbreviation + expansion + domain 不产生重复项
同一 abbreviation 的不同 expansion 可以共存
```

## 7. 测试矩阵

### Analyze

1. 无 benchmark 任务时，单条 fallback 候选写入成功。
2. benchmark 运行时，单条 fallback 候选写入成功。
3. benchmark 运行时打开并关闭确认弹窗，弹窗不闪烁。
4. benchmark 完成后，Analyze 输入文本、扩写文本和诊断仍在。

### Overview

1. 上传合法 JSON，进度阶段正常变化。
2. 上传非法 JSON，错误只显示在 Overview。
3. 上传期间切换页面，返回 Overview 后任务状态一致。
4. 重复上传两个文件，只有最新任务可以更新当前状态。

### Error Analysis

1. benchmark 完成后读取新报告。
2. 旧报告不会继续展示为当前结果。
3. 点击错误类型筛选仍然正常。

### Fallback Promotions

1. benchmark 完成后显示新候选。
2. Analyze 中提前写入的候选显示为 `already_exists`。
3. 批量确认写入不会重复添加。

## 8. 不在本轮范围内

本轮不做：

```text
不修改 benchmark 后端算法
不修改 primary 候选数据结构
不引入 WebSocket
不引入全局状态管理框架
不把 Analyze 结果持久化为 benchmark 数据
不强制阻止 benchmark 期间的用户操作
```

## 9. 最终产品行为

用户视角应当是：

```text
我在 Overview 上传 benchmark 时，Overview 显示任务进度。
我切换到 Analyze 后，Analyze 仍然是一个稳定可用的工作台。
我可以继续分析文本，也可以把 fallback 候选写入 primary。
benchmark 完成后，相关的错误分析和候选沉淀自动更新。
```

这比让一次后台 benchmark 任务重绘整个应用更符合多页面工具的交互预期。

## 10. 完成标准

满足以下条件才算完成：

```text
[ ] benchmark 轮询不再调用全局 render 重建 Analyze
[ ] Analyze primary 弹窗不再频闪
[ ] Analyze 在 benchmark 运行期间仍可正常分析和写入
[ ] 旧 benchmark 任务不能覆盖新任务状态
[ ] benchmark 完成后 Error Analysis 和 Fallback Promotions 更新
[ ] promotion 刷新会重新判断当前 primary 候选
[ ] 重复候选不会重复写入
[ ] Analyze 当前输入和结果不会因 benchmark 完成而丢失
```


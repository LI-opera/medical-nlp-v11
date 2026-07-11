# Benchmark 上传真实进度机制详述

本文解释 V11 前端中“上传 benchmark cases 并运行”为什么要改成 job 机制，以及前后端分别做了什么。

## 1. 之前为什么会显得卡住

之前前端点击上传后，直接调用一个同步接口：

```text
POST /benchmark/cases/run
```

这个接口会在一次 HTTP 请求里完成所有事情：

```text
读取上传 JSON
-> 校验 cases
-> 逐条运行 benchmark 主链路
-> 写 benchmark_results.json
-> 生成 error_analysis_report.json
-> 调用 LLM 生成 error_triage_report.md
-> 生成 fallback_candidate_promotions.json
-> 返回前端
```

问题是：HTTP 请求没有结束前，前端拿不到后端的中间状态。

所以前端只能用一个“假进度条”定时涨到 88%，然后一直等后端返回。实际后端可能正在跑 LLM triage，但前端不知道，于是用户会感觉页面卡住。

## 2. 新方案的核心思想

新方案把“长任务”拆成两个接口：

```text
POST /benchmark/cases/jobs
创建 benchmark 运行任务，立即返回 job_id。

GET /benchmark/cases/jobs/{job_id}
查询这个任务当前跑到哪一步。
```

也就是说，上传按钮不再傻等一个长请求结束，而是：

```text
1. 前端上传 cases JSON
2. 后端创建后台任务，返回 job_id
3. 前端每 1 秒查询一次 job 状态
4. 后端每完成一个阶段就更新 job 状态
5. 前端根据真实 job 状态刷新文案和进度条
```

## 3. 后端新增的状态结构

后端在 `backend/api/main.py` 中新增了内存 job 表：

```python
BENCHMARK_JOBS = {}
BENCHMARK_JOBS_LOCK = threading.Lock()
```

每个 job 里保存这些字段：

```json
{
  "id": "job id",
  "status": "queued | running | completed | failed",
  "stage": "running_benchmark",
  "message": "正在运行 benchmark cases: 18/50",
  "progress": 42,
  "current": 18,
  "total": 50,
  "case_id": "case_xxx",
  "category": "upload_single_meaning",
  "result": {}
}
```

这里要注意：

```text
status 是任务总状态。
stage 是当前执行阶段。
message 是给前端直接展示的人话。
progress 是 0-100 的整体进度。
current / total 是 benchmark case 的运行数量。
```

## 4. 后端阶段划分

本次把 benchmark 上传运行分为 7 个阶段：

```text
1. queued
   已读取上传文件，准备创建后台任务。

2. preparing
   准备 benchmark 运行。当前版本不再自动备份旧的 benchmark_results.json。

3. running_benchmark
   逐条运行 ABBRService 主链路。
   这是最慢的一段之一。

4. saving_results
   写入新的 benchmark_results.json。

5. error_analysis_report
   生成 error_analysis_report.json。

6. error_triage
   调用 LLM 生成 error_triage_report.md。
   这一步也可能很慢，因为要等待外部 LLM。

7. fallback_promotions
   从本轮 benchmark 中提取可沉淀的 fallback 成功候选。

8. completed / failed
   任务完成或失败。
```

## 5. run_benchmark 如何提供 case 级进度

`backend/evaluation/run_benchmark.py` 中的 `run_benchmark` 增加了一个可选参数：

```python
def run_benchmark(cases=None, output_path=None, progress_callback=None):
```

每跑一个 case 前，会调用：

```python
progress_callback({
    "current": index,
    "total": total,
    "case_id": case.get("id"),
    "category": case.get("category"),
    "text": case.get("text"),
})
```

这样 API 层就能把真实进度写入 job：

```text
正在运行 benchmark cases: 18/50 (case_xxx)
```

## 6. 前端轮询逻辑

前端 `frontend/app.js` 的上传流程改为：

```text
读取本地 JSON
-> POST /benchmark/cases/jobs
-> 保存返回的 job_id
-> 每 1 秒 GET /benchmark/cases/jobs/{job_id}
-> 根据 job.progress / job.message 刷新页面
-> completed 后重新读取 benchmark overview
```

因此前端不再展示固定的“正在运行上传的 benchmark cases...”。

它会根据后端真实状态显示：

```text
准备运行
正在准备 benchmark 运行

运行 benchmark
正在运行 benchmark cases: 18/50 (case_xxx)

LLM 解读
正在生成 LLM 错误解读
```

## 7. 为什么不用 WebSocket

这次没有上 WebSocket，原因是当前场景更适合简单轮询：

```text
1. benchmark 上传不是高频实时交互。
2. 1 秒轮询已经足够及时。
3. 后端和前端都更容易调试。
4. 不需要引入新的连接管理复杂度。
```

如果未来 benchmark 变成多人并发、任务很长、需要实时日志流，再考虑 WebSocket 或 SSE。

## 8. 当前方案的边界

这个 job 表是内存态：

```text
服务重启后，历史 job 状态会丢失。
```

但已经生成的文件不会丢：

```text
backend/evaluation/benchmark_results.json
backend/evaluation/error_analysis_report.json
backend/logs/triage/error_triage_report.md
backend/evaluation/fallback_candidate_promotions.json
```

当前这是本地项目工作台，所以内存 job 足够。

如果以后要做成正式多人系统，可以升级为：

```text
SQLite / Redis 保存 job 状态
后台任务队列管理并发
任务日志持久化
```

## 9. 为什么取消自动备份

当前前端测试阶段经常会反复上传同一个 cases 文件。如果每次运行都生成：

```text
benchmark_results.backup_YYYYMMDD_HHMMSS.json
```

目录会很快堆积大量重复结果文件。

所以当前版本取消自动备份。上传 benchmark cases 后，系统会直接把本轮运行结果写入：

```text
backend/evaluation/benchmark_results.json
```

这个文件仍然是页面的当前结果源：

```text
Overview
Error Analysis
Fallback Promotions
```

都会围绕当前这份结果继续生成和展示。

如果以后需要保留多轮运行历史，更适合做成显式的 run 管理：

```text
benchmark_runs/
  run_20260711_001/
    cases.json
    benchmark_results.json
    error_analysis_report.json
    error_triage_report.md
    fallback_candidate_promotions.json
```

而不是在当前目录里自动堆积 backup 文件。

## 10. 面试表达

可以这样解释这个改动：

> benchmark 上传运行是一个长任务，里面包含主链路评估、错误分析、LLM triage 和候选沉淀。如果用同步 HTTP 接口，前端只能等待最终结果，用户会误以为页面卡住。所以我把它改成了 job 模式：上传后创建任务并返回 job_id，后端后台执行并维护 stage、message、progress、current/total，前端轮询任务状态并展示真实进度。这样既保留了实现简单性，又解决了长任务可观测性问题。

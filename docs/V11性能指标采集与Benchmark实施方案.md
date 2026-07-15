# V11 性能指标采集与 Benchmark 实施方案

## 1. 方案目的

当前项目已经有 Benchmark accuracy，但只有正确率还不能完整说明 RAG 系统的工程性能。

本方案希望在不改变医学判断逻辑的前提下，补充：

```text
系统整体耗时
Benchmark 吞吐量
P50 / P95 延迟
LLM 调用耗时
Embedding 耗时
Milvus 检索耗时
串行与并行 Benchmark 对比
错误与超时数量
```

目标不是立即建设复杂的监控平台，而是生成一份可以用于 GitHub 展示和面试说明的可信性能报告。

---

## 2. 当前基础盘点

项目已经存在以下可复用基础：

```text
backend/evaluation/run_benchmark.py
    Benchmark 主入口，支持 workers 参数。

backend/utils/structured_logger.py
    统一 JSONL 结构化日志。

backend/logs/benchmark.jsonl
    Benchmark job 和 case 级事件。

backend/logs/pipeline.jsonl
    ABBRService 主链路阶段事件。

backend/logs/dependency.jsonl
    LLM、Embedding、Milvus 和 collection 相关事件。

backend/evaluation/paths.py
    runtime/archive 评估产物路径管理。
```

因此第一版性能采集应优先聚合已有日志中的 `duration_ms`，而不是新建独立数据库或监控服务。

---

## 3. 指标口径

### 3.1 Case 级指标

一个 Benchmark case 从开始处理到得到最终结果，统计为一个 case。

字段建议：

```json
{
  "case_id": "coverage_003",
  "category": "low_context_abbreviation",
  "duration_ms": 1820.4,
  "correct": false,
  "success": false,
  "expansion_success": true,
  "standardization_success": false,
  "error": null
}
```

### 3.2 Job 级指标

一次 Benchmark 上传或运行任务是一个 job。

```json
{
  "job_id": "bench_xxx",
  "total_cases": 50,
  "workers": 2,
  "duration_ms": 91234.5,
  "throughput_cases_per_second": 0.55,
  "correct": 47,
  "accuracy": 0.94,
  "error_count": 0
}
```

### 3.3 阶段级指标

阶段耗时用于判断瓶颈，不作为业务正确率的一部分。

建议阶段：

```text
candidate_retrieval
coverage
embedding
milvus_search
verification
reflection
llm_call
render
```

### 3.4 百分位延迟

不只报告平均值：

```text
平均延迟：所有 case duration 的算术平均。
P50：排序后中位数，代表典型请求。
P95：95% 请求低于该耗时，代表尾延迟。
最大延迟：用于发现异常 case。
```

面试中建议优先展示：

```text
P50、P95、平均延迟、吞吐量。
```

---

## 4. 第一版报告设计

建议新增脚本：

```text
backend/evaluation/performance_report.py
```

职责：

1. 读取指定 Benchmark 结果文件；
2. 读取对应的 Benchmark JSONL 日志；
3. 按 job_id 和 case_id 关联事件；
4. 计算 case/job/stage 级统计；
5. 输出 JSON 和 Markdown 报告。

建议输出目录：

```text
backend/evaluation/runtime/performance_report.json
backend/evaluation/runtime/performance_report.md
```

历史结果自动归档到：

```text
backend/evaluation/archive/
```

不要把性能数据混入 `error_analysis_report.json`。错误分析回答“哪里错了”，性能报告回答“哪里慢了”，两者应保持独立。

---

## 5. 数据采集方式

### 5.1 Job 总耗时

复用 `run_benchmark.py` 已有的 job 开始和结束日志：

```text
benchmark.job.start
benchmark.job.end
```

计算：

```text
job_duration_ms = job_end.ts - job_start.ts
```

如果结束事件已经写入 `duration_ms`，优先使用日志中的显式值。

### 5.2 Case 耗时

复用：

```text
benchmark.case.start
benchmark.case.end
```

按以下字段关联：

```text
job_id + case_id + request_id
```

计算：

```text
case_duration_ms = case_end.duration_ms
```

Benchmark 结果中的 `correct`、`success`、`category` 只用于关联和分组，不重新计算业务结果。

### 5.3 LLM、Embedding、Milvus 耗时

读取：

```text
backend/logs/dependency.jsonl
```

按 `request_id` 或 `case_id` 关联阶段事件：

```text
dependency.llm.call
dependency.embedding.encode
dependency.milvus.search
dependency.collection.load
```

如果某个阶段当前没有明确的开始/结束事件，本阶段先标记为：

```text
available = false
reason = "missing_stage_duration_log"
```

不能用整条请求耗时冒充 Milvus 或 LLM 耗时。

---

## 6. 并行与串行对比

Benchmark 已经支持：

```python
run_benchmark(cases=cases, workers=1)
run_benchmark(cases=cases, workers=2)
```

对比实验应固定：

```text
同一批 cases
同一模型
同一 Milvus collection
同一 max_retries
同一机器
```

建议执行两轮以上，避免一次运行受网络抖动影响：

```powershell
$env:BENCH_WORKERS="1"
python backend/evaluation/run_benchmark.py

$env:BENCH_WORKERS="2"
python backend/evaluation/run_benchmark.py
```

注意：当前每个并行 worker 可能独立初始化模型和服务。并行度不是越高越好，过高可能造成：

- LLM 限流；
- BGE-M3 重复加载；
- 内存增长；
- Milvus 请求竞争；
- 总耗时反而增加。

最终报告应同时记录：

```text
workers
total_duration_ms
throughput_cases_per_second
accuracy
error_count
```

不能只用耗时变短就宣称并行更好，必须确认准确率和错误数没有异常变化。

---

## 7. 建议的报告结构

### 7.1 Markdown 报告

```markdown
# Benchmark Performance Report

## 运行环境

- cases: 50
- workers: 2
- model: BAAI/bge-m3
- milvus: concepts_only_name / rxnorm_concepts
- generated_at: ...

## 总体结果

| 指标 | 数值 |
| --- | ---: |
| 总 cases | 50 |
| 正确 cases | 47 |
| accuracy | 94.0% |
| 总耗时 | ... |
| 平均耗时 | ... |
| P50 | ... |
| P95 | ... |
| 吞吐量 | ... cases/s |
| 错误数 | ... |

## 阶段耗时

| 阶段 | 样本数 | 平均 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: |
| LLM | ... | ... | ... | ... |
| Embedding | ... | ... | ... | ... |
| Milvus search | ... | ... | ... | ... |
| verifier | ... | ... | ... | ... |

## 分类延迟

| category | cases | accuracy | average_ms | p95_ms |
| --- | ---: | ---: | ---: | ---: |

## 异常 case

只列出超时、异常或 P95 以上的 case。
```

### 7.2 JSON 报告

JSON 用于后续前端或脚本读取，建议保留原始口径：

```json
{
  "schema_version": "1.0",
  "source_result_file": "benchmark_results.json",
  "job_id": "bench_xxx",
  "generated_at": "2026-07-15T12:00:00+08:00",
  "run": {
    "workers": 2,
    "total_cases": 50,
    "duration_ms": 91234.5,
    "throughput_cases_per_second": 0.55
  },
  "quality": {
    "correct": 47,
    "accuracy": 0.94,
    "error_count": 0
  },
  "latency": {
    "average_ms": 1824.7,
    "p50_ms": 1602.1,
    "p95_ms": 3101.4,
    "max_ms": 4800.2
  },
  "stages": {},
  "categories": {}
}
```

---

## 8. 测试方案

性能报告脚本应补充纯函数测试：

```text
backend/tests/unit/test_performance_report.py
```

至少覆盖：

- 百分位计算；
- 空输入处理；
- 单 case 计算；
- 多 case 分组；
- job/case 日志关联；
- 缺失阶段日志时返回 `available=false`；
- 异常 case 不影响其他 case 统计。

不应该在默认 CI 中运行真实 Benchmark。默认 CI 只测试统计逻辑和日志解析逻辑。

---

## 9. 数据可信性规则

性能报告必须记录环境信息：

```text
操作系统
Python 版本
workers
Embedding 模型
LLM 模型
Milvus collection
cases 数量
是否 Docker
生成时间
```

以下情况不能直接比较：

- 机器不同；
- 模型缓存状态不同；
- 第一次冷启动和后续热运行混在一起；
- workers 不同；
- cases 数量或类别分布不同；
- LLM 服务端限流或网络状态不同。

建议区分：

```text
cold_start
    模型和 collection 尚未加载。

warm_run
    模型和 collection 已加载。
```

面试展示时优先使用 warm_run，并在报告中注明测试条件。

---

## 10. 第一阶段实施范围

建议第一版只做：

1. 新增 `performance_report.py`；
2. 从 Benchmark 日志提取 job/case 总耗时；
3. 计算平均值、P50、P95、最大值和吞吐量；
4. 按 category 汇总延迟；
5. 输出 JSON 和 Markdown；
6. 增加纯函数单元测试；
7. 使用 50 或 60 条固定 cases 做串行/并行对比。

第二阶段再补：

1. LLM/Embedding/Milvus 精确阶段计时；
2. Docker 与本机环境对比；
3. 前端 Overview 展示性能指标；
4. 历史性能趋势。

---

## 11. 验收标准

第一版完成后应满足：

- 不改变 Benchmark 的预测逻辑；
- 不改变 accuracy 计算；
- 不改变错误分析口径；
- 能输出一份独立性能 JSON；
- 能输出一份人可阅读 Markdown；
- 报告中明确 workers、cases、环境和生成时间；
- 能区分平均耗时与 P95 尾延迟；
- 缺失日志时不伪造阶段耗时；
- 纯逻辑测试通过；
- 串行和并行结果可对照。

---

## 12. 面试表达

可以这样介绍：

> 我没有把性能指标和业务正确率混在一起。Benchmark 负责 case 级准确率，性能报告独立读取 job、case 和 dependency 日志，计算平均延迟、P50、P95 和吞吐量。同时我固定测试集、模型、Milvus collection 和机器环境，对比 workers=1 与 workers=2 的串行并行效果，并检查并行是否造成准确率或错误数变化。LLM、Embedding 和 Milvus 的阶段耗时只有在有明确日志证据时才单独报告，不用总请求耗时冒充某个组件耗时。

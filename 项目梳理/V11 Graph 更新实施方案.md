# V11 Graph 更新实施方案

## 1. 方案定位

本轮目标是把 `backend/graph/standardization_graph.py` 更新到当前 V11 生产逻辑的参考实现状态，并重新生成流程图、执行一致性检查。

本轮明确不做：

- 不让 LangGraph 接管 FastAPI 生产主流程。
- 不修改前端页面和前端请求协议。
- 不修改 `/expand/simple`、`/analysis/diagnose` 的 API 返回结构。
- 不把 Graph 当作第二套生产业务实现长期独立演进。

最终定位仍然是：

```text
ABBRService = 生产主链路
StandardizationGraph = 流程参考实现、可视化和回归对照工具
```

## 2. 当前生产逻辑盘点

当前网页 Analyze 的主要调用链是：

```text
frontend/app.js
    -> POST /expand/simple
        -> api.main
            -> ABBRService.expand_verify_with_retry(text)
                -> 识别缩写候选
                -> primary / fallback 候选处理
                -> coverage 判断
                -> 确定性扩写文本
                -> 按 domain 路由 SNOMED 或 RxNorm
                -> 候选检索
                -> verifier 校验
                -> reflection / re-query
                -> 重新验证
                -> 生成 mapping_states、standardized_entities 和 success_breakdown
```

当前主要业务状态包括：

```text
PENDING
CODED
WITHHELD
ABSTAIN
NOT_EXPANDED
```

当前生产结果的关键边界：

- `expanded_text` 是根据原始文本和最终 record 状态重新渲染的结果。
- `mapping_states` 是每个缩写 record 的诊断状态。
- `success` 由扩写成功和标准化成功共同决定。
- `WITHHELD` 表示扩写可信但标准概念不够可靠，不能当作标准化成功。
- `NOT_EXPANDED` 不进入确定性替换，也不进入标准化检索。
- Drug domain 走 RxNorm，其余医学概念默认走 SNOMED。

Benchmark 的生产入口仍然是：

```text
backend/evaluation/run_benchmark.py
```

Graph 不参与 Benchmark 网页运行，也不参与 API 的默认请求处理。

## 3. Graph 与生产逻辑差异表

| 对比项 | 当前生产主链路 | 当前 Graph 参考实现 | 更新要求 |
|---|---|---|---|
| 生产入口 | `ABBRService.expand_verify_with_retry` | `StandardizationGraph.run` | Graph 只跟随生产行为，不改变生产入口 |
| 一句话多个缩写 | 服务层统一编排 records | Graph 外层逐 mapping 调图后再拼回句子 | 明确记录“逐 mapping 模拟”边界 |
| 候选扩写 | 使用当前 primary、fallback、coverage 和 subtype/evidence | 通过服务方法获取初始候选 | 对齐当前 record 字段和失败信息 |
| 确定性替换 | 依据最终可见 records 从原文重新生成 | 当前也调用服务的确定性渲染方法 | 保持原文重渲染规则一致 |
| domain 路由 | `_route_source` 决定 SNOMED/RxNorm | `n_route` 决定 SNOMED/RxNorm | 对齐 domain 缺失和未知 domain 的默认规则 |
| 检索 | 当前生产 retriever 参数和 collection 配置 | Graph 内部有一份检索参数 | 避免参数漂移，集中定义或明确同步点 |
| 校验 | 生产 verifier 处理完整 mapping 集合 | Graph 按单 mapping 调 verifier | 保留单 mapping 模拟限制，不能宣称逐字节等价 |
| reflection | 生产状态机控制 re-query、候选池、rank 和停止条件 | Graph 复刻部分 reflection 分支 | 对齐停止条件、`_tried`、`_reflect_stop` 和 rank 采纳规则 |
| 输出状态 | API 返回完整 `mapping_states` 和 `success_breakdown` | Graph 返回相近的 `final_result` | 字段名、状态含义和失败 evidence 要统一 |
| 日志 | 生产链路写 pipeline/dependency/app 日志 | Graph 当前主要用于脚本输出 | 增加 Graph 运行上下文日志，但不污染业务日志口径 |
| 前端 | 只依赖 API | 不直接感知 Graph | 本轮不改前端 |

### 必须特别处理的差异

当前 Graph 不是简单地调用一套公共纯函数，而是复刻了部分生产逻辑。这样容易出现：

```text
生产代码修改了
Graph 没有同步修改
Graph parity 仍然通过旧样例
```

因此本轮至少要把以下规则逐项核对：

- 当前 `NOT_EXPANDED` 子原因、`failure_subtype`、`fallback_reason` 和 evidence 是否完整保留。
- 当前 `WITHHELD`、`ABSTAIN`、`CODED` 的终态转换是否一致。
- 当前 reflection 采用新候选的 rank 条件是否一致。
- 当前标准化检索使用的 source、domain boost、score threshold 和 collection 配置是否一致。
- 当前 `success_breakdown` 的 case/record 统计边界是否被 Graph 正确表达。

## 4. `standardization_graph.py` 更新范围

### 4.1 保留的内容

保留以下 Graph 结构：

```text
route
retrieve_snomed / retrieve_rxnorm
verify
propose_requery
re_retrieve
re_verify
finalize
```

这些节点能清楚表达当前项目的：

```text
domain 路由 → 标准库检索 → verifier → reflection → 最终状态
```

### 4.2 需要更新的内容

1. **输入状态**

核对 `MappingState` 是否包含当前 Graph 调试所需字段：

```text
text
expanded_text
record
reflect_iter
result
```

必要时补充：

```text
request_id
runtime_id
source
failure_subtype
evidence
```

这些字段只服务于 Graph 追踪，不改变生产 API 协议。

2. **候选与 coverage**

Graph 初始候选必须使用当前 `ABBRService` 的结果，不能重新设计一套旧的 fallback 判断。特别要保留：

```text
NO_CANDIDATES
FALLBACK_RETURNED_EMPTY
FALLBACK_ERROR
PRIMARY_EMPTY_FALLBACK_DISABLED
AMBIGUOUS_LOW_CONTEXT
```

如果当前代码实际采用的 subtype 名称不同，以生产代码为准，方案文档中的名称不能替代代码事实。

3. **标准化结果**

Graph 的 `mapping_states` 至少应能表达：

```text
abbreviation
expansion
source
status
coverage
failure
```

其中 `failure` 应保留 `type`、`stage`、`reason`、`evidence` 等当前字段。

4. **reflection**

对照当前生产实现更新：

```text
初始检索结果
    -> verifier 判断
    -> 生成 re-query
    -> 合并去重候选
    -> 重新验证
    -> 比较 rank
    -> 采纳或停止
```

需要明确：

- 新 re-query 词不等于修改原始 expansion。
- 只有候选结果改善并满足采纳规则时，才改变最终标准化结果。
- 如果新检索结果没有提升，保留上一轮最终结果。
- Graph 的 `re_verify` 不能因为试过新词就无条件覆盖原结果。

5. **最终结果**

Graph 最终输出应与生产结果保持相同的核心语义：

```text
final_expanded_text
success
expansion_success
standardization_success
success_breakdown
mapping_states
mapping_standardizations
```

### 4.3 不应加入的内容

本轮不在 Graph 中加入：

- 前端页面逻辑
- API 路由注册
- 数据库持久化
- 新的 LLM provider
- 新的 Milvus collection
- 独立的业务规则解释器
- 与生产不同的 success 判定

## 5. `render_graph.py` 同步更新方案

`render_graph.py` 不需要重写成新的业务入口，但需要同步承担三件事：

### 5.1 生成 Mermaid 图

继续调用：

```python
StandardizationGraph(...).mermaid()
```

并把结果写入：

```text
项目梳理/L3_pipeline.mmd
```

该文件是可再生成的展示产物，不参与 API 运行。

### 5.2 使用固定样例做对照

当前固定样例应覆盖：

```text
单义缩写
多缩写句子
Drug domain
需要 reflection 的候选
未知缩写或无候选
```

必要时把已有 4 条样例扩充为覆盖 SNOMED、RxNorm、WITHHELD、NOT_EXPANDED 的最小集合。

### 5.3 输出可读的 parity 结果

每条样例应显示：

```text
case 文本
生产 expanded_text
Graph expanded_text
生产状态
Graph 状态
生产 concept_id
Graph concept_id
PASS / FAIL
```

对于差异，应打印结构化 diff，而不是只显示 `MISMATCH`。

## 6. `L3_pipeline.mmd` 重新生成方案

运行位置：项目根目录。

```powershell
..\.venv\Scripts\python.exe backend\graph\render_graph.py
```

运行前提：

- Milvus 已启动。
- SNOMED collection 已建立。
- 如果测试包含 Drug domain，RxNorm collection 已建立。
- `.env` 中有需要的 LLM key。
- 当前 Python 环境已经安装 LangGraph 及项目依赖。

生成过程：

```text
实例化 ABBRService
    ↓
实例化 StandardizationGraph
    ↓
读取 Graph 节点与边
    ↓
生成 Mermaid 文本
    ↓
写入 项目梳理/L3_pipeline.mmd
    ↓
执行生产逻辑与 Graph parity
```

验收时检查：

- 文件确实更新。
- Mermaid 中包含 route、SNOMED/RxNorm、verify、reflection、finalize 节点。
- 没有把前端或 Docker 节点错误混入标准化 Graph。
- Graph 输出不是空文件。

## 7. Parity 测试方案

### 7.1 比较单位

Graph 和生产链路分别运行同一输入，比较以下结果：

```text
final_expanded_text
success
expansion_success
standardization_success
每个 abbreviation 的 status
每个 abbreviation 的 expansion
chosen concept_id
failure type / stage
```

不要求比较：

- JSON 字段排列顺序
- 日志时间
- request_id
- candidate 列表排序中的非关键差异

### 7.2 最小测试集

至少覆盖：

```text
The patient has CP and DM.
The patient took ASA for chest pain.
Patient reports SOB.
The patient has XYZ.
The patient has ABC and SOB.
包含 Drug domain 的缩写样例
```

### 7.3 验收规则

```text
所有样例的最终扩写文本一致
所有目标 record 的终态一致
CODED 的 concept_id 一致
WITHHELD / ABSTAIN / NOT_EXPANDED 的原因阶段一致
success_breakdown 语义一致
```

如果只是候选列表顺序不同，但最终 concept_id、状态和最终文本一致，可以记录为非阻断差异；如果状态或最终文本不同，必须继续修正 Graph。

## 8. Benchmark 对照方案

本轮不通过网页上传来验证 Graph，而是对同一份 benchmark cases 分别执行：

```text
生产入口：run_benchmark.py
Graph 对照：render_graph.py 或单独的 parity runner
```

推荐顺序：

1. 先使用 5~6 条最小样例做快速 parity。
2. 再使用当前 74 条 benchmark cases 做完整对照。
3. 记录生产和 Graph 的：

```text
总 case 数
benchmark correct 数
失败 case ID
扩写成功数
标准化成功数
CODED / WITHHELD / ABSTAIN / NOT_EXPANDED 数量
```

4. 对失败 case 逐条比较，不只比较总 accuracy。
5. 运行完成后重新生成 `L3_pipeline.mmd`，确认图文件与代码同步。

### Benchmark 对照的通过标准

```text
失败 case 集合一致
每个 case 的最终 expanded_text 一致
每个 record 的 status 一致
标准化 concept_id 一致
success_breakdown 的关键计数一致
```

如果 Graph 只是用于流程展示而不是完整执行，可以将 Graph benchmark 限定为 parity 子集，并在 `backend/graph/README.md` 中明确“不是完整生产评测入口”。

## 9. 文件变化预期

本轮预计只涉及：

```text
backend/graph/standardization_graph.py
backend/graph/render_graph.py
项目梳理/L3_pipeline.mmd
backend/graph/README.md（如需补充说明）
```

不应修改：

```text
frontend/
backend/api/main.py 的生产路由
backend/evaluation/run_benchmark.py 的生产入口
Docker Compose 的 Milvus 服务
```

## 10. 最终定位

完成后项目中的流程关系应保持：

```text
FastAPI
  -> ABBRService
      -> 当前生产标准化状态机

StandardizationGraph
  -> 调用/对照当前生产能力
  -> 生成 Mermaid 流程图
  -> 执行 parity 回归
```

Graph 更新的目标是让架构图和实际 V11 逻辑一致，而不是引入一条新的生产执行路径。

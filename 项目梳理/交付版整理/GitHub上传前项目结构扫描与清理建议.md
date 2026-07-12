# GitHub 上传前项目结构扫描与清理建议

> 扫描时间：2026-07-12
> 
> 本文是现状审查和候选方案，不代表已经执行删除、移动或 `.gitignore` 修改。后续每一项都应在确认用途、保留快照并完成验证后再执行。

## 1. 扫描结论

当前项目不是“代码不能运行”，而是“运行主链路、实验脚本、测试样例、运行产物和历史文档混在一起”。主功能已经形成，但 GitHub 交付前需要做一次分层整理。

当前主链路可以确认如下：

```text
frontend/app.js
  -> POST /expand/simple
  -> backend/api/main.py
  -> ABBRService
  -> MedicalNER + primary candidates + fallback LLM + coverage
  -> deterministic expanded_text
  -> MedicalRetriever
  -> StdService
  -> Milvus SNOMED/RxNorm collection
  -> verifier / reflection
  -> mappings / mapping_states / standardized_entities
```

评估与分析链路为：

```text
benchmark cases
  -> evaluation/run_benchmark.py
  -> evaluation/archive/benchmark_results.json
  -> evaluation/error_analysis_report.py
  -> evaluation/archive/error_analysis_report.json
  -> evaluation/error_triage.py
  -> logs/triage/error_triage_report.md
  -> evaluation/collect_fallback_candidate_promotions.py
  -> evaluation/archive/fallback_candidate_promotions.json
```

## 2. 当前目录的职责

### 2.1 根目录

| 文件/目录 | 当前作用 | GitHub 建议 |
|---|---|---|
| `backend/` | 后端 API、服务、评估、工具和测试 | 保留，但建议继续按职责细分 |
| `frontend/` | 无构建步骤的静态工作台 | 保留 |
| `Dockerfile` | 构建包含后端和前端的 API 镜像 | 保留 |
| `docker-compose.yml` | 编排 API、Milvus、etcd、MinIO | 保留 |
| `.gitignore` | Git 忽略规则 | 需要补充运行缓存和环境样例例外规则 |
| `.run-logs/` | 本地启动输出 | 不应提交，加入忽略 |
| `model_cache/` | Hugging Face/Embedding 模型缓存 | 不应提交，加入忽略 |
| `.venv/` | 本地 Python 虚拟环境 | 已忽略，保留在本机即可 |
| `README.md` | 当前项目说明草稿 | 保留，但应在清理后重写最终版 |

### 2.2 `backend/api`

- `main.py` 是当前 FastAPI 入口，也是前端静态文件挂载、Analyze、Benchmark、Error Analysis、Fallback Promotions 和日志接收接口的集中入口。
- `schemas.py` 定义主要请求和响应模型。
- `main.py` 目前职责偏多，暂时不建议为了 GitHub 上传立刻拆分；后续可以拆成 `api/routes/analysis.py`、`api/routes/benchmark.py`、`api/routes/promotions.py` 和 `api/routes/logs.py`。

### 2.3 `backend/services`

当前真正被主链路使用的核心文件：

| 文件 | 作用 | 状态 |
|---|---|---|
| `abbr_service.py` | 缩写识别、候选扩写、coverage、确定性替换、标准化、验证和反思重试 | 主链路 |
| `medical_ner.py` | 当前 ABBRService 使用的医学实体/领域辅助识别 | 主链路依赖 |
| `abbr_candidate_retriever.py` | primary 候选词典检索 | 主链路 |
| `abbr_candidate_fallback_retriever.py` | primary 不足时调用 fallback LLM 生成候选 | 主链路 |
| `abbr_candidate_coverage_evaluator.py` | 判断候选扩写是否符合当前上下文 | 主链路 |
| `abbr_verifier.py` | mapping 验证、候选校验、反思用的重新检索词建议 | 主链路 |
| `medical_retriever.py` | 按领域调用标准化检索服务 | 主链路 |
| `std_service.py` | 连接 Milvus，并在 SNOMED/RxNorm 集合中向量检索 | 主链路 |
| `diagnosis_explainer.py` | 把结构化诊断交给 LLM 整理成人话 | Analyze/错误解读 |

需要重点确认的残留：

- `ner_service.py` 与 `medical_ner.py` 代码职责高度相似，但当前 `ABBRService` 导入的是 `medical_ner.py`。
- `ner_service.py` 目前主要被 `test_ner_service.py` 引用，不能直接删除；应先确认测试是否仍有展示价值，再决定将测试迁移到 `medical_ner.py` 后清理。
- `笔记.md` 是开发笔记，不应作为正式模块说明；建议迁移有价值内容到项目梳理文档后再移出代码目录。

### 2.4 `backend/data`

- `abbr_candidates.py` 是 primary 缩写候选库，属于主链路配置/数据源，应保留。
- `SNOMED_5000.csv` 是小型示例或筛选数据，适合保留用于演示，但需要在 README 中说明来源和用途。
- `snomed_clinical.csv`、`rxnorm_clinical.csv` 是较大的数据文件，不建议提交到 GitHub。当前 `.gitignore` 已忽略它们，但应在部署文档中说明如何准备。

### 2.5 `backend/evaluation`

这里是当前最需要整理的目录。建议按“源数据、执行脚本、生成产物”分层。

#### 当前应保留的评估代码

- `run_benchmark.py`：当前主 benchmark 执行入口。
- `concept_match.py`：benchmark 的 SNOMED 语义等价比较。
- `error_analysis_report.py`：生成结构化错误分析报告。
- `error_triage.py`：读取本轮错误分析报告并调用 LLM 生成人话解释。
- `collect_fallback_candidate_promotions.py`：提取 fallback 成功候选。
- `apply_fallback_candidate_promotions.py`：人工确认后写入 primary。

#### 需要标注为实验/兼容入口的文件

- `run_benchmark.py`：唯一 benchmark 入口；默认串行，传入 `--workers 2` 或设置 `BENCH_WORKERS=2` 后启用并行。
- `run_source_ab.py`：来源对比实验，不属于日常主流程。
- `run_concept_benchmark.py`、`concept_benchmark_cases.py`：概念检索独立评估，不是缩写主 benchmark。
- `evaluate_abbr_expansion.py`、`abbr_eval_cases.py`：较早的扩写评估脚本，需要确认是否仍用于回归测试。
- `examples/benchmarks/abbr_benchmark_cases.json`：统一格式的 74 条默认 benchmark 样例，其中包含项目自建案例和 CASI 案例。

#### 不建议提交的生成产物

- `benchmark_results.json`
- `benchmark_results.backup_*.json`
- `error_analysis_report.json`
- `error_taxonomy_report.json`
- `fallback_candidate_promotions.json`
- `fallback_candidate_promotions.md`
- `upload_test_benchmark_cases_50.json`
- `upload_test_benchmark_cases_60.json`

上传测试 cases 和默认 benchmark 样例统一放在 `examples/benchmarks/`，运行结果放在 `backend/evaluation/archive/`，两类内容不再混放。

### 2.6 `backend/tools`

建议保留，但要在 README 或部署文档中明确入口：

- `rebuild_milvus.py`：建立 SNOMED collection，当前推荐入口。
- `rebuild_rxnorm_milvus.py`：建立 RxNorm collection，当前推荐入口。
- `build_concept_csv.py`、`build_rxnorm_csv.py`：原始数据预处理。
- `create_milvus_db.py`：较早的通用建库脚本，与两个 rebuild 脚本存在职责重叠，建议标记为 legacy 或后续统一。
- `show_snomed_file.py`：查看数据文件的辅助脚本，适合放到 `tools/inspect/` 或标注为开发工具。

### 2.7 `backend/graph`

`standardization_graph.py` 和 `render_graph.py` 目前是独立的 LangGraph/流程图实现。根据当前导入关系，FastAPI 主链路没有调用它们，生产行为仍由 `ABBRService` 内部流程负责。

因此当前建议：

- 不要在 GitHub README 中把 LangGraph 写成当前线上主链路。
- 保留目录作为实验/参考实现，补一份说明它与 `ABBRService` 的关系。
- 如果后续不再维护，应在完成 parity 验证后整体移入 `experimental/graph/` 或删除。

### 2.8 `backend` 根目录测试

当前测试文件是脚本式测试和 pytest 风格测试混合：

- 与主链路相关的候选检索、coverage、确定性替换、NER、StdService 测试应保留。
- `test_support_htn.py`、`test_abbr_retry.py` 等单个问题验证脚本需要统一命名，例如 `tests/test_*.py`，并在 README 中给出运行方法。
- 建议后续新建 `backend/tests/`，逐步迁移测试，不建议本轮直接批量移动，避免影响导入和已有运行命令。

## 3. 需要优先处理的盲肠候选

以下是“需要确认后处理”，不是立即删除清单：

| 优先级 | 候选 | 判断 | 建议 |
|---|---|---|---|
| P0 | `backend/evaluation/archive/benchmark_results.backup_*.json` | 历史运行备份，非代码 | 不提交；仅本地需要时保留 |
| P0 | `backend/evaluation/archive/*.json`、`*.md` | 可重复生成的报告 | 不提交，保留生成脚本 |
| P0 | `.run-logs/`、`model_cache/` | 本地运行产物/模型缓存 | 加入 `.gitignore` |
| P1 | `backend/services/ner_service.py` | 与 `medical_ner.py` 重复，仍有旧测试引用 | 先迁移/改测试，再决定删除 |
| P1 | `backend/tools/create_milvus_db.py` | 与两个 rebuild 脚本有重叠 | 标注 legacy，确认无人使用后再处理 |
| P1 | benchmark 并行逻辑 | 已合并到 `run_benchmark.py` | 通过 `workers` 参数或 `BENCH_WORKERS` 调试 |
| P1 | `backend/graph/` | 当前主链路未接入 | 明确为实验/参考实现，避免 README 误导 |
| P2 | `backend/services/笔记.md` | 代码目录中的临时笔记 | 提取有价值内容后移到项目梳理 |
| P2 | `examples/benchmarks/*.json` | Benchmark 输入样例 | 保留，作为 GitHub 可复现实例 |

## 4. `.gitignore` 补充建议

当前 `.gitignore` 已覆盖 `.venv`、`.env`、Milvus 数据 CSV、评估报告和 `backend/logs`，但仍建议补充：

```gitignore
# Local runtime output
.run-logs/
model_cache/

# Python tooling
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Generated benchmark artifacts
backend/evaluation/archive/*.json
backend/evaluation/archive/*.md

# Keep the safe environment template visible
!.env.example
```

当前规则中的 `.env.*` 会把 `.env.example` 一并忽略。如果补充 `.env.example`，必须显式使用 `!.env.example` 取消忽略。

是否忽略 `upload_test_benchmark_cases_*.json` 需要你决定：

- 如果作为 GitHub 演示样例：移动到 `examples/benchmarks/` 并保留。
- 如果只是本地反复上传测试：加入 `.gitignore`。

## 5. 建议补充的交付文件

GitHub 上传前建议至少补齐：

| 文件 | 用途 |
|---|---|
| `.env.example` | 展示必需环境变量，但不包含真实 API key |
| `.dockerignore` | 避免把 `.venv`、日志、模型缓存和评估产物送进 Docker build context |
| `LICENSE` | 明确代码授权方式；如果暂不授权，应在 README 说明 |
| `docs/architecture.md` 或交付版技术总结 | 解释模块职责和数据流 |
| `docs/deployment.md` | 解释 Docker、Milvus、SNOMED/RxNorm 建库步骤 |
| `examples/benchmarks/README.md` | 解释 benchmark JSON 格式和运行方式 |
| `examples/screenshots/` | 展示前端工作台、Benchmark 和 Error Analysis |

## 6. 不建议现在做的事情

- 不要在没有确认用途前删除 `ner_service.py`、`create_milvus_db.py` 或 `graph/`。
- 不要把运行生成的 60 条 benchmark 结果、LLM 错误报告和模型缓存提交到 GitHub。
- 不要为了“目录看起来整齐”立刻拆分 `api/main.py`；先用测试锁定行为，再做模块拆分。
- 不要把 LangGraph 写成当前主链路已经使用的技术，除非主 API 确实切换到它。
- 不要直接覆盖当前 README；应在清理和最小验证完成后再生成最终版。

## 7. 推荐执行顺序

### 阶段一：只做确认

1. 保存当前 Git 快照。
2. 确认 `create_milvus_db.py` 和 `graph/` 是否还需要保留；benchmark 并行入口已经合并。
3. 确认上传 benchmark 样例是否作为 GitHub 演示数据。

### 阶段二：低风险清理

1. 补充 `.gitignore` 和 `.dockerignore`。
2. 补 `.env.example`、LICENSE 和部署说明。
3. 把运行产物从版本控制范围排除。
4. 给实验脚本加文件头说明，而不是直接删除。

### 阶段三：结构整理

1. 建立 `backend/tests/` 并迁移测试。
2. 维护 `examples/benchmarks/` 中的统一 JSON 样例。
3. 将实验脚本和图实现移动到 `experimental/`，每次移动后跑回归测试。
4. 最后重写 GitHub README。

## 8. 本轮已经补充的代码注释范围

本轮只增加解释性注释，不改变业务逻辑，重点覆盖：

- `backend/api/main.py`：服务懒加载、benchmark 后处理和上传任务边界。
- `backend/services/abbr_service.py`：主流程、确定性替换、NOT_EXPANDED 分类和 success 口径。
- `backend/services/std_service.py`：Milvus collection 路由和懒加载。
- `backend/evaluation/run_benchmark.py`：case 级执行、mapping 判定和报告字段。
- `backend/evaluation/error_analysis_report.py`：错误标签的来源和 case/record 统计边界。
- `backend/utils/structured_logger.py`、`backend/utils/trace_context.py`：日志通道和 request/job/case 关联关系。
- `frontend/utils/frontend_logger.js`：前端日志缓冲、Console 开关和上传后端逻辑。

这些注释是给维护者定位流程用的，不替代模块文档，也不代表所有旧脚本都已经成为正式主链路。










# Medical NLP V11

面向临床文本的医学缩写扩写与标准化系统。项目围绕“临床句子中医学缩写如何被可靠扩写，并进一步映射到 SNOMED / RxNorm 标准概念”这一任务构建，包含后端主链路、前端工作台、Benchmark 评估、错误分析、fallback 候选沉淀、结构化日志与 Docker 部署。

> 当前 V11 的主链路重点是“医学缩写扩写与标准化”，不是完整的“整句所有医学实体 NER + 标准化”系统。完整医学实体标准化可以作为后续 `/full-standardize` 模块扩展。

## 项目亮点

- **缩写扩写主链路**：从临床文本中识别目标缩写，优先使用本地候选词典，必要时使用 LLM fallback 生成候选。
- **上下文 coverage 校验**：候选扩写不会直接采纳，而是结合原句上下文判断是否可信，避免低上下文过度扩写。
- **标准概念映射**：扩写后调用向量检索服务，在 SNOMED / RxNorm 向量库中召回候选概念，并通过 verifier 判断是否可编码。
- **清晰状态语义**：将成功拆分为扩写成功、标准化成功等结构化字段，避免一个 `success` 混淆全部含义。
- **Benchmark 与错误分析**：支持上传 benchmark cases，运行后自动生成结果、错误分析报告和 LLM 人话解释。
- **fallback 候选沉淀**：将 fallback 成功且已标准化的候选整理出来，经人工确认后写入 primary 缩写词库。
- **前端工作台**：提供 Analyze、Benchmark Overview、Error Analysis、Fallback Promotions 等页面，方便演示和调试。
- **结构化日志**：后端日志按 app / dependency / pipeline / benchmark / audit / frontend 分流，前端日志可串联 request_id。
- **Docker 部署**：Docker Compose 包含 API、Milvus、etcd、MinIO，便于本地部署和复现。

## 系统流程

```text
临床文本
  -> FastAPI /expand/simple
  -> ABBRService 缩写处理主状态机
  -> primary 本地缩写候选词典
  -> fallback LLM 候选生成
  -> coverage 上下文校验
  -> 确定性替换生成 expanded_text
  -> StdService 标准化检索
  -> Milvus SNOMED / RxNorm 向量库
  -> verifier 校验候选概念
  -> CODED / WITHHELD / NOT_EXPANDED
  -> 前端展示 / benchmark / error analysis / fallback promotions
```

示例：

```text
Input:
The patient has SOB and CP.

Expanded text:
The patient has shortness of breath and chest pain.

Mapping states:
SOB -> shortness of breath -> Dyspnea
CP  -> chest pain          -> Chest pain
```

## 目录结构

```text
medical-nlp/
├── backend/
│   ├── api/
│   │   ├── main.py                 # FastAPI 入口、前端托管、benchmark/error/promotions API
│   │   └── schemas.py              # API 请求与响应结构
│   ├── data/
│   │   └── abbr_candidates.py      # primary 缩写候选词典
│   ├── services/
│   │   ├── abbr_service.py         # 缩写扩写与标准化主编排
│   │   ├── abbr_candidate_fallback_retriever.py
│   │   ├── abbr_candidate_coverage_evaluator.py
│   │   ├── std_service.py          # SNOMED / RxNorm 标准化检索服务
│   │   ├── medical_retriever.py
│   │   ├── medical_ner.py
│   │   ├── abbr_verifier.py
│   │   └── diagnosis_explainer.py
│   ├── evaluation/
│   │   ├── run_benchmark.py
│   │   ├── error_analysis_report.py
│   │   ├── error_triage.py
│   │   ├── collect_fallback_candidate_promotions.py
│   │   └── apply_fallback_candidate_promotions.py
│   ├── tools/
│   │   ├── rebuild_milvus.py       # 构建 SNOMED 向量集合
│   │   └── rebuild_rxnorm_milvus.py# 构建 RxNorm 向量集合
│   └── utils/
│       ├── embedding_factory.py
│       ├── llm_factory.py
│       ├── structured_logger.py
│       └── trace_context.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── utils/frontend_logger.js
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 技术栈

后端：

- Python 3.12
- FastAPI / Uvicorn
- Pydantic
- sentence-transformers / BGE-M3 embedding
- pymilvus
- pandas
- LLM API，用于 fallback、coverage、verifier、错误解释等环节

向量检索与部署：

- Milvus
- etcd
- MinIO
- Docker Compose

前端：

- 原生 HTML / CSS / JavaScript
- FastAPI 静态托管 `/app`
- 浏览器端结构化日志与 request_id 串联

## 快速启动

### 1. 准备环境变量

在 `backend/.env` 中配置本地运行所需变量。示例：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_MODEL=deepseek-chat

MILVUS_URI=http://127.0.0.1:19530
MILVUS_COLLECTION_NAME=concepts_only_name
MILVUS_RXNORM_COLLECTION=rxnorm_concepts
```

如果使用 Docker Compose，容器内 API 默认连接：

```env
MILVUS_URI=http://milvus:19530
```

### 2. 准备标准概念数据

项目需要本地标准概念 CSV 来构建向量库：

```text
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

这两个文件通常体积较大，且可能涉及数据授权问题，不建议直接提交到 GitHub。请在本地准备后再执行建库脚本。

### 3. 使用 Docker Compose 启动

```bash
docker compose up -d --build
```

启动后检查：

```bash
docker compose ps
```

前端工作台：

```text
http://127.0.0.1:8000/app
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

### 4. 构建向量库

首次启动 Milvus 后，需要构建 SNOMED 与 RxNorm 集合：

```bash
docker compose exec api python tools/rebuild_milvus.py
docker compose exec api python tools/rebuild_rxnorm_milvus.py
```

默认集合名：

```text
SNOMED: concepts_only_name
RxNorm: rxnorm_concepts
```

### 5. 运行一次 Analyze

打开：

```text
http://127.0.0.1:8000/app
```

输入：

```text
The patient has SOB and CP.
```

预期可以看到：

```text
expanded_text: The patient has shortness of breath and chest pain.
mapping_states: SOB / CP 均进入 CODED 状态
```

## API 示例

### 缩写扩写与标准化

```http
POST /expand/simple
Content-Type: application/json

{
  "text": "The patient has SOB and CP."
}
```

返回中重点关注：

```text
expanded_text
mapping_states
standardized_entities
success_breakdown
request_id
```

### 单句诊断

```http
POST /analysis/diagnose
```

用于把当前单句分析结果整理成人话解释，方便前端展示。

### Benchmark

```http
GET  /benchmark/summary
GET  /benchmark/results
POST /benchmark/cases/jobs
GET  /benchmark/cases/jobs/{job_id}
```

支持上传 benchmark cases JSON，后端会运行 benchmark，并继续生成：

```text
evaluation/archive/benchmark_results.json
evaluation/archive/error_analysis_report.json
error_triage_report.md
evaluation/archive/fallback_candidate_promotions.json
```

### fallback 候选沉淀

```http
GET  /candidate-promotions
POST /candidate-promotions/apply
POST /candidate-promotions/apply-single
```

用于将 fallback 成功且已 CODED 的候选，经人工确认后写回 `backend/data/abbr_candidates.py`。

## 前端页面

### Analyze

用于单句临床文本分析：

- 输入文本
- 展示扩写文本
- 展示每个缩写的扩写、来源、coverage、状态、标准概念
- 支持对 fallback 且 CODED 的单个候选写入 primary
- 支持生成 LLM 单句诊断
- Raw JSON 默认折叠，供开发调试查看

### Benchmark Overview

用于查看 benchmark 总体表现：

- 总 case 数
- 正确 case 数
- 失败 case 数
- accuracy
- 分类正确 / 失败分布
- benchmark 失败案例
- 支持上传新的 benchmark cases 并异步运行

### Error Analysis

用于查看本轮 benchmark 的错误分布：

- benchmark mismatch
- expansion blocked
- standardization failure
- benchmark + standardization 交集
- LLM triage 人话解释卡片

### Fallback Promotions

用于查看并确认 fallback 候选沉淀：

- abbreviation
- expansion
- domain
- support count
- case ids
- new / already exists 状态
- 确认写入 primary

## Benchmark 与评估

项目内置 benchmark 运行脚本：

```bash
python backend/evaluation/run_benchmark.py
```

Docker 中运行：

```bash
docker compose exec api python evaluation/run_benchmark.py
```

也可以在前端 Benchmark Overview 页面上传 cases JSON。上传后，后端会真正运行 benchmark，而不是直接展示上传文件中的结果。

当前评估报告会区分：

```text
benchmark 是否符合 gold
扩写是否被阻断
标准化是否失败
错误是否存在交集
```

这样可以避免把“benchmark 错误”“扩写错误”“标准化错误”混成一个口径。

## 日志系统

后端日志默认写入：

```text
backend/logs/app.jsonl
backend/logs/dependency.jsonl
backend/logs/pipeline.jsonl
backend/logs/benchmark.jsonl
backend/logs/audit.jsonl
backend/logs/frontend.jsonl
```

用途：

- `app.jsonl`：API 启动、请求级事件等
- `dependency.jsonl`：LLM、embedding、Milvus 等依赖状态
- `pipeline.jsonl`：Analyze 主链路执行过程
- `benchmark.jsonl`：benchmark 上传、运行、后处理
- `audit.jsonl`：写入 primary 等重要变更
- `frontend.jsonl`：浏览器端前端日志落盘

这些日志属于运行产物，默认不建议提交到 GitHub。

前端临时打开 INFO 日志：

```javascript
localStorage.setItem("medicalNlpFrontendLogConsole", "1")
```

关闭：

```javascript
localStorage.removeItem("medicalNlpFrontendLogConsole")
```

查看前端日志 buffer：

```javascript
window.frontendLogger.print()
```

## GitHub 上传注意事项

不要提交：

```text
backend/.env
backend/logs/
model_cache/
.venv/
.run-logs/
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
backend/evaluation/archive/benchmark_results.json
backend/evaluation/archive/error_analysis_report.json
backend/evaluation/archive/benchmark_results.backup_*.json
```

建议提交：

```text
backend/
frontend/
Dockerfile
docker-compose.yml
README.md
项目梳理/交付版整理/
```

正式上传前建议检查：

```bash
git status --short
git diff --stat
```

如果需要给别人复现项目，建议额外补充：

```text
backend/.env.example
LICENSE
docs/images/ 页面截图
```

## 当前边界与后续计划

当前边界：

- 主链路处理医学缩写，不保证覆盖整句所有医学实体。
- LLM fallback、coverage、verifier、triage 等环节依赖可用的 LLM API。
- 标准概念库需要本地准备 CSV 并构建 Milvus collection。
- 本项目用于技术展示与研究验证，不构成医学诊断建议。

后续可扩展：

- `/full-standardize`：完整医学实体 NER + 标准化
- 前端日志查看页
- Milvus 自动建库 init service
- 更完整的 `.env.example`
- 更严格的 benchmark case 管理与版本记录
- GitHub Actions 基础测试流程

## License

当前仓库尚未指定开源协议。正式公开前建议根据展示目标补充 `LICENSE` 文件。

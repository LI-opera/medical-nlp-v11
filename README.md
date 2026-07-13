# Medical NLP V11

面向临床文本的医学缩写扩写与标准概念映射工作台。

Medical NLP V11 将临床文本中的医学缩写扩展为完整术语，并进一步映射到 SNOMED CT 或 RxNorm 标准概念。系统同时提供 Analyze、Benchmark、错误分析和 fallback 候选审核工作台。

> 当前生产主链路聚焦于“医学缩写扩写与标准化”，不等同于覆盖整句所有医学实体的通用 NER 标准化系统。`backend/graph/` 中的 LangGraph 代码用于流程实验和流程图展示，不是当前 API 的生产入口。

## 项目演示

### Analyze：缩写扩写与标准化

输入：

```text
The patient has SOB and CP.
```

输出：

```text
The patient has shortness of breath and chest pain.
```

标准化结果示例：

```text
SOB -> shortness of breath -> Dyspnea
CP  -> chest pain          -> Chest pain
```

![](C:\Users\Administrator\Desktop\medical_nlp项目流程\github\analyze2.png)

### Benchmark：运行评估并查看失败分布

上传包含 `cases` 列表的 JSON 文件，系统会运行整套 benchmark，并展示总数、正确数、失败数、accuracy 和分类统计。

![](C:\Users\Administrator\Desktop\medical_nlp项目流程\github\overview.png)

### Error Analysis 与 Fallback Promotions

错误分析页面将 benchmark 失败拆分为 benchmark mismatch、扩写阻断和标准化失败，并使用 LLM 生成“情况、可能原因、下一步建议”。Fallback Promotions 页面用于审核 fallback 成功且标准化成功的候选，再决定是否写入 primary 词典。

![](C:\Users\Administrator\Desktop\medical_nlp项目流程\github\erroranalysis.png)

![](C:\Users\Administrator\Desktop\medical_nlp项目流程\github\fallback.png)

## 快速开始

本项目有两种使用方式。第一次体验建议选择**简易演示版**；需要完整医学概念覆盖、RxNorm 药品标准化或正式 benchmark 时，再准备完整数据库。

```text
简易演示版：SNOMED_5000.csv + 一个 SNOMED collection，适合快速看到页面和主流程
完整版：完整 SNOMED / RxNorm CSV + 两个 Milvus collection，适合完整评估和深入使用
```

### 方式一：Docker 简易演示版（推荐第一次使用）

这个方式不需要把 BGE-M3 模型或 Milvus collection 上传到 GitHub。Docker 会启动服务，BGE-M3 在第一次使用 embedding 时自动从 Hugging Face 下载，模型会缓存到本地 `model_cache/huggingface/`。

首次下载需要网络连接和较大的磁盘空间，下载完成后后续启动会复用缓存。

#### 1. 准备配置

在仓库根目录执行：

```powershell
Copy-Item backend/.env.example backend/.env
```

打开 `backend/.env`，至少填写 LLM Key：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
```

#### 2. 启动 API、Milvus、etcd 和 MinIO

```powershell
docker compose up -d --build
docker compose ps
```

确认 `api`、`milvus`、`etcd`、`minio` 都处于运行状态后，先不要立即测试标准化。新建的 Milvus 还是空集合，需要继续执行下一步。

#### 3. 使用仓库自带的小型 SNOMED 数据建库

仓库中保留了一个小型演示数据文件：

```text
backend/data/SNOMED_5000.csv
```

它由 `create_milvus_db.py` 读取，并创建名为 `concepts_only_name` 的 SNOMED collection：

```powershell
docker compose exec api python tools/milvus/create_milvus_db.py
```

首次执行时会加载或下载 BGE-M3，生成向量并写入 Milvus，因此可能需要等待较长时间。

#### 4. 打开网页验证

访问：

```text
http://127.0.0.1:8000/app
```

在 Analyze 页面输入：

```text
The patient has SOB and CP.
```

点击“分析”，可以查看缩写扩写和 SNOMED 标准化结果。

#### 简易演示版的范围和限制

简易演示版的目标是让使用者快速看到项目主链路，不是完整生产数据包：

- 只有小型 SNOMED 演示数据，概念覆盖范围有限。
- 不包含完整的 `snomed_clinical.csv`。
- 不包含 `rxnorm_clinical.csv`，因此不能完整演示 RxNorm 药品标准化。
- 没有上传 BGE-M3，第一次运行必须联网下载模型。
- 某些扩写虽然正确，但可能因为演示 collection 中没有对应概念而返回 `WITHHELD`。
- Benchmark 的结果只能用于流程演示，不能代表完整医学词汇库的准确率。

### 方式二：Docker 完整数据库版

完整版本需要使用者自行准备 SNOMED CT 和 RxNorm 数据。项目不把这些原始数据、模型和 Milvus collection 放入 GitHub，因此完整版本需要额外的数据准备步骤。

#### 1. 准备原始概念数据

准备可用于筛选的 Athena/OHDSI `CONCEPT.csv` 或项目允许使用的等价数据源。将原始文件放在仓库外部，避免把大型原始数据复制进 Git 仓库。

然后分别检查并修改：

```text
backend/tools/data/build_concept_csv.py
backend/tools/data/build_rxnorm_csv.py
```

将脚本中的 `INPUT_CSV` 指向你的原始 `CONCEPT.csv`。

#### 2. 生成完整 CSV

在本机 Python 环境中执行：

```powershell
python backend/tools/data/build_concept_csv.py
python backend/tools/data/build_rxnorm_csv.py
```

成功后应生成：

```text
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

这两个文件被 `.gitignore` 忽略，不会进入 GitHub。Docker Compose 会把本地 `backend/data/` 挂载到容器内，因此容器可以读取这两个文件。

#### 3. 启动 Docker 服务

```powershell
docker compose up -d --build
docker compose ps
```

#### 4. 构建两个完整 Milvus collection

SNOMED collection：

```powershell
docker compose exec api python tools/milvus/rebuild_milvus.py
```

它读取 `backend/data/snomed_clinical.csv`，创建或重建：

```text
concepts_only_name
```

RxNorm collection：

```powershell
docker compose exec api python tools/milvus/rebuild_rxnorm_milvus.py
```

它读取 `backend/data/rxnorm_clinical.csv`，创建或重建：

```text
rxnorm_concepts
```

两个脚本都会使用 BGE-M3 将概念名称转为向量，并批量写入 Milvus。完整数据量较大，建库时间和磁盘占用会明显高于简易演示版。

#### 5. 验证完整版本

访问：

```text
http://127.0.0.1:8000/app
```

建议分别测试 SNOMED 和 RxNorm 相关文本，并检查两个 collection 是否都已经建立且可以检索。

### 方式三：本机启动

本机启动适合开发调试。它不会自动启动 Milvus、etcd 和 MinIO，需要先单独启动这些依赖，或者让本机 API 连接已经运行的 Docker Milvus。

本机启动同样需要 BGE-M3：第一次调用 embedding 时会从 Hugging Face 下载到本机 Hugging Face 缓存目录。如果本机没有模型缓存且无法访问 Hugging Face，标准化检索无法正常工作。

启动 API：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

访问：

```text
前端工作台：http://127.0.0.1:8001/app
Swagger：  http://127.0.0.1:8001/docs
健康检查：http://127.0.0.1:8001/health
```

本机简易演示建库：

```powershell
python backend/tools/milvus/create_milvus_db.py
```

本机完整建库：

```powershell
python backend/tools/milvus/rebuild_milvus.py
python backend/tools/milvus/rebuild_rxnorm_milvus.py
```

运行完整建库命令前，必须先准备对应的两个 CSV 文件。仅有仓库中的 `SNOMED_5000.csv` 时，只能运行简易 SNOMED 演示流程。

## 输入输出示例

### 输入缩写文本

```text
The patient has SOB and CP.
```

### 扩写文本

```text
The patient has shortness of breath and chest pain.
```

### 结构化结果

```text
SOB
  expansion: shortness of breath
  standard concept: Dyspnea
  status: CODED

CP
  expansion: chest pain
  standard concept: Chest pain
  status: CODED
```

对于无法安全扩写或无法可靠标准化的实体，系统会保留结构化失败状态，例如 `NOT_EXPANDED`、`ABSTAIN` 或 `WITHHELD`，不会强行绑定一个不可靠的标准概念。

## 功能概览

- **缩写扩写**：优先使用 `primary` 本地候选词典，必要时调用 LLM fallback。
- **上下文 coverage**：根据原始句子、候选扩写和 domain 判断候选是否适合当前语境。
- **确定性替换**：只替换通过 coverage 的扩写结果，生成 `expanded_text`。
- **标准化检索**：使用 embedding 检索 Milvus 中的 SNOMED CT 或 RxNorm 概念。
- **候选验证与反思**：验证扩写和标准概念是否忠实，必要时进行受控的同义词重检索。
- **结构化状态**：返回 `CODED`、`WITHHELD`、`NOT_EXPANDED`、`ABSTAIN`、`PENDING` 等状态，以及 failure、evidence 和 suggestion。
- **Benchmark 评估**：上传 cases JSON，运行 benchmark 并自动生成错误分析、LLM triage 和 fallback 候选沉淀。
- **候选沉淀**：人工审核 fallback 成功且标准化成功的候选，再写入 primary；同一缩写可以保留多个扩写。
- **可观测性**：后端和前端按不同职责记录 JSONL 日志，并通过 request_id、backend_request_id 和 job_id 关联排查。
- **Docker 部署**：Compose 编排 API、Milvus、etcd 和 MinIO。

## 系统架构

```text
临床文本
  -> FastAPI /expand/simple
  -> ABBRService
       -> primary 缩写候选
       -> fallback LLM 候选
       -> coverage 上下文校验
       -> 确定性扩写，生成 expanded_text
  -> StdService
       -> SNOMED / RxNorm 检索源选择
       -> embedding 检索 Milvus
       -> verifier 校验
       -> 可选反思与同义词重检索
  -> mapping_states / standardized_entities / success_breakdown
  -> 前端 Analyze 展示
```

核心边界是：

```text
扩写负责回答：缩写在当前句子中应该展开成什么？
标准化负责回答：这个扩写对应哪个标准医学概念？
```

`WITHHELD` 表示系统拒绝不可靠编码，不等于标准化成功。`success`、`expansion_success` 和 `standardization_success` 是不同层级的状态。

## 前端工作台

### Analyze

用于单句缩写分析：

1. 输入临床文本并点击“分析”。
2. 查看确定性扩写后的文本。
3. 在当前单句诊断中查看 source、coverage、扩写状态、标准概念和 domain。
4. 对 fallback 且 `CODED` 的候选，可单条确认写入 primary。
5. 点击“生成 LLM 诊断”查看面向人的解释。
6. Raw JSON 默认折叠，供开发者查看完整返回结构。

建议测试文本：

```text
The patient has SOB and CP.
The patient has XYZ.
The ABG revealed respiratory acidosis with hypoxemia.
```

### Benchmark Overview

上传 JSON 后，后端创建 benchmark job，前端显示实时进度。Benchmark 轮询只更新自身页面的进度区域，不重绘 Analyze 页面，因此不会干扰单句诊断或 primary 写入弹窗。

### Error Analysis

读取本轮 `error_analysis_report.json` 和 LLM triage 结果，展示：

- benchmark mismatch
- expansion blocked
- standardization failure
- benchmark 与标准化失败的交集
- 失败类型分布图
- 每个 case 的“情况、可能原因、下一步建议”

### Fallback Promotions

读取本轮 fallback 成功且标准化成功的候选，展示缩写、扩写、domain、support 和 case id。用户确认后才会向 `backend/data/abbr_candidates.py` 追加候选；同一缩写可以保留多个扩写，重复的缩写-扩写组合会跳过。

## Benchmark 与错误分析

默认 benchmark 文件位于：

```text
examples/benchmarks/abbr_benchmark_cases.json
```

上传文件的最小格式：

```json
{
  "cases": [
    {
      "id": "demo_001",
      "category": "single_meaning",
      "text": "The patient has SOB.",
      "expected_mappings": [
        {
          "abbreviation": "SOB",
          "expansion": "shortness of breath"
        }
      ]
    }
  ]
}
```

Benchmark 的评估口径是 case 级别：一个 case 中只要最终映射与 gold 不一致，该 case 就会失败。错误分析同时保留 case 级总失败和 record 级状态原因，避免把“案例失败数”和“实体状态数”混在一起。

手动运行默认 benchmark：

```powershell
python backend/evaluation/run_benchmark.py
```

并行运行：

```powershell
$env:BENCH_WORKERS="2"
python backend/evaluation/run_benchmark.py
```

评估链路：

```text
benchmark_results.json
  -> error_analysis_report.py
  -> error_analysis_report.json
  -> error_triage.py
  -> error_triage_report.md
  -> collect_fallback_candidate_promotions.py
  -> fallback_candidate_promotions.json
```

当前结果默认写入 `backend/evaluation/runtime/`，历史结果由评估路径管理逻辑归档到 `backend/evaluation/archive/`。这些目录属于运行产物，不是项目源代码。

## 项目目录

```text
medical-nlp/
├─ backend/
│  ├─ api/
│  │  ├─ main.py                 # FastAPI 入口、静态前端和业务 API
│  │  └─ schemas.py              # 请求与响应模型
│  ├─ data/
│  │  └─ abbr_candidates.py      # primary 缩写候选词典
│  ├─ services/
│  │  ├─ abbr_service.py         # 缩写主链路
│  │  ├─ abbr_candidate_retriever.py
│  │  ├─ abbr_candidate_fallback_retriever.py
│  │  ├─ abbr_candidate_coverage_evaluator.py
│  │  ├─ abbr_verifier.py         # 扩写与标准化结果验证
│  │  ├─ std_service.py           # 标准概念检索
│  │  ├─ medical_retriever.py     # Milvus 检索适配
│  │  ├─ medical_ner.py           # fallback 使用的实体识别能力
│  │  └─ diagnosis_explainer.py   # 单句与 benchmark 的 LLM 解释
│  ├─ utils/
│  │  ├─ embedding_config.py / embedding_factory.py
│  │  ├─ llm_config.py / llm_factory.py
│  │  ├─ structured_logger.py     # 后端 JSONL 日志
│  │  └─ trace_context.py          # request_id / job_id 上下文
│  ├─ evaluation/
│  │  ├─ run_benchmark.py         # 串行/并行统一入口
│  │  ├─ error_analysis_report.py # 结构化错误分析
│  │  ├─ error_triage.py          # LLM 人话解释
│  │  ├─ collect_fallback_candidate_promotions.py
│  │  ├─ apply_fallback_candidate_promotions.py
│  │  └─ paths.py                 # runtime/archive 路径管理
│  ├─ tools/milvus/               # SNOMED / RxNorm 建库工具
│  └─ graph/                      # LangGraph 流程实验与可视化
├─ examples/benchmarks/           # benchmark 样例
├─ frontend/
│  ├─ app.js / router.js          # 应用装配与路由
│  ├─ api/client.js               # API 请求和 request_id
│  ├─ state/store.js              # 前端运行状态
│  ├─ pages/                      # 各业务页面
│  ├─ components/                 # 弹窗、图表、进度和报告组件
│  ├─ utils/frontend_logger.js    # 前端日志 buffer 与上报
│  └─ styles.css
├─ Dockerfile
├─ docker-compose.yml
└─ README.md
```

## 配置变量

复制配置模板：

```powershell
Copy-Item backend/.env.example backend/.env
```

常用配置：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DASHSCOPE_API_KEY=your_dashscope_api_key
MILVUS_URI=http://127.0.0.1:19530
MILVUS_COLLECTION_NAME=concepts_only_name
MILVUS_RXNORM_COLLECTION=rxnorm_concepts
BENCH_WORKERS=1
REFLECT_MAX_ITER=2
```

完整变量和日志参数以 `backend/.env.example` 为准。`backend/.env` 只用于本地配置，不要提交到仓库。

## 日志与可观测性

后端日志按职责写入 JSONL：

```text
backend/logs/app.jsonl
backend/logs/dependency.jsonl
backend/logs/pipeline.jsonl
backend/logs/benchmark.jsonl
backend/logs/audit.jsonl
backend/logs/frontend.jsonl
```

业务返回中的 `mapping_states` 和 `failure` 负责说明“这条文本最终怎样”；日志负责说明“请求何时进入哪个阶段、依赖是否可用、耗时和异常是什么”。两者不是重复数据。

前端日志默认进入浏览器 buffer。开发调试时可以在 Console 执行：

```javascript
window.frontendLogger.print()
```

临时打开 INFO 自动输出：

```javascript
localStorage.setItem("medicalNlpFrontendLogConsole", "1")
```

关闭：

```javascript
localStorage.removeItem("medicalNlpFrontendLogConsole")
```

## 当前边界与后续方向

当前系统的主要边界：

- 主流程处理医学缩写，不承诺完整覆盖整句中的所有医学实体。
- fallback、coverage、verifier 和 LLM triage 需要可用的 LLM API。
- 标准化效果取决于 Milvus collection、embedding 模型和输入数据质量。
- `WITHHELD` 是安全拒绝，不应被解释为标准化成功。
- 项目用于技术展示、研究和工程验证，不构成医学诊断或治疗建议。

后续可以扩展：

- 增加 `/full-standardize`，对完整临床文本执行 NER 与实体标准化。
- 增加 Milvus 自动建库初始化服务。
- 增加 GitHub Actions 的静态检查、单元测试和基础 API 检查。
- 增加更完整的 benchmark 版本管理和回归测试。

## License

当前仓库未指定开源许可证，主要用于个人项目展示、学习和面试交流。

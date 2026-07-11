# 12_GitHub交付清理路线：README 与盲肠怎么处理

> 前 00-11 章解决的是：你怎么重新理解这个项目。
>
> 这一章解决的是：这个项目怎么干净地放到 GitHub 上，让面试官和未来的你都能看懂、跑起、追问时讲清楚。

---

## 0. 先说结论：GitHub 交付不是“把整个文件夹上传”

你现在的项目不是没有价值。

真正的问题是：

```text
主链路代码、实验代码、施工文档、旧版文档、运行产物、调试日志、AI 生成中间稿
全都挤在一个仓库里。
```

如果直接上传，面试官看到的不是“一个医学 NLP 项目”，而是：

```text
一堆不知道哪个能跑、哪个是旧的、哪个是主线、哪个是草稿的文件。
```

所以 GitHub 交付的核心不是美化，而是**降噪**。

你要让别人第一眼明白：

1. 这个项目解决什么问题；
2. 主入口在哪里；
3. 怎么启动；
4. 怎么跑一个例子；
5. 怎么看评估；
6. 哪些是核心代码；
7. 哪些是实验或归档材料；
8. 项目当前边界是什么。

---

## 1. GitHub 版项目应该长什么样

理想交付结构可以是：

```text
medical-nlp/
  README.md
  .gitignore
  Dockerfile
  docker-compose.yml
  backend/
    api/
    services/
    utils/
    tools/
    evaluation/
    graph/
    data/
    requirements.txt
  docs/
    architecture.md
    demo_cases.md
    benchmark.md
    limitations.md
  examples/
    sample_request.json
    sample_response.json
  archive/
    old_docs/
    construction_notes/
```

注意，这不是说你现在必须马上移动所有文件。

这是最终目标。

当前可以分阶段做：

```text
第一阶段：先写 README，把主链路讲清楚。
第二阶段：补 examples，让别人不用读源码也能看懂输入输出。
第三阶段：清 .gitignore，避免上传日志、缓存、私密配置和大数据。
第四阶段：把旧文档/施工指令移动到 archive 或 docs/internal。
第五阶段：最后再删真正无用的盲肠。
```

不要一上来大删。

先分层。

---

## 2. 先定义 GitHub 展示的“主项目”

这个项目对外应该叫：

```text
Medical NLP Abbreviation Expansion and Standardization
```

中文理解：

```text
医学缩写扩写与标准概念标准化系统
```

它不是一个泛泛聊天机器人。

也不是一个普通 RAG 问答项目。

它的主线是：

```text
英文临床文本
  -> 医学缩写候选召回
  -> coverage 闸门
  -> 确定性替换
  -> SNOMED / RxNorm 多源标准化
  -> verifier 忠实性校验
  -> reflection 重检索
  -> benchmark / error analysis
```

GitHub 上所有文件都应该服务于这条主线。

如果一个文件不能解释它和这条主线的关系，它就应该：

- 移到 `archive/`；
- 或移动到 `docs/internal/`；
- 或删掉；
- 或在 README 里明确标注为实验。

---

## 3. README 应该写什么

README 不是论文。

README 的目标是让一个外部读者在 3 分钟内知道：

```text
这个项目是什么
怎么跑
看哪个文件
输出长什么样
项目亮点和限制是什么
```

建议 README 结构如下：

```text
# Medical NLP Abbreviation Expansion and Standardization

## Overview
## What Problem It Solves
## Architecture
## Example
## Quick Start
## API Usage
## Benchmark
## Project Structure
## Design Highlights
## Limitations
## Roadmap
```

下面逐块拆。

---

## 4. README 第一段：项目定位

可以写：

```text
This project is a clinical NLP pipeline for English medical abbreviation expansion
and medical concept standardization. It expands abbreviations such as ASA, CP and
SOB in clinical sentences, then maps the expanded terms to standard medical
concepts from SNOMED and RxNorm.

Unlike direct LLM rewriting, the system uses a constrained pipeline:
candidate retrieval, coverage gating, deterministic replacement, source-routed
concept retrieval, LLM-based faithful verification, reflection retry and
benchmark-driven error analysis.
```

中文解释：

> 这个项目是英文临床文本缩写扩写与标准化系统。它不是让 LLM 直接改写病历，而是用受控流水线降低幻觉和语义漂移风险。

这段应该放 README 最上面。

---

## 5. README 里必须放一个样例

永远用这个样例：

```text
The patient took ASA for CP and denies SOB.
```

示例输出可以写成简化版：

```json
{
  "success": true,
  "expanded_text": "The patient took aspirin for chest pain and denies shortness of breath.",
  "mappings": [
    {"abbreviation": "ASA", "expansion": "aspirin"},
    {"abbreviation": "CP", "expansion": "chest pain"},
    {"abbreviation": "SOB", "expansion": "shortness of breath"}
  ],
  "standardized_entities": [
    {
      "text": "aspirin",
      "source": "rxnorm",
      "concept_id": "..."
    },
    {
      "text": "chest pain",
      "source": "snomed",
      "concept_id": "..."
    }
  ]
}
```

这里要小心：

如果你没有稳定的真实 concept_id，就不要在 README 里写死具体 ID。

可以用：

```text
...
```

或者写：

```text
Actual concept IDs depend on the local SNOMED/RxNorm data loaded into Milvus.
```

这是诚实边界。

---

## 6. README 里要解释 success 的语义

这点你已经发现了。

当前代码里的 `success` 不应该被包装成：

```text
所有医学实体都标准化成功
```

更准确的 README 写法是：

```text
Note: the current `success` field indicates whether the abbreviation expansion
workflow completed with at least one resolved expansion. It does not mean that
every expanded term has been assigned a standard medical code. Per-term coding
status should be inspected through mappings, standardized_entities or internal
mapping states.
```

中文理解：

> 当前 success 更接近流程完成，不等于所有实体都 CODED。标准化是否成功要看每个实体状态。

后续如果你要改代码，建议新增：

```text
workflow_success
expansion_success
standardization_success
all_coded
```

但 GitHub 交付前，至少 README 不能夸大。

---

## 7. Quick Start 应该怎么写

项目现在有：

```text
Dockerfile
docker-compose.yml
backend/requirements.txt
```

所以 README 可以给两种启动方式。

### 方式 A：本地 Python

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

注意：Windows 下虚拟环境激活是：

```powershell
.venv\Scripts\activate
```

Linux / macOS 是：

```bash
source .venv/bin/activate
```

### 方式 B：Docker

```bash
docker compose up --build
```

但这里必须加一句：

```text
Milvus and local SNOMED/RxNorm data must be prepared before concept retrieval works.
```

否则别人以为一条命令就能完整跑通，结果向量库没数据，会直接困惑。

---

## 8. API Usage 怎么写

README 里应该给一个最小 curl：

```bash
curl -X POST "http://127.0.0.1:8000/expand/simple" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"The patient took ASA for CP and denies SOB.\"}"
```

如果 Windows PowerShell，写成：

```powershell
$body = @{
  text = "The patient took ASA for CP and denies SOB."
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/expand/simple" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

这样面试官或者你自己复制就能试。

---

## 9. Project Structure 怎么写

README 里可以这样解释目录：

```text
backend/api
  FastAPI entrypoints and response schemas.

backend/services
  Core business logic: abbreviation expansion, candidate retrieval, coverage
  evaluation, standardization retrieval, verifier and reflection.

backend/utils
  Embedding and LLM configuration factories.

backend/tools
  Offline data preparation scripts for SNOMED/RxNorm CSV and Milvus collections.

backend/evaluation
  Benchmark cases, benchmark runners, concept matching and error analysis.

backend/graph
  LangGraph visualization/reference implementation for the standardization flow.

backend/data
  Local medical concept data. Large/generated files should not be committed.
```

这里重点是：**让每个目录都有身份**。

不要让读者自己猜。

---

## 10. 交付时哪些文件是核心

核心代码应该保留：

```text
backend/api/
backend/services/
backend/utils/
backend/tools/
backend/evaluation/
backend/graph/
backend/requirements.txt
Dockerfile
docker-compose.yml
.gitignore
README.md
```

这些构成项目主体。

---

## 11. 哪些文件不能直接上传

这些不应该进 GitHub：

```text
.venv/
__pycache__/
*.pyc
backend/.env
backend/logs/
backend/evaluation/benchmark_results.json
backend/evaluation/error_analysis_report.json
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

原因：

- `.venv/` 是本地环境；
- `__pycache__/` 是 Python 运行缓存；
- `.env` 可能包含 API key；
- `logs/` 是运行日志；
- benchmark 结果是运行产物；
- SNOMED/RxNorm 数据可能很大，也可能涉及许可证；
- 生成型 CSV 应该通过 tools 重建，而不是直接提交。

你现在 `.gitignore` 已经包含了一部分：

```text
.venv/
venv/
__pycache__/
*.pyc
.env
.env.*
backend/evaluation/benchmark_results.json
backend/logs/
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

后续建议补充：

```text
backend/evaluation/error_analysis_report.json
backend/evaluation/error_taxonomy_report.json
backend/evaluation/unresolved_cases.jsonl
backend/data/*.csv
!backend/data/*sample*.csv
```

如果你有小样例数据，可以保留 sample。

不要上传真实大数据。

---

## 12. 什么叫“盲肠”

这里说的盲肠不是“所有看不懂的文件”。

盲肠是指：

```text
不在主链路中被调用
不再用于实验
不再用于文档解释
不再用于复现结果
但仍然躺在仓库里制造误解的文件
```

盲肠的危害不是占空间。

真正危害是：

```text
面试官问这个文件干什么的，你答不上来。
未来你自己维护时，也不知道能不能删。
```

所以盲肠要处理，但不能莽删。

---

## 13. 盲肠处理四分类

不要只有“删/不删”两种。

建议分四类：

| 类别 | 处理方式 | 例子 |
|---|---|---|
| 主链路 | 保留 | `abbr_service.py`, `medical_retriever.py`, `std_service.py` |
| 交付辅助 | 保留或整理 | `tools/`, `evaluation/`, Docker 文件 |
| 学习/施工资料 | 移到 docs/internal 或 archive | 批次指令、旧模块文档、AI 施工说明 |
| 真废弃 | 删除 | 无调用、无文档价值、无复现实验价值的临时文件 |

先移动，再删除。

这样最稳。

---

## 14. 如何判断一个文件是不是主链路

用 3 个问题判断：

### 问题 1：运行 API 会不会用到它

从入口开始追：

```text
backend/api/main.py
  -> ABBRService
  -> candidate retriever
  -> coverage evaluator
  -> deterministic replacement
  -> MedicalRetriever
  -> StdService
  -> ABBRVerifier
```

如果在这个链路上，就是主链路。

### 问题 2：benchmark 会不会用到它

例如：

```text
backend/evaluation/run_benchmark.py
backend/evaluation/concept_match.py
backend/evaluation/abbr_benchmark_cases.py
```

这些不一定是线上 API，但对项目证明很重要。

保留。

### 问题 3：离线建库会不会用到它

例如：

```text
backend/tools/build_concept_csv.py
backend/tools/rebuild_milvus.py
backend/tools/build_rxnorm_csv.py
backend/tools/rebuild_rxnorm_milvus.py
```

这些是数据准备链路。

保留，但 README 要说明“需要本地数据”。

---

## 15. 最可能需要归档的内容

当前仓库里有很多项目梳理资料。

它们对你学习有价值，但不一定适合放在 GitHub 根目录。

建议：

```text
项目梳理/
anti的项目梳理/
PROJECT_TECHNICAL_DOCUMENTATION.md
项目解析.md
```

处理方式：

```text
保留一份正式 docs/
其它旧版/施工版放 archive/
```

可以整理成：

```text
docs/
  architecture.md
  interview_notes.md
  benchmark.md
  cleanup_plan.md

archive/
  project_notes/
  v9_docs/
  v11_construction_notes/
```

这样不是把学习资料丢掉，而是给它们一个“内部资料”的身份。

---

## 16. 测试脚本怎么处理

`backend/` 根目录下有很多：

```text
test_abbr_candidate_coverage.py
test_abbr_candidate_retriever.py
test_abbr_candidate_retry.py
test_abbr_fallback_retriever.py
test_abbr_retry.py
test_embedding.py
test_fallback_coverage.py
test_medical_retriever.py
test_medical_standardizer.py
test_ner_service.py
test_ner_to_retriever.py
test_std_service.py
test_support_htn.py
test_v11_deterministic.py
```

这些可能不是标准 pytest 测试，而是开发期调试脚本。

不要立刻删。

建议分成：

```text
backend/tests/
  test_v11_deterministic.py
  test_abbr_service.py
  test_retriever.py

backend/scripts/dev_checks/
  check_embedding.py
  check_std_service.py
  check_fallback_coverage.py
```

如果短期不想改目录，README 里至少说明：

```text
Some root-level test_*.py files are development smoke checks rather than a fully organized pytest suite.
```

但 GitHub 展示版最好整理一下。

---

## 17. 数据文件怎么处理

医学标准库数据很敏感。

不是因为它一定包含隐私，而是因为：

- 文件可能很大；
- 数据来源可能有许可证；
- GitHub 上传会让仓库臃肿；
- 别人也不一定能直接使用你的本地数据。

建议：

```text
backend/data/
  sample_abbreviations.json
  sample_concepts.csv
  README.md
```

真实大数据不提交。

在 `backend/data/README.md` 里说明：

```text
This project expects locally prepared SNOMED and RxNorm concept CSV files.
Generated full-size CSV files are ignored by Git and should be rebuilt using backend/tools.
```

如果你没有时间补 `backend/data/README.md`，至少主 README 里写清楚。

---

## 18. .env 怎么处理

`backend/.env` 绝对不要上传。

README 里应该提供：

```text
backend/.env.example
```

内容类似：

```text
MILVUS_URI=http://127.0.0.1:19530
MILVUS_COLLECTION_NAME=concepts_only_name
MILVUS_RXNORM_COLLECTION=rxnorm_concepts
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
REFLECT_MAX_ITER=2
```

注意：

```text
.env.example 可以上传
.env 不可以上传
```

这是 GitHub 项目基本卫生。

---

## 19. Docker 交付要注意什么

有 Dockerfile 和 docker-compose 不代表项目完全容器化完成。

README 里要讲清：

```text
Docker starts the API runtime, but Milvus and concept collections must be available.
```

如果 `docker-compose.yml` 只启动后端，没有启动 Milvus，就不要写成：

```text
docker compose up 就能完整跑通所有标准化能力
```

而应该写：

```text
Docker support is provided for the API service. A Milvus instance with prepared
SNOMED/RxNorm collections is required for concept retrieval.
```

这叫交付边界清楚。

---

## 20. Benchmark 怎么放到 GitHub

Benchmark 相关代码要保留。

但运行结果不一定要提交。

README 可以写：

```bash
cd backend
python -m evaluation.run_benchmark
```

然后说明：

```text
The benchmark evaluates abbreviation mappings and expanded text. Mapping
correctness uses a hybrid criterion: exact string match or equivalent SNOMED
concept_id when both expansions can be reliably resolved.
```

中文意思：

> benchmark 不是只看字符串，还允许同义扩写通过 SNOMED concept_id 判等。

但是要加限制：

```text
Evaluation quality depends on the local concept library coverage.
```

---

## 21. Error Analysis 怎么放

`error_analysis_report.json` 这类运行产物不建议提交。

但可以保留生成脚本：

```text
backend/evaluation/analyze_errors.py
backend/evaluation/error_analysis_report.py
backend/evaluation/error_triage.py
```

README 里可以写：

```text
Error analysis scripts collect unresolved cases and group failures into stages
such as candidate retrieval, coverage, concept retrieval, verifier rejection
and gold mismatch.
```

这能体现项目不是只做 demo，而是有调试闭环。

---

## 22. 文档怎么收敛

你现在有两类文档：

### 第一类：给自己理解项目用

比如：

```text
项目梳理/交付版整理/00-12
```

这类文档很长，很适合你学习和面试准备。

但不一定全部放进 GitHub 主 README。

### 第二类：给外部读者快速理解用

应该压缩成：

```text
docs/architecture.md
docs/benchmark.md
docs/limitations.md
```

GitHub 不需要把每个学习章节都摆在首页。

它需要的是：

```text
README 简洁
docs 分层
archive 不干扰
```

---

## 23. 建议 GitHub 交付版 README 模板

下面是一个可以直接改成 README 的骨架：

```markdown
# Medical NLP Abbreviation Expansion and Standardization

## Overview

This project is a clinical NLP pipeline for English medical abbreviation
expansion and medical concept standardization. It expands abbreviations such as
ASA, CP and SOB, then maps expanded terms to SNOMED or RxNorm concepts.

Unlike direct LLM rewriting, the system uses candidate retrieval, coverage
gating, deterministic replacement, source-routed concept retrieval, faithful
verification and benchmark-driven error analysis.

## Example

Input:

```text
The patient took ASA for CP and denies SOB.
```

Output:

```json
{
  "expanded_text": "The patient took aspirin for chest pain and denies shortness of breath.",
  "mappings": [
    {"abbreviation": "ASA", "expansion": "aspirin"},
    {"abbreviation": "CP", "expansion": "chest pain"},
    {"abbreviation": "SOB", "expansion": "shortness of breath"}
  ]
}
```

## Architecture

```text
FastAPI
  -> ABBRService
  -> candidate retrieval
  -> coverage gate
  -> deterministic replacement
  -> SNOMED/RxNorm retrieval
  -> verifier
  -> reflection retry
  -> benchmark/error analysis
```

## Quick Start

```bash
cd backend
pip install -r requirements.txt
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

## API Usage

```bash
curl -X POST "http://127.0.0.1:8000/expand/simple" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"The patient took ASA for CP and denies SOB.\"}"
```

## Project Structure

```text
backend/api          FastAPI routes and schemas
backend/services     Core abbreviation and standardization pipeline
backend/utils        Embedding and LLM configuration
backend/tools        Offline SNOMED/RxNorm data preparation
backend/evaluation   Benchmark and error analysis
backend/graph        LangGraph reference/visualization
```

## Limitations

- Local SNOMED/RxNorm coverage depends on prepared data.
- `success` indicates workflow completion, not full per-entity coding success.
- Large generated CSV files and private `.env` files are not committed.
- Some development scripts are retained as smoke checks and may be reorganized.
```

```

注意：真正写 README 时，上面这个模板里的代码围栏要处理好，别嵌套错。

---

## 24. 交付前必须检查的 10 件事

### 1. `.env` 没有进 Git

命令：

```bash
git status --short
```

确认没有：

```text
backend/.env
```

### 2. 大数据 CSV 没有进 Git

确认没有：

```text
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

### 3. 日志和运行结果没有进 Git

确认没有：

```text
backend/logs/
backend/evaluation/benchmark_results.json
backend/evaluation/error_analysis_report.json
```

### 4. README 能说明项目

别人不看文档，只看 README，也应该知道：

```text
项目是什么
怎么跑
例子是什么
限制是什么
```

### 5. API 能启动

至少本地能跑：

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### 6. 示例请求能返回

至少测试：

```text
The patient took ASA for CP and denies SOB.
```

### 7. benchmark 命令写清楚

不一定保证别人立刻跑通所有数据，但命令和依赖要说明。

### 8. 旧文档不干扰首页

旧文档可以保留，但不要让根目录堆满。

### 9. 施工指令不要放在显眼位置

类似：

```text
批次*_Codex指令.md
```

这种对你有用，但对面试官不是第一阅读材料。

建议归档。

### 10. 项目边界要诚实

README 里明确：

```text
This is a prototype / research-oriented project.
It requires local concept data and API keys.
It is not a production clinical decision system.
```

这不是示弱。

这是专业。

---

## 25. 推荐清理顺序

不要今天就全删。

按这个顺序来：

### 第 1 步：写 README

先让项目有门面。

### 第 2 步：补 `.env.example`

让别人知道需要哪些配置。

### 第 3 步：补 `examples/`

至少放：

```text
examples/sample_request.json
examples/sample_response.json
```

### 第 4 步：补 `docs/`

从交付版整理里提炼：

```text
docs/architecture.md
docs/benchmark.md
docs/limitations.md
```

### 第 5 步：整理测试脚本

把真正能跑的 smoke test 留下。

### 第 6 步：归档旧文档

把 V9、施工指令、旧版模块文档移到 archive。

### 第 7 步：删除确定无用文件

只有当你能说清：

```text
这个文件不在主链路
不在评估链路
不在建库链路
不在文档链路
不需要复现历史
```

再删。

---

## 26. 面试时怎么讲 GitHub 清理

可以这样说：

> 这个项目最初是高频迭代出来的，里面有不少实验代码和 AI 辅助生成的施工材料。为了交付到 GitHub，我做了主链路收敛：把 API、缩写扩写、候选召回、coverage、确定性替换、多源标准化、verifier、benchmark 和 error analysis 作为主项目；把旧版文档、施工指令和运行产物归档或忽略；README 里明确启动方式、示例输入输出和项目边界。

如果面试官问：

> “为什么不直接把所有东西删掉？”

你可以说：

> 因为部分实验脚本和旧文档仍然有复现和解释价值，所以我先做分类归档，确认没有主链路依赖后再删除。这样比一次性清空更稳，也更符合工程维护习惯。

---

## 27. 这一章你要记住的 5 句话

1. GitHub 交付不是全量上传，而是让主链路清楚可见。
2. README 要回答“是什么、怎么跑、例子是什么、限制是什么”。
3. `.env`、日志、大数据、运行结果不要提交。
4. 盲肠先分类归档，再确认删除。
5. 项目边界诚实，比把原型包装成生产系统更专业。

---

## 28. 下一步建议

下一步可以开始做真正的交付文件：

```text
13_README草稿_项目首页怎么写.md
```

或者直接进入代码仓库清理：

```text
补 README.md
补 backend/.env.example
补 examples/sample_request.json
补 examples/sample_response.json
检查 .gitignore
```

如果你现在还没准备动代码，那就先写 `13_README草稿`。

如果你准备进入 GitHub 交付，那下一步就该开始真正改仓库结构了。


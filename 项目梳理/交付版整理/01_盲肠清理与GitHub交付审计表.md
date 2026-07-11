# 01_盲肠清理与 GitHub 交付审计表

> 这份表不是最终删除清单，而是第一轮审计。
> 原则：先分类，再动刀。生产链路、评估链路、实验链路要分开处理。

---

## 当前判断

这个仓库现在主要混在一起的东西有 6 类：

| 类别 | 例子 | GitHub 展示策略 |
|---|---|---|
| 生产主链路 | `backend/api/main.py`、`backend/services/abbr_service.py` | 保留，重点解释 |
| 核心服务模块 | 候选召回、coverage、retriever、verifier、std service | 保留，整理 README |
| 评估系统 | `backend/evaluation/*` | 保留，但要标清用途 |
| 实验/可视化 | `backend/graph/*`、部分 ablation 脚本 | 可保留，标 experimental |
| 本地运行痕迹 | `.env`、logs、cache、pycache | 不上传，必要时删除 |
| 文档和批次指令 | `项目梳理/批次*.md`、旧版文档 | 归档，不放 GitHub 首页显眼处 |

---

## 已发现的代码级“疑似盲肠”

### 1. `ABBRService.__init__` 里的 `self.abbr_dict`

位置：

- `backend/services/abbr_service.py`

现象：

- 初始化了一个小型硬编码缩写词典。
- 当前主链路实际使用的是 `backend/data/abbr_candidates.py` 里的 `ABBR_CANDIDATES`。
- 在当前扫到的主链路中，`self.abbr_dict` 没有参与 `expand_verify_with_retry`。

初步判断：

- 疑似早期原型遗留。
- 可以考虑删除，但删除前要全仓搜索确认没有测试或旧接口引用。

建议动作：

```text
先全仓 rg "abbr_dict"
如果只有定义没有使用，则删除
同时更新对应文档说明
```

---

### 2. `ABBRService.__init__` 里的 `self.llm`

位置：

- `backend/services/abbr_service.py`

现象：

- 初始化了 `ChatDeepSeek`。
- 当前 V11 主扩写链路不是直接用 `self.llm` 生成整句。
- LLM 能力主要下沉到 fallback retriever、verifier、reflection 等子模块。

初步判断：

- 疑似早期“ABBRService 自己调 LLM 扩写”的遗留。
- 如果 `self.llm` 没有被引用，可以删除。
- 删除后 `ABBRService.__init__` 对 `DEEPSEEK_API_KEY` 的强依赖也要重新审视，因为子模块自己可能会加载 LLM 配置。

风险：

- 直接删 `api_key` 检查可能改变启动失败时机。
- 要先确认所有子模块的 LLM 初始化路径。

建议动作：

```text
rg "self.llm|ChatDeepSeek|DEEPSEEK_API_KEY" backend
确认 ABBRService 是否需要直接持有 llm
再决定是否删除
```

---

### 3. `mapping_support_results = []`

位置：

- `backend/services/abbr_service.py`

现象：

- 主状态机里初始化为空数组。
- 返回结构里多处保留 `mapping_support_results`。
- V11 已经删除/废弃 `MappingSupportVerifier`，但字段仍为了兼容旧响应保留。

初步判断：

- 不是危险代码，但属于响应结构历史包袱。
- 如果前端、评估脚本、旧文档不依赖，可以删字段。
- 如果想保持 API 兼容，可以保留但在 README 中不再强调。

建议动作：

```text
rg "mapping_support_results"
如果只有后端返回和旧文档引用：
  方案 A：保留字段，标 legacy
  方案 B：删除字段，更新评估/文档
```

---

### 4. `backend/services/test.py`

位置：

- `backend/services/test.py`

现象：

- 文件名不像标准 pytest 测试位置。
- 放在 `services` 包里容易让人误以为是业务模块。

初步判断：

- 疑似临时测试脚本。

建议动作：

```text
打开确认内容
如果只是手工测试：
  移到 backend/tests/ 或 backend/dev_scripts/
  或删除
```

---

### 5. `backend/services/笔记.md`

位置：

- `backend/services/笔记.md`

现象：

- 业务代码目录里混入笔记文档。

初步判断：

- 不适合放在 GitHub 展示的生产 services 目录。

建议动作：

```text
移到 项目梳理/归档/
或删除无价值内容
```

---

### 6. `MedicalStandardizer.standardize()` 是否还在主链路

位置：

- `backend/services/medical_standardizer.py`

现象：

- V11 主接口走 `ABBRService.expand_verify_with_retry`。
- `MedicalStandardizer` 仍用于初始化 NER 服务，也可能被测试和旧接口使用。

初步判断：

- 不能简单删除。
- 它可能是旧整句标准化编排，也可能仍提供可复用组件。

建议动作：

```text
先标为 legacy orchestration
保留 NER 相关依赖
如果要删旧 standardize API，必须先看 api/main.py 和 tests
```

---

## 已发现的 GitHub 风险项

### 1. `.env`

位置：

- `backend/.env`

风险：

- 可能包含 API key。
- 绝对不能上传 GitHub。

当前 `.gitignore` 已包含：

```text
.env
.env.*
```

建议动作：

- 确认 `.env` 没有被 git tracked。
- 增加 `backend/.env.example`，只放变量名，不放真实值。

---

### 2. `__pycache__` 和 `.pyc`

风险：

- 本地缓存，不应该上传。
- 当前 `.gitignore` 已包含：

```text
__pycache__/
*.pyc
```

建议动作：

- 如果已被 Git 跟踪，需要从 index 移除。
- 如果只是工作区文件，不必管，但发布前可以本地清理。

---

### 3. 日志目录

位置：

- `backend/logs/`

风险：

- 可能包含真实运行输入、失败样例、LLM 输出。
- 不适合直接上传。

当前 `.gitignore` 已包含：

```text
backend/logs/
```

建议动作：

- 保留一份脱敏样例到 `docs/examples/`。
- 不上传真实日志。

---

### 4. 大型医学 CSV

位置：

- `backend/data/snomed_clinical.csv`
- `backend/data/rxnorm_clinical.csv`

风险：

- 文件较大。
- 可能涉及数据来源和授权说明。

当前 `.gitignore` 已包含：

```text
backend/data/snomed_clinical.csv
backend/data/rxnorm_clinical.csv
```

建议动作：

- README 写清楚需要用户自行准备数据。
- 提供 sample CSV 或构建脚本说明。
- 不把大 CSV 当作普通代码上传。

---

### 5. 批次指令文档过多

位置：

- `项目梳理/批次*.md`
- `项目梳理/批次L3_*.md`

风险：

- 对你自己复盘有价值。
- 但放在 GitHub 主展示区会显得项目过程很乱。

建议动作：

```text
项目梳理/归档/批次指令/
```

或者 GitHub 只保留：

- `docs/architecture.md`
- `docs/interview_notes.md`
- `docs/error_analysis.md`

---

## 暂时不要删的东西

### 1. `backend/graph/*`

原因：

- 虽然它不是 FastAPI 生产入口。
- 但它能展示 LangGraph 实验和流程可视化。
- 对简历亮点有价值。

建议：

- 标注为 experimental。
- 不要混在主链路里讲。

---

### 2. `backend/evaluation/*`

原因：

- 这是证明项目不是只写 demo 的关键。
- 面试时能讲 benchmark、错误分析、消融。

建议：

- 保留。
- 但整理文件说明，区分主 benchmark、并行 benchmark、错误归因、概念匹配。

---

### 3. `backend/tools/*`

原因：

- 离线建库是项目完整性的一部分。
- SNOMED/RxNorm 两个 Milvus collection 的创建逻辑在这里。

建议：

- 保留。
- README 里写成“离线准备步骤”，不要让它和在线 API 主链路混在一起。

---

## 建议的 GitHub 目录形态

目标不是现在立刻搬文件，而是先明确最终长什么样。

```text
medical-nlp/
  backend/
    api/
    services/
    data/
      abbr_candidates.py
      sample_*.csv
    tools/
    evaluation/
    graph/
    utils/
  docs/
    architecture.md
    data_flow.md
    interview_notes.md
    error_analysis.md
  Dockerfile
  docker-compose.yml
  README.md
  .env.example
  .gitignore
```

`项目梳理/` 可以本地保留，但 GitHub 展示版不一定要全部放上去。

---

## 清理顺序

### 第 1 步：只做审计，不删

命令思路：

```powershell
git status --short
rg "abbr_dict|self.llm|mapping_support_results|MappingSupportVerifier" backend
rg --files backend | sort
```

产出：

- keep
- delete
- move
- legacy
- experimental

### 第 2 步：清本地缓存和敏感文件

只处理：

- pycache
- pyc
- logs
- `.env`

注意：

- 如果这些没有被 Git 跟踪，只需要确保 `.gitignore` 正确。
- 如果已被跟踪，需要用 `git rm --cached`，不是简单删除本地文件。

### 第 3 步：清代码盲肠

优先级：

1. 删除确认无引用的 `self.abbr_dict`。
2. 删除确认无引用的 `self.llm`。
3. 决定 `mapping_support_results` 是 legacy 保留还是彻底移除。
4. 移走 `services/test.py` 和 `services/笔记.md`。

### 第 4 步：整理 GitHub 展示文档

只保留读者需要的：

- README
- 架构图
- 样例输入输出
- 运行方式
- 评估结果
- 局限性

---

## 下一步建议

下一步不要继续新增 23、24、25 章。

建议直接进入：

```text
02_主链路样例跟踪_ASA_CP_SOB.md
```

这份文档只做一件事：

把 `The patient took ASA for CP and denies SOB.` 这句话从 FastAPI 入口一路跟到最终返回 JSON，中间每一步展示真实字段怎么变。

这会比继续读模块文档有效得多。


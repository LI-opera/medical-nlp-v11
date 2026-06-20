# Codex 对项目的改动日志

## 2026-06-20 · V11 批次 1：确定性缩写扩写

### 改动目的

- 将稳定主链路的缩写扩写从“LLM 重写整句”改为“coverage 选择唯一候选 + token 边界确定性替换”。
- 避免扩写阶段改写否定、增加信息或误伤缩写子串。
- 本批不修改 verifier、reflection、SNOMED 检索、Milvus/embedding 配置及 attempts 留痕结构。

### 涉及文件

- `backend/services/abbr_candidate_coverage_evaluator.py`
  - coverage 输出新增 `best_expansion`，要求值必须逐字来自候选集合。
  - LLM 漏返回字段时以 `None` 容错。
- `backend/services/abbr_service.py`
  - 新增 `_build_expanded_text_deterministic()`，按 `\b` token 边界从后向前替换。
  - `_get_abbreviation_candidates()` 对所有分支补齐 `best_expansion`、`chosen_label`、`chosen_domain`。
  - `expand_verify_with_retry()` 主链路不再调用 `simple_llm_expansion()`，改为使用唯一候选确定性构建文本。
  - 按要求保留旧 `simple_llm_expansion()` 及 MappingSupportVerifier 实验代码。
- `backend/test_v11_deterministic.py`
  - 新增否定保留、CP 不误命中 CPR、多缩写替换无 offset 错位三个测试。

### 验证结果

- `.venv\Scripts\python.exe backend\test_v11_deterministic.py`：通过，输出 `OK`。
- `python -m compileall`（三个本批文件）：通过。
- `git diff --check`：通过。
- 完整 Benchmark：`47/50`，accuracy `0.9400`；V9 基线为 `46/50`，accuracy `0.9200`。
- 分类：single_meaning `10/10`、ambiguous `10/10`、multi_abbreviation `10/10`、coverage_failed `5/5`、low_context_abbreviation `2/5`、negation_preservation `10/10`。
- 必须守住的四个满分类均未下降；ambiguous 由 `9/10` 提升为 `10/10`，满足合入标准。
- 仍失败：LMN、QRS、NOP 三个低上下文过度扩写案例，留待后续批次的 NER/domain 约束处理。

### 环境与追溯说明

- 系统 Python 缺少 `pymilvus`，测试与 Benchmark 使用项目 `.venv`。
- 沙箱内首次 Benchmark 被 Hugging Face 网络访问限制拦截；获准在非沙箱环境重跑后成功。
- `backend/evaluation/benchmark_results.json` 是 Benchmark 运行产物，运行前工作区已处于修改状态，本批提交不主动纳入该文件。
- 回退方式：对本批提交执行 `git revert`；不要使用 `git reset --hard`，以免覆盖工作区原有文件。

## 2026-06-20 · V11 批次 2：Per-mapping 状态机与失败隔离

### 改动目的

- 将 `expand_verify_with_retry()` 的工作单位从整句降为单个 mapping。
- 引入 `PENDING → LOCKED_OK / LOCKED_ABSTAIN` 状态流，避免一个缩写失败时重算或改写已通过的缩写。
- 将反思修正改为从固定候选池选择下一个未尝试候选，不再由旧 Reflection LLM 整句重写。
- 对已锁定 mapping 复用标准化缓存，仅在 expansion 变化时重新检索。

### 涉及文件

- `backend/services/abbr_service.py`
  - 仅重写 `expand_verify_with_retry()` 方法体。
  - 为每个 mapping 建立候选池、已尝试集合、状态、`std_cache` 与 `changed` 标记。
  - 每轮只检索和验证 `PENDING` mapping；`LOCKED_OK` 冻结，候选耗尽则 `LOCKED_ABSTAIN`。
  - 最终输出仅保留 `LOCKED_OK` mappings；弃权项在文本中恢复为原缩写。
  - 保留 attempts 每轮留痕，并在终态增加 `mapping_states`。
- 按批次铁律，未修改该文件其他方法，也未修改 verifier、旧 reflect、检索实现及环境配置。

### 验证结果

- `.venv\Scripts\python.exe -m compileall -q backend\services\abbr_service.py`：通过。
- `.venv\Scripts\python.exe backend\test_v11_deterministic.py`：通过，输出 `OK`。
- `git diff --check`：通过。
- 本地 mock 失败隔离验证：通过，输出 `FAILURE_ISOLATION_OK`。
  - CP 第一轮通过后只检索一次，第二轮不再进入 pending。
  - MS 从 `multiple sclerosis` 切换到 `mitral stenosis`，两次 expansion 各检索一次。
  - 总检索序列：`chest pain`、`multiple sclerosis`、`mitral stenosis`，无锁定项重复检索。
- 完整 Benchmark：`47/50`，accuracy `0.9400`，与批次1持平并达到合入门槛。
- 分类：single_meaning `10/10`、ambiguous `10/10`、multi_abbreviation `10/10`、coverage_failed `5/5`、low_context_abbreviation `2/5`、negation_preservation `10/10`。
- 五个不得下降的分类均保持满分，未观察到新增 over-abstention 回归。
- LMN、QRS、NOP 三个低上下文过度扩写仍存在：当前 verifier 接受了这些 mapping，因此状态机未触发弃权，需后续批次增强候选质量或约束。

### 环境与追溯说明

- Benchmark 使用项目 `.venv` 并在获准的网络环境中访问 Hugging Face、DeepSeek 与本机 Milvus。
- `backend/evaluation/benchmark_results.json` 为本轮 Benchmark 生成产物，不纳入本批代码提交。
- 回退方式：对本批提交执行 `git revert`；批次1提交 `1871873` 保持不动。

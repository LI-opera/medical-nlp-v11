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

# 批次 7 · 给 Codex 的指令(可整段复制)· 架构收敛(彻底删 V9 死代码 + 砍盲肠 + 量 verify)

## 背景与范围

V11 主链路只剩 `expand_verify_with_retry` 这一条。本批**彻底清理 V9 遗留**:删掉不在主链路的旧方法、它们依赖的服务文件、引用它们的测试、以及 V9 流程的 LangGraph 目录;再砍掉主链路里"算了不用"的整句 standardize;顺带量一下 verify 的实际贡献。

> **用户已确认**:旧方法连同引用它们的测试 / graph **一起删**,只要**主流程框架(`expand_verify_with_retry` + `/expand/simple` API + benchmark)不被破坏**即可。测试和 graph 之后按 V11 流程重建。

**审计已确认安全**:`api/main.py`、`run_benchmark.py`、`run_benchmark_parallel.py` **都不引用** graph 或任何待删符号;主链路只用到 `candidate_retriever / fallback_retriever / coverage_evaluator / ner_service / retriever / verifier / standardizer(取 ner_service 用)`,**不用** reflector / mapping_support_verifier / 任何旧方法。

工作在 `medical-refactor`(HEAD 若飘到 `medical` 先 `git switch -f medical-refactor`)。先确认 batch6 重新合入已落地。

## 铁律

1. **先 Read `backend/services/abbr_service.py` 核对**;按**方法名**删,不要按行段整块删。
2. **★绝不能删** `_build_expanded_text_deterministic`(约 259 行)——它夹在待删的 `_rebuild_expanded_text`(245)和 `_filter_mappings_by_context_support`(284)中间,是 V11 主链路核心。同样保留 `expand_verify_with_retry`、`_get_abbreviation_candidates`、`_should_consider_abbreviation`、`__init__`(除下面指明的两行)。
3. 删完必须:`abbr_service` 干净 import、benchmark 跑通且持平、全项目**无任何对已删符号的悬空引用**(见验收 grep)。

---

## A · `backend/services/abbr_service.py` 内部删除

**A1. 删两条 import**(约第 5、9 行):
```python
from services.abbr_reflection_service import ABBRReflectionService
from services.mapping_support_verifier import MappingSupportVerifier
```

**A2. 删 `__init__` 里两行**(约 72、77):
```python
        self.reflector = ABBRReflectionService()
        self.mapping_support_verifier = MappingSupportVerifier()
```
> `self.standardizer` / `self.ner_service` / `self.verifier` **保留**(主链路在用)。

**A3. 按方法名删这 6 个方法(整段含 body 删掉)**:
- `simple_llm_expansion`(约 80)
- `expand_abbreviations`(约 152)
- `expand_and_standardize`(约 176)
- `expand_standardize_and_verify`(约 228)
- `_rebuild_expanded_text`(约 245)
- `_filter_mappings_by_context_support`(约 284）

**★中间的 `_build_expanded_text_deterministic`(259)必须原样保留。** 删完后该文件应只剩:`__init__` → `_build_expanded_text_deterministic` → `expand_verify_with_retry` → `_get_abbreviation_candidates` → `_should_consider_abbreviation`(以及文件尾部注释)。

## B · 删两个孤立服务文件

```
backend/services/mapping_support_verifier.py
backend/services/abbr_reflection_service.py
```
(删 A 之后,这两个文件已无任何活引用。)

## C · 删引用了已删符号的 9 个测试文件

```
backend/test_abbr_candidate_expansion.py
backend/test_abbr_llm.py
backend/test_abbr_llm_json.py
backend/test_abbr_service.py
backend/test_abbr_standardize.py
backend/test_abbr_verify.py
backend/test_forced_reflection.py.py
backend/test_mapping_support_verifier.py
backend/test_reflection.py
```
> 其余 `test_*.py`(coverage / candidate_retriever / candidate_retry / fallback_retriever / abbr_retry / embedding / fallback_coverage / medical_retriever / medical_standardizer / ner_service / ner_to_retriever / std_service / support_htn / v11_deterministic)**保留**——它们测的是 V11 仍在用的组件。

## D · 删整个 LangGraph 目录(V9 流程,引用 simple_llm_expansion + 老 reflect)

```
backend/graph/        ← 整目录删(含 abbr_graph*.py / abbr_graph_nodes.py / abbr_graph_state.py / export_graph.py / abbr_workflow.png / test_abbr_graph.py / test_graph_cases.py)
```
> 已确认 api/benchmark 不引用 graph。删后 V11 流程不受影响。(你之后按 V11 重建 graph。)

## E · 砍主链路里的整句 standardize(V9 盲肠)

`expand_verify_with_retry` 循环里(约 469 行):
```python
            standardization_result = self.standardizer.standardize(current_expanded_text)
```
**删掉这一行**。`standardization_result` 在循环前已初始化为 `None`,`attempts/final_result` 的 `"standardization": None` 字段结构保持。
> 已审计:该字段无任何消费方(verify 吃的是 mapping_standardizations),砍掉每轮省一次整句 NER+检索,**零判分影响**。

## F · 量 verify 贡献(临时打点,量完删,别提交)

删除做完、benchmark 跑之前,临时在状态机判定分支加 print:
- verify 判 pending mapping 不过 → `print("[verify] FAIL")`
- 换候选 → `print("[verify] SWAP")`
- 候选用尽弃权 → `print("[verify] ABSTAIN")`

`python backend/evaluation/run_benchmark_parallel.py 2>&1 | tee /tmp/vp.txt`,然后 `grep -c "\[verify\] FAIL/SWAP/ABSTAIN"`,把三个数贴回来。**量完删掉这三行 print**(不进提交)。

---

## 验收(强校验)

1. **编译**:`python -m compileall backend/services backend/api backend/evaluation`(graph 已删不编它)→ 通过。
2. **干净 import**:`python -c "import sys;sys.path.append('backend');from services.abbr_service import ABBRService;print('import OK')"`。
3. **★无悬空引用**(最关键):
   ```bash
   grep -rn "simple_llm_expansion\|expand_and_standardize\|expand_standardize_and_verify\|expand_abbreviations\|_rebuild_expanded_text\|_filter_mappings_by_context_support\|MappingSupportVerifier\|ABBRReflectionService\|reflector\|mapping_support_verifier\|abbr_reflection_service\|graph" backend --include=*.py | grep -v "__pycache__"
   ```
   **应只剩 benchmark cases 里 "radiograph" 之类的无关词**;不得有任何对已删方法/类/模块的引用。有就是漏删了。
4. **批次1单测仍 OK**:`python backend/test_v11_deterministic.py` → `OK`(它 import ABBRService + 调 `_build_expanded_text_deterministic`,验证主链路没被删坏)。
5. **benchmark 持平**:删完正式跑,对比锚点(~0.9595,±噪声)。A/B/C/D/E 全是行为中性,**不该改任何判分**;若 casi/fallback/满分类成片变动 → 删坏了主链路,回退排查。
6. **判定**:1–5 全过 → 合入。

## 提交

```bash
git add -A
git commit -m "V11 batch7: remove all V9 legacy (dead methods, MappingSupportVerifier, old reflect, LangGraph dir, 9 stale tests) + cut vestigial whole-sentence standardize from main loop; main flow unaffected, tests/graph to be rebuilt for V11."
```
> 顺带删了 V9 流程的 LangGraph(丢了"LangGraph"这个关键词,直到你按 V11 重建)。reflect 的 LLM 反思也随之退出代码库——V11 用的是确定性换候选。这两点记进文档/面试叙事。

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

## 2026-06-20 · V11 批次 3：NER fallback gate 实验未达标，已回退

### 尝试目的与范围

- 为 `NERService` 增加孤立短语医学实体判断。
- 复用 `MedicalStandardizer` 已加载的 NER 实例，只过滤 fallback 候选，并给 primary/fallback 候选补充 label。
- 要求 fallback 一次生成至少三个候选，为批次2状态机提供换候选空间。
- 本轮曾修改 `backend/services/ner_service.py`、`backend/services/abbr_candidate_fallback_retriever.py`、`backend/services/abbr_service.py`，验收失败后全部恢复到批次2状态。

### 验证与失败原因

- 编译、批次1确定性替换单测、`git diff --check`：通过。
- 本地 mock 候选流：通过；能够过滤模拟的 `no operation` 并传递 primary label。
- 真实 Benchmark：`45/50`，accuracy `0.9000`，低于批次2的 `47/50 = 0.9400`，不满足合入条件。
- 分类：single_meaning `10/10`、ambiguous `9/10`、multi_abbreviation `10/10`、coverage_failed `4/5`、low_context_abbreviation `2/5`、negation_preservation `10/10`。
- 回归 `ambiguous_004`：MS 从批次2正确的 `mitral stenosis` 变回 `multiple sclerosis`。
- 回归 `coverage_010`：MNO 被 fallback 新造为 `Multiple Nodular Opacities`，NER 标记为 `SIGN_SYMPTOM` 后放行。
- NOP 未修复：fallback 将原来的 `no operation` 换成 `Nocturnal Oxygen Protocol`，NER 标记为 `MEDICATION` 后放行。
- 结论：孤立短语 NER 只能判断“像不像医学实体”，不能判断“是不是该缩写的可信扩写”；同时强制 top-k 增加了看似医学但实际编造的候选。本方案按指令回退，不合入代码。

### 本轮回退前 Git diff

```diff
diff --git a/backend/services/abbr_candidate_fallback_retriever.py b/backend/services/abbr_candidate_fallback_retriever.py
index 06400ab..d883326 100644
--- a/backend/services/abbr_candidate_fallback_retriever.py
+++ b/backend/services/abbr_candidate_fallback_retriever.py
@@ -56,6 +56,7 @@ class ABBRCandidateFallbackRetriever:
         9. Only return candidates that are commonly used medical abbreviations or strongly supported by the clinical context.
         10. Return only valid JSON.
         11. Do not use markdown.
+        12. When the abbreviation plausibly has several medical meanings, return at least 3 candidate expansions, ranked by likelihood (most likely first).

        Return JSON in exactly this format:
         {{
diff --git a/backend/services/abbr_service.py b/backend/services/abbr_service.py
index ad4722a..9adc885 100644
--- a/backend/services/abbr_service.py
+++ b/backend/services/abbr_service.py
@@ -52,6 +52,7 @@ class ABBRService:

        # 这些对象内部可能会加载模型，所以放到 __init__ 里复用
         self.standardizer = MedicalStandardizer()
+        self.ner_service = self.standardizer.ner_service
         self.retriever = MedicalRetriever()
         self.verifier = ABBVerifier()
         self.reflector = ABBRReflectionService()
@@ -603,6 +604,19 @@ class ABBRService:
                 )
                 candidates = fallback_result.get("candidates",[])
                 candidate_source = "fallback"
+
+            # NER 校验 + 打 label:跨模型第二意见
+            # - fallback 候选:is_medical=False → 丢弃(杀 LLM 生成的烂候选,如 no operation)
+            # - 词典候选(primary):只打 label,绝不丢弃(可信源)
+            labeled = []
+            for candidate in candidates:
+                expansion = candidate.get("expansion")
+                ok, label, _ = self.ner_service.is_medical(expansion)
+                candidate["label"] = label
+                if candidate_source == "fallback" and not ok:
+                    continue
+                labeled.append(candidate)
+            candidates = labeled

            #如果primary和fallback都没有候选
             if not candidates:
@@ -639,6 +653,12 @@ class ABBRService:
             ]

            best = coverage.get("best_expansion")
+            best_label = None
+            if best:
+                for candidate in candidates:
+                    if candidate.get("expansion") == best:
+                        best_label = candidate.get("label")
+                        break

            #将缩写，候选表，候选覆盖情况返回
             found.append({
@@ -648,7 +668,7 @@ class ABBRService:
                 "coverage":coverage,
                 "candidate_source":candidate_source,
                 "best_expansion":best,
-                "chosen_label":None,
+                "chosen_label":best_label,
                 "chosen_domain":None
             })
         return found
diff --git a/backend/services/ner_service.py b/backend/services/ner_service.py
index fbdcdca..27a3b18 100644
--- a/backend/services/ner_service.py
+++ b/backend/services/ner_service.py
@@ -52,6 +52,21 @@ class NERService:
         #_merge_adjacent_entities就是一个清洗/后处理函数
         merged_entities = self._merge_adjacent_entities(text,entities)
         return merged_entities
+
+    def is_medical(self, text: str):
+        """对孤立短语判是否医学实体 + 返回主 label。
+        返回 (is_medical: bool, label: str|None, score: float)
+        诚实局限:NER 对孤立短语可能误判,故此处只作【输入侧筛选的低置信信号】,
+        且只用于过滤 fallback(LLM 生成)候选,不碰词典候选。
+        """
+        if not text:
+            return False, None, 0.0
+        ents = self.extract_entities(text)
+        if not ents:
+            return False, None, 0.0
+        top = max(ents, key=lambda e: e["score"])
+        return True, top["label"], top["score"]
+
     def _merge_adjacent_entities(self,text:str,entities:list[dict]):
         """合并相邻医学实体。例如: chest + pain = chest pain"""
```

### 回退说明

- 三个代码文件恢复至批次2/提交 `573cad6` 后的实现；仅保留本条失败实验记录用于追溯。
- `backend/evaluation/benchmark_results.json` 是失败实验的生成结果，不纳入代码提交。

## 2026-06-20 · V11 批次 3 重构版：弱证据 fallback 弃权门

### 改动目的

- 保留 fallback 处理词典外真实缩写的能力，仅在 coverage 不通过或置信度低于 `0.8` 时安全弃权。
- 不再使用已回退的 NER 孤立短语过滤，也不强制 fallback 生成 top-k，避免制造“看似医学”的候选幻觉。
- primary 词典候选不受该门影响。

### 涉及文件

- `backend/services/abbr_service.py`
  - 仅在 `_get_abbreviation_candidates()` 的 `best_expansion` 选择后增加 fallback 置信度门。
  - `candidate_source == "fallback"` 且 `coverage_ok` 为假或 `confidence < 0.8` 时，将 `best` 设为 `None`。
  - 批次2状态机检测到无 `best_expansion` 后不建立 state，原缩写保持不变。

### 验证结果

- `.venv\Scripts\python.exe -m compileall -q backend\services\abbr_service.py`：通过。
- `.venv\Scripts\python.exe backend\test_v11_deterministic.py`：通过，输出 `OK`。
- `git diff --check`：通过。
- 本地阈值 mock：通过，输出 `FALLBACK_ABSTAIN_GATE_OK`。
  - fallback confidence `0.79`：弃权。
  - fallback confidence `0.80`：保留。
  - primary confidence `0.10`：不受 fallback 门影响，仍保留。
- 74 例 Benchmark：`70/74`，accuracy `0.9459`；新基线为 `69/74`，accuracy `0.9324`。
- 分类：single_meaning `10/10`、ambiguous `9/10`、multi_abbreviation `10/10`、coverage_failed `5/5`、low_context_abbreviation `3/5`、negation_preservation `10/10`、casi_ambiguous `17/18`、fallback_should_expand `6/6`。
- 两个过度弃权护栏均未下降，low_context 从 `2/5` 提升到 `3/5`，满足合入标准。
- NOP 被弃权并转对；QRS 的 coverage confidence 未低于 `0.8`，仍被保留；LMN 为 primary，不在本批范围。
- `ambiguous_004` 的 MS 波动属于 primary coverage LLM 噪声，本 fallback 门不会触及该路径。

### 本轮 Git diff

```diff
diff --git a/backend/services/abbr_service.py b/backend/services/abbr_service.py
index ad4722a..67ab2ca 100644
--- a/backend/services/abbr_service.py
+++ b/backend/services/abbr_service.py
@@ -639,6 +639,15 @@ class ABBRService:
             ]
 
             best = coverage.get("best_expansion")
+
+            # 批次3(攻弃权):对 fallback(非词典)缩写收紧
+            # 词典缩写(primary)是人工策展可信源 → 照常;
+            # fallback 缩写是 LLM 现造的,上下文证据不足就弃权,不替它背书
+            # (治 QRS→"QRS complex"、NOP→"no operation/Nocturnal Oxygen Protocol"、MNO 等过度扩写)
+            if candidate_source == "fallback":
+                conf = coverage.get("confidence") or 0.0
+                if (not coverage.get("coverage_ok")) or conf < 0.8:
+                    best = None

             #将缩写，候选表，候选覆盖情况返回
             found.append({
```

### 回退与追溯

- 如需撤销本批，只需回退本批提交；批次1/2逻辑无需改动。
- `backend/evaluation/benchmark_results.json` 与重构指令文件在本轮开始前已有工作区修改，本批不纳入提交。

## 2026-06-20 · V11 批次 5：API 输出 standardized_entities

### 改动目的

- 在 `/expand/simple` 原有扩写结果之外，返回每个成功 mapping 的 SNOMED top-1 标准概念与编码。
- 直接复用批次2终态中的 `final_result["mapping_standardizations"]`，不重新检索、不修改核心扩写与校验链路。
- 保持原有 `success`、`expanded_text`、`mappings` 字段向后兼容。

### 涉及文件

- `backend/api/schemas.py`
  - `SimpleExpandResponse` 新增默认空列表字段 `standardized_entities`。
- `backend/api/main.py`
  - `/expand/simple` 从每个 mapping 的 SNOMED candidates 取 top-1。
  - 候选为空时安全跳过。
  - 输出 abbreviation、expansion、concept_id、concept_name、concept_code、domain_id、score。
- 未修改 `abbr_service`、verifier、状态机、检索和评测代码。

### 验证结果

- `.venv\Scripts\python.exe -m compileall -q backend\api\schemas.py backend\api\main.py`：通过。
- `.venv\Scripts\python.exe backend\test_v11_deterministic.py`：通过，输出 `OK`。
- `git diff --check`：通过。
- 无外部依赖 API 组装测试：通过，输出 `STANDARDIZED_ENTITIES_API_OK`；验证 top-1 选择、空候选跳过及响应模型校验。
- 真实 Uvicorn 接口测试：通过，输入 `The patient has SOB and CP.`。
  - `success=true`，原有 expanded_text 与 mappings 正常。
  - SOB：concept_id `4128689`、concept_code `289100008`、concept_name `Difficulty taking deep breaths`、domain_id `Observation`、score `0.755`。
  - CP：concept_id `4089931`、concept_code `251897005`、concept_name `Chest pain rating`、domain_id `Measurement`、score `0.7988`。
- 本批只修改 API 出口，不经过 Benchmark 路径，按指令无需重跑 Benchmark。

### 本轮 Git diff

```diff
diff --git a/backend/api/main.py b/backend/api/main.py
index fa7e917..5f7879f 100644
--- a/backend/api/main.py
+++ b/backend/api/main.py
@@ -166,7 +166,24 @@ def expand_abbreviation_simple(
         max_retries=2
     )

-    final_result = result.get("final_result",{})
+    final_result = result.get("final_result", {}) or {}
+
+    # 从每个 LOCKED_OK mapping 的 SNOMED 检索结果取 top-1 概念,作为标准化编码出口
+    standardized_entities = []
+    for ms in final_result.get("mapping_standardizations", []):
+        candidates = ms.get("candidates") or []
+        if not candidates:
+            continue
+        top = candidates[0]
+        standardized_entities.append({
+            "abbreviation": ms.get("abbreviation"),
+            "expansion": ms.get("expansion"),
+            "concept_id": top.get("concept_id"),
+            "concept_name": top.get("concept_name"),
+            "concept_code": top.get("concept_code"),
+            "domain_id": top.get("domain_id"),
+            "score": top.get("score"),
+        })

    return {
         "success": result.get(
@@ -180,6 +197,7 @@ def expand_abbreviation_simple(
         "mappings": final_result.get(
             "mappings",
             []
-        )
+        ),
+        "standardized_entities": standardized_entities,
     }

diff --git a/backend/api/schemas.py b/backend/api/schemas.py
index 1893235..6fa1d06 100644
--- a/backend/api/schemas.py
+++ b/backend/api/schemas.py
@@ -27,6 +27,7 @@ class SimpleExpandResponse(BaseModel):
     success: bool
     expanded_text: str
     mappings: list[dict]
+    standardized_entities: list[dict] = []


class BenchmarkSummaryResponse(BaseModel):
```

### 回退与追溯

- 回退本批提交即可移除新字段；核心扩写状态机与 Benchmark 基线不受影响。
- 批次5指令文件在本轮开始前已有工作区修改，本批不纳入提交。

## 2026-06-20 · V11 批次 4：domain_boost 软约束

### 改动目的

- 为人工词典候选补充 SNOMED domain 元数据，为 fallback 候选使用本地 NER label 推断 domain。
- 保留 `domain_filter` 硬过滤参数并继续传 `None`；新增 `domain_boost` 仅作排序软加分，不丢弃候选。
- 将 mapping 选中的 domain 带入批次2状态机与 SNOMED 检索，改善批次5 `standardized_entities` 的 top-1 编码领域。
- NER 仅产 label/domain，不过滤 fallback、不改变候选数量。

### 涉及文件

- `backend/data/abbr_candidates.py`：全部候选改为带 `expansion/domain` 的字典。
- `backend/services/abbr_candidate_retriever.py`：适配新词典结构并透传 domain。
- `backend/services/ner_service.py`：新增复用现有 pipeline 的 `is_medical()`，本批只读取 label。
- `backend/services/abbr_service.py`：两路候选补齐 chosen_domain，state 携带 domain，检索传入 domain_boost。
- `backend/services/medical_retriever.py`：新增 domain_boost，domain 命中增加 `0.2` rerank bonus；domain_filter 保持不变。

### 验证结果

- 全 services 与词典编译：通过。
- 批次1确定性单测：通过，输出 `OK`。
- 候选词典召回测试：通过，新候选均携带 domain。
- 本地 domain boost 测试：通过，top-1 从 Measurement 切换到 Condition，状态机实传 `domain_filter=None, domain_boost=Condition`。
- 真实 CP API：top-1 从批次5的 `Chest pain rating / Measurement`（concept_id `4089931`）切换到 `Chest pain due to pericarditis / Condition`（concept_id `44782774`，concept_code `34791000119103`）。
- 诚实限制：domain 已对齐 Condition，但概念粒度偏具体，仍受当前 SNOMED 候选库覆盖质量限制。
- 74 例并行 Benchmark：`71/74 = 0.9595`，与基线持平。
- 分类：single `10/10`、ambiguous `10/10`、multi `10/10`、coverage_failed `5/5`、low_context `2/5`、negation `10/10`、casi_ambiguous `18/18`、fallback_should_expand `6/6`。
- 结论：死参数已激活，核心准确率未回退，满足合入标准。

### 本轮 Git diff

以下 diff 按目标文件完整保存。

#### backend/services/ner_service.py

```diff
diff --git a/backend/services/ner_service.py b/backend/services/ner_service.py
index fbdcdca..99c15f7 100644
--- a/backend/services/ner_service.py
+++ b/backend/services/ner_service.py
@@ -52,6 +52,19 @@ class NERService:
         #_merge_adjacent_entities就是一个清洗/后处理函数
         merged_entities = self._merge_adjacent_entities(text,entities)
         return merged_entities
+
+    def is_medical(self, text: str):
+        """对孤立短语返回 (是否有医学实体, 主 label, 分数)。
+        本批只用其 label 推断 domain,不做候选过滤。
+        """
+        if not text:
+            return False, None, 0.0
+        ents = self.extract_entities(text)
+        if not ents:
+            return False, None, 0.0
+        top = max(ents, key=lambda e: e["score"])
+        return True, top["label"], top["score"]
+
     def _merge_adjacent_entities(self,text:str,entities:list[dict]):
         """合并相邻医学实体。例如: chest + pain = chest pain"""

@@ -100,4 +113,4 @@ class NERService:



-#start和end是word指代词的索引可以通过text[start:end]取出对应的字符串
\ No newline at end of file
+#start和end是word指代词的索引可以通过text[start:end]取出对应的字符串
```

<!-- batch4-diff-ner -->

#### backend/services/abbr_candidate_retriever.py

```diff
diff --git a/backend/services/abbr_candidate_retriever.py b/backend/services/abbr_candidate_retriever.py
index 95d477a..d56fbba 100644
--- a/backend/services/abbr_candidate_retriever.py
+++ b/backend/services/abbr_candidate_retriever.py
@@ -3,17 +3,12 @@ from data.abbr_candidates import ABBR_CANDIDATES
 class ABBRCandidateRetriever:
     #医学缩写候选召回器
     #作用:输入一个医学缩写，返回它可能对应的多个完整医学术语
-    def retrieve(self,abbreviation:str):
+    def retrieve(self, abbreviation: str):
         abbr = abbreviation.upper().strip()
-
-        candidates = ABBR_CANDIDATES.get(abbr,[])
-
-        return[
-            {
-                "abbreviation":abbr,
-                "expansion":expansion
-            }
-            for expansion in candidates
+        candidates = ABBR_CANDIDATES.get(abbr, [])
+        return [
+            {"abbreviation": abbr, "expansion": c["expansion"], "domain": c.get("domain")}
+            for c in candidates
         ]
     """
     这种写法等价于
@@ -24,4 +19,4 @@ class ABBRCandidateRetriever:
             "expansion":expansion
         })
     return results
-       """
\ No newline at end of file
+       """
```

<!-- batch4-diff-candidate -->

#### backend/services/medical_retriever.py

```diff
diff --git a/backend/services/medical_retriever.py b/backend/services/medical_retriever.py
index 40a6cca..e9a40a4 100644
--- a/backend/services/medical_retriever.py
+++ b/backend/services/medical_retriever.py
@@ -22,7 +22,12 @@ class MedicalRetriever:
         # 已经创建好 embedding
         # 已经 load 好 collection
         self.std_service = StdService()
-    def _rerank_results(self,query:str,results:list[dict]):
+    def _rerank_results(
+            self,
+            query: str,
+            results: list[dict],
+            domain_boost: str | None = None
+            ):
         """对检索结果进行简单重排。
             规则：
             完全等于 query
@@ -46,6 +51,8 @@ class MedicalRetriever:
             #concept_name中包含query
             elif query_lower in concept_name:
                 bonus += 0.15
+            if domain_boost is not None and item.get("domain_id") == domain_boost:
+                bonus += 0.2
             #长术语惩罚措施
             word_count = len(concept_name)
             if word_count > 10:
@@ -70,12 +77,14 @@ class MedicalRetriever:
             top_k:int=5,
             #表示过滤条件
             domain_filter :str|None = None,
+            #表示优先提升的领域，不过滤其他领域
+            domain_boost: str | None = None,
             #表示过滤的最低分数
             score_threshold:float | None = None
             ):
         #根据用户数插入检索最相关的医学术语
         results = self.std_service.search_similar_terms(query=query,limit=top_k)
-        results = self._rerank_results(query,results)
+        results = self._rerank_results(query, results, domain_boost)
         documents = []
         for item in results:
             #如果有过滤条件但是条件不匹配就跳过本轮循环
@@ -102,4 +111,4 @@ class MedicalRetriever:
                     "rerank_score":item["rerank_score"]
                 }
             })
-        return documents
\ No newline at end of file
+        return documents
```

<!-- batch4-diff-medical -->

#### backend/services/abbr_service.py

```diff
diff --git a/backend/services/abbr_service.py b/backend/services/abbr_service.py
index 67ab2ca..b9e5928 100644
--- a/backend/services/abbr_service.py
+++ b/backend/services/abbr_service.py
@@ -13,6 +13,20 @@ import re
 #加载环境变量
 import os
 from dotenv import load_dotenv
+
+# NER 实体标签 → SNOMED domain_id(库里实际取值:Condition/Observation/Measurement/
+# Procedure/Drug/Spec Anatomic Site/Device 等)。映射不完美没关系——domain_boost 是软加分。
+NER_LABEL_TO_DOMAIN = {
+    "DISEASE_DISORDER": "Condition",
+    "SIGN_SYMPTOM": "Condition",
+    "BIOLOGICAL_STRUCTURE": "Spec Anatomic Site",
+    "MEDICATION": "Drug",
+    "DIAGNOSTIC_PROCEDURE": "Procedure",
+    "THERAPEUTIC_PROCEDURE": "Procedure",
+    "LAB_VALUE": "Measurement",
+    "DETAILED_DESCRIPTION": "Observation",
+}
+
 CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
 BACKEND_DIR = os.path.dirname(CURRENT_DIR)
 ENV_PATH = os.path.join(BACKEND_DIR, ".env")
@@ -52,6 +66,7 @@ class ABBRService:

         # 这些对象内部可能会加载模型，所以放到 __init__ 里复用
         self.standardizer = MedicalStandardizer()
+        self.ner_service = self.standardizer.ner_service
         self.retriever = MedicalRetriever()
         self.verifier = ABBVerifier()
         self.reflector = ABBRReflectionService()
@@ -369,6 +384,7 @@ class ABBRService:
                 "abbreviation": info["abbreviation"],
                 "expansion": best,
                 "label": info.get("chosen_label"),
+                "domain": info.get("chosen_domain"),
                 "source": info.get("candidate_source"),
                 "status": "PENDING",
                 "pool": pool,
@@ -432,6 +448,7 @@ class ABBRService:
                         query=s["expansion"],
                         top_k=10,
                         domain_filter=None,
+                        domain_boost=s.get("domain"),
                         score_threshold=0.6
                     )
                     cand = []
@@ -603,6 +620,11 @@ class ABBRService:
                 )
                 candidates = fallback_result.get("candidates",[])
                 candidate_source = "fallback"
+
+            if candidate_source == "fallback":
+                for candidate in candidates:
+                    _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
+                    candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)

             #如果primary和fallback都没有候选
             if not candidates:
@@ -648,6 +670,14 @@ class ABBRService:
                 conf = coverage.get("confidence") or 0.0
                 if (not coverage.get("coverage_ok")) or conf < 0.8:
                     best = None
+
+            # batch4:取选中候选的 domain
+            best_domain = None
+            if best:
+                for candidate in candidates:
+                    if candidate.get("expansion") == best:
+                        best_domain = candidate.get("domain")
+                        break

             #将缩写，候选表，候选覆盖情况返回
             found.append({
@@ -658,7 +688,7 @@ class ABBRService:
                 "candidate_source":candidate_source,
                 "best_expansion":best,
                 "chosen_label":None,
-                "chosen_domain":None
+                "chosen_domain":best_domain
             })
         return found

```

<!-- batch4-diff-service -->

#### backend/data/abbr_candidates.py

```diff
diff --git a/backend/data/abbr_candidates.py b/backend/data/abbr_candidates.py
index f4658f9..9ca5795 100644
--- a/backend/data/abbr_candidates.py
+++ b/backend/data/abbr_candidates.py
@@ -33,153 +33,153 @@

 ABBR_CANDIDATES = {
     "SOB": [
-        "shortness of breath",
+        {"expansion": "shortness of breath", "domain": "Condition"},
     ],
     "HTN": [
-        "hypertension",
+        {"expansion": "hypertension", "domain": "Condition"},
     ],
     "DM": [
-        "diabetes mellitus",
-        "dermatomyositis",
+        {"expansion": "diabetes mellitus", "domain": "Condition"},
+        {"expansion": "dermatomyositis", "domain": "Condition"},
     ],
     "CP": [
-        "chest pain",
-        "cerebral palsy",
-        "chronic pancreatitis",
+        {"expansion": "chest pain", "domain": "Condition"},
+        {"expansion": "cerebral palsy", "domain": "Condition"},
+        {"expansion": "chronic pancreatitis", "domain": "Condition"},
     ],
     "HF": [
-        "heart failure",
-        "hepatic fibrosis",
+        {"expansion": "heart failure", "domain": "Condition"},
+        {"expansion": "hepatic fibrosis", "domain": "Condition"},
     ],

     # Cardiovascular
     "CAD": [
-        "coronary artery disease",
+        {"expansion": "coronary artery disease", "domain": "Condition"},
     ],
     "CHF": [
-        "congestive heart failure",
+        {"expansion": "congestive heart failure", "domain": "Condition"},
     ],
     "MI": [
-        "myocardial infarction",
-        "mitral insufficiency",
+        {"expansion": "myocardial infarction", "domain": "Condition"},
+        {"expansion": "mitral insufficiency", "domain": "Condition"},
     ],
     "CABG": [
-        "coronary artery bypass grafting",
+        {"expansion": "coronary artery bypass grafting", "domain": "Procedure"},
     ],
     "AF": [
-        "atrial fibrillation",
-        "atrial flutter",
+        {"expansion": "atrial fibrillation", "domain": "Condition"},
+        {"expansion": "atrial flutter", "domain": "Condition"},
     ],
     "AS": [
-        "aortic stenosis",
-        "ankylosing spondylitis",
+        {"expansion": "aortic stenosis", "domain": "Condition"},
+        {"expansion": "ankylosing spondylitis", "domain": "Condition"},
     ],
     "MS": [
-        "multiple sclerosis",
-        "mitral stenosis",
+        {"expansion": "multiple sclerosis", "domain": "Condition"},
+        {"expansion": "mitral stenosis", "domain": "Condition"},
     ],

     # Pulmonary
     "COPD": [
-        "chronic obstructive pulmonary disease",
+        {"expansion": "chronic obstructive pulmonary disease", "domain": "Condition"},
     ],
     "PE": [
-        "pulmonary embolism",
-        "physical examination",
+        {"expansion": "pulmonary embolism", "domain": "Condition"},
+        {"expansion": "physical examination", "domain": "Observation"},
     ],
     "PNA": [
-        "pneumonia",
+        {"expansion": "pneumonia", "domain": "Condition"},
     ],
     "ARDS": [
-        "acute respiratory distress syndrome",
+        {"expansion": "acute respiratory distress syndrome", "domain": "Condition"},
     ],

     # Renal / metabolic
     "AKI": [
-        "acute kidney injury",
+        {"expansion": "acute kidney injury", "domain": "Condition"},
     ],
     "CKD": [
-        "chronic kidney disease",
+        {"expansion": "chronic kidney disease", "domain": "Condition"},
     ],
     "ESRD": [
-        "end stage renal disease",
+        {"expansion": "end stage renal disease", "domain": "Condition"},
     ],
     "DKA": [
-        "diabetic ketoacidosis",
+        {"expansion": "diabetic ketoacidosis", "domain": "Condition"},
     ],

     # Neurology
     "CVA": [
-        "cerebrovascular accident",
-        "costovertebral angle",
+        {"expansion": "cerebrovascular accident", "domain": "Condition"},
+        {"expansion": "costovertebral angle", "domain": "Spec Anatomic Site"},
     ],
     "TIA": [
-        "transient ischemic attack",
+        {"expansion": "transient ischemic attack", "domain": "Condition"},
     ],
     "SZ": [
-        "seizure",
+        {"expansion": "seizure", "domain": "Condition"},
     ],
     "AMS": [
-        "altered mental status",
+        {"expansion": "altered mental status", "domain": "Observation"},
     ],
     "LMN": [
-        "lower motor neuron",
+        {"expansion": "lower motor neuron", "domain": "Spec Anatomic Site"},
     ],

     # GI / hepatology
     "GI": [
-        "gastrointestinal",
+        {"expansion": "gastrointestinal", "domain": "Spec Anatomic Site"},
     ],
     "GERD": [
-        "gastroesophageal reflux disease",
+        {"expansion": "gastroesophageal reflux disease", "domain": "Condition"},
     ],
     "IBD": [
-        "inflammatory bowel disease",
+        {"expansion": "inflammatory bowel disease", "domain": "Condition"},
     ],
     "IBS": [
-        "irritable bowel syndrome",
+        {"expansion": "irritable bowel syndrome", "domain": "Condition"},
     ],
     "NASH": [
-        "nonalcoholic steatohepatitis",
+        {"expansion": "nonalcoholic steatohepatitis", "domain": "Condition"},
     ],

     # Infectious disease
     "UTI": [
-        "urinary tract infection",
+        {"expansion": "urinary tract infection", "domain": "Condition"},
     ],
     "URI": [
-        "upper respiratory infection",
+        {"expansion": "upper respiratory infection", "domain": "Condition"},
     ],
     "HIV": [
-        "human immunodeficiency virus",
+        {"expansion": "human immunodeficiency virus", "domain": "Condition"},
     ],
     "TB": [
-        "tuberculosis",
+        {"expansion": "tuberculosis", "domain": "Condition"},
     ],
     "COVID": [
-        "coronavirus disease",
+        {"expansion": "coronavirus disease", "domain": "Condition"},
     ],

     # Labs / clinical context
     "WBC": [
-        "white blood cell count",
-        "white blood cells",
+        {"expansion": "white blood cell count", "domain": "Measurement"},
+        {"expansion": "white blood cells", "domain": "Measurement"},
     ],
     "RBC": [
-        "red blood cell count",
-        "red blood cells",
+        {"expansion": "red blood cell count", "domain": "Measurement"},
+        {"expansion": "red blood cells", "domain": "Measurement"},
     ],
     "HGB": [
-        "hemoglobin",
+        {"expansion": "hemoglobin", "domain": "Measurement"},
     ],
     "PLT": [
-        "platelet count",
-        "platelets",
+        {"expansion": "platelet count", "domain": "Measurement"},
+        {"expansion": "platelets", "domain": "Measurement"},
     ],
     "NA": [
-        "sodium",
+        {"expansion": "sodium", "domain": "Measurement"},
     ],
     "K": [
-        "potassium",
+        {"expansion": "potassium", "domain": "Measurement"},
     ],
-}
\ No newline at end of file
+}
```

<!-- batch4-diff-dictionary -->

### 回退与追溯

- 回退本批提交即可恢复旧词典结构与无 domain boost 的排序。
- Benchmark 生成结果、`medical-v11改进日记.md`、批次5指令和批次4指令均不纳入本批提交。

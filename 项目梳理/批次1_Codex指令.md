# 批次 1 · 给 Codex 的指令(可整段复制)

---

## 背景(给你 Codex 的上下文)

项目是「医学缩写扩写 + SNOMED 标准化」服务,当前是 V9:扩写阶段用 LLM **造句**把缩写扩成全称,这会引入「丢否定 / 幻觉」。本批次(V11 批次 1)要把扩写改成**确定性**:让 coverage 选出唯一最佳扩写 → 用 token 边界正则做替换,**移除扩写阶段的 LLM 调用**。这一批**不动** verify / reflect / 检索逻辑。

工作在分支 `medical-refactor`,基线已 tag 为 `medical-before-refactor`。

## 铁律(必须遵守)

1. **先 Read 现状再改**:下面给的行号是 2026-06-20 快照,可能漂移,动手前先 Read 对应文件核对。
2. **不要删除**:`simple_llm_expansion`(保留供老接口)、`_rebuild_expanded_text`、`_filter_mappings_by_context_support`、`MappingSupportVerifier` 及其注释段——都是有意保留的实验分支/老接口。
3. **不要动**:`verify` / `reflect` 逻辑、检索调用、Milvus/embedding 配置、`.env`、`attempts` 留痕结构。
4. 改完只做本批 4 个改动 + 1 个单测文件,不顺手改别的。

---

## 改动 1 — `backend/services/abbr_candidate_coverage_evaluator.py · evaluate()`

让 coverage 直接选出**唯一最佳** expansion。

- 在 prompt 的 `Rules` 列表末尾**追加**三条:
  ```
  8. From the plausible candidates, choose the SINGLE expansion that best fits the clinical context, and put its exact string into "best_expansion".
  9. If coverage_ok is false, set "best_expansion" to null.
  10. "best_expansion" must be copied verbatim from the candidate list; do not invent or reword it.
  ```
- 在返回 JSON 模板里**加一行字段**(放在 `"plausible_candidates"` 之后即可):
  ```
  "best_expansion": "single best candidate or null",
  ```
- **保留** `plausible_candidates` 字段(向后兼容)。
- 解析返回处,加一行容错,防 LLM 漏字段:`parsed.setdefault("best_expansion", None)`,然后再 `return parsed`。

## 改动 2 — `backend/services/abbr_service.py · _get_abbreviation_candidates()`

为每个缩写带出唯一选择 + label/domain 占位字段。

- 在「有候选、走完 coverage」那条 `found.append({...})` 里,新增三个字段:
  ```python
  best = coverage.get("best_expansion")
  found.append({
      "abbreviation": abbr,
      "candidates": candidates,
      "filtered_candidates": filtered_candidates,
      "coverage": coverage,
      "candidate_source": candidate_source,
      "best_expansion": best,      # 新增:唯一选择(可能 None)
      "chosen_label": None,        # 占位,批次3填
      "chosen_domain": None,       # 占位,批次4用
  })
  ```
- 「无候选」那条 `found.append({...})`(primary 和 fallback 都空的分支)也补上同样三个字段:`"best_expansion": None, "chosen_label": None, "chosen_domain": None`,保持字段一致。

## 改动 3 — `backend/services/abbr_service.py` 新增确定性替换方法

放在 `_rebuild_expanded_text` 方法**下方**(不要删 `_rebuild_expanded_text`)。文件顶部已 `import json`,**补一行 `import re`**。

```python
def _build_expanded_text_deterministic(self, text: str, chosen: list[dict]) -> str:
    """确定性扩写:对每个 {abbreviation -> expansion} 按 token 边界替换。
    - \\b...\\b 保证不误伤子串(CP 不命中 CPR)
    - 从后往前替,避免多次替换的 offset 错位
    - 只替换 chosen 里有 expansion 的项;否定/其它词原样保留
    """
    if not chosen:
        return text

    spans = []
    for item in chosen:
        abbr = item.get("abbreviation")
        expansion = item.get("expansion")
        if not abbr or not expansion:
            continue
        pattern = re.compile(rf"\b{re.escape(abbr)}\b")
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end(), expansion))

    spans.sort(key=lambda s: s[0], reverse=True)
    result = text
    for start, end, expansion in spans:
        result = result[:start] + expansion + result[end:]
    return result
```

> 大小写:`abbr` 在 gate 里已 `.upper()`,gate 也只放行已知缩写或全大写 token,所以原句里缩写通常是大写。默认**大小写敏感**(只替大写 `CP`,不碰小写词),**先不要加 `re.IGNORECASE`**。

## 改动 4 — `backend/services/abbr_service.py · expand_verify_with_retry()`

把第 1 步的「LLM 造句扩写」换成「选唯一 → 确定性替换」。

- 找到函数开头取 `current_expansion_result = self.simple_llm_expansion(text)` 那一段(到取出 `current_expanded_text / current_mappings / current_abbreviation_candidates`),**整段替换为**:
  ```python
  candidate_infos = self._get_abbreviation_candidates(text)

  chosen = []
  for info in candidate_infos:
      best = info.get("best_expansion")
      if not best:                      # coverage 选不出 → 该缩写不进 mappings
          continue
      chosen.append({
          "abbreviation": info["abbreviation"],
          "expansion": best,
          "label": info.get("chosen_label"),
          "source": info.get("candidate_source"),
      })

  current_expanded_text = self._build_expanded_text_deterministic(text, chosen)
  current_mappings = [
      {"abbreviation": c["abbreviation"], "expansion": c["expansion"],
       "label": c["label"], "source": c["source"]}
      for c in chosen
  ]
  current_abbreviation_candidates = candidate_infos
  ```
- **早停哨兵改判**:把循环里 `valid_mappings = [m for m in current_mappings if m.get("expansion")]` 改为 `valid_mappings = current_mappings`(重构后凡进 mappings 的都带 expansion);把 `if not valid_mappings:` 改为 `if not current_mappings:`。早停分支内部逻辑、`stop_reason="coverage_failed_no_valid_expansion"` 措辞**不变**。
- 循环体其余部分(标准化、检索 `domain_filter=None`、`verify_mappings`、`reflect`)**本批一律不动**。
- 主链路不再调用 `simple_llm_expansion`;该方法保留不删。

---

## 新建单测 — `backend/test_v11_deterministic.py`

只测 `_build_expanded_text_deterministic`(纯函数,不连 Milvus/LLM),验证替换正确:

```python
import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__)))
from services.abbr_service import ABBRService

def _build(text, chosen):
    # 只调纯方法,不触发 __init__ 里的模型加载
    return ABBRService._build_expanded_text_deterministic(None, text, chosen)

def test_negation_preserved():
    out = _build("Patient denies CP", [{"abbreviation": "CP", "expansion": "chest pain"}])
    assert out == "Patient denies chest pain"

def test_no_substring_hit():
    # CP 不应命中 CPR
    out = _build("CPR was performed", [{"abbreviation": "CP", "expansion": "chest pain"}])
    assert out == "CPR was performed"

def test_multi_abbr_no_offset_error():
    out = _build("Patient has CP and MS",
                 [{"abbreviation": "CP", "expansion": "chest pain"},
                  {"abbreviation": "MS", "expansion": "mitral stenosis"}])
    assert out == "Patient has chest pain and mitral stenosis"

if __name__ == "__main__":
    test_negation_preserved(); test_no_substring_hit(); test_multi_abbr_no_offset_error()
    print("OK")
```
跑 `python backend/test_v11_deterministic.py`,应打印 `OK`。

---

## 验收(改完做这些)

1. **单测过**:`python backend/test_v11_deterministic.py` → `OK`。
2. **benchmark**:`python backend/evaluation/run_benchmark.py`,和 V9 基线逐类对比。
   - **必须守住的满分类**:single_meaning(10/10)、multi_abbreviation(10/10)、negation_preservation(10/10)、coverage_failed(5/5)——**任何一类掉都要警觉**。
   - 总体 **net accuracy ≥ 0.9200**(基线)。
   - low_context(基线 2/5)能升最好;持平可接受;掉了要查为什么。
3. **判定**:net ≥ 基线且满分类没掉 → 合入;否则 `git revert`,把原因记下来。

> 诚实预期:批次 1 主要消除「丢否定/幻觉」的根源、让扩写确定化。基线那 3 个 low_context 过度扩写(LMN/QRS/NOP)里,**QRS/NOP 这类 fallback 烂候选的彻底清除要等批次 3(NER 校验)**;批次 1 能改善的是「coverage 选不出就不扩」的那部分。所以批次 1 的目标是 **net 不退** + 满分类全守住,不是一步治好 low_context。

## 提交

```bash
git add -A
git commit -m "V11 batch1: coverage best_expansion + deterministic token-boundary replace"
```

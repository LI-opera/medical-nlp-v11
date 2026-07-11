# 批次 8 · 给 Codex 的指令(可整段复制)· 把 verify 改造成"标准化卡点"

## 第 0 步 · 先恢复工作树(必做)

batch7 提交干净,但工作树被并发写坏(`abbr_service.py` 含 null 字节)。先:
```bash
git switch -f medical-refactor
git status
python -c "import sys;sys.path.append('backend');from services.abbr_service import ABBRService;print('OK')"
```
打印 `OK` 再继续。**改前先 Read `abbr_service.py` / `abbr_verifier.py` 现状**(batch7 删了 271 行,行号已大幅漂移)。

## 设计背景(为什么这么改)

项目是两块:① 扩写(缩写→全称),② 标准化(全称→SNOMED 概念)。

- **块①的对错,coverage 已经管了**(选 best_expansion + 弃权门)。
- coverage 之后**唯一新进来的数据 = SNOMED 检索结果**。
- 旧 verify 去复核块①(扩写对不对),用的是和 coverage 同源的 LLM + 循环的 SNOMED 支持 → 结构冗余 → 实测贡献 0(FAIL/SWAP/ABSTAIN=0/0/0)。

**所以 verify 唯一不冗余、有独立证据的职责 = 守块②(标准化)**:在检索回来的 top-k SNOMED 概念里,判**哪个才是这个扩写的忠实标准化**,或者**一个都不忠实就别给码**。

它要 catch 的错误是块①管不了的那类——**扩写对、但标准化错**。例如(batch5 实见):
- `SOB → shortness of breath` 标到了 "Difficulty taking deep breaths";
- `CP → chest pain` 标到了 "Chest pain **rating**"(一个评分量表,不是症状本身)。

这类错 coverage 看不见(它没看检索结果),**只有 verify 在 SNOMED 这关能抓**。抓住后让 `standardized_entities`(batch5 出口)只端出**真有把握**的编码 → 交付物变可信。

> 说明:这一版 verify **不再换扩写**(扩写归 coverage)。它在 retrieve 回来的 **top-k 概念**里选最忠实的那个、或都不选——retrieve(top-k)→ verify(选概念/弃码)就是块②上真正的"检索-检验-反思"。

## Part 1 · `abbr_verifier.py · verify_mappings` —— 改成"概念选择/接地"判定

输入每个 mapping 仍是 `{abbreviation, expansion, candidates}`(candidates 已是该扩写检索回的 top-3 概念,带 name/domain/score)。把 mapping 级评判从"扩写对不对"改成"**哪个候选概念是这个扩写的忠实标准化**"。prompt 关键段改写(sentence_validity 块可保留不动,或一并简化):

```
For each abbreviation mapping you are given the expansion and a SHORT LIST of candidate
SNOMED concepts retrieved for that expansion (each: index, concept_name, domain, score).

Your job is NOT to re-judge whether the expansion is correct (that is already decided).
Your job is to pick which candidate concept is a FAITHFUL standardization of the expansion:

- chosen_index = the index of the candidate whose concept_name means the SAME clinical
  thing as the expansion.
- chosen_index = null if NONE of them faithfully represents the expansion
  (e.g. the expansion is a finding/condition but the only candidates are a rating scale,
   a measurement, a procedure, or an unrelated concept).

Rules:
- Judge concept_name vs the expansion's meaning; do NOT just trust the retrieval score.
- "chest pain" is a finding; "Chest pain rating" (a scale) is NOT a faithful match → null.
- Only choose among the given candidates; never invent a concept.
```

`mapping_validations` 每项返回结构改为(至少含):
```json
{ "abbreviation": "CP", "expansion": "chest pain",
  "chosen_index": 0, "standardization_faithful": true, "reason": "..." }
```
(其它字段可保留,但状态机只读 `chosen_index` / `standardization_faithful`。)

## Part 2 · `abbr_service.py` 状态机 —— 用 verify 的选择定标准化概念

在状态机里,每个 pending mapping 经 verify 后:
1. 读该 mapping 的 `chosen_index`:
   - 有效(0..len-1 且 faithful)→ `s["std_concept"] = s["std_cache"][chosen_index]`,`status = "LOCKED_OK"`。
   - null / 不 faithful → `s["std_concept"] = None`,**仍 `status = "LOCKED_OK"`**(扩写归 coverage,保留;只是没有可信编码)。
2. **expansion 不再因 verify 改动**(删掉旧的"verify 不过就换候选/弃权"逻辑——那是冗余消歧的残留)。状态机本轮对每个 mapping 处理完即 LOCKED_OK;循环基本一轮收敛。
3. 终态/出口:`mapping_standardizations` 里每项带上 `"chosen_concept": s["std_concept"]`(可能 None)。

> 这样 LOCKED_OK 的含义升级成"扩写已定 + 标准化已裁决";有 `std_concept` 的才是块②也过关的。

## Part 3 · `api/main.py` —— standardized_entities 用 verify 选中的概念

batch5 那段组装改为:用每个 mapping 的 `chosen_concept`(verify 选中的),而不是盲取 `candidates[0]`;`chosen_concept` 为 None 的**不进** `standardized_entities`(诚实:扩了但没可信编码就不端码)。

```python
    standardized_entities = []
    for ms in final_result.get("mapping_standardizations", []):
        top = ms.get("chosen_concept")     # verify 选中的概念(可能 None)
        if not top:
            continue
        standardized_entities.append({
            "abbreviation": ms.get("abbreviation"),
            "expansion": ms.get("expansion"),
            "concept_id": top.get("concept_id"),
            "concept_name": top.get("concept_name"),
            "concept_code": top.get("concept_code"),
            "domain_id": top.get("domain_id"),
            "score": top.get("score"),
        })
```

## Part 4 · 量 + 验收(注意:benchmark 不是这批的尺子)

**关键认知**:benchmark 判的是 `(缩写, 扩写)`,**不判标准化概念对不对**。所以这批改的是块②,**benchmark 本就该持平**——它衡量不到 verify 的价值。verify 的价值要**另看**:

1. **能编译 + import OK + 批次1单测 OK**。
2. **benchmark 持平**(对锚点 ~0.9595 ±噪声):证明没碰坏块①(扩写)。掉了=改坏了主链路,排查。
3. **临时打点**:数 verify `chosen_index=null`(弃码)发生几次 → 这就是它现在真在干活的证据(>0 = 不再是橡皮图章)。量完删 print。
4. **★标准化质量实测(这批真正的验收)**:起服务 curl 几个 case,看 `standardized_entities`:
   - `"Patient has CP."` → 期望 CP 的概念**不再是** "Chest pain rating",而是更忠实的症状概念,或**干脆不给码**(若库里没有忠实概念)。
   - `"Patient denies SOB."` → 同理看 SOB 的概念是否更忠实 / 被诚实弃码。
   - 对比 batch5 时的盲取 top-1,**概念质量应改善或诚实弃码**。
5. **判定**:benchmark 不掉(块①没坏)+ verify 弃码计数>0(它在干活)+ 抽查的 standardized_entities 概念更忠实或诚实弃码 → 合入。

> ⚠️ 诚实预期:5000 条稀疏库下,很多扩写没有忠实概念,verify 会**大量弃码**——这**不是 bug,是它对了**:系统诚实地说"扩出来了,但这个库标准化不了"。`standardized_entities` 会变稀但变可信。这正是从"玩具"到"认真做标准化"的体现。

## 提交

```bash
git add backend/services/abbr_verifier.py backend/services/abbr_service.py backend/api/main.py
git commit -m "V11 batch8: repurpose verify as the standardization gate (select faithful SNOMED concept among retrieved top-k, or withhold code) instead of redundant expansion re-check; standardized_entities now reflects verify's choice."
```

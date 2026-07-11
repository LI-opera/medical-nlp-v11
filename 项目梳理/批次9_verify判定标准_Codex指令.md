# 批次 9 · 给 Codex 的指令(可整段复制)· verify 判定标准收敛(只改 prompt,治 CAD 过度弃码+抖动)

## 背景与范围

concept 层 benchmark(新建,11 例硬 gold)实测标准化基线:PASS 10/11=0.909、canonical 9/11=0.818。唯一 FAIL 是 **CAD**:忠实的上位概念 `Disorder of coronary artery` 明明在 top-10 里,verify 却因"它比精确的病宽泛"而弃码;且 verify 在父概念上**抖动**(3 候选拒、15 候选收同一个)。

根因:`verify_mappings` 的判定标准只说了"选意思相同的、没有就 null",**没规定**:① 无精确概念时能否接受忠实的**父概念/同义词**;② 多个忠实候选里选哪个(最具体)。本批**只补这段判定标准的 prompt 文字**,不碰代码逻辑、不碰检索/重排/状态机。

> 目标:CAD 由 FAIL→PASS(选中 `Disorder of coronary artery` 或更规范的);其余 10 例**一个都不许回归**;主 benchmark(判扩写)**必须持平 0.9595**(prompt 改的是标准化层,碰不到扩写判分——若它动了就是改坏了)。

工作在 `medical-refactor`(HEAD 若飘到 `medical` 先 `git switch -f medical-refactor`)。

## 铁律

1. **先 Read `backend/services/abbr_verifier.py` 核对**。只动 `verify_mappings`(约 89-158 行)里的判定标准那段;**绝不碰** 上面那个老的 `verify()` 方法、也不碰本方法的 context 文本 / 输入 JSON / 返回结构 / 解析逻辑。
2. 不改任何 `.py` 逻辑代码、不改检索/rerank/状态机/IO 契约。verify 仍返回 `chosen_index` + `standardization_faithful` + `reason`,字段不变。
3. 改完必须三关全过(见验收),尤其主 benchmark 持平。

---

## A · 替换判定标准段(`verify_mappings` 内)

把下面这段【旧】整段替换成【新】整段。保持每行前面的 8 空格缩进(它在三引号 f-string 里)。

### 旧(约 114-135 行,从 "Your job is NOT to re-judge" 到 "Do not use markdown."):
```text
        Your job is NOT to re-judge whether the abbreviation expansion is correct.
        That decision has already been made by the abbreviation coverage stage.

        Your job is to pick which candidate concept is a FAITHFUL standardization of
        the expansion:

        - chosen_index must be the zero-based index of the candidate whose concept_name
          means the SAME clinical thing as the expansion.
        - chosen_index must be null if NONE of the candidates faithfully represents the
          expansion.
        - standardization_faithful must be true only when chosen_index points to a
          faithful candidate.
        - Judge concept_name against the expansion's clinical meaning. Do not trust the
          retrieval score by itself.
        - A finding or condition must not be grounded to a rating scale, measurement,
          procedure, or other related-but-different concept.
        - Example: "chest pain" and "Chest pain rating" are not the same clinical thing,
          so choose null unless another candidate faithfully represents chest pain.
        - Only choose among the supplied candidates. Never invent a concept.
        - Return exactly one mapping_validations item for each input mapping, in the
          same order.
        - Return raw valid JSON only. Do not use markdown.
```

### 新(整段替换为):
```text
        Your job is NOT to re-judge whether the abbreviation expansion is correct.
        That decision has already been made by the abbreviation coverage stage.

        Your job is to pick the BEST FAITHFUL standardization of the expansion among
        the candidates, and to abstain ONLY when none is faithful.

        A candidate is FAITHFUL when its concept_name denotes the SAME clinical entity
        as the expansion. This includes:
        - an exact clinical synonym of the expansion (most preferred); and
        - the SAME disease/finding named more GENERALLY, i.e. a faithful PARENT term,
          when no exact synonym is present. For example, for "coronary artery disease"
          the candidates "Disorder of coronary artery" and "Coronary arteriosclerosis"
          are faithful; for "hypertension" the candidate "Hypertensive disorder" is
          faithful.

        A candidate is NOT faithful (do not choose it; if only such candidates exist,
        abstain):
        - it ADDS a qualifier the expansion does not state - a specific subtype, cause,
          stage, acuity, laterality or site (e.g. "... due to diabetes",
          "type 1 stage 2", "acute ...", "of inferior wall") - UNLESS the expansion
          itself carries that qualifier; or
        - it is a related-but-different concept: a rating scale, measurement, procedure,
          device, service, monitoring / education / administration, risk level, or
          family history. For example, "chest pain" and "Chest pain rating" are not the
          same clinical thing.

        How to choose:
        - chosen_index = the zero-based index of the BEST faithful candidate. Among
          faithful candidates, prefer the MOST SPECIFIC one that does NOT add information
          absent from the expansion (prefer the disease itself over a broad parent, and
          over the disease's subtypes or related services).
        - Do NOT abstain just because no candidate is a word-for-word match: a faithful
          synonym or a faithful parent still counts as faithful.
        - chosen_index = null ONLY when no candidate denotes the same clinical entity.
        - standardization_faithful must be true only when chosen_index points to a
          faithful candidate.
        - Judge concept_name against the expansion's clinical meaning. Do not trust the
          retrieval score by itself.
        - Only choose among the supplied candidates. Never invent a concept.
        - Return exactly one mapping_validations item for each input mapping, in the
          same order.
        - Return raw valid JSON only. Do not use markdown.
```

---

## 验收(强校验)

1. **编译 + import**:`python -m compileall backend/services` 通过;`python -c "import sys;sys.path.append('backend');from services.abbr_verifier import ABBVerifier;print('OK')"`。
2. **concept 层 benchmark**:`python backend/evaluation/run_concept_benchmark.py`
   - **CAD 必须 FAIL→PASS**(选中 `Disorder of coronary artery` 或 accept 内其它,faithful=True)。
   - **其余 10 例一个都不许回归**;canonical 计数 ≥ 9(原本 CP/DM/MI/PNA/CHF/HTN/ASTHMA/AFIB/RA)。
   - 目标态:PASS 11/11、canonical ≥ 9。**任一原 PASS 例变 FAIL = 改坏了,回退。**
3. **主 benchmark**:`python backend/evaluation/run_benchmark.py` → **必须 ~0.9595 持平**(各类同前)。prompt 改标准化层,理论上碰不到扩写判分;**若分数动了,说明 prompt 改动有副作用,回退排查。**
4. **判定**:1-3 全过且 CAD 上分、无回归 → 合入;有任何回归 → 回退。

## 提交

把本次 verify 改动 + 新建的 concept benchmark 一起提交(benchmark 是本批的验收尺子):
```bash
git add backend/services/abbr_verifier.py backend/evaluation/concept_benchmark_cases.py backend/evaluation/run_concept_benchmark.py
git commit -m "V11 batch9: tighten verify faithfulness rubric (accept faithful parent/synonym, prefer most specific, abstain only when none faithful) + add concept-level benchmark. Fixes CAD over-abstention; concept PASS 10/11->11/11 target, main benchmark flat 0.9595."
```
> 注:本批是 prompt-only 行为收敛。主 benchmark 持平是硬门槛(证明没碰到扩写层);concept benchmark 是本批专属的标准化尺子,首次让 verify 的标准化质量可量化、可证伪。

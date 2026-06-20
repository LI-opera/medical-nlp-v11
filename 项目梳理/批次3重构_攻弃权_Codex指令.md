# 批次 3(重构版 · 攻弃权)· 给 Codex 的指令(可整段复制)

> **背景**:原批次 3(fallback top-k + NER 过滤)已**回退**——它方向搞反了:top-k 让 LLM 给非临床 token 造更多像样的假扩写(MNO→"Multiple Nodular Opacities"、NOP→"Nocturnal Oxygen Protocol"),NER 还拦不住这些"长得像医学"的幻觉,net 从 0.94 掉到 0.90,带崩 ambiguous 和 coverage_failed。
>
> **本重构版**只做一件事、最小改动:**对 fallback(非词典)缩写收紧——coverage 证据不足就弃权(best_expansion=null),不替 LLM 现造的扩写背书。** 直接打 QRS/NOP/MNO 这类过度扩写。

## 为什么这版低风险(给你 Codex 的判断依据)

- benchmark 里**没有任何 case 期望 fallback 扩写被保留**:该扩的(SOB/CP/MS/DM/HTN…)全是词典缩写;fallback 只产生 low_context/coverage_failed 里的过度扩写垃圾。
- 所以"对 fallback 缩写收紧弃权"**只会帮忙或中性**,物理上碰不到 single/ambiguous/multi/negation 这四个满分类(它们全走词典 primary)。
- **词典候选完全不动**(LMN 是词典缩写,本版不处理它,留作后续;别为了 LMN 去动词典逻辑而误伤满分类)。

## 铁律

1. **先确认已回到批次 2**:`git log --oneline -1` 顶部应是 `573cad6 V11 batch2 ...`,`git status` clean。不在批次 2 别开始。
2. **先 Read 现状再改**:只改 `abbr_service.py · _get_abbreviation_candidates` 一处。
3. **不动**:`ner_service.py`、`fallback_retriever.py`、coverage_evaluator、状态机循环、verifier、检索、Milvus/embedding、`.env`。(本版完全不碰 NER 和 top-k。)
4. **不删** 批次 1/2 任何成果。

## 改动 — `backend/services/abbr_service.py · _get_abbreviation_candidates()`

找到 coverage 之后那行 `best = coverage.get("best_expansion")`(批次2后约第 641 行),在它**下面**加一段弃权门:

```python
            best = coverage.get("best_expansion")

            # 批次3(攻弃权):对 fallback(非词典)缩写收紧
            # 词典缩写(primary)是人工策展可信源 → 照常;
            # fallback 缩写是 LLM 现造的,上下文证据不足就弃权,不替它背书
            # (治 QRS→"QRS complex"、NOP→"no operation/Nocturnal Oxygen Protocol"、MNO 等过度扩写)
            if candidate_source == "fallback":
                conf = coverage.get("confidence") or 0.0
                if (not coverage.get("coverage_ok")) or conf < 0.8:
                    best = None
```

其余不变(`found.append` 里 `best_expansion` 仍取这个 `best`,`chosen_label`/`chosen_domain` 仍为 None)。

> 原理:`best=None` → 该缩写在 `expand_verify_with_retry` 里**不进 states**(批次2逻辑:`if not best: continue`)→ 不扩、保留原缩写。词典缩写 `candidate_source=="primary"`,这段不触发,行为完全不变。

## 验收(对齐 74 例新基线)

新锚点 = 批次 2 在 74 例 CASI 补强 benchmark 上的 **0.9324(69/74)**,每类见 `benchmark_baseline_V9.md`。

1. **能编译**:`python -m compileall backend/services/abbr_service.py`;批次1单测仍 `OK`。
2. **benchmark**:`python backend/evaluation/run_benchmark.py`,对比新锚点。
   - **net ≥ 0.9324**。
   - **★过度弃权护栏(最关键)**:`casi_ambiguous(17/18)` 和 `fallback_should_expand(6/6)` **绝不能掉**——它们大量走 fallback,弃权门若误伤真实该扩的缩写,这两类立刻塌。掉了 = 门太狠 = 回退。
   - 词典类(single/multi/negation/coverage_failed)理论上碰不到(门只管 fallback);`ambiguous_004` 若翻动是 LLM 噪声(MS 是 primary),不算门的账。
   - low_context:QRS/NOP 若 coverage confidence < 0.8 → 弃权 → `coverage_006/008` 有望转对。
3. **判定**:net ≥ 新锚点 **且** casi_ambiguous/fallback_should_expand 没掉 → 合入;否则 `git revert`。

## ⚠️ 诚实预期 + 旋钮 + 不要做的事

**这个门的正当性来自原则,不是来自 benchmark**:医疗场景下,非词典缩写 + 上下文证据不足时,弃权(安全失败)优于硬猜(幻觉)。所以它**保留 fallback 能力**,只在 fallback 不自信时不背书。

- **能治**:coverage 对 QRS/NOP 这类假扩写若不够自信(confidence<0.8)→ 弃权转对。
- **未必治**:① 若 coverage 对假扩写**过度自信**(confidence≥0.8)→ 门不触发。可把阈值提到 0.9 再试。② **LMN**(词典缩写)本版不处理,仍会失败。
- **唯一旋钮**:阈值 `0.8`。先按 0.8 跑一次拿干净信号;不够再调,**一次只动这一个数**。

### ★ 明确不要做(避免 benchmark 过拟合)

- **不要"fallback 一律弃权 / 砍掉 fallback"**。本 benchmark 恰好没有"需要 fallback 扩写"的 case,所以砍掉 fallback 会让分数虚高——这是**为单一弱 benchmark 过拟合**,牺牲了"处理词典外真缩写"的真实能力。**宁可分数不涨,也不焊死 fallback。**
- 判定本批用**双标准**:net 不退 **且** 改动是"本身就对的原则"。若门触发后某满分类反而掉了,说明它误伤了真实能力,**回退**。

## 提交

```bash
git add -A
git commit -m "V11 batch3-rev: abstain on weakly-supported fallback abbreviations"
```

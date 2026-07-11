# ABBRCandidateCoverageEvaluator（覆盖度闸门：先问"答案在不在锅里"）

> 文件：`backend/services/abbr_candidate_coverage_evaluator.py`（85 行）
> 入口：`evaluate(original_text, abbreviation, candidates)`
> 衔接：**阶段三的收口，质控的第一道闸门**。第 8/9 篇召回了候选（可能有噪声、有多义，fallback 还可能幻觉）。Coverage 在把候选交给扩写 LLM 之前先筛一遍：这批候选靠不靠谱、哪些被上下文支持。这就是上一篇说的"召回激进、把关在后"的那个**把关**。

## 核心速记
> 1. **核心区分：Coverage ≠ Correctness**。它只问"候选集里**至少有一个**在当前上下文说得通吗"，**不**负责选出最终答案。这是本篇最该讲、也是项目区别于普通扩写系统的关键。
> 2. **产出 `plausible_candidates`**：挑出"上下文支持的候选"，上游据此过滤出 `filtered_candidates`，只把这些交给扩写 LLM——缩小决策空间，提 Precision。
> 3. **专治召回的脏**：收拾 fallback（第 9 篇）可能的幻觉 + 多义候选的上下文裁决。
> 次要（trivia）：`temperature=0`、markdown 清洗、`parse_error` 兜底为 `coverage_ok=False`——扫一眼。

## 这一段在解决什么

大白话：**给一个缩写、它的一堆候选、还有原句，判断"这堆候选里，至少有一个在这句话里说得通吗？"并把说得通的挑出来。**

```text
"The patient has MS with a diastolic murmur."   缩写 MS
候选 = [multiple sclerosis, mitral stenosis]
   ↓ coverage 评估
{ coverage_ok: true,
  plausible_candidates: ["mitral stenosis"],   ← 有杂音→心脏病，留这个
  confidence: 0.9, reason: "...", issues: [] }
```

## 核心1 · Coverage vs Correctness：先问"答案在不在锅里"（骨架，必背）

这是整个项目最重要的概念区分之一，prompt 里专门写了：

```text
"Coverage evaluation asks: Is there at least one reasonable candidate in this candidate set?
 It does NOT need to perform final expansion."
```

翻译这个区分：

- **Correctness（正确性）**：最终选的那个 expansion 对不对？——这是后面 Verification 的事。
- **Coverage（覆盖度）**：正确答案**到底在不在候选集里**？

**为什么必须先问 Coverage**：假设缩写 `AKI`，正确答案是 `acute kidney injury`，但候选集里只有 `acute kidney infection`（错的）。这时候**后面做什么都白搭**——扩写 LLM 只能在候选里选，正确答案根本不在锅里，它必然选错或被逼幻觉。

所以在让 LLM 动手之前，先确认"**答案在不在锅里**"。在 → 继续；不在（`coverage_ok=false`）→ 别硬扩，宁可不扩（回扣文档里"什么时候不该扩写"的决策思想）。

> 一句话记忆：**Coverage 管"够不够"，Verification 管"对不对"。** 两道闸门，先后把关。

## 核心2 · 它专门收拾召回的脏（设计定位）

回想前两篇：
- 第 8 篇词典召回：多义缩写把 `CP` 三个意思**全列出来**（高召回，不挑）。
- 第 9 篇 LLM fallback：可能**幻觉**出不靠谱的候选。

这些"脏"候选不能直接喂给扩写 LLM。Coverage 就是那道过滤网：

```text
召回（激进，可能脏）→ Coverage（裁决哪些上下文支持）→ filtered_candidates（干净）→ 扩写 LLM
```

prompt 的规则就是这个裁决逻辑：

```text
Rule 1: 至少一个候选上下文说得通 → coverage_ok = true
Rule 2: 没有一个合适           → coverage_ok = false
Rule 3: 候选为空               → coverage_ok = false
Rule 4: 上下文不足但候选是常见义 → coverage_ok = true，但 confidence 降低
Rule 5: 不许发明新候选（只能从给定候选里挑）
```

Rule 5 很关键——coverage 只**裁判**，不**新增**，避免它越权变成又一个生成器。

## 核心3 · 产出怎么被用（真实数据，串起数据流）

`evaluate` 返回后，上游 `ABBRService._get_abbreviation_candidates` 这样用（第 14 篇细讲）：

```python
plausible_expansions = coverage.get("plausible_candidates", [])
filtered_candidates = [
    c for c in candidates if c["expansion"] in plausible_expansions   # ← 字符串精确匹配过滤
]
```

翻译：coverage 挑出的 `plausible_candidates`（一串 expansion 文字），上游用它**过滤原候选**，只留下"被上下文支持"的，作为 `filtered_candidates` 交给扩写 LLM。

**效果**：把扩写 LLM 的选择范围从"所有召回候选"缩小到"上下文支持的候选"，**减少决策空间 → 提高 Precision**。

## 数据快照

```text
【入】 evaluate(
        original_text="The patient has MS with a diastolic murmur.",
        abbreviation="MS",
        candidates=[{abbr:"MS",exp:"multiple sclerosis"},{abbr:"MS",exp:"mitral stenosis"}])

【出】 { coverage_ok:true, confidence:0.9,
        plausible_candidates:["mitral stenosis"],   # diastolic murmur → 心脏病
        reason:"Diastolic murmur indicates a cardiac condition.", issues:[] }

【上游过滤】 filtered_candidates = [{abbr:"MS",exp:"mitral stenosis"}]   # multiple sclerosis 被滤掉
```

## 会被追问 / 诚实局限（★主动说）

- **`plausible_candidates` 是字符串，上游用"精确匹配"过滤**：`c["expansion"] in plausible_expansions`。如果 LLM 返回的字符串和原候选**大小写/措辞稍有出入**（"Mitral Stenosis" vs "mitral stenosis"），匹配就漏，候选被错误丢弃。这是个真实的脆弱耦合。
  → 面试这么说："这里用字符串精确匹配把 coverage 结果映射回候选，LLM 一旦改了大小写或措辞就匹配不上。更稳的做法是让 coverage 返回候选的**索引或 ID**，而不是回传文字串。" 这条很能体现你读到了实现细节。
- **coverage 判断本身也是 LLM，也会错**：把对的判成 false（over-abstention，该扩没扩）或把错的判成 true（漏网）。文档里 V10 的 over-abstention 问题就和这类判断的保守度有关。
  → "coverage 是用 LLM 当裁判，本身有误判风险。它和 verification 是两道独立把关，互为补充降低单点误判。"
- **又一次 LLM 调用，成本叠加**：召回阶段如果走了 fallback（一次 LLM），这里 coverage 再一次。一个多义/未知缩写可能两次 LLM。
  → "确实有成本，但 coverage 换来的是 precision 和'不该扩就不扩'的能力，对医疗场景值得。可优化的是单义缩写直接跳过 coverage（只有一个候选无需裁决）。"
- **Rule 5"不许发明候选"靠 prompt 约束，LLM 不保证遵守**；`confidence` 同样是自报的，参考为主。
- **`parse_error` 兜底为 `coverage_ok=False`**：解析失败就当"覆盖不通过"，偏保守（宁可不扩也不乱扩），方向是安全的。

```
先说 `parse_error` 是什么:coverage 让 LLM 返回 JSON,但 LLM 偶尔会返回坏掉的、不是合法 JSON 的文本。代码用 try/except 接住:

try:
    parsed = json.loads(content)        # 尝试解析 LLM 返回的 JSON
except json.JSONDecodeError:            # 解析失败（LLM 返回了非法 JSON）
    return {"coverage_ok": False, ...,  # ← 兜底：当作"覆盖不通过"
            "issues": ["invalid_json"]}


"兜底为 `coverage_ok=False`"的意思:**连 LLM 在说什么都没解析出来时,默认判定"覆盖不通过"。**
```



- **关键:coverage 其实在干两件事**

**(a) 消歧**:多个候选里,哪个对?(MS → mitral stenosis 还是 multiple sclerosis)

**(b) 要不要扩**:这个缩写在当前上下文,到底**该不该扩写**?(上下文够不够支持)

## 面试怎么说

**合格版（30 秒）**：

> Coverage 是质控第一道闸门：判断召回的候选集里，至少有没有一个在当前上下文说得通，并挑出说得通的 plausible_candidates。它不选最终答案，只确认"正确答案在不在候选集里"。上游用它过滤候选，只把支持的交给扩写 LLM。

**优秀版（1 分钟）**：
> 这是项目区别于普通扩写系统的关键设计。我把"覆盖度"和"正确性"分开：coverage 先问"答案在不在锅里"——如果候选集根本不含正确答案，后面让 LLM 硬选只会逼出幻觉，所以先确认覆盖，不覆盖宁可不扩。它专门收拾召回阶段的脏：词典多义候选、fallback 的幻觉，裁决出 plausible_candidates，上游据此过滤、缩小扩写 LLM 的决策空间、提 precision。诚实说两个点：一是 coverage 结果用字符串精确匹配映射回候选，LLM 改个大小写就漏，应该返回索引/ID；二是 coverage 自己也是 LLM 判断，会有 over-abstention，这也是文档里记录的已知问题，靠它和 verification 两道独立把关来互补。

## 易错点 / 面试问答

**Q：Coverage 和 Verification 有什么区别？** A：Coverage 管"够不够"——正确答案在不在候选集里；Verification 管"对不对"——最终选的那个扩写对不对。两道闸门，先后把关。

**Q：为什么要先做 Coverage？** A：如果正确答案根本不在候选集里，后面怎么选都白搭，还会逼 LLM 幻觉。先确认覆盖，不覆盖就宁可不扩。

**Q：coverage_ok=false 会怎样？** A：上游不强行扩写（filtered_candidates 为空），宁可保留原样也不乱扩——这是"什么时候不该扩"的决策能力。

**Q：plausible_candidates 怎么被用？** A：上游用它过滤原候选（字符串匹配），只留支持的作为 filtered_candidates 交给扩写 LLM。缺点是字符串匹配脆弱，应该用索引/ID。

**Q：coverage 用 LLM 判断不会也错吗？** A：会，可能 over-abstention 或漏网。所以它和 verification 是两道独立把关，互补降低单点误判。

## 一句话总结

> Coverage 评估器是质控第一道闸门，核心是区分 Coverage（候选集够不够、答案在不在锅里）与 Correctness（选得对不对）：它用 LLM 判断候选集里至少有没有上下文支持的扩写、挑出 plausible_candidates，上游据此过滤、缩小扩写 LLM 决策空间、提 precision，并赋予"不该扩就不扩"的能力。它专治召回的多义与幻觉。局限是字符串匹配映射脆弱（应返回 ID）、coverage 本身也会误判（over-abstention）、成本叠加——靠它与 verification 两道独立把关互补。

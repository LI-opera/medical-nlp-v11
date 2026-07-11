# ABBRCandidateRetriever（主候选召回：查词典，确定性优先）

> 文件：`backend/services/abbr_candidate_retriever.py`（27 行，全项目最短的服务）
> 入口：`retrieve(abbreviation)`
> 衔接：进入**阶段三（缩写召回与质控）**。第 1 篇是缩写候选词典（数据），这一篇就是"读词典的那只手"（服务）。它是缩写召回的**第一层（primary）**——查得到就用，查不到才走下一篇的 LLM 兜底。

## 核心速记
> 1. **确定性优先**：第一层召回用字典查找，**不碰 LLM**。零延迟、零成本、完全可控、可解释。把不确定性留给后面（fallback / coverage）。这是本篇骨架。
> 2. **高召回，不做决定**：多义缩写（CP→3 个）把所有可能都列出来，选哪个是后面的事。
> 3. **`upper().strip()` 归一化**：词典 key 统一大写，查表前先标准化输入，`htn`/`HTN`/`" HTN "` 都能命中。
> 次要（trivia）：`dict.get(abbr, [])` 查不到返回空列表不报错、列表推导式——扫一眼。

## 这一段在解决什么

大白话：**输入一个缩写，把它在词典里所有可能的全称都查出来，整理成统一格式。**

```text
"CP"  →  [{abbreviation:"CP", expansion:"chest pain"},
          {abbreviation:"CP", expansion:"cerebral palsy"},
          {abbreviation:"CP", expansion:"chronic pancreatitis"}]
"XYZ" →  []   # 词典里没有，返回空（不报错）
```

## 核心1 · 全部代码就这几行（实现）

```python
class ABBRCandidateRetriever:
    def retrieve(self, abbreviation: str):
        abbr = abbreviation.upper().strip()          # ① 归一化：统一大写去空格
        candidates = ABBR_CANDIDATES.get(abbr, [])   # ② 查词典，查不到给空列表
        return [                                      # ③ 转成统一结构
            {"abbreviation": abbr, "expansion": expansion}
            for expansion in candidates
        ]
```

三步：**归一化输入 → 查词典 → 转成 `{abbreviation, expansion}` 列表**。就这么多。

为什么 `upper().strip()`：第 1 篇说过词典 key 统一大写存储。所以查之前先把输入标准化，`htn`、`HTN`、`" HTN "` 都能命中同一个 `HTN`。

为什么 `.get(abbr, [])` 而不是 `[abbr]`：查不到时返回空列表，**不抛 KeyError**。空列表是个合法信号——告诉上层"主候选没货，去走 fallback"。

## 核心2 · 为什么第一层召回不用 LLM（骨架，必背）

这是整个召回设计的关键取舍。完全可以让 LLM 直接生成候选，但项目**第一层故意用字典**：

| | 字典查找（本层） | LLM 生成 |
|---|---|---|
| 速度 | 微秒级 | 几百毫秒 ~ 秒 |
| 成本 | 0 | 花 token / 钱 |
| 可控 | 完全可控、可解释 | 可能幻觉、不稳定 |
| 覆盖 | 受限于词典 | 理论上无限 |

**思路是"确定性优先"**：能用规则确定回答的，绝不动用 LLM；只有词典覆盖不到时，才退而求其次让 LLM 兜底（第 9 篇 fallback）。这和 RAG 里"能精确匹配就别向量检索"是同一个哲学——**把昂贵、不可控的手段留到最后**。

> 面试讲召回设计时，这句"确定性优先、LLM 兜底"是个很好的总纲。

## 核心3 · 它只召回，不做决定（设计点）

注意它对多义缩写的处理：**把所有候选平等地全列出来**，不排序、不挑选、不看上下文。

```text
CP → [chest pain, cerebral palsy, chronic pancreatitis]   ← 三个都给，不替你选
```

这是**高召回（high recall）**策略——这一层的目标是"**别漏掉正确答案**"。到底选哪个、上下文支不支持，交给后面的 Coverage（第 10 篇）和 Verification。**召回与决策分离**，每层只干一件事。

## 数据快照

```text
retrieve("htn")  → [{abbreviation:"HTN", expansion:"hypertension"}]        # 单义
retrieve("MS")   → [{abbreviation:"MS", expansion:"multiple sclerosis"},
                    {abbreviation:"MS", expansion:"mitral stenosis"}]      # 多义，全给
retrieve("ZZZ")  → []                                                      # 没有，空列表
```

## 会被追问 / 诚实局限（★主动说）

- **完全依赖词典覆盖**：词典里没有的缩写直接返回空，能力上限就是第 1 篇那 ~45 个缩写。
  → 面试这么说："主召回是确定性的字典查找，覆盖范围等于词典。覆盖不到的走 LLM fallback 兜底，是有意的两层设计——常见缩写走确定性、长尾走 LLM。"
- **不做任何排序或上下文判断**：多义缩写三个候选完全平等，没有先验概率（哪个更常见）。
  → "这一层只保证高召回，消歧完全下放给 coverage 和 verification。如果词典带了频率/科室元数据（第 1 篇说的），这里可以顺手做个先验排序，减轻下游负担。"
- **职责极薄，几乎是词典的 wrapper**：单看这个类好像"没干啥"。
  → 别当缺点讲，要讲成优点："它薄是因为单一职责——就负责'把词典查询包成统一接口'。这样词典换数据源（接 UMLS）时，只改这一层，上游 ABBRService 完全无感。" 这是封装的价值。
- **大小写归一化只做了 `upper`**：对极少数大小写敏感的写法可能误判，但医学缩写基本不敏感，实际无影响。

## 面试怎么说

**合格版（30 秒）**：
> ABBRCandidateRetriever 是缩写召回的第一层：把输入缩写统一大写，去词典里查所有可能的全称，返回 `{abbreviation, expansion}` 列表，查不到返回空。它纯字典查找、不用 LLM，确定性、零延迟。

**优秀版（1 分钟）**：
> 这是召回的第一层，我刻意用字典而不是 LLM——确定性优先：常见缩写用词典查，微秒级、零成本、可解释，把昂贵又可能幻觉的 LLM 留到词典覆盖不到时再兜底。它对多义缩写把所有候选平等列出，只保证高召回，不做消歧——选哪个交给后面的 coverage 和 verification，召回与决策分离。这个类很薄，但薄得有道理：它是词典的统一接口，将来换成 UMLS 数据源只改这一层，上游无感。局限是覆盖受限于词典、候选没有先验排序，都可以靠接大词表和加元数据改进。

## 易错点 / 面试问答

**Q：第一层召回为什么不用 LLM？** A：确定性优先。字典查找微秒级、零成本、可控可解释；LLM 慢、花钱、可能幻觉。能确定回答的就别动 LLM，覆盖不到才用它兜底。

**Q：多义缩写它怎么处理？** A：把所有候选平等列出，不排序不挑选。这一层只保证高召回，消歧交给 coverage 和 verification。

**Q：查不到会报错吗？** A：不会。`dict.get(abbr, [])` 返回空列表，空是合法信号——告诉上层去走 fallback。

**Q：这个类这么薄有意义吗？** A：有。单一职责——把词典查询封成统一接口。换数据源（接 UMLS）只改这里，上游不受影响，这是封装的价值。

## 一句话总结

> ABBRCandidateRetriever 是缩写召回第一层：归一化输入 → 查词典 → 返回 `{abbreviation, expansion}` 列表，查不到返回空。它确定性优先、不用 LLM（零延迟可控），对多义缩写高召回地全列出、不做消歧（决策下放）。它薄但单一职责，是词典的统一接口、便于换数据源。局限是覆盖受词典限制、候选无先验排序——都靠接大词表/加元数据改进，长尾交给下一篇的 LLM fallback。

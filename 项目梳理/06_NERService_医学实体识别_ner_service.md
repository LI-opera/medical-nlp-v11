# NERService（医学实体识别：把句子里的医学词"圈出来"）

> 文件：`backend/services/ner_service.py`（102 行）
> 入口：`extract_entities(text)`；核心私有方法 `_merge_adjacent_entities()` / `_can_merge()`
> 衔接：前面几篇打通了"一个词 → SNOMED 检索"。但一整句临床文本里只有部分词是医学概念。NERService 负责**先把这些词圈出来**，下一篇 MedicalStandardizer 再把每个实体逐个丢给 MedicalRetriever 去查 SNOMED。

## 核心速记
> 1. **为什么要 NER**：整句话里只有 `chest pain`、`hypertension` 是医学概念，`the/patient/has` 是噪声。先抽实体再逐个标准化，比拿整句去检索精度高。这是本篇骨架。
> 2. **用现成医学 NER 模型**：`Clinical-AI-Apollo/Medical-NER`，不自训。`aggregation_strategy="simple"` 防止把词切碎。
> 3. **相邻实体合并**：模型可能把 `chest pain` 拆成 `chest`+`pain` 两个，合并成一个完整概念才好检索。这是本篇唯一的自定义逻辑。
> 次要（trivia）：`entity_group` 字段、score 取平均、start/end 索引——扫一眼。

## 这一段在解决什么

大白话：**给一句话，把里面的医学词标出来，每个标上"是什么类型、多大把握、在第几个字"。**

```text
"The patient has chest pain and hypertension."
   ↓ NER
[ {text:"chest pain", label:"SIGN_SYMPTOM", score:0.98, start:16, end:26},
  {text:"hypertension", label:"DISEASE_DISORDER", score:0.99, start:31, end:43} ]
```

## 核心1 · 为什么需要 NER（骨架，必背）

最朴素的想法是：直接拿整句话去 Milvus 检索。问题是——**整句里大部分是噪声**（`the`、`patient`、`has`、`and`），只有少数词是真正要标准化的医学概念。

```text
不好：检索 "The patient has chest pain"  → 向量被无关词稀释，检索不准
好：  先抽出 "chest pain" → 单独检索    → 精准命中 SNOMED 概念
```

所以流程是"**先定位（NER 找出医学实体）→ 再标准化（每个实体单独查 SNOMED）**"。NER 是整个标准化链路的**源头**——它圈错了，下游全错（这点也是它最大的风险，见局限）。

## 核心2 · 站在现成模型肩上（实现机制）

```python
def __init__(self):
    self.ner_pipeline = pipeline(
        task="token-classification",            # 给每个 token 分类
        model="Clinical-AI-Apollo/Medical-NER", # HuggingFace 上的现成医学 NER 模型
        aggregation_strategy="simple",          # 把 subword 合并成完整词
    )
```

两个要会讲的点：
- **不自己训练 NER**：直接用 HuggingFace 上现成的医学 NER 模型。理由——自训需要大量标注医学数据、成本高，现成模型够用。这是务实的取舍。
- **`aggregation_strategy="simple"`**：Transformer 会把词切成 subword（`hypertension` → `hyper`、`##tension`）。这个参数让 pipeline 自动把它们**拼回完整词**，否则你拿到的是一堆碎片。

`extract_entities` 把模型原始输出整理成统一结构：

```python
raw_entities = self.ner_pipeline(text)   # [{entity_group, score, word, start, end}, ...]
# 重命名字段 → {text, label, score, start, end}，score 保留 4 位
merged_entities = self._merge_adjacent_entities(text, entities)   # 再做合并
```

## 核心3 · 相邻实体合并：把 `chest`+`pain` 拼成 `chest pain`（本篇核心自定义逻辑）

模型有时会把一个完整医学概念拆成两个相邻实体：

```text
"chest pain"
   模型输出 → chest (BIOLOGICAL_STRUCTURE) + pain (SIGN_SYMPTOM)   ← 拆成两个了
   我们想要 → chest pain (一个完整概念)                            ← 才好去检索
```

`_merge_adjacent_entities` 就是来拼回去的，判断两个条件：

```python
gap_text = text[current["end"]:next_entity["start"]]      # 两实体之间的字符
should_merge = (gap_text.strip() == ""                    # ① 紧挨着（中间没别的词）
                and self._can_merge(current, next_entity)) # ② 类型在白名单里
```

`_can_merge` 是一张**手写的可合并类型白名单**（只有 3 对）：

```python
merge_label_pairs = {
    ("BIOLOGICAL_STRUCTURE", "SIGN_SYMPTOM"),    # 身体部位 + 症状：chest + pain
    ("BIOLOGICAL_STRUCTURE", "DISEASE_DISORDER"),# 身体部位 + 疾病
    ("SIGN_SYMPTOM", "SIGN_SYMPTOM"),            # 症状 + 症状
}
```

合并时：`text` 用 `text[start:end]` 从原文重切（保留原始大小写空格），`label` 拼成 `"A+B"`，`score` 取两者平均。

**为什么需要这步**：检索 `chest pain` 能命中 SNOMED 的 "Chest pain" 概念；但拆成 `chest` 和 `pain` 分别检索，命中的就是错的（胸部、疼痛各自的概念）。合并是为了**让实体边界和 SNOMED 概念边界对齐**。

## 数据快照：合并前后

```text
输入："chest pain"，模型拆成两个：
  {text:"chest", label:"BIOLOGICAL_STRUCTURE", start:0, end:5}
  {text:"pain",  label:"SIGN_SYMPTOM",         start:6, end:10}

gap = text[5:6] = " " → strip()=="" ✅ 紧挨
(BIOLOGICAL_STRUCTURE, SIGN_SYMPTOM) 在白名单 ✅

合并后：
  {text:"chest pain", label:"BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM",
   score:平均, start:0, end:10}
```

## 会被追问 / 诚实局限（★主动说）

- **NER 是整条标准化链的源头，它错了下游全错**（error propagation）。模型没识别出某个实体，或边界切错，后面检索、校验再准也救不回来。
  → 面试这么说："NER 是单点源头风险，我清楚。当前靠现成医学模型 + 合并规则兜底；要更稳的话得评估多个 NER 模型、或加规则字典兜底。"
- **合并白名单只有手写 3 对，覆盖有限**。像 `lower motor neuron` 这种三词概念合并不了（见下条），换个领域的复合实体也可能漏。
  → "合并规则是启发式的，只覆盖最常见的'部位+症状'类组合，是可以扩充或学习的。"
- **合并后 label 变成 `"A+B"`，无法再继续合并**。三词以上的概念拼不起来：`chest`+`pain` 合并成 `BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM` 后，再遇到第三个词，`(A+B, C)` 不在白名单，链式合并就断了。
  → 这是个真实的边界局限，能主动说明你读懂了滚动合并的逻辑。
- **`score` 取平均没有理论依据**，只是个简单启发式。
- **模型加载重**：`pipeline(...)` 在 `__init__` 加载，首次慢（回扣懒加载）；没指定 `device`，默认 CPU，也是 Benchmark 慢的原因之一。
- **复合 label 下游未必用得上**：`"BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM"` 这种拼接标签语义模糊，标准化时其实主要用 `text` 字段去检索，label 更多是参考。

## 面试怎么说

**合格版（30 秒）**：
> NERService 用 HuggingFace 的医学 NER 模型把临床文本里的医学实体抽出来，每个带类型、置信度和位置。我加了一步相邻实体合并——模型有时把 chest pain 拆成 chest + pain，我按"部位+症状"等白名单规则、用 start/end 判断是否紧挨，拼回完整概念，方便后面检索。

**优秀版（1 分钟）**：
> 标准化前必须先定位医学概念——整句话大部分是噪声，直接检索不准，所以先 NER 抽实体再逐个标准化。我没自训模型，直接用现成的 Clinical-AI-Apollo/Medical-NER，开了 aggregation_strategy=simple 把 subword 拼成完整词。唯一的自定义逻辑是相邻实体合并：模型常把 chest pain 拆成 chest（部位）+ pain（症状），我用一张可合并类型白名单 + start/end 间隙判断，把它们拼成一个概念，让实体边界和 SNOMED 概念边界对齐。诚实说几个局限：NER 是单点源头，错了下游全错；合并白名单只手写了 3 对、三词以上概念拼不起来；score 取平均是启发式。这些都是可以靠扩充规则或更强模型改进的。

## 易错点 / 面试问答

**Q：为什么要先 NER，不直接拿整句检索？** A：整句里大部分是噪声词，会稀释向量、降低检索精度。先抽出医学实体再单独标准化，精准得多。

**Q：NER 模型是你训练的吗？** A：不是，用 HuggingFace 现成的医学 NER 模型。自训需要大量标注数据，成本高，现成够用——这是务实取舍。

**Q：为什么要合并相邻实体？** A：模型会把 chest pain 拆成 chest + pain 两个实体，分别检索会命中错误概念。合并成完整概念，让边界和 SNOMED 概念对齐。

**Q：合并怎么判断？** A：两条件——start/end 间隙为空（紧挨）+ 两实体类型在可合并白名单里（如部位+症状）。

**Q：这套 NER 有什么风险？** A：它是整条链的源头，识别错或边界切错，下游全错（error propagation）。这是单点风险，要靠更强模型或规则兜底降低。

## 一句话总结

> NERService 用现成医学 NER 模型把临床文本里的医学实体抽出来（带类型/置信度/位置），并用一张手写的可合并类型白名单 + start/end 间隙判断，把被拆开的相邻实体（如 chest + pain）拼成完整概念，让边界与 SNOMED 对齐。它是标准化链路的源头。局限是单点 error propagation、合并白名单只 3 对、三词以上拼不起来、模型加载重——都是可扩充规则或换更强模型改进的启发式取舍。

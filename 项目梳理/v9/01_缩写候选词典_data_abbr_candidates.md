# 缩写候选词典（项目的知识地基 + V0 进化起点）

> 文件：`backend/data/abbr_candidates.py`（185 行，核心就是一个 `ABBR_CANDIDATES` 字典）
> 衔接：这是整条链路的**最底层数据**。后面所有"召回候选"的模块（主候选 retriever、coverage、reflection）都从这里取数据。先理解它，后面才有得选。

## 核心速记
> 1. **一句设计哲学**：把"缩写扩写问题"**转化成"候选选择问题"**——不让 LLM 自由生成，先给一个受控候选集让它选。这是整个项目 retrieval-first 思路的源头，必背。
> 2. **单义 vs 多义**：`SOB→1 个`、`CP→3 个`。多义缩写正是后面 coverage / 消歧 / verification 全部存在的理由。
> 3. **key 统一大写**：查表前输入会先 `.upper()`，所以 `htn` 和 `HTN` 都查 `HTN`。
> 次要（trivia）：value 是 list、单字母 key（`K`/`NA`）、注释里的数据来源说明——扫一眼即可。

## 这一段在解决什么

大白话：**这是一本"缩写 → 可能的全称"的小字典**，是项目最早、最底层的知识。

```text
"CP"  →  ["chest pain", "cerebral palsy", "chronic pancreatitis"]
"SOB" →  ["shortness of breath"]
```

它不做任何判断，只回答一个问题："这个缩写**可能**是哪些意思？"——到底选哪个，交给后面的模块。

## 核心1 · 设计哲学：把"扩写"变成"选择"（为什么是骨架，必背）

先看项目最初的 V0 长什么样。`ABBRService.__init__` 里至今还留着一段"化石"：

```python
self.abbr_dict = {                      # V0：6 条硬编码
    "SOB":"shortness of breath", "HTN":"hypertension", "DM":"diabetes mellitus",
    "CP":"chest pain", "CAD":"coronary artery disease", "CHF":"congestive heart failure"
}
# 配套方法 expand_abbreviations()：纯字符串替换
expanded_text = expanded_text.replace(abbr, full_term)
```

**这个 V0 的致命问题**：`CP` 被写死成 `chest pain`，但 `CP` 也可能是 `cerebral palsy`、`chronic pancreatitis`。一个缩写一个答案，**根本没法消歧**。

于是升级成现在的 `ABBR_CANDIDATES`：**value 从"一个全称"变成"一串候选"**。

```python
"CP": ["chest pain", "cerebral palsy", "chronic pancreatitis"]   # 现在：一串候选
```

**为什么这一步是整个项目的灵魂**：
- 纯规则词典（V0）= 无法消歧；
- 纯 LLM 自由扩写 = 容易幻觉、可能编出不存在的医学概念；
- **折中方案 = 词典先召回"所有可能"，再让 LLM 在候选里选** → 既挡住幻觉（LLM 不能乱编），又能消歧（结合上下文选）。

文件开头注释原话："**将'缩写扩写问题'转化为'候选选择问题'**"——面试就背这句。

## 核心2 · 单义 vs 多义：后面所有质控模块的存在理由

词典里的缩写分两种，**真实数据**：

```text
单义（1 个候选）：SOB→shortness of breath；HTN→hypertension；AKI→acute kidney injury
多义（多候选）：  CP →[chest pain, cerebral palsy, chronic pancreatitis]
                  MS →[multiple sclerosis, mitral stenosis]
                  PE →[pulmonary embolism, physical examination]
                  CVA→[cerebrovascular accident, costovertebral angle]
```

**这是后面整条质控链的源头**：
- 单义缩写 → 几乎不会错，直接扩；
- 多义缩写 → 召回多个后，必须靠 **Coverage（候选够不够）+ 上下文消歧（选哪个）+ Verification（选对没）** 一层层收窄。

> 记住这个因果：**词典的"多义"制造了歧义问题，后面三层质控模块就是来收拾这个问题的。** 面试讲到 coverage/verification 时，可以一路回溯到这里。

## 数据快照：词典规模与结构

```text
规模：约 45 个缩写，按科室分组（心血管/呼吸/肾代谢/神经/消化/感染/检验）
结构：{ 大写缩写(str) : [候选全称(str), ...] }
查表规则（注释明确写）：输入先 .upper() 再查 → "htn"/"HTN" 都命中 "HTN"
```

## 其余细节（次要，一行带过）

【次要】value 永远是 list（哪怕只有一个候选，也写成 `["..."]`，保证下游格式统一）；存在单字母/双字母 key（`K`→potassium、`NA`→sodium），这类极短 key 是后面 gate 要重点提防的噪声源（见核心局限）。

## 会被追问 / 诚实局限（★主动说）

- **词典是人工硬编码的、规模极小（~45 个缩写）**。文件注释自己都写明："本文件不是完整的医学缩写数据库……定位是候选召回层，用于演示、评测和系统流程验证。"
  → 面试这么说："候选库是项目级轻量词典，我有意做小——它的作用是验证'召回+选择'这套架构跑得通；生产化第一步就是接 UMLS / MeDAL / 医学缩写 Meta-Inventory 自动生成候选，把人工维护成本降下来。"
- **候选没有任何元数据**（频率、科室领域、来源、先验概率）。所以多义缩写无法按"哪个更常见"排序，只能完全依赖后面的上下文消歧。
  → "下一步会给每个候选加来源/频率/科室，让消歧能用上先验，而不是纯靠 LLM。"
- **单字母/超短 key 是定时炸弹**：`K`（potassium）、`NA`（sodium）。文本里的 `NA` 也可能是 "not applicable"，`K` 更是到处出现。
  → "正因为有这种噪声，我在召回前加了一道 gate（`_should_consider_abbreviation`），不是所有 token 都进召回；这块在第 11 篇细讲。"
- **词典本身不解决歧义**，只负责"召回所有可能"。正确答案选哪个，全靠下游。这是有意的职责切分（召回与决策分离）。
- **候选全称的措辞/大小写不一定和 SNOMED 标准名一致**（如 `white blood cells` vs `white blood cell count` 都列了）。这块靠后面 embedding 检索 + 规则重排去对齐。

## 面试怎么说

**合格版（30 秒）**：
> 最底层是一个缩写候选词典 `ABBR_CANDIDATES`，结构是"缩写 → 候选全称列表"。它的核心思想是把缩写扩写问题转化成候选选择问题——不让 LLM 自由生成，而是先给受控候选集再让它选，既防幻觉又能消歧。词典是项目级轻量库，约 45 个缩写。

**优秀版（1 分钟）**：
> 项目最早的版本其实是个 6 条的硬编码字典 + 字符串替换，问题是 `CP` 这种缩写只能映射一个意思，没法消歧。所以我把它升级成"缩写 → 候选列表"的结构——单义缩写一个候选，多义缩写如 `MS`、`CP`、`PE` 给多个。这一步是整个项目的设计支点：词典负责高召回地列出所有可能，真正的消歧和正确性判断交给后面的 Coverage、上下文选择和 Verification。我清楚它的局限——人工维护、规模小、没有元数据，所以定位就是验证架构的演示库，生产化会接 UMLS/MeDAL 自动构建。

## 易错点 / 面试问答

**Q：这词典数据哪来的，是你编的吗？** A：项目级轻量候选库，参考常见临床缩写用法和 MeDAL、医学缩写 Meta-Inventory 等公开资源人工整理。定位是召回层演示，不是完整医学库——这点我在文件里写明了，下一步接 UMLS。

**Q：为什么用字典不直接用 LLM？** A：确定性、可解释、零延迟、省 token。字典负责把"扩写"降维成"在候选里选"，把不确定性留给后面专门的消歧/校验模块，而不是让 LLM 一步到位（那样不可控）。

**Q：多义缩写（CP 三个意思）怎么办？** A：词典只管召回所有可能，不做决定。消歧交给 Coverage（判断候选集够不够）+ 上下文选择 + Verification。这是"召回与决策分离"。

**Q：词典里没有的缩写怎么办？** A：走 fallback retriever，用 LLM 结合上下文临时生成候选（阶段三第 9 篇讲），但生成的候选同样要过 coverage 和 verification，不能直接信。

**Q：`K`、`NA` 这种单字母 key 不会误判吗？** A：会，这正是风险点。所以召回前有一道 gate 过滤掉不像缩写的 token（第 11 篇），多义/可疑的再交给 coverage 裁决。

## 一句话总结

> `ABBR_CANDIDATES` 是项目的知识地基：一本"缩写 → 候选全称列表"的轻量词典（~45 个缩写，单义/多义混合）。它把项目从 V0 的"硬编码一对一替换"升级为"候选选择"范式——这是 retrieval-first、防幻觉、可消歧架构的源头。词典只负责高召回地列出可能，消歧与正确性判断全部下放给后续模块。局限是人工维护、规模小、无元数据，定位为演示/评测库，生产化接 UMLS。

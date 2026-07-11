# 缩写候选词典(项目的知识地基 + retrieval-first 起点)· V11

> 文件:`backend/data/abbr_candidates.py`(202 行,核心是一个 `ABBR_CANDIDATES` 字典)
> 衔接:这是整条链路的**最底层数据**。后面所有"召回候选"的模块(主候选 retriever、coverage、反思)都从这里取数。先理解它,后面才有得选。
> **V11 最大变化(相对老版必看)**:候选从"一个字符串"升级成 `{expansion, domain}` 字典,并新增了药品段——`domain` 这个字段后面同时驱动"检索软加分"和"L3 多源路由"。

## 核心速记
> 1. **一句设计哲学**:把"缩写扩写问题"**转化成"候选选择问题"**——不让 LLM 自由生成,先给受控候选集让它选。这是整个项目 retrieval-first 思路的源头,必背。
> 2. **🆕 每个候选带 `domain`**:`{"expansion":"aspirin","domain":"Drug"}`。domain 决定后面①检索 domain 软加分、②**走哪本库**(Drug→RxNorm、其它→SNOMED)。这是 V11 相对 V9 最关键的结构升级。
> 3. **单义 vs 多义**:`SOB→1 个`、`CP→3 个`。多义缩写正是后面 coverage / 消歧 / verify 全部存在的理由。
> 次要(trivia):key 统一大写(查表前 `.upper()`);value 永远是 list(哪怕一个候选);单/双字母 key(`K`/`NA`)是 gate 要提防的噪声源。

## 这一段在解决什么

大白话:**这是一本"缩写 → 可能的全称(+ 它是病还是药)"的小字典**,是项目最早、最底层的知识。

```text
"CP"  →  [ {chest pain, 病}, {cerebral palsy, 病}, {chronic pancreatitis, 病} ]
"ASA" →  [ {aspirin, 药} ]
"SOB" →  [ {shortness of breath, 病} ]
```

它不做任何判断,只回答:"这个缩写**可能**是哪些意思、各自属于哪个领域?"——到底选哪个,交给后面的模块。

## 核心1 · 把"扩写"变成"选择"(retrieval-first,必背)

项目最初的 V0 是个硬编码字典 + 字符串替换(这段"化石"至今还留在 `ABBRService.__init__` 里,见下方死代码提醒):

```python
self.abbr_dict = {"CP":"chest pain", ...}        # V0:一个缩写一个答案
expanded_text = expanded_text.replace(abbr, full_term)  # 纯替换
```

**V0 的致命问题**:`CP` 被写死成 `chest pain`,但它也可能是 `cerebral palsy`、`chronic pancreatitis`——**根本没法消歧**。

于是升级成 `ABBR_CANDIDATES`:**value 从"一个全称"变成"一串候选"**。为什么这一步是项目灵魂:

- 纯规则词典(V0)= 无法消歧;
- 纯 LLM 自由扩写 = 易幻觉、可能编出不存在的医学概念;
- **折中 = 词典先召回"所有可能",再让 LLM 在候选里选** → 既挡幻觉(不能乱编)、又能消歧(结合上下文)。

文件注释原话:"**将'缩写扩写问题'转化为'候选选择问题'**"——面试就背这句。

## 核心2 · 🆕 每个候选带 `domain`(消歧 + 路由的源头)

V11 把每个候选从字符串升级成 `{expansion, domain}`:

```python
"ASA": [ {"expansion": "aspirin", "domain": "Drug"} ],
"CP":  [ {"expansion": "chest pain", "domain": "Condition"}, ... ],
```

`domain` 用 SNOMED 的领域口径(Condition/Drug/Procedure/Measurement/Observation/Spec Anatomic Site…)。它后面被用在两处:

1. **检索软加分**(domain_boost):检索 SNOMED 时,命中目标领域的概念 +0.2 分(第 06 篇);
2. **🆕 L3 多源路由**(`_route_source`):`domain=="Drug"` → 去 RxNorm 药品库,其它 → SNOMED(第 15 篇)。**这就是末尾那段药品缩写存在的意义**——`ASA/MTX/APAP/HCTZ/NTG` 标 `Drug`,从词典这一层就决定了它们将被送进药品库。

**一句话**:词典里这个小小的 `domain` 标签,是后面"病走 SNOMED、药走 RxNorm"整套多源路由的**最源头**。

## 核心3 · 单义 vs 多义(后面所有质控模块的存在理由)

```text
单义(1 个候选):SOB→shortness of breath;HTN→hypertension;ASA→aspirin
多义(多候选):  CP →[chest pain / cerebral palsy / chronic pancreatitis]
                MS →[multiple sclerosis / mitral stenosis]
                PE →[pulmonary embolism / physical examination]
```

因果链:**词典的"多义"制造了歧义 → 后面 Coverage(候选够不够)+ 上下文选唯一 + Verify(选对没/库里有没有) 一层层收拾它。** 面试讲到 coverage/verify 时可一路回溯到这里。

## 数据快照

```text
规模:46 个缩写,按科室分组(心血管/呼吸/肾代谢/神经/消化/感染/检验)+ 末尾药品段(5 个)
结构:{ 大写缩写(str) : [ {expansion:str, domain:str}, ... ] }
domain 取值:Condition / Drug / Procedure / Measurement / Observation / Spec Anatomic Site
查表规则:输入先 .upper() 再查 → "asa"/"ASA" 都命中 "ASA"
```

## 其余细节(次要,一行带过)

【次要】value 永远是 list(哪怕一个候选,保证下游格式统一);药品段是 L3 Stage-4 加的成分级缩写(ingredient,故能精确对到 RxNorm 成分概念)。

## 🧹 死代码 / 盲肠提醒

- **`ABBRService.__init__` 里的 `self.abbr_dict`(6 条:SOB/HTN/DM/CP/CAD/CHF)= V0 化石,V11 主链路根本不读它。** 真正的词典是本文件的 `ABBR_CANDIDATES`(经 `ABBRCandidateRetriever` 取),gate 用的也是 `ABBR_CANDIDATES.keys()`。
  → **可安全删除**(grep 全项目:`abbr_dict` 只在定义处出现、无任何读取)。删它能消除"到底哪个才是词典"的困惑。
- 本文件自身无死代码(就是一个字典 + 注释)。

## 🚀 优化方向(更好 / 更稳)

1. **给候选加元数据(频率/科室/先验概率)**:现在多义缩写无法按"哪个更常见"排序,完全靠 LLM 消歧。加先验后可"先验 + 上下文"双信号,更稳、更省一次 LLM。
2. **自动构建词典**:接 UMLS / MeDAL / 医学缩写 Meta-Inventory 自动生成候选,替代人工维护(现在 46 个是手工策展,规模小)。
3. **domain 用受约束的枚举而非自由字符串**:目前 domain 是裸字符串,和 Milvus 里的 `domain_id`、路由的 `source` 映射靠"约定"对齐;抽成枚举/常量 + 单测,避免某天写错一个 domain 导致悄悄路由错库。
4. **校准几个可疑 domain**:如 `GI→gastrointestinal` 标了 `Spec Anatomic Site`、`PE→physical examination` 标 `Observation`——这些边界 domain 会影响软加分/路由,值得逐条核一遍。
5. **药品覆盖扩面**:现只有 5 个成分级缩写;可扩更多成分,并明确"复方/商品名不在词典口径内"(对齐 L3 诚实边界)。
6. **单/超短 key 加保护**:`K`/`NA` 既是钾/钠也是 not applicable,可给这类 key 标"需强上下文才扩",在 gate/coverage 多一道闸。

## 会被追问 / 诚实局限(★主动说)

- **人工硬编码、规模小(~46)**:文件注释自己写明"不是完整医学库,定位是召回层演示"。
  → 面试这么说:"候选库我有意做小,作用是验证'召回+选择'架构跑得通;生产化第一步接 UMLS/MeDAL 自动生成候选。"
- **候选无元数据**:多义只能靠下游上下文消歧,用不上先验。
- **单字母 key 是定时炸弹**:`K`/`NA`。→ "所以召回前有 gate(第 12 篇),不是所有 token 都进召回。"
- **词典本身不解决歧义**,只负责高召回。正确答案选哪个全靠下游(召回与决策分离,有意为之)。
- **候选措辞不一定等于 SNOMED 标准名**(如 white blood cells vs white blood cell count)→ 靠后面 embedding 检索 + 规则重排 + verify 去对齐。

## 面试怎么说

**合格版(30 秒)**:
> 最底层是缩写候选词典 `ABBR_CANDIDATES`,结构是"缩写 → 候选列表",每个候选带 expansion 和 domain。核心思想是把缩写扩写转化成候选选择——不让 LLM 自由生成,先给受控候选集再选,既防幻觉又能消歧。domain 字段后面驱动检索加分和多源路由。库是项目级轻量库,约 46 个缩写。

**优秀版(1 分钟)**:
> 项目最早是 6 条硬编码字典 + 字符串替换,`CP` 只能映射一个意思、没法消歧。我把它升级成"缩写 → 候选列表",单义一个、多义多个。V11 又把每个候选从字符串升级成 `{expansion, domain}`:domain 既给检索做领域软加分,又是 L3 多源路由的依据——药品缩写标 Drug 就会被送去 RxNorm 库、疾病走 SNOMED。这一层负责高召回地列出所有可能,真正的消歧和正确性判断交给后面的 coverage、选唯一、verify。我清楚它的局限——人工维护、规模小、无频率元数据,所以定位是验证架构的演示库,生产化接 UMLS 自动构建。

## 易错点 / 面试问答

**Q:这词典是你编的吗?** A:项目级轻量库,参考常见临床缩写 + MeDAL/Meta-Inventory 等公开资源人工整理,文件里写明定位是召回层演示,下一步接 UMLS。

**Q:为什么用字典不直接用 LLM?** A:确定性、可解释、零延迟、省 token。字典把"扩写"降维成"在候选里选",不确定性留给后面专门的消歧/校验,而不是让 LLM 一步到位。

**Q:`domain` 字段是干嘛的?** A:标每个候选是病/药/操作/检验等。①检索时命中目标领域加分;②**L3 路由**——Drug 去 RxNorm、其它去 SNOMED。它是多源标准化的源头信号。

**Q:多义缩写(CP 三个意思)怎么办?** A:词典只管召回所有可能,不做决定。消歧交给 coverage + 上下文选唯一 + verify。召回与决策分离。

**Q:词典里没有的缩写怎么办?** A:走 fallback retriever 用 LLM 临时生成候选(第 10 篇),但同样要过 coverage 和后续校验,不直接信;且 fallback 候选的 domain 靠 NER 补。

**Q:`K`/`NA` 这种单字母不会误判?** A:会,正是风险点。所以召回前有 gate(第 12 篇)过滤不像缩写的 token,多义/可疑的再交 coverage 裁决。

## 一句话总结

> `ABBR_CANDIDATES` 是项目的知识地基:一本"缩写 → [{候选全称, domain}]"的轻量词典(46 个,单义/多义混合 + 药品段)。它把项目从 V0"硬编码一对一替换"升级为"候选选择"范式(retrieval-first、防幻觉、可消歧),V11 又给每个候选加 domain,成为"检索软加分 + 多源路由"的最源头。词典只负责高召回,消歧与正确性下放给下游;局限是人工维护、规模小、无元数据,定位演示/评测,生产化接 UMLS。

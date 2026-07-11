# ABBRService —— 多源路由与标准化反思重检索 · V11

> 文件:`backend/services/abbr_service.py`、`backend/services/abbr_verifier.py`
> 相关函数:`_route_source()`、`_std_rank()`、`_reflect_refine_standardization()`、`ABBVerifier.propose_requeries()`
> 衔接:第 14 篇讲主状态机如何把 record 从 `PENDING` 推到 `CODED/WITHHELD`。本篇放大两个 V11 关键增强:①根据 domain 决定查 SNOMED 还是 RxNorm;②当第一次标准化不够理想时,用反思生成新检索词,重新检索并复判。
> **V11 必看变化**:反思不是重新扩写缩写,也不是让 LLM 直接改 concept。它只让 LLM 提出同义/规范检索词,再走 retriever + verifier 的同一套受控流程。

## 核心速记

> 1. **多源路由很小但关键**:`_route_source(domain)` 只有一行:`Drug → rxnorm, 其它 → snomed`。它把候选词典/NER 推出来的 `domain` 转成 Milvus collection source。
> 2. **反思只改检索词,不改扩写**:`propose_requeries()` 只输出 search words,不能输出 SNOMED/RxNorm concept,也不能添加 subtype/cause/stage/site。
> 3. **采纳很保守**:`_std_rank()` 把标准化质量分成 2/1/0;只有新候选带来严格更好结果才继续,否则停。首轮横移可保留,后续横移不采纳。
> 次要(trivia):`REFLECT_MAX_ITER` 默认 2,可用环境变量做 ablation。

## 这一段在解决什么

本篇解决两个问题:

```text
1. 同一个 expansion 到底该查哪本库?
   aspirin → RxNorm
   chest pain → SNOMED

2. 第一次检索/verify 没拿到好概念时,怎么补救?
   不直接编概念
   而是换一个忠实同义检索词重新检索
```

一句话:

```text
多源路由决定去哪搜;
反思重检索决定搜不准时怎么再搜一次。
```

## 核心1 · 多源路由:Drug 走 RxNorm,其它走 SNOMED

代码非常小:

```python
@staticmethod
def _route_source(domain):
    return "rxnorm" if domain == "Drug" else "snomed"
```

但它很关键。

前面文档已经说过,候选的 `domain` 来自两处:

```text
primary 本地词典:
  abbr_candidates.py 里候选自带 domain

fallback LLM 候选:
  NERService.is_medical(expansion)
  ↓
  NER_LABEL_TO_DOMAIN 映射出 domain
```

然后主链路检索时:

```python
docs = self.retriever.retrieve(
    query=r["expansion"],
    top_k=10,
    domain_filter=None,
    domain_boost=r.get("domain"),
    score_threshold=0.6,
    source=self._route_source(r.get("domain")),
)
```

也就是说:

```text
domain = Drug
  → source = rxnorm
  → StdService 查 rxnorm_concepts

domain = Condition / Procedure / Measurement / ...
  → source = snomed
  → StdService 查 concepts_only_name
```

## 核心2 · 为什么要多源

SNOMED 和 RxNorm 的职责不同:

```text
SNOMED:
  疾病、症状、观察、检查、部位、手术等临床概念

RxNorm:
  药品成分、药物标准名
```

如果把药品也硬塞到 SNOMED:

```text
ASA → aspirin
```

可能检索到的不是最合适的药品 ingredient 标准概念。

V11 通过:

```text
abbr candidate domain = Drug
  ↓
_route_source("Drug") = "rxnorm"
  ↓
MedicalRetriever.retrieve(source="rxnorm")
  ↓
StdService.search_similar_terms(source="rxnorm")
  ↓
rxnorm_concepts collection
```

把药品扩写送到药品库里搜。

这也是第 01 篇里药品缩写段存在的意义:

```python
"ASA": [{"expansion": "aspirin", "domain": "Drug"}]
"MTX": [{"expansion": "methotrexate", "domain": "Drug"}]
"APAP": [{"expansion": "acetaminophen", "domain": "Drug"}]
"HCTZ": [{"expansion": "hydrochlorothiazide", "domain": "Drug"}]
"NTG": [{"expansion": "nitroglycerin", "domain": "Drug"}]
```

## 核心3 · 多源路由不是在 StdService 判断

要分清职责:

```text
ABBRService._route_source()
  业务判断:这个 mapping 应该查哪本库

MedicalRetriever.retrieve(source=...)
  接住 source,做重排/过滤/包装

StdService.search_similar_terms(source=...)
  按 source 选 collection 执行 Milvus 搜索
```

所以:

```text
StdService 不知道什么是 Drug
MedicalRetriever 也不判断什么是 Drug
它们只执行传入的 source
```

这是一条清楚的分层:

```text
domain → source 的业务路由在 ABBRService
source → collection 的物理映射在 StdService
```

## 核心4 · _std_rank():反思前先给标准化质量打等级

代码:

```python
@staticmethod
def _std_rank(s):
    """标准化质量秩:2=精确同名,1=忠实非同名,0=弃码。"""
    sc = s.get("std_concept")
    if not sc:
        return 0
    name = (sc.get("concept_name") or "").strip().lower()
    return 2 if name == s["expansion"].strip().lower() else 1
```

含义:

```text
rank = 2
  std_concept 概念名和 expansion 完全同名
  例如 expansion=chest pain, concept_name=Chest pain

rank = 1
  有 std_concept,但不是完全同名
  可能是 faithful parent / synonym

rank = 0
  没有 std_concept
  即 WITHHELD / 弃码
```

反思只在:

```text
rank < 2
```

时有意义。

如果已经精确同名:

```python
if rank_before == 2:
    return
```

直接停,没必要再折腾。

## 核心5 · _reflect_refine_standardization 的总体流程

简化流程:

```text
输入一个 record s
  ↓
算当前标准化质量 rank_before
  ↓
如果已经精确同名(rank=2) → 停
  ↓
让 verifier.propose_requeries() 提最多 2 个新检索词
  ↓
过滤掉已经试过的词
  ↓
用新检索词重新 MedicalRetriever.retrieve()
  ↓
合并旧候选池 + 新候选池
  ↓
如果没有新增候选 → 停
  ↓
verify_mappings() 对新候选池重新选 concept
  ↓
如果新结果 faithful 且可采纳 → 更新 std_cache/std_concept
  ↓
否则停
```

它的核心不是"让 LLM 想一个概念",而是:

```text
让 LLM 想一个更好的搜索词
再用真实检索和 verifier 复判
```

## 核心6 · propose_requeries():只产检索词

`ABBVerifier.propose_requeries()` 的 prompt 边界非常明确:

```text
Output SEARCH WORDS only.
Never invent or output a SNOMED concept.
Each phrasing must mean EXACTLY the same clinical thing as the expansion.
Do not add subtype, cause, stage, acuity, site, or mechanism.
```

例子:

```text
expansion = myocardial infarction
可提: heart attack

expansion = coronary artery disease
不可提: atherosclerosis
因为 atherosclerosis 是机制/病理过程,原 expansion 不一定声明
```

代码还做了额外过滤:

```python
if query_lower == expansion_lower:
    continue

mechanism_terms = ("arteriosclerosis", "atherosclerosis")
if any(term in query_lower and term not in expansion_lower for term in mechanism_terms):
    continue
```

所以它不仅靠 prompt,还用简单规则挡一部分机制词漂移。

## 核心7 · 新候选池怎么合并

反思拿到新检索词后:

```python
pool = {c["concept_id"]: c for c in s["std_cache"]}
for rq in new_terms:
    docs = self.retriever.retrieve(
        query=rq,
        top_k=10,
        domain_filter=None,
        domain_boost=s.get("domain"),
        score_threshold=0.6,
        source=self._route_source(s.get("domain")),
    )
    for doc in docs:
        md = doc["metadata"]
        if md["concept_id"] not in pool:
            pool[md["concept_id"]] = {...}
```

要点:

```text
1. 旧候选按 concept_id 放进 pool
2. 新检索词搜回来的候选也按 concept_id 合并
3. 已见过的 concept_id 不重复加入
```

然后:

```python
new_cands = sorted(
    pool.values(),
    key=lambda c: float(c.get("score") or 0),
    reverse=True
)[:15]
```

也就是:

```text
合并后按 raw score 排序
最多保留 15 个候选
```

如果新候选池没有变大:

```python
if len(new_cands) <= len(s["std_cache"]):
    return
```

说明没带回新证据,直接停。

## 核心8 · 新候选还要再过 verifier

新候选不是直接采用。

代码会重新调用:

```python
verification = self.verifier.verify_mappings(
    original_text=original_text,
    expanded_text=expanded_text,
    mapping_standardizations=[{
        "abbreviation": s["abbreviation"],
        "expansion": s["expansion"],
        "candidates": new_cands,
    }],
)
```

然后读取:

```python
ci = v.get("chosen_index") if v else None
faithful = bool(v and v.get("standardization_faithful") is True)
```

只有:

```text
faithful = true
chosen_index 合法
```

才考虑采纳。

这说明反思仍然走同一套受控验证链:

```text
新检索词 → 新候选 → verifier 选择 index
```

不是让 LLM 自己宣布哪个 concept 对。

## 核心9 · 采纳规则:必须在 requery_names 里,且 rank 更好才继续

采纳代码里有一个很保守的条件:

```python
refined = new_cands[ci]
requery_names = {q.strip().lower() for q in new_terms}
if refined.get("concept_name", "").strip().lower() in requery_names:
    ...
```

意思是:

```text
verifier 选中的 refined concept_name
必须刚好等于某个新检索词
```

这很保守。它倾向于采纳:

```text
LLM 提的规范检索词本身就是库里的概念名
```

然后计算:

```python
refined_rank = 2 if refined.concept_name == expansion else 1
```

如果:

```python
refined_rank <= rank_before
```

说明没有严格变好。

处理方式:

```python
if iter_index == 0:
    s["std_cache"] = new_cands
    s["std_concept"] = refined
return
```

含义:

```text
首轮允许保留一次横移结果;
但不继续多轮横移,避免越搜越偏。
```

如果:

```python
refined_rank > rank_before
```

则:

```python
s["std_cache"] = new_cands
s["std_concept"] = refined
accepted = True
```

并允许进入下一轮。

这就是注释里的:

```text
只有本轮秩严格变高才再来一轮,否则停。
首轮保留单趟反思;后续横移不采纳,避免多轮扰动。
```

## 核心10 · 反思如何把 WITHHELD 救回 CODED

在主状态机里:

```python
for r in pending:
    self._reflect_refine_standardization(r, text, current_expanded_text)
    if r.get("std_concept") and r["status"] == "WITHHELD":
        r["status"] = "CODED"
        r["failure"] = None
```

也就是说:

```text
第一次 verifier 没选到 std_concept
  → status = WITHHELD
  → 反思提出新检索词
  → 新检索词带回忠实 std_concept
  → status 从 WITHHELD 改为 CODED
```

这就是标准化反思的主要收益:

```text
不是改变 expansion
而是改善 expansion 到标准概念的对齐。
```

## 数据快照

### 多源路由

```json
{
  "abbreviation": "ASA",
  "expansion": "aspirin",
  "domain": "Drug"
}
```

路由:

```text
_route_source("Drug") → "rxnorm"
MedicalRetriever.retrieve(source="rxnorm")
StdService.search_similar_terms(source="rxnorm")
collection = rxnorm_concepts
```

### 反思重检索

```text
expansion:
"heart attack"

初次检索:
std_concept = None
status = WITHHELD

propose_requeries:
["myocardial infarction"]

重新检索:
Myocardial infarction 被召回

verify_mappings:
chosen_index = 0
standardization_faithful = true

状态:
WITHHELD → CODED
```

注意:这是结构示例,真实结果取决于 Milvus 当前库和 verifier 判断。

## 和 LangGraph 图包装的关系

`backend/graph/standardization_graph.py` 把这套逻辑可视化成图:

```text
route
  ├─ Drug → retrieve_rxnorm
  └─ else → retrieve_snomed
      ↓
verify
  ↓
propose_requery
  ↓
re_retrieve
  ↓
re_verify
  ↓
finalize
```

这个图不是 FastAPI 热路径,但它很好地说明了本篇逻辑:

```text
显式路由岔路 + 显式反思环
```

生产主链路仍然在 `ABBRService.expand_verify_with_retry()`。

## 其余细节(次要,一行带过)

【次要】`_route_source(None)` 会回退 snomed;fallback 候选如果 NER domain 没推出来,也会走 snomed;反思 `tried` 初始包含原 expansion,避免重复搜原词;`REFLECT_MAX_ITER` 默认 2;新候选排序用 raw `score`,不是 `rerank_score`。

## 死代码 / 盲肠提醒

- `_route_source()` 只认严格字符串 `"Drug"`。如果 domain 是 `"drug"`、`"Medication"` 或复合 label 没映射成功,都会走 snomed。
- `propose_requeries()` prompt 仍写 "SNOMED standardization",但 V11 多源下药品也可能走 RxNorm。文案应泛化成 standard terminology / SNOMED or RxNorm。
- 反思采纳要求 refined concept_name 必须等于 requery phrase,这很保守,可能漏掉 faithful 但不同名的候选。
- `new_cands` 排序用 raw score,没有显式使用 rerank_score,可能和 MedicalRetriever 的排序口径略不一致。

## 优化方向(更好 / 更稳)

1. **domain/source 枚举化**:避免 `"Drug"` 字符串写错导致药品走 SNOMED。
2. **路由规则扩展**:未来可支持 lab → LOINC、药品 → RxNorm、疾病/症状 → SNOMED,不止二分。
3. **fallback domain 增强**:NER 推不出 Drug 时可用药品词典/RxNorm quick lookup 辅助判断。
4. **反思 prompt 多源化**:把 SNOMED 文案改成 standard terminology candidates,并为 RxNorm 增加药品 rubric。
5. **采纳规则放宽但加保护**:不一定要求 concept_name 等于 requery,可以让 verifier 选 faithful candidate,再用 rank/不加信息规则兜底。
6. **排序口径统一**:合并候选池时考虑 `rerank_score`,不要只按 raw score。
7. **反思日志化**:把 new_terms、new_cands、是否采纳写入 mapping_states,便于错误分析。
8. **为反思加单测/ablation**:验证 `REFLECT_MAX_ITER=0/1/2` 对 benchmark 的影响。

## 会被追问 / 诚实局限(主动说)

- **路由很简单**:只有 Drug vs 非 Drug,不是完整医学 ontology router。
- **domain 质量决定路由质量**:词典 domain 或 NER domain 错了,source 就会错。
- **反思只救检索/标准化,不救错误扩写**:如果 coverage 把 MS 选错了,这里不会改 expansion。
- **反思也是 LLM 驱动**:虽然只产检索词,仍可能给出不合适的词,所以必须再检索再 verify。
- **采纳规则偏保守**:安全但可能 over-withhold。

## 面试怎么说

**合格版(30 秒)**:
> V11 的多源路由在 ABBRService 里很简单:domain 是 Drug 就查 RxNorm,否则查 SNOMED。标准化反思是在 verifier 没选到精确/忠实概念时,让 LLM 提最多两个同义检索词,再用同一套 retriever 和 verifier 重新检索复判。它不发明概念,也不改 expansion。

**优秀版(1 分钟)**:
> 我把 source 路由和物理检索分开:ABBRService 根据候选 domain 做业务路由,Drug 走 RxNorm,其它走 SNOMED;MedicalRetriever 和 StdService 只负责执行 source。标准化反思也保持受控:如果当前 std_concept 为空或不是精确同名,我先用 `_std_rank` 给质量打 0/1/2 分,再让 verifier 只提出忠实同义检索词,绝不输出概念。新检索词会重新跑 Milvus,合并候选池,再让 verifier 选 index。只有新结果 faithful 且质量秩变好才继续,否则停止,避免多轮漂移。这样反思救的是检索召回不足,不是让 LLM 直接编标准概念。

## 易错点 / 面试问答

**Q:多源路由在哪里做?**  
A:在 `ABBRService._route_source(domain)`。`domain=="Drug"` 返回 rxnorm,其它返回 snomed。

**Q:StdService 会判断 Drug 吗?**  
A:不会。StdService 只根据传入 source 选 collection。业务路由在 ABBRService。

**Q:反思会改 expansion 吗?**  
A:不会。它只为同一个 expansion 提新检索词,改善标准概念检索。

**Q:反思会直接输出 SNOMED/RxNorm concept 吗?**  
A:不会。`propose_requeries()` 只输出 search words,概念仍必须由 retriever 检索回来、verifier 从候选里选。

**Q:什么时候不反思?**  
A:当前概念已经精确同名(rank=2)、没有新检索词、没带回新候选、或新 verifier 结果不可采纳时都会停。

**Q:反思为什么要保守?**  
A:因为多轮 LLM 检索词容易语义漂移。医疗标准化宁可 WITHHELD,也不能为了编码而引入扩写没有声明的新含义。

## 一句话总结

> `ABBRService` 的多源路由和标准化反思是 V11 的两个增强点:路由用 `domain=="Drug"` 把药品扩写送到 RxNorm,其它概念走 SNOMED;反思在标准概念不精确或弃码时,只让 LLM 提忠实同义检索词,再重新检索和 verify,不改 expansion、不发明 concept。它用 `_std_rank` 和保守采纳规则控制反思漂移,目标是在安全边界内把 `WITHHELD` 尽量救回 `CODED`。

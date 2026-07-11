# 08_标准化反思重检索：如何把 WITHHELD 救回 CODED

> 这一章接着 07 讲：
> 07 解释了 verifier 选不到忠实标准概念时会 `WITHHELD`，08 解释系统怎么在安全边界内再试一轮。

---

## 先说结论

标准化反思不是让 LLM 重新扩写，也不是让 LLM 发明标准概念。

它只做一件事：

```text
当当前标准化结果不好时，
让 LLM 提出等价的检索词 requery，
再用这个检索词重新查 Milvus，
然后仍然交给 verifier 从候选里选。
```

核心函数：

```text
backend/services/abbr_service.py
ABBRService._reflect_refine_standardization()
```

辅助函数：

```text
backend/services/abbr_verifier.py
ABBVerifier.propose_requeries()
```

一句话：

> 反思救的是“检索词没召回好候选”，不是让 LLM 绕过检索和 verifier 直接给答案。

---

## 1. 为什么需要反思重检索

假设 expansion 是：

```text
shortness of breath
```

第一次向量检索可能没有找到最好的标准概念，或者找到一些相关但不忠实的候选：

```text
Shortness of breath questionnaire
Breathing observation
Respiratory assessment service
```

verifier 看到这些候选后可能说：

```text
chosen_index = null
standardization_faithful = false
```

于是 record 进入：

```text
WITHHELD
```

但医学上 `shortness of breath` 还有一个常见同义检索词：

```text
dyspnea
```

如果用 `dyspnea` 去查，可能就能召回更标准的概念。

这就是反思重检索要解决的问题：

```text
不是 expansion 错了，
而是第一次检索词可能没召回最合适的标准概念。
```

---

## 2. 反思发生在主状态机哪里

主状态机里 verifier 之后有一段：

```python
for r in pending:
    self._reflect_refine_standardization(r, text, current_expanded_text)
    if r.get("std_concept") and r["status"] == "WITHHELD":
        r["status"] = "CODED"
        r["failure"] = None
```

也就是说：

```text
先正常 retrieve + verify
  ↓
如果没有好概念，可能变 WITHHELD
  ↓
再调用反思重检索
  ↓
如果反思找到了 std_concept，就把 WITHHELD 救回 CODED
```

注意：

```text
反思不改变 expansion。
```

例如：

```text
SOB -> shortness of breath
```

反思可能用 `dyspnea` 去检索，但 record 的 expansion 仍然是：

```text
shortness of breath
```

---

## 3. 反思前先打质量等级：_std_rank

函数：

```python
def _std_rank(s):
    sc = s.get("std_concept")
    if not sc:
        return 0
    name = (sc.get("concept_name") or "").strip().lower()
    return 2 if name == s["expansion"].strip().lower() else 1
```

它把当前标准化质量分成三档：

| rank | 含义 |
|---:|---|
| `2` | 已经精确同名，最理想 |
| `1` | 有 std_concept，但不是精确同名，可能是忠实父概念或同义 |
| `0` | 没有 std_concept，也就是 WITHHELD / 弃码 |

反思一开始会算：

```python
rank_before = self._std_rank(s)
```

如果已经是 `2`：

```python
if rank_before == 2:
    return
```

意思是：

```text
已经精确同名了，就不要再反思。
```

这能避免过度优化，把本来很好的结果越改越偏。

面试说法：

> 反思前我会用 `_std_rank` 给当前标准化结果打等级。精确同名是 2，非精确但有概念是 1，弃码是 0。已经是精确同名时直接停止，不做多余反思。

---

## 4. REFLECT_MAX_ITER 控制最多反思几轮

代码：

```python
if max_iter is None:
    max_iter = int(os.getenv("REFLECT_MAX_ITER", "2"))
```

默认：

```text
REFLECT_MAX_ITER = 2
```

也就是说：

```text
最多尝试 2 轮反思。
```

为什么不能无限反思？

因为 LLM 多轮生成检索词时，容易发生：

- 语义漂移
- 越查越宽
- 加入 expansion 没有的信息
- 为了找到 code 而牺牲忠实性

所以 V11 的策略是：

```text
反思可以试，但必须短、保守、可停止。
```

面试说法：

> 反思不是无限 agent loop，而是有 `REFLECT_MAX_ITER` 限制，默认最多 2 轮。医疗标准化宁可 withheld，也不能让多轮 LLM 检索词漂移。

---

## 5. tried 防止重复查同一个词

代码：

```python
tried = {s["expansion"].strip().lower()}
```

反思开始时，先把原 expansion 放进 `tried`。

如果 expansion 是：

```text
shortness of breath
```

那么：

```python
tried = {"shortness of breath"}
```

后面 LLM 如果又提出：

```text
shortness of breath
```

会被过滤掉：

```python
new_terms = [q for q in requeries if q.strip().lower() not in tried]
```

这防止系统重复搜同一个 query，浪费轮次。

---

## 6. propose_requeries 只生成检索词

函数：

```text
ABBVerifier.propose_requeries()
```

输入：

```python
expansion
current_concept
seen_concepts
```

例如：

```text
expansion = shortness of breath
current_concept = none yet
seen_concepts = ["Shortness of breath questionnaire", "Respiratory assessment"]
```

它的 prompt 要求：

```text
Propose up to 2 alternative SEARCH phrasings
```

注意是：

```text
SEARCH phrasings
```

不是：

```text
SNOMED concept
```

更不是：

```text
最终 concept id
```

它还明确限制：

- 只输出 search words。
- 不能发明概念。
- 每个检索词必须和 expansion 表示完全相同的临床含义。
- 不能添加 subtype、cause、stage、acuity、site、mechanism。
- 想不到就返回空列表。

返回格式：

```json
{
  "requeries": ["dyspnea"]
}
```

面试说法：

> `propose_requeries()` 只让 LLM 生成等价检索词，不允许输出标准概念。标准概念仍然必须由 retriever 从 Milvus 召回，再由 verifier 选择。

---

## 7. propose_requeries 还有本地过滤

LLM 返回后，代码还会过滤：

```python
if not isinstance(q, str) or not q.strip():
    continue
```

空值和非字符串不要。

然后过滤和 expansion 一样的词：

```python
if query_lower == expansion_lower:
    continue
```

还有一个机制词保护：

```python
mechanism_terms = ("arteriosclerosis", "atherosclerosis")
if any(term in query_lower and term not in expansion_lower for term in mechanism_terms):
    continue
```

这个保护是为了避免类似：

```text
coronary artery disease
```

被反思成：

```text
atherosclerosis
```

因为后者可能是机制/病理过程，不一定等于原 expansion 陈述的临床概念。

最后只取前两个：

```python
return out[:2]
```

这说明：

```text
prompt 限制 + 代码过滤一起控制反思漂移。
```

---

## 8. 用新检索词重新查 Milvus

拿到 `new_terms` 后：

```python
for rq in new_terms:
    docs = self.retriever.retrieve(
        query=rq,
        top_k=10,
        domain_filter=None,
        domain_boost=s.get("domain"),
        score_threshold=0.6,
        source=self._route_source(s.get("domain")),
    )
```

它仍然走原来的检索链路：

```text
MedicalRetriever
  ↓
StdService
  ↓
Milvus
```

并且仍然使用：

```text
domain_boost = record.domain
source = _route_source(record.domain)
```

也就是说：

```text
Drug 还是查 RxNorm。
非 Drug 还是查 SNOMED。
```

反思不会绕过多源路由。

---

## 9. 新旧候选会合并去重

代码先把旧候选放进 pool：

```python
pool = {c["concept_id"]: c for c in s["std_cache"]}
```

然后新检索结果里，如果 concept_id 没见过：

```python
if md["concept_id"] not in pool:
    pool[md["concept_id"]] = {...}
```

这一步做的是：

```text
按 concept_id 合并新旧候选，避免重复。
```

然后排序取前 15：

```python
new_cands = sorted(
    pool.values(),
    key=lambda c: float(c.get("score") or 0),
    reverse=True
)[:15]
```

注意当前实现这里按 raw `score` 排，不是 `rerank_score`。

如果新候选数量没有变多：

```python
if len(new_cands) <= len(s["std_cache"]):
    return
```

意思是：

```text
没带回来新证据，就停止。
```

---

## 10. 新候选仍然要 verifier

反思拿到 `new_cands` 后，不会直接选。

仍然调用：

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

这说明：

```text
反思只是扩大候选池。
最终概念仍由 verifier 从候选里选。
```

然后再次检查：

```python
faithful = bool(v and v.get("standardization_faithful") is True)
ci = v.get("chosen_index") if v else None
```

并且要求：

```python
faithful
and isinstance(ci, int)
and not isinstance(ci, bool)
and 0 <= ci < len(new_cands)
```

和 07 章一样，仍然要合法 index + faithful。

---

## 11. 为什么采纳规则很保守

即使 verifier 选出了 refined concept，代码也不是无条件采纳。

先取：

```python
refined = new_cands[ci]
requery_names = {q.strip().lower() for q in new_terms}
```

然后要求：

```python
if refined.get("concept_name", "").strip().lower() in requery_names:
```

也就是说：

```text
新选中的 concept_name 必须和 requery phrase 对齐。
```

这很保守。

例如 requery 是：

```text
dyspnea
```

如果新候选里选中的 concept_name 也是：

```text
Dyspnea
```

就比较可信。

但如果 requery 是 `dyspnea`，verifier 选了一个相关但名字不同的候选，当前实现可能不会采纳。

这能降低漂移风险，但也可能漏掉忠实但不同名的好候选。

这属于后续可优化点。

面试说法：

> 当前反思采纳规则比较保守，要求 refined concept name 和 requery phrase 对齐，避免 LLM 用同义检索词把系统带到另一个相关但不同的概念上。代价是可能漏掉一些忠实但不同名的候选。

---

## 12. refined_rank 决定是否继续

如果候选可以采纳，会计算：

```python
refined_rank = 2 if refined["concept_name"].lower() == s["expansion"].lower() else 1
```

也就是：

| refined_rank | 含义 |
|---:|---|
| `2` | 新概念名和 expansion 精确同名 |
| `1` | 有忠实概念，但不是精确同名 |

然后和反思前的：

```python
rank_before
```

比较。

如果：

```python
refined_rank <= rank_before
```

说明没有严格变好。

当前生产代码里：

```python
if refined_rank <= rank_before:
    if iter_index == 0:
        s["std_cache"] = new_cands
        s["std_concept"] = refined
    return
```

含义可以理解为：

```text
第一轮可以保留一次横向改进，但不继续多轮漂移。
后续没有严格变好就停。
```

如果：

```python
refined_rank > rank_before
```

说明质量等级变好了，就采纳并允许循环继续。

---

## 13. WITHHELD 怎么被救回 CODED

回到主状态机：

```python
self._reflect_refine_standardization(r, text, current_expanded_text)
if r.get("std_concept") and r["status"] == "WITHHELD":
    r["status"] = "CODED"
    r["failure"] = None
```

所以救回条件是：

```text
反思后 record.std_concept 不为空
并且当前 status 还是 WITHHELD
```

然后：

```text
WITHHELD → CODED
failure 清空
```

也就是说：

```text
第一次 verifier 选不到 concept
  → WITHHELD
反思重检索找到忠实 concept
  → CODED
```

---

## 14. 用 SOB 举一个完整例子

原始 record：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "domain": "Condition",
  "status": "PENDING"
}
```

第一次检索：

```text
query = shortness of breath
source = snomed
```

std_cache：

```json
[
  {"concept_name": "Shortness of breath questionnaire"},
  {"concept_name": "Respiratory assessment"}
]
```

verifier：

```json
{
  "chosen_index": null,
  "standardization_faithful": false
}
```

状态：

```json
{
  "status": "WITHHELD",
  "failure": {
    "type": "CODE_WITHHELD"
  }
}
```

反思：

```json
{
  "requeries": ["dyspnea"]
}
```

重检索：

```text
query = dyspnea
source = snomed
```

新候选：

```json
[
  {"concept_name": "Dyspnea"}
]
```

重新 verifier：

```json
{
  "chosen_index": 0,
  "standardization_faithful": true
}
```

最终：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "std_concept": {
    "concept_name": "Dyspnea"
  },
  "status": "CODED",
  "failure": null
}
```

这是示意，不是本机真实运行结果。真实结果取决于 Milvus 数据和 LLM 输出。

---

## 15. 反思不会做什么

### 1. 不改 expansion

```text
shortness of breath
```

仍然是 record 的 expansion。

requery 只是检索词。

### 2. 不发明 concept

LLM 不能说：

```text
concept_id = xxx
```

概念必须从 Milvus 候选里来。

### 3. 不绕过 verifier

新候选仍然要走：

```text
verify_mappings()
```

### 4. 不无限循环

默认最多 2 轮。

### 5. 不为了有 code 牺牲忠实性

找不到就保持 `WITHHELD`。

---

## 16. 生产逻辑和 LangGraph 可视化的关系

生产热路径在：

```text
ABBRService.expand_verify_with_retry()
ABBRService._reflect_refine_standardization()
```

另外项目里还有：

```text
backend/graph/standardization_graph.py
```

它把同一套逻辑显式画成图：

```text
route
  ↓
retrieve_snomed / retrieve_rxnorm
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

这个图的作用是：

```text
实验可视化 / 面试展示 / 与生产逻辑做 parity 对照
```

不是 FastAPI 请求的主入口。

面试说法：

> 生产链路里的反思逻辑在 `ABBRService`，LangGraph 版本是把同样的 route-retrieve-verify-reflect loop 显式图形化，主要用于解释和 parity 检查，不是线上 API 必经路径。

---

## 17. 当前实现的真实边界

这块要诚实，因为面试可能会追问。

### 1. `propose_requeries()` 文案仍偏 SNOMED

函数 prompt 写的是：

```text
SNOMED standardization
```

但 V11 现在已经有 RxNorm。

实际检索时 source 仍然会按 domain 路由到 RxNorm/SNOMED，但 prompt 文案可以后续泛化成：

```text
standard medical terminology
```

### 2. 新候选排序用 raw score

反思合并新候选后：

```python
key=lambda c: float(c.get("score") or 0)
```

这里按 raw `score` 排，不是 `rerank_score`。

后续可以考虑统一排序逻辑。

### 3. 采纳规则可能过保守

当前要求：

```text
refined concept_name 必须等于 requery phrase
```

这减少漂移，但可能漏掉忠实不同名候选。

这些都属于可改进点，不影响你讲清当前 V11 主线。

---

## 18. 这章和前后章节怎么连起来

前一章 07：

```text
std_cache
  ↓
verifier
  ↓
CODED / WITHHELD
```

本章 08：

```text
WITHHELD 或非精确结果
  ↓
propose_requeries
  ↓
re_retrieve
  ↓
re_verify
  ↓
可能救回 CODED
```

下一章应该讲：

```text
API 最终怎么把 CODED/WITHHELD 映射成 mappings 和 standardized_entities
```

因为到这里，核心处理链路已经基本走完。

---

## 19. 面试怎么讲这章

30 秒版本：

> 当第一次标准化没有找到忠实 concept 时，系统不会直接失败，也不会让 LLM 编 concept，而是进入标准化反思。反思只让 LLM 提出和 expansion 等价的检索词，比如 `shortness of breath` 可以尝试 `dyspnea`，然后重新走 MedicalRetriever/Milvus 检索，再让 verifier 从新候选里选。如果选出忠实概念，就把 `WITHHELD` 救回 `CODED`；如果没有，就保持 `WITHHELD`。

2 分钟版本：

> 标准化反思解决的是召回不足的问题。第一次检索如果没有找到忠实候选，record 会进入 `WITHHELD`。这不一定说明 expansion 错了，也可能只是 query phrasing 没召回最标准的概念。所以 V11 在 verifier 后增加了 `_reflect_refine_standardization`。
>
> 反思过程很受控。首先 `_std_rank` 会给当前结果打等级：精确同名是 2，有非精确概念是 1，没有 concept 是 0；如果已经是精确同名就不反思。然后 `propose_requeries()` 让 LLM 只提出最多两个等价检索词，不能输出 concept，不能添加 subtype、cause、stage、site，也不能改变 expansion 含义。系统再用这些检索词重新查 Milvus，把新旧候选按 concept_id 合并，最后仍然调用 `verify_mappings()` 选择 faithful candidate。
>
> 采纳也很保守。新候选必须由 verifier 判断 faithful，chosen_index 合法，而且当前实现还要求 concept_name 和 requery phrase 对齐，避免多轮漂移。默认最多反思 2 轮。这个设计的原则是：反思可以改善召回，但不能让 LLM 绕过检索和 verifier 去编标准码。

---

## 20. 你要记住的 8 句话

1. 反思救的是检索召回，不是重新扩写。
2. `propose_requeries()` 只产检索词，不产 concept。
3. requery 必须和 expansion 等价，不能加新信息。
4. 新检索仍然走 SNOMED/RxNorm 路由。
5. 新旧候选按 `concept_id` 合并。
6. 新候选仍然必须经过 `verify_mappings()`。
7. 找到忠实 concept 才能把 `WITHHELD` 救回 `CODED`。
8. 默认最多反思 2 轮，宁可 withheld，也不漂移。

---

## 21. 下一章建议

下一章建议写：

```text
09_API最终返回_为什么mappings和standardized_entities不是一回事.md
```

因为核心链路已经处理完了，下一步最容易混的是返回结构：

```text
mappings 表示扩写成功
standardized_entities 表示编码成功
WITHHELD 有 mapping 但没有 standardized_entity
mapping_states 才能解释失败原因
```


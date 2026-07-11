# MedicalRetriever（RAG 检索层：向量召回 + 规则重排 + 过滤）

> 文件：`backend/services/medical_retriever.py`（105 行）
> 入口：`retrieve(query, top_k=5, domain_filter=None, score_threshold=None)`；核心私有方法 `_rerank_results()`
> 衔接：上一篇 StdService 给的是"按向量相似度排好的原始 TopK"。这一篇在它之上做两件事——**重排**（纠正向量相似度的偏差）和**过滤**（按 domain / score 门槛筛），再包成统一的 document 结构。它才是业务直接调用的 Retriever。

## 核心速记
> 1. **两阶段检索**：向量召回（StdService）+ 业务规则重排（本篇）。这是 RAG 工程里的经典套路，也是本篇最该讲的设计。
> 2. **重排规则**：完全相等 +0.5、前缀 +0.3、包含 +0.15；术语太长按长度扣分。目的是让"精确、标准、简短"的概念排前面。
> 3. **`rerank_score = 原始 score + bonus`**，按 rerank_score 重新排序；但**阈值过滤用的是原始 score**（两套口径，注意）。
> 次要（trivia）：`page_content` 拼接、`domain_filter`/`score_threshold` 可选、metadata 结构——扫一眼。

## 这一段在解决什么

大白话：**StdService 找回来的 TopK，向量相似度未必靠谱——有时"又长又宽泛但语义相关"的概念会排在"精确简短"的前面。MedicalRetriever 就是来"纠偏 + 筛选"的。**

```text
StdService 原始 TopK（纯向量相似度排序）
   ↓ _rerank_results：按字面匹配加分、按长度扣分，重新排序
   ↓ 过滤：domain 不符 / score 不够的踢掉
   ↓ 包成 {page_content, metadata} 文档结构
返回给业务用
```

## 核心1 · 为什么向量召回还不够，要规则重排（骨架，必背）

向量相似度只懂"语义像不像"，但它有个毛病：**语义相关但概念过宽/过长的术语，相似度也可能很高**。

举例：查 `chest pain`，Milvus 可能把这些都判得很像——

```text
Chest pain              ← 我们最想要的：精确、标准、简短
Chest pain on exertion  ← 也很像，但更具体、更长
Chest wall pain         ← 也相关，但不是同一个概念
```

纯按向量分数，未必能保证 `Chest pain` 排第一。于是加一层**规则重排**，用"字面匹配程度"和"术语长度"去纠偏：

```python
def _rerank_results(self, query, results):
    query_lower = query.lower()
    for item in results:
        concept_name = item["concept_name"].lower().strip()
        bonus = 0.0
        if concept_name == query_lower:            bonus += 0.5   # 完全相等：最该排第一
        elif concept_name.startswith(query_lower): bonus += 0.3   # 前缀匹配
        elif query_lower in concept_name:          bonus += 0.15  # 包含

        word_count = len(concept_name)             # 长度惩罚（见局限：其实是字符数）
        if   word_count > 10: bonus -= 0.25
        elif word_count > 6:  bonus -= 0.15
        elif word_count > 4:  bonus -= 0.08

        item["rerank_score"] = item["score"] + bonus
    results.sort(key=lambda x: x["rerank_score"], reverse=True)   # 按新分数降序
    return results
```

**为什么这是骨架**：这就是 **"向量召回（粗排）+ 业务规则重排（精排）"** 的两阶段检索思想。向量负责"把可能相关的捞回来"，规则负责"把最精确标准的顶上去"。医学标准化要的是**唯一精确的标准概念**，不是"语义沾边"，所以精排很关键。

## 核心2 · `retrieve`：重排之后再过滤、再打包（实现 + 真实数据）

```python
def retrieve(self, query, top_k=5, domain_filter=None, score_threshold=None):
    results = self.std_service.search_similar_terms(query=query, limit=top_k)  # 召回
    results = self._rerank_results(query, results)                              # 重排
    documents = []
    for item in results:
        if domain_filter is not None and item["domain_id"] != domain_filter:
            continue                                  # 领域不符，跳过
        if score_threshold is not None and item["score"] < score_threshold:
            continue                                  # 相似度不够，跳过（注意用原始 score）
        content = (f"Concept Name:{item['concept_name']}\n"
                   f"Fully Specified Name:{item.get('FSN','')}\n"
                   f"Domain:{item['domain_id']}\nConcept Code:{item['concept_code']}")
        documents.append({"page_content": content,
                          "metadata": {"input":..., "concept_id":..., "concept_name":...,
                                       "domain_id":..., "concept_code":...,
                                       "score":..., "rerank_score":...}})
    return documents
```

**真实调用**：`ABBRService` 这样调它——

```python
docs = self.retriever.retrieve(query=expansion, top_k=10, domain_filter=None, score_threshold=0.6)
# 然后只取 docs[:3]
```

翻译：召回 10 个 → 重排 → 踢掉 score < 0.6 的 → 取前 3 个作为这个 expansion 的 SNOMED 候选。

**两个要会讲的细节**：
- **`page_content` vs `metadata`**：`page_content` 是给"人/LLM 读"的拼接文本；`metadata` 是给"程序用"的结构化字段（含 score 和 rerank_score 两个分数）。这是 LangChain 文档的标准形态。
- **过滤用 `score`、排序用 `rerank_score`**：排序看重排后的分，但"够不够像"的门槛卡的是**原始向量相似度**。两套口径并存（见局限）。

## 数据快照：查 "chest pain"

```text
【入】 retrieve("chest pain", top_k=10, score_threshold=0.6)

【重排中】
  Chest pain            score 0.98  +0.5(相等) -0.15(10字符)  → rerank 1.33  ✅ 顶上来
  Chest pain on exertion score 0.95 +0.3(前缀) -0.25(超长)    → rerank 1.00
  Chest wall pain       score 0.90  +0.15(包含) -0.25(超长)   → rerank 0.80

【出】 documents（取前 3，每个含 page_content + metadata{score, rerank_score}）
```

## 会被追问 / 诚实局限（★主动说）

- **`word_count = len(concept_name)` 其实是"字符数"不是"词数"**，变量名误导。长术语惩罚是按**字符串长度**算的（`chest pain` = 10 个字符）。逻辑能用，但命名和注释（写的"长术语"）和实际不符。
  → 面试这么说："这里有个命名瑕疵——叫 word_count 但实际是字符长度，惩罚是按字符数。功能上能起到'压制超长术语'的作用，但严格说应该按词数或专门的概念宽泛度来衡量，这是我会修的点。" 主动说 = 诚实 + 细心，加分。
- **加减分全是拍脑袋常数**（+0.5/+0.3/+0.15、-0.25/-0.15/-0.08），没有数据支撑，靠经验定。
  → "这是 MVP 的启发式规则，下一步可以用标注数据学习权重，或换成 cross-encoder 重排模型。"
- **过滤用原始 score、排序用 rerank_score，两套口径**：重排把某个项顶上去了，但它可能因为原始 score < 0.6 又被门槛踢掉。两个分数的语义边界要想清楚。
  → "阈值卡原始相似度、排序用重排分，是有意分工，但容易混淆，我会在文档里写清。"
- **重排只看字面匹配**（`==`/`startswith`/`in`），不懂医学同义。查 "MI" 想匹配 "Myocardial infarction"，字面不匹配就拿不到 bonus，全靠向量分。
  → "字面规则是对向量的补充，不是替代；真正的同义匹配还得靠 embedding 或医学词表。"
- **`domain_filter` 调用方一直传 `None`**：这个过滤口子留了但没用上，接近死代码。
  → 诚实讲："预留了按领域过滤的能力（比如只要 Condition），当前主链路没用到。"

## 面试怎么说

**合格版（30 秒）**：
> MedicalRetriever 是 RAG 的检索层，做两阶段检索：先用 StdService 向量召回 TopK，再用规则重排——完全匹配、前缀、包含加分，术语过长扣分，把最精确标准的概念顶上去；之后按 score 阈值和 domain 过滤，包成带 metadata 的文档返回。

**优秀版（1 分钟）**：
> 纯向量召回有个问题：语义相关但过宽、过长的术语相似度也高，未必能保证那个精确标准概念排第一。所以我在 StdService 之上加了规则重排——对完全相等、前缀、包含分别加分，对过长术语扣分，再按重排分排序。这是"向量粗排 + 规则精排"的两阶段检索，医学标准化要的是唯一精确概念，精排很关键。之后按 score 阈值（主链路用 0.6）和 domain 过滤，输出 page_content + metadata 的标准文档。诚实说重排是启发式的：分数是经验常数、长度惩罚其实按字符数算（变量名 word_count 有点误导）、字面规则不懂同义词。下一步我想用标注数据学权重，或上 cross-encoder 重排模型。

## 易错点 / 面试问答

**Q：为什么向量召回后还要重排？** A：向量只懂语义相似，会把宽泛/过长但相关的术语排前面。医学标准化要精确唯一概念，所以用规则把完全/前缀匹配的短标准术语顶上去。

**Q：重排分怎么算的？** A：`rerank_score = 原始相似度 + bonus`。bonus 来自字面匹配加分（相等+0.5/前缀+0.3/包含+0.15）和长度惩罚（越长扣越多）。按 rerank_score 降序。

**Q：score 和 rerank_score 区别？过滤用哪个？** A：score 是原始向量相似度，rerank_score 是加 bonus 后的。排序用 rerank_score，但阈值过滤卡的是原始 score。

**Q：page_content 和 metadata 干嘛的？** A：page_content 是给人/LLM 看的拼接文本，metadata 是给程序用的结构化字段（含两个分数）。这是 LangChain 文档的标准结构。

**Q：这个重排有什么不足？** A：规则和分数是经验常数、长度惩罚按字符数（命名有瑕疵）、只看字面不懂同义。改进方向是学习式权重或 cross-encoder 重排。

## 一句话总结

> MedicalRetriever 是 RAG 检索层，实现"向量粗排 + 规则精排"两阶段：StdService 召回 TopK 后，按字面匹配加分、术语长度扣分重排，让精确标准概念排前，再按 score 阈值和 domain 过滤，输出 page_content + metadata 文档。主链路用 `top_k=10, score≥0.6` 取前 3。局限是重排为启发式（经验常数、长度惩罚按字符数、命名瑕疵、不懂同义词、domain_filter 未启用）——都可讲成"MVP 启发式，下一步上学习式重排"。

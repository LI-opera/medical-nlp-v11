# 批次 6 · 给 Codex 的指令(可整段复制)· 修检索过滤口径不一致

## 背景(这个 bug 是什么)

`MedicalRetriever.retrieve` 现在的顺序是:Milvus 取 top_k → `_rerank_results`(按 `rerank_score = score + bonus` 排序)→ filter。**问题在 filter**:它用 `score_threshold` 卡的是**原始向量分 `item["score"]`**(约第 94 行),不是 `rerank_score`。

后果:一个被 bonus(完全相等/开头/包含/domain 命中)顶到最前的候选,只要**原始分 < 阈值**就被砍掉——**重排白排了,排序和过滤用了两套互相打架的分数**。这在"raw 偏低但 domain/字面匹配很强"的医学概念上会真实丢答案。

> 注:**单纯把 filter 和 rerank 调换顺序解决不了**——filter 卡的还是 raw score,先筛后排和先排后筛通过的是同一批。必须改 threshold 卡哪个分数。

## 本批怎么修(改法 B)

filter 改成卡 **`max(原始分, 重排分)`**:**原始相似度 或 重排分,任一过线就保留**。
- 正 bonus(domain/字面命中)能把 raw 偏低的好候选**救回来**(修掉本 bug);
- 长度惩罚(负 bonus)**不会**把 raw 已达标的相关概念误删(`max` 取了 raw 那一边)。

工作在 `medical-refactor`(HEAD 若飘到 `medical` 先 `git switch -f medical-refactor`)。

## 铁律

1. **只改 `backend/services/medical_retriever.py` 一个文件**;不动 rerank 规则本身、不动 domain_filter、不动状态机/coverage/评测。
2. **先 Read 现状核行号**(下面是当前快照)。
3. 这是**真行为改动**(改了返回哪些 SNOMED 概念 → 喂 verify),**benchmark 会动**,必须门控:net 不退才合入。

---

## 改动 — `backend/services/medical_retriever.py · retrieve()`

找到过滤循环里这段(约 93–95 行):
```python
            #如果有最低分数限制，分数没达到就跳过
            if score_threshold is not None and item["score"] < score_threshold:
                continue
```
改成(卡 `max(原始分, 重排分)`):
```python
            #如果有最低分数限制：原始分 或 重排分 任一过线即保留
            #(修复:原来只卡 raw score,会把被 bonus 顶到最前、但 raw 偏低的好候选误删)
            if score_threshold is not None:
                effective_score = max(item["score"], item.get("rerank_score", item["score"]))
                if effective_score < score_threshold:
                    continue
```

> `rerank_score` 在 `_rerank_results` 里已给每个 item 赋值,这里 `.get` 兜底纯防御。

## (建议)临时打点:量一下这个 bug 实际发生几次

为了不靠拍脑袋判断值不值得改,**临时**在过滤循环里数一下"被救回的候选"(raw < 阈值 但 max 过线)。在 `retrieve` 里加一个计数,函数返回前 print。验收量完后**删掉这段**(别留在主链路):

```python
        # —— 临时打点(量完删) ——
        rescued = 0
        for item in results:
            if score_threshold is not None:
                if item["score"] < score_threshold <= max(item["score"], item.get("rerank_score", item["score"])):
                    rescued += 1
        if rescued:
            print(f"[retrieve] query={query!r} rescued_by_rerank={rescued}")
```

跑一次 benchmark,看日志里 `rescued_by_rerank` 总共出现多少次——这就是这个 bug 在评测集上的真实发生频率。**量完把这段删掉再正式提交。**

---

## 验收

1. **能编译**:`python -m compileall backend/services/medical_retriever.py`;批次1单测仍 `OK`。
2. **量 bug 频率**:带临时打点跑一次 `python backend/evaluation/run_benchmark_parallel.py`,记录 `rescued_by_rerank` 出现次数(顺带看总分)。
3. **删打点后正式 benchmark**:对比当前锚点(batch4 后 0.9595)。
   - **net ≥ 0.9595 → 合入**。
   - 若 net 掉:说明救回来的概念里有"raw 不相关、但被 bonus 误顶"的噪声,反而带偏了 verify。这时两条路:① 收紧 bonus(如 domain 0.2→0.1);② 回退本批,把这个 bug 作为"已知 + 量化"的诚实局限记进文档(面试也能讲:"我发现并量化了这个检索口径不一致,但当前评测集上修它净收益为负,所以保留观察")。
4. **判定**:net 不退 → 合入;掉 → 按上面处理。

## 诚实补充(面试可讲的更深一层)

- 还有个**更上游**的相关限制:Milvus `search_similar_terms(limit=top_k=10)` 先按**原始相似度**砍到 top-10,bonus 只能在这 10 个里重排——一个 raw 排第 15、但 domain 完全对的概念**根本进不来**。这是"检索-重排"两阶段的固有局限,扩大 top_k 可缓解但增延迟,**不在本批改**(本批只修过滤口径)。
- 这两点(过滤口径、召回池大小)合起来,就是"玩具 demo"和"认真做检索"的差别——能在面试里点出来本身就是加分。

## 提交

```bash
git add backend/services/medical_retriever.py
git commit -m "V11 batch6: fix retrieval filter to use max(raw_score, rerank_score) so reranking is not overridden by raw-score threshold"
```

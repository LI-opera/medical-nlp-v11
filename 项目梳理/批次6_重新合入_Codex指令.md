# 批次 6(重新合入)· 给 Codex 的指令(可整段复制)

## 决定背景(为什么明知 benchmark 没涨也合入)

batch6 上一轮被回退,不是因为修复有问题,而是**门控误伤**:

- 修复本身**正确**:filter 从只卡 raw score 改为卡 `max(raw, rerank)`,临时打点实测**触发 9 次救回**——bug 真实存在。
- 触发回退的唯一失败是 `ambiguous_004`(MS→multiple sclerosis),它发生在 **coverage(LLM)选词阶段、在检索过滤之前**,与本修复**因果无关**,是已知的上游 LLM 抖动(噪声地板)。
- 即:同一份修复逻辑,带打点那轮 0.9595、干净两轮 0.9459,**分差全来自 ambiguous_004 抖动**,不是修复。

**结论(用户拍板 A)**:这是正确修复,74 例小 benchmark 太小太吵、奖励不到它(救回的候选多落在不判分的整句 standardize 存档路径)。当有**直接机理证据**证明回归无关时,机理压过噪声代理——**按正确性合入**。

## 改动 — 重新应用到 `backend/services/medical_retriever.py · retrieve()`

找到过滤循环里(约 93–95 行):
```python
            #如果有最低分数限制，分数没达到就跳过
            if score_threshold is not None and item["score"] < score_threshold:
                continue
```
改为:
```python
            #如果有最低分数限制：原始分 或 重排分 任一过线即保留
            #(修复:原来只卡 raw score,会把被 bonus/domain 顶到最前、但 raw 偏低的好候选误删;
            # 重排和过滤用同一口径,避免互相打架)
            if score_threshold is not None:
                effective_score = max(item["score"], item.get("rerank_score", item["score"]))
                if effective_score < score_threshold:
                    continue
```

**不带临时打点**(上一轮已量化:8 次调用、9 个候选,大多落在整句 standardize 存档路径)。只改这一处,别动别的。

## 验收(本批不走"net 必须涨"硬门槛)

1. **能编译**:`python -m compileall backend/services/medical_retriever.py`;批次1单测仍 `OK`。
2. **确认无新增异常**:跑一次 `python backend/evaluation/run_benchmark_parallel.py`,数字应在 0.9459~0.9595 之间波动,**唯一变动应只有 ambiguous_004**(MS 抖动)。若出现**别的**类塌陷,才需警觉(说明修复真有副作用,回退)。
3. **判定**:编译过 + 单测过 + 无 ambiguous_004 以外的新失败 → 合入(这是"按正确性合入、benchmark 噪声内持平"的有意决定)。

## 提交（commit message 要把理由写进历史）

```bash
git add backend/services/medical_retriever.py
git commit -m "V11 batch6 (re-merge): retrieval filter uses max(raw, rerank_score).

Correct fix for a real bug (rerank could be overridden by raw-score threshold;
instrumentation showed 9 candidates rescued). Merged on correctness despite flat
benchmark: the only benchmark mover was ambiguous_004 (MS picked at the LLM
coverage stage, upstream of and causally unrelated to this retrieval filter),
i.e. noise-floor, not a regression. 74-case benchmark is too small to reward this."
```

## 记一笔(诚实局限,文档/面试用)

- 更上游仍有 Milvus 先按 raw score 截断 top_k=10 的两阶段召回限制(raw 排 15 但 domain 全对的概念进不来),本批未处理。
- 这是"benchmark 驱动开发的边界"的一个真实案例:**信号低于噪声地板时,要靠机理判断,不能让一个吵闹的小代理否决正确的工程**。

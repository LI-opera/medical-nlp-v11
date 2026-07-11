# 批次 L3 Stage-6e:LangGraph 图的反思环对齐生产 6d(纯代码保真)

## 目的
生产 6d 已把 reflection 升级成"有界迭代(秩门 + 首轮横移/次轮严格)"。但 6c 的图仍是
`max_reflect_iter=1` 单趟。本轮把图的反思环逻辑改成与生产 6d **同款**,使图"代码上"也能转 2 轮——
让可视化不撒谎(图能力上限 == 生产)。**复用生产 `svc._std_rank`,不重写判秩。**

## 行为/验收口径
- 在 4 条 parity 样例上行为不变(SOB 仍单轮横移到 Dyspnea;其余不进/不触发第 2 轮)。
- 所以**验收仍是 render_graph parity ALL PASS**;第 2 轮逻辑虽不被这 4 样例触发,但代码要对齐 6d。

## 修改文件
- `backend/graph/standardization_graph.py`(改 __init__ 默认 + 替换 3 个反思节点 + _enter_reflect + n_route 初始化)
- `项目梳理/L3_pipeline.mmd`(render 重新生成,内容应不变)
- `项目梳理/后续改进/codex对项目的改动日志.md`

## 改动(targeted,逐处替换)

### 1) `__init__` 默认改 2
```python
    def __init__(self, svc: Optional[ABBRService] = None, max_reflect_iter: int = 2):
```

### 2) `n_route` 增加 tried / 停止标志的初始化
```python
    def n_route(self, state):
        # 显式决策节点:把选中的源标到 record 上;真正分流在条件边。
        r = state["record"]
        r["source"] = self.svc._route_source(r.get("domain"))
        r.setdefault("_tried", {r["expansion"].strip().lower()})
        r["_reflect_stop"] = False
        return {"record": r}
```

### 3) 整体替换 `n_propose_requery`
```python
    def n_propose_requery(self, state):
        svc, r = self.svc, state["record"]
        r.pop("_requeries", None)
        r.pop("_new_cands", None)
        r["_rank_before"] = svc._std_rank(r)          # 复用生产判秩
        sc = r.get("std_concept")
        chosen_name = sc.get("concept_name") if sc else None
        seen = [c["concept_name"] for c in r["std_cache"]]
        requeries = svc.verifier.propose_requeries(r["expansion"], chosen_name, seen) or []
        tried = r.setdefault("_tried", {r["expansion"].strip().lower()})
        new_terms = [q for q in requeries if q.strip().lower() not in tried]
        if not new_terms:
            r["_reflect_stop"] = True
            r["_requeries"] = []
        else:
            tried.update(q.strip().lower() for q in new_terms)
            r["_requeries"] = new_terms
        return {"record": r, "reflect_iter": state.get("reflect_iter", 0) + 1}
```

### 4) 整体替换 `n_re_retrieve`(无新候选时置停)
```python
    def n_re_retrieve(self, state):
        svc, r = self.svc, state["record"]
        requeries = r.get("_requeries") or []
        if requeries:
            pool = {c["concept_id"]: c for c in r["std_cache"]}
            for rq in requeries:
                docs = svc.retriever.retrieve(
                    query=rq, top_k=10, domain_filter=None,
                    domain_boost=r.get("domain"), score_threshold=0.6,
                    source=svc._route_source(r.get("domain")),
                )
                for doc in docs:
                    md = doc["metadata"]
                    if md["concept_id"] not in pool:
                        pool[md["concept_id"]] = {
                            "concept_id": md["concept_id"],
                            "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"],
                            "concept_code": md["concept_code"],
                            "score": md["score"],
                            "rerank_score": md.get("rerank_score"),
                        }
            new_cands = sorted(pool.values(), key=lambda c: float(c.get("score") or 0), reverse=True)[:15]
            r["_new_cands"] = new_cands if len(new_cands) > len(r["std_cache"]) else None
            if r["_new_cands"] is None:
                r["_reflect_stop"] = True
        return {"record": r}
```

### 5) 整体替换 `n_re_verify`(同款"首轮横移采纳/次轮严格"规则)
```python
    def n_re_verify(self, state):
        svc, text, expanded, r = (
            self.svc, state["text"], state["expanded_text"], state["record"],
        )
        new_cands = r.get("_new_cands")
        requeries = r.get("_requeries") or []
        rank_before = r.get("_rank_before", svc._std_rank(r))
        reflect_iter = state.get("reflect_iter", 0)
        r.pop("_requeries", None)
        r.pop("_new_cands", None)
        if new_cands:
            verification = svc.verifier.verify_mappings(
                original_text=text, expanded_text=expanded,
                mapping_standardizations=[{
                    "abbreviation": r["abbreviation"], "expansion": r["expansion"],
                    "candidates": new_cands,
                }])
            vs = verification.get("mapping_validations", [])
            v = vs[0] if vs else None
            ci = v.get("chosen_index") if v else None
            faithful = bool(v and v.get("standardization_faithful") is True)
            handled = False
            if faithful and isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(new_cands):
                refined = new_cands[ci]
                requery_names = {q.strip().lower() for q in requeries}
                if refined.get("concept_name", "").strip().lower() in requery_names:
                    refined_rank = 2 if refined.get("concept_name", "").strip().lower() == r["expansion"].strip().lower() else 1
                    if refined_rank <= rank_before:
                        # 横移:仅首轮(reflect_iter==1)采纳,之后停;次轮起不采纳横移
                        if reflect_iter == 1:
                            r["std_cache"] = new_cands
                            r["std_concept"] = refined
                            if r["status"] == "WITHHELD":
                                r["status"], r["failure"] = "CODED", None
                        r["_reflect_stop"] = True
                        handled = True
                    else:
                        # 秩严格变高:采纳并允许继续
                        r["std_cache"] = new_cands
                        r["std_concept"] = refined
                        if r["status"] == "WITHHELD":
                            r["status"], r["failure"] = "CODED", None
                        handled = True
            if not handled:
                r["_reflect_stop"] = True
        return {"record": r}
```

### 6) 整体替换 `_enter_reflect`(加 _reflect_stop 判断)
```python
    def _enter_reflect(self, state):
        r = state["record"]
        if state.get("reflect_iter", 0) >= self.max_reflect_iter:
            return "finalize"
        if r.get("_reflect_stop"):
            return "finalize"
        return "propose_requery" if _reflectable(r) else "finalize"
```

## 验收
1. `python -m compileall backend/graph` 通过。
2. `python backend/graph/render_graph.py`:
   - **parity 仍 ALL PASS**(4 样例行为不变;SOB 仍 Dyspnea);
   - mermaid 重新生成,节点/边应**与 6c 相同**(图形状没变,变的是 maxiter 与环内逻辑);
3. 顺带确认生产没被碰:`git status` 里不应出现 abbr_service.py / api 改动。
4. 贴回 parity 结果。

## 合入 / 回滚
- parity ALL PASS 则提交 standardization_graph.py + L3_pipeline.mmd + 日志。
- 回滚:退回 6c 版(max_reflect_iter=1 单趟)。生产不依赖,零影响。

## 一句话
图现在"代码能力上限"== 生产(都最多 2 轮),可视化不再撒谎;行为在现数据上仍与之前一致(parity 兜底)。

# 批次 L3 Stage-6d:反思真迭代(放进生产)+ 补硬 case + ablation

## 目的
把 reflection 从"一次性单趟"升级成"**有界自纠环**":每轮换同义词重检索→verify 重选,
**只有这轮把标准化质量秩严格抬高才再来一轮**,否则立刻停。放进**生产** `abbr_service`
(不是只在 LangGraph 图里),让 agentic 自纠环真正服务请求。用 concept + 主 benchmark 卡关,
并补几个"俗称→规范概念"的硬 case 做 ablation。

## 关键不变量(必须验证)
- **老 16 条 concept gold:`REFLECT_MAX_ITER=1` 与 `=2` 跑出来必须完全一致**
  (它们 ≤1 轮就定;若两者不同说明逻辑改错了)。
- 主 benchmark 仍 71/74=0.9595(reflection 只改标准化层,不改扩写判分)。
- render_graph parity 仍 ALL PASS(本轮不碰 backend/graph/,4 样例不触发第 2 轮)。

## 设计:停/留规则
- 质量秩 `_std_rank`:**2=精确同名 / 1=忠实非同名 / 0=弃码**。
- **接受**这轮结果:沿用保守门(忠实 + 新概念名 ∈ 这轮改写词)。
- **继续**下一轮 当且仅当:本轮秩**严格变高**(0→1 或 1→2)。
- **停**(任一):秩=2 / 无没试过的新改写词 / 无新候选入池 / 本轮没采纳 / 秩没涨 / 到 max_iter。
- `max_iter` 读 env `REFLECT_MAX_ITER`(默认 2);初始 verify(1)+ 最多 2 轮反思 = 最多 3 次判定。

## 修改文件
- `backend/services/abbr_service.py`(新增 `_std_rank`;整体替换 `_reflect_refine_standardization`)
- `backend/evaluation/concept_benchmark_cases.py`(末尾补 3 条硬 case,confirmed=False)
- `项目梳理/后续改进/codex对项目的改动日志.md`

## 改动 1:`abbr_service.py`
在 `_route_source` 附近新增静态方法:
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

**整体替换** `_reflect_refine_standardization`(现 line 101-163)为:
```python
    def _reflect_refine_standardization(self, s, original_text, expanded_text, max_iter=None):
        """batch10 → L3-6d:标准化反思【真迭代】。
        每轮:非精确同名(或弃码)时换同义词重检索 → verify 重选(保守门);
        只有本轮秩严格变高才再来一轮,否则停。带新证据,非同源复判。
        max_iter 默认读 env REFLECT_MAX_ITER(默认 2),便于 ablation。
        """
        if max_iter is None:
            max_iter = int(os.getenv("REFLECT_MAX_ITER", "2"))
        tried = {s["expansion"].strip().lower()}
        for _ in range(max_iter):
            rank_before = self._std_rank(s)
            if rank_before == 2:
                return  # 已精确同名,不可能更好
            chosen = s.get("std_concept")
            chosen_name = chosen.get("concept_name") if chosen else None
            seen = [c["concept_name"] for c in s["std_cache"]]
            requeries = self.verifier.propose_requeries(s["expansion"], chosen_name, seen) or []
            new_terms = [q for q in requeries if q.strip().lower() not in tried]
            if not new_terms:
                return  # 没有没试过的新方向
            tried.update(q.strip().lower() for q in new_terms)

            pool = {c["concept_id"]: c for c in s["std_cache"]}
            for rq in new_terms:
                docs = self.retriever.retrieve(
                    query=rq, top_k=10, domain_filter=None,
                    domain_boost=s.get("domain"), score_threshold=0.6,
                    source=self._route_source(s.get("domain")),
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
            if len(new_cands) <= len(s["std_cache"]):
                return  # 没带回新候选

            verification = self.verifier.verify_mappings(
                original_text=original_text, expanded_text=expanded_text,
                mapping_standardizations=[{
                    "abbreviation": s["abbreviation"], "expansion": s["expansion"],
                    "candidates": new_cands,
                }],
            )
            vs = verification.get("mapping_validations", [])
            v = vs[0] if vs else None
            ci = v.get("chosen_index") if v else None
            faithful = bool(v and v.get("standardization_faithful") is True)
            accepted = False
            if faithful and isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(new_cands):
                refined = new_cands[ci]
                requery_names = {q.strip().lower() for q in new_terms}
                if refined.get("concept_name", "").strip().lower() in requery_names:
                    s["std_cache"] = new_cands
                    s["std_concept"] = refined
                    accepted = True
            if not accepted:
                return  # 本轮没产出可采纳结果
            if self._std_rank(s) <= rank_before:
                return  # 横移/没提升 → 采纳但不再循环
        return
```
注:`os` 已在 abbr_service.py 导入(load_dotenv 处),无需新增 import。调用方
`expand_verify_with_retry`(line 325-329)不变,反思后仍由它把 WITHHELD 升 CODED。

## 改动 2:`concept_benchmark_cases.py` 末尾补 3 条硬 case(confirmed=False)
俗称→规范概念,天生需要改写;**先 confirmed=False 只打印**,跑完 ablation 看实际名再锁。
不设 domain(→ snomed):
```python
    {
        "label": "HBP", "expansion": "high blood pressure", "expect": "concept",
        "prefer": "Hypertensive disorder", "accept": [], "confirmed": False,
        "note": "L3-6d 多轮观察:俗称→规范;待 ablation 锁定实际概念名",
    },
    {
        "label": "HRTATTACK", "expansion": "heart attack", "expect": "concept",
        "prefer": "Myocardial infarction", "accept": [], "confirmed": False,
        "note": "L3-6d 多轮观察:俗称→规范;待锁定",
    },
    {
        "label": "FLUID_LUNG", "expansion": "fluid in the lungs", "expect": "concept",
        "prefer": "Pulmonary edema", "accept": [], "confirmed": False,
        "note": "L3-6d 多轮观察:俗称→规范;待锁定",
    },
```

## 验收(按顺序)
1. `python -m compileall backend/services backend/evaluation` 通过。
2. **不变量①(老用例零回归)**:分别跑
   - `set REFLECT_MAX_ITER=1` → `python backend/evaluation/run_concept_benchmark.py`
   - `set REFLECT_MAX_ITER=2` → `python backend/evaluation/run_concept_benchmark.py`
   - 老 16 条硬 gold 在两次下**必须完全一致**(PASS 16/16、canonical 15/16);贴两次输出。
   (PowerShell:`$env:REFLECT_MAX_ITER=1; python ...` 然后 `$env:REFLECT_MAX_ITER=2; python ...`)
3. **ablation(新 case 看环值不值)**:看 3 条新 case 在"②待锁定"区,
   `max_iter=1` vs `=2` 选中的概念名/是否 PASS 有没有差异——
   - 有差异 = 第 2 轮真的够到了更好的概念(环的实证),把实际名抄回 prefer、择机翻 confirmed=True;
   - 无差异 = 诚实记录"现数据上多轮无额外收益",case 仍留作样本多样性。
4. **不变量②**:`python backend/evaluation/run_benchmark.py` 仍 71/74=0.9595。
5. **不变量③**:`python backend/graph/render_graph.py` parity 仍 ALL PASS(本轮没碰 graph)。
6. 贴回:两次 concept 输出(含新 case)、main 结果。

## 合入 / 回滚
- 不变量①②③ 全过则提交 abbr_service.py + concept_benchmark_cases.py + 日志。
- 回滚:`_reflect_refine_standardization` 退回单趟版 + 删 `_std_rank` + 删 3 条新 case。
- 若 ablation 显示多轮在现数据上**净负**(老用例被扰动或主 bench 掉),按纪律回退。

## 面试讲法
- "反思是**有界自纠环**:verify 判不够忠实/不够规范 → 改写检索词重检索重判,**只在质量秩严格上升时才继续**,
  最多 N 轮(env 可调),并有'无新词/无新候选/结果不动'多重早停——**保证终止、不空转**。"
- "我没把它停在'转一轮的装饰环':它在生产里真迭代;并补了俗称类测试样本做 ablation,
  诚实量化多轮到底带来多少额外收益。"

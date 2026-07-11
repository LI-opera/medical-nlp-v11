# L3 · Stage-3 给 Codex 的指令(可整段复制)· 标准化按 NER domain 路由(Drug→RxNorm)

## 背景与范围

Stage-2 已让检索能按 `source` 选库。本批**接上路由**:标准化检索时,按每条 mapping 的 **domain**(NER 早就产的标签)选源——**`domain=="Drug"` → `source="rxnorm"`(查药品库),其它 → `source="snomed"`**。这是 L3 的 agentic 路由决策,**确定性、不加 LLM、不花钱**(延续"激活死参数":domain 从前只做软加分,现在升级成路由开关)。

> **对现有用例行为中性**:当前 benchmark 里没有 Drug-domain 的输入,全部走 snomed,所以主 bench / concept bench 应**完全不变**。真正点亮要等 Stage-4 补药品缩写 + 药品 gold。

**铁律**:只改 `backend/services/abbr_service.py`(加一个小路由 helper + 给两处 `retriever.retrieve(...)` 调用加 `source=`);不动检索器/verify/coverage;benchmark 必须持平。

工作在 `medical-refactor`。

---

## A · `abbr_service.py` 加路由 helper

在 `ABBRService` 类里(例如 `_build_expanded_text_deterministic` 附近)新增:

```python
    @staticmethod
    def _route_source(domain):
        """L3 路由:按 NER/词典 的 domain 选标准化检索源。
        Drug → RxNorm 药品库;其它(Condition/Procedure/Measurement/...) → SNOMED。"""
        return "rxnorm" if domain == "Drug" else "snomed"
```

## B · 给状态机主检索调用加 `source=`

先 Read 核对。`expand_verify_with_retry` 里、每个 pending 检索 SNOMED 候选那处(形如 `docs = self.retriever.retrieve(query=r["expansion"], top_k=10, domain_filter=None, domain_boost=r.get("domain"), score_threshold=0.6)`)——**加一个参数 `source=self._route_source(r.get("domain"))`**:

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
> 变量名以你 Read 到的实际为准(11A 后该循环变量是 `r`;若是别的名照实改)。

## C · 给反思精炼里的重检索也加 `source=`

`_reflect_refine_standardization` 里、换同义词重检索那处(形如 `docs = self.retriever.retrieve(query=rq, top_k=10, domain_filter=None, domain_boost=s.get("domain"), score_threshold=0.6)`)——同样加 `source`,**用这条 mapping 的 domain 路由**:

```python
            docs = self.retriever.retrieve(
                query=rq,
                top_k=10,
                domain_filter=None,
                domain_boost=s.get("domain"),
                score_threshold=0.6,
                source=self._route_source(s.get("domain")),
            )
```
> 反思和主检索路由到同一个源,保持一致。

---

## 验收

1. **编译+import**:`python -m compileall backend/services` 通过;`ABBRService` 干净 import。
2. **路由 helper 正确**:
   ```bash
   python -c "import sys;sys.path.append('backend');from services.abbr_service import ABBRService as A;print(A._route_source('Drug'), A._route_source('Condition'), A._route_source(None))"
   ```
   预期:`rxnorm snomed snomed`。
3. **现有 benchmark 持平(行为中性)**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74=0.9595**;`python backend/evaluation/run_concept_benchmark.py` → 仍 PASS 11/11、canonical 10/11。(现有用例 domain 都不是 Drug,全走 snomed,不变。)
4. **判定**:1-3 全过 → 合入。

## 提交

```bash
git add backend/services/abbr_service.py
git commit -m "V11 L3 stage3: route standardization retrieval by NER domain (Drug->rxnorm, else->snomed). Deterministic, no extra LLM; behavior-neutral on current cases (no Drug inputs yet), benchmarks flat."
```
> 下一步 Stage-4:词典补药品缩写(ASA→aspirin、MTX→methotrexate…,domain=Drug)+ concept bench 补药品 gold(走 rxnorm),这样药品真路由到 RxNorm、能量出新能力。Stage-5 量、Stage-6 可选 LangGraph 收尾。

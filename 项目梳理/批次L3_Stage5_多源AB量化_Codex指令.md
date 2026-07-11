# 批次 L3 Stage-5:多源 A/B 量化(SNOMED-only vs RxNorm 路由)

## 目的
L3 的卖点是"按 domain 路由到第二知识源 RxNorm"。但 SNOMED 本身也含药品/物质概念,
所以必须诚实量化:**同样的药品词,强制走 SNOMED vs 走 RxNorm,标准化结果差在哪**
(选中概念名 / concept_code / domain_id / top 相似分 / 是否弃码)。
本轮只新增一个一次性测量脚本,**不改主链路、不改任何 service、不加 LLM 行为**(verify 照常调用)。

## 修改文件
- 新增 `backend/evaluation/run_source_ab.py`
- `项目梳理/后续改进/codex对项目的改动日志.md`(追加日志)

## 脚本要求(`run_source_ab.py`)
复刻 concept benchmark 的标准化那一步,但**对每个药品词跑两次**:一次 source="snomed",一次 source="rxnorm"。

```python
"""
L3 Stage-5:多源 A/B 量化
对每个药品扩写,分别强制走 SNOMED 和 RxNorm,跑 检索 top-10 → verify 选概念,
并排打印:选中概念名 / concept_code / domain_id / top1 相似分 / 是否弃码。
目的:诚实回答"路由到 RxNorm 相对只用 SNOMED 到底改变了什么"。
跑法:python backend/evaluation/run_source_ab.py(需 Milvus + DeepSeek key)
"""
import sys, os
from pathlib import Path
os.environ["ERROR_LOG_RUNTIME"] = "0"
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
from services.abbr_service import ABBRService

DRUGS = ["aspirin", "methotrexate", "acetaminophen", "hydrochlorothiazide", "nitroglycerin"]
TOP_K, SCORE_TH = 10, 0.6

def run_one(svc, expansion, source):
    docs = svc.retriever.retrieve(
        query=expansion, top_k=TOP_K, domain_filter=None,
        score_threshold=SCORE_TH, source=source,
    )
    cands = [d["metadata"] for d in docs]
    top1 = docs[0]["score"] if docs else None      # 若 retrieve 返回的键名不是 score,按实际键名取
    res = svc.verifier.verify_mappings(
        original_text=f"The patient took {expansion}.",
        expanded_text=f"The patient took {expansion}.",
        mapping_standardizations=[{
            "abbreviation": expansion, "expansion": expansion, "candidates": cands,
        }],
    )
    mv = (res.get("mapping_validations") or [{}])[0]
    ci = mv.get("chosen_index")
    chosen = None
    if (isinstance(ci, int) and not isinstance(ci, bool)
            and 0 <= ci < len(cands) and mv.get("standardization_faithful") is True):
        chosen = cands[ci]
    return {
        "n_cands": len(cands),
        "top1_score": round(top1, 4) if isinstance(top1, (int, float)) else top1,
        "name": chosen.get("concept_name") if chosen else None,
        "code": chosen.get("concept_code") if chosen else None,
        "domain": chosen.get("domain_id") if chosen else None,
    }

def main():
    svc = ABBRService()
    print(f"{'drug':<20}{'source':<8}{'chosen':<28}{'code':<10}{'domain':<14}{'top1':<8}")
    print("-" * 88)
    for drug in DRUGS:
        for source in ("snomed", "rxnorm"):
            r = run_one(svc, drug, source)
            name = r["name"] if r["name"] else "(弃码)"
            print(f"{drug:<20}{source:<8}{name:<28}{str(r['code']):<10}{str(r['domain']):<14}{str(r['top1_score']):<8}")
        print()

if __name__ == "__main__":
    main()
```

注意:`docs` 元素里相似分的键名以现有 retrieve 返回结构为准(concept benchmark runner 里取的是 `d["metadata"]`)。
如果 `d["score"]` 不存在,按 retrieve 实际返回的分数键名改 `top1`;取不到就打印 None,不要报错。

## 验证
1. `python -m compileall backend/evaluation` 通过。
2. `python backend/evaluation/run_source_ab.py`(需 Milvus + 两个 collection + DeepSeek key)。
3. 把完整输出表贴回来(10 行:5 药 × 2 源)。不需要改任何 gold。

## 我要从输出里读什么(给面试结论用)
- **RxNorm 列**:应都命中 Drug 域 ingredient(如 aspirin / code 1191),粒度=成分。
- **SNOMED 列**:看它给什么——可能命中 substance/product 概念(不同 code、可能 domain=Substance/Drug),
  也可能因为候选粒度不对而被 verify 弃码。
- **差异即价值**:若 SNOMED 给的是 substance 而 RxNorm 给的是可对接处方/相互作用的 Drug ingredient,
  这就是"为什么需要第二知识源"的实证;若两边几乎一样,也要诚实说"该词上多源增益有限"。

## 合入
- 这是测量脚本,可与日志一起提交,或留作本地一次性脚本由你决定。
- 不动主链路,无回滚风险;不要它时直接删 `run_source_ab.py`。

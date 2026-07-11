# 批次 L3 Stage-4:补药品缩写(domain=Drug)+ concept bench 药品 gold(走 RxNorm)

## 目的
Stage-3 已让标准化检索按 NER domain 确定性路由(Drug→RxNorm,其它→SNOMED),
但当前没有任何 domain=Drug 的输入,所以路由还没被真正点亮。
本轮补两件事,让"多源标准化"这个新能力第一次跑出分:
1) 词典补一批**成分级(ingredient)药品缩写**,每条标 `domain="Drug"` → 生产链路自动路由到 RxNorm;
2) concept benchmark 补几条**药品 gold**,并让 runner 按 domain 路由,使药品 gold 查 RxNorm 库。

本轮**不加 LLM 调用、不改检索器、不改 verify/coverage/路由逻辑**。

## 修改文件
- `backend/data/abbr_candidates.py`
- `backend/evaluation/concept_benchmark_cases.py`
- `backend/evaluation/run_concept_benchmark.py`
- `项目梳理/后续改进/codex对项目的改动日志.md`(按惯例追加本轮日志)

## 改动 1:`abbr_candidates.py` 末尾(`}` 之前)新增药品缩写段
在 `ABBR_CANDIDATES` 字典里追加以下条目(都是单一、无歧义的成分级药名,
domain 一律 "Drug";key 大写,与现有规则一致):

```python
    # Drugs (ingredient-level; domain=Drug → 路由到 RxNorm)
    "ASA": [
        {"expansion": "aspirin", "domain": "Drug"},
    ],
    "MTX": [
        {"expansion": "methotrexate", "domain": "Drug"},
    ],
    "APAP": [
        {"expansion": "acetaminophen", "domain": "Drug"},
    ],
    "HCTZ": [
        {"expansion": "hydrochlorothiazide", "domain": "Drug"},
    ],
    "NTG": [
        {"expansion": "nitroglycerin", "domain": "Drug"},
    ],
```

注:不要动 `abbr_service.py` 里那个 `self.abbr_dict`——它在检测流程里未被使用。

## 改动 2:`concept_benchmark_cases.py` 末尾(列表 `]` 之前)新增药品 gold
这些是**新增的 domain=Drug 用例**,带新字段 `"domain": "Drug"`(现有用例没有这个键)。
**先全部 `confirmed=False`**(只打印、不计入准确率):因为 RxNorm 里 ingredient 概念名的
确切写法要以本机首跑实际输出为准。首跑后据实把 prefer/accept 改成库里真实名字,再翻 `confirmed=True`。
这是本项目一贯的 gold 锁定纪律(同 RA_room_air 注释口径)。

```python
    {
        "label": "ASA", "expansion": "aspirin", "expect": "concept",
        "domain": "Drug",
        "prefer": "aspirin", "accept": [], "confirmed": False,
        "note": "Drug→RxNorm;待首跑锁定 ingredient 概念名",
    },
    {
        "label": "MTX", "expansion": "methotrexate", "expect": "concept",
        "domain": "Drug",
        "prefer": "methotrexate", "accept": [], "confirmed": False,
        "note": "Drug→RxNorm;待首跑锁定",
    },
    {
        "label": "APAP", "expansion": "acetaminophen", "expect": "concept",
        "domain": "Drug",
        "prefer": "acetaminophen", "accept": [], "confirmed": False,
        "note": "Drug→RxNorm;待首跑锁定(美式 RxNorm 用 acetaminophen)",
    },
    {
        "label": "HCTZ", "expansion": "hydrochlorothiazide", "expect": "concept",
        "domain": "Drug",
        "prefer": "hydrochlorothiazide", "accept": [], "confirmed": False,
        "note": "Drug→RxNorm;待首跑锁定",
    },
    {
        "label": "NTG", "expansion": "nitroglycerin", "expect": "concept",
        "domain": "Drug",
        "prefer": "nitroglycerin", "accept": [], "confirmed": False,
        "note": "Drug→RxNorm;待首跑锁定",
    },
```

## 改动 3:`run_concept_benchmark.py` 按 domain 路由(两处)
现状 runner 检索写死走默认 snomed,药品 gold 会查错库。改两处:

(a) 初次检索 retrieve() 增加 source 路由参数:
```python
        cands = [
            d["metadata"]
            for d in svc.retriever.retrieve(
                query=case["expansion"],
                top_k=TOP_K,
                domain_filter=None,
                score_threshold=SCORE_TH,
                source=svc._route_source(case.get("domain")),
            )
        ]
```

(b) 反思用的 `s` 字典,domain 从写死 None 改成读 case:
```python
        s = {
            "abbreviation": case["label"],
            "expansion": case["expansion"],
            "std_cache": cands,
            "std_concept": init,
            "domain": case.get("domain"),
        }
```
说明:现有 11 条用例没有 "domain" 键 → `case.get("domain")` 为 None → `_route_source(None)="snomed"`,
所以**老用例行为完全不变**;只有新增 Drug 用例走 rxnorm。

## 验证(按顺序)
1. `python -m compileall backend/services backend/evaluation backend/data` 通过。
2. 路由 helper 不变,顺手再确认:
   `python -c "import sys; sys.path.append('backend'); from services.abbr_service import ABBRService as A; print(A._route_source('Drug'), A._route_source(None))"`
   → 期望 `rxnorm snomed`。
3. `python backend/evaluation/run_concept_benchmark.py`(需 Milvus + 两个 collection):
   - 老 11 条硬 gold 仍 PASS 11/11、canonical 10/11(不受影响);
   - 新 5 条药品用例出现在"②待锁定假设"区,**打印出 RxNorm 实际选中的概念名**。
   - 把实际名抄回 prefer/accept,确认无误后将这 5 条 `confirmed` 改 True(下一轮或本轮二跑)。
4. `python backend/evaluation/run_benchmark.py`:Total 74 / Correct 71 / 0.9595 不变
   (主 benchmark 用例里没有药品缩写 → 行为中性)。
5. 端到端冒烟(可选,证明生产链路真的路由到 RxNorm):
   对一句含药品缩写的文本跑一次完整 `process`,确认 ASA 被扩成 aspirin、
   标准化命中 RxNorm 概念而非 SNOMED。

## 合入
- 验证通过后提交:`backend/data/abbr_candidates.py`、
  `backend/evaluation/concept_benchmark_cases.py`、
  `backend/evaluation/run_concept_benchmark.py`、本日志文件。
- 其它历史未提交文件不纳入本轮。

## 回滚
- 删除 abbr_candidates.py 新增的 Drug 段;
- 删除 concept_benchmark_cases.py 新增的 5 条;
- run_concept_benchmark.py 把 (a) 的 `source=...` 删掉、(b) 的 domain 改回 None。

## 为什么这么设计(给面试讲)
- **路由开关是确定性的、零成本的**:domain 这个标签 NER/词典早就产了,Stage-3 只是把它从
  "检索软加分(domain_boost)"升级成"选哪个知识库的硬开关"。不引入新 LLM、不引入新不确定性。
- **gold 先 confirmed=False 再据实锁定**:概念名以库里真实输出为准,不拍脑袋写死,避免假 gold。
- **老用例零影响**:没有 domain 键的用例默认 snomed,新老隔离,benchmark 可对照。
- **诚实局限**:成分级缩写是策展的小集合(演示+评测定位),不是完整药品缩写库;
  真实场景需接 UMLS/RxNorm 全量缩写表 + 处理剂型/复方歧义(如 APAP 复方制剂)。

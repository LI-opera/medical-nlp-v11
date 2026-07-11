# ABBRCandidateRetriever —— 主候选召回 / 本地词典读取层 · V11

> 文件:`backend/services/abbr_candidate_retriever.py`(约 25 行,全项目最薄的服务之一)
> 衔接:第 01 篇讲的是 `ABBR_CANDIDATES` 这本"缩写候选词典";本篇就是**读这本词典的服务层**。它是 V11 缩写召回的第一层(primary):先查本地受控候选,查不到才交给下一篇 fallback LLM。
> **V11 变化(必看)**:候选不再只是字符串 expansion,而是 `{expansion, domain}`。所以本层返回的每个候选都带 `domain`,后面会影响 `domain_boost` 和 SNOMED/RxNorm 多源路由。

## 核心速记

> 1. **一句定位**:ABBRCandidateRetriever 是缩写候选召回第一层,只做"输入缩写 → 查本地词典 → 返回候选列表"。
> 2. **确定性优先**:它不调用 LLM、不看上下文、不做消歧。词典有就返回,词典没有就返回空列表,让上层去 fallback。
> 3. **V11 关键字段**:返回结构是 `{abbreviation, expansion, domain}`。`domain` 从词典透传出来,后面决定检索领域软加分,并可能驱动 Drug → RxNorm 路由。
> 次要(trivia):`upper().strip()` 做输入归一化;`ABBR_CANDIDATES.get(abbr, [])` 查不到不报错。

## 这一段在解决什么

大白话:**给它一个缩写,它去本地候选词典里把所有可能全称查出来。**

```text
输入: "CP"
输出:
[
  {"abbreviation": "CP", "expansion": "chest pain", "domain": "Condition"},
  {"abbreviation": "CP", "expansion": "cerebral palsy", "domain": "Condition"},
  {"abbreviation": "CP", "expansion": "chronic pancreatitis", "domain": "Condition"}
]
```

如果词典里没有:

```text
输入: "XYZ"
输出: []
```

它只负责召回候选,不负责判断哪个候选最适合当前句子。

## 核心1 · 全部代码就几行

```python
from data.abbr_candidates import ABBR_CANDIDATES

class ABBRCandidateRetriever:
    def retrieve(self, abbreviation: str):
        abbr = abbreviation.upper().strip()
        candidates = ABBR_CANDIDATES.get(abbr, [])
        return [
            {
                "abbreviation": abbr,
                "expansion": c["expansion"],
                "domain": c.get("domain")
            }
            for c in candidates
        ]
```

拆开看就是三步:

```text
1. abbreviation.upper().strip()
   统一大写、去首尾空格

2. ABBR_CANDIDATES.get(abbr, [])
   查本地词典,查不到返回空列表

3. 组装成统一候选结构
   abbreviation / expansion / domain
```

这就是典型的"薄服务层"。它薄不是问题,反而说明职责很干净。

## 核心2 · 为什么第一层不用 LLM

V11 的召回策略是:

```text
能用本地确定性词典解决的,先用本地词典;
本地词典没有覆盖的,才让 LLM fallback 生成候选。
```

为什么?

| 对比项 | 本地词典 primary | LLM fallback |
|---|---|---|
| 速度 | 极快 | 慢,要请求模型 |
| 成本 | 0 token | 花 token / API 成本 |
| 稳定性 | 完全确定 | 输出可能波动 |
| 可解释性 | 来自候选库 | 需要看 prompt 和模型输出 |
| 覆盖 | 受词典限制 | 长尾更灵活 |
| 幻觉风险 | 低 | 更高 |

所以 primary retriever 的设计哲学是:

```text
常见缩写走确定性候选库
长尾未知缩写才交给 LLM 兜底
```

这和整个项目 retrieval-first / constrained-LLM 的思路是一致的。

## 核心3 · 它只召回,不消歧

对于多义缩写,它不会偷偷帮你选一个。

例如:

```text
CP
  chest pain
  cerebral palsy
  chronic pancreatitis
```

这三个会全部返回。

为什么不在这里选?

因为这个模块没有上下文。它只知道缩写是 `CP`,不知道原句是:

```text
The patient reports CP after exertion.
```

还是:

```text
Child with CP has motor delay.
```

没有上下文就不应该强行选择。所以本层只追求:

```text
高召回:正确答案尽量在候选里
```

真正的上下文判断交给:

```text
ABBRCandidateCoverageEvaluator.evaluate()
```

也就是后面的 coverage 闸门。

## 核心4 · V11 的 domain 字段为什么重要

第 01 篇讲过,`ABBR_CANDIDATES` 的候选已经从:

```python
"CP": ["chest pain", "cerebral palsy"]
```

升级成:

```python
"CP": [
    {"expansion": "chest pain", "domain": "Condition"},
    {"expansion": "cerebral palsy", "domain": "Condition"}
]
```

本层会把 `domain` 原样透传:

```python
"domain": c.get("domain")
```

这个字段后面有两种用途。

### 1. 传给 MedicalRetriever 做 domain_boost

在 `ABBRService.expand_verify_with_retry()` 中:

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

如果候选 domain 是 `Condition`,检索结果里 `domain_id == "Condition"` 的概念会加分。

### 2. 传给 _route_source 做多源路由

```python
def _route_source(domain):
    return "rxnorm" if domain == "Drug" else "snomed"
```

含义:

```text
domain == Drug → source = rxnorm
其它            → source = snomed
```

所以如果词典里:

```python
"ASA": [{"expansion": "aspirin", "domain": "Drug"}]
```

后面标准化 `aspirin` 时就会走 RxNorm 药品库。

一句话:

```text
ABBRCandidateRetriever 不只是拿 expansion,还把后续路由需要的 domain 信号带出来。
```

## 它在 ABBRService 主链路里的位置

调用位置在 `ABBRService._get_abbreviation_candidates()`:

```text
text
  ↓
按空格和标点切 token
  ↓
_should_consider_abbreviation(raw_token, known_abbrs)
  ↓
abbr = raw_token.upper()
  ↓
candidates = self.candidate_retriever.retrieve(abbr)
candidate_source = "primary"
  ↓ 如果 candidates 为空
fallback_retriever.retrieve(...)
candidate_source = "fallback"
  ↓
coverage_evaluator.evaluate(...)
```

也就是说 primary retriever 是 fallback 之前的第一道候选来源。

如果它查到了候选:

```text
candidate_source = "primary"
```

如果它返回空:

```text
candidate_source = "fallback"
```

这个 `candidate_source` 后面也会被放入 record / mappings,让最终结果知道某个扩写来自本地词典还是 LLM 兜底。

## 数据快照

### 单义缩写

```python
retrieve("HTN")
```

```json
[
  {
    "abbreviation": "HTN",
    "expansion": "hypertension",
    "domain": "Condition"
  }
]
```

### 多义缩写

```python
retrieve("MS")
```

```json
[
  {
    "abbreviation": "MS",
    "expansion": "multiple sclerosis",
    "domain": "Condition"
  },
  {
    "abbreviation": "MS",
    "expansion": "mitral stenosis",
    "domain": "Condition"
  }
]
```

### 药品缩写

```python
retrieve("ASA")
```

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "domain": "Drug"
  }
]
```

后续:

```text
domain Drug → _route_source() → rxnorm
```

### 未收录缩写

```python
retrieve("XYZ")
```

```json
[]
```

后续:

```text
空列表 → fallback retriever
```

## 和上下游的边界

### 上游:ABBRService 的 gate

本层不会判断 token 是否像缩写。这个判断在:

```python
ABBRService._should_consider_abbreviation()
```

所以:

```text
是否进入候选召回流程 = 上游 gate 的责任
进入后查本地词典 = ABBRCandidateRetriever 的责任
```

### 下游:CoverageEvaluator

本层不会判断候选是否符合上下文。这个判断在:

```python
ABBRCandidateCoverageEvaluator.evaluate()
```

所以:

```text
列出所有候选 = ABBRCandidateRetriever
结合上下文选 best_expansion = CoverageEvaluator
```

### 兜底:FallbackRetriever

本层查不到时,才走:

```python
ABBRCandidateFallbackRetriever.retrieve()
```

所以:

```text
primary = 本地词典,确定性
fallback = LLM,长尾兜底
```

这三层边界非常清楚。

## 其余细节(次要,一行带过)

【次要】它没有 `__init__`,因为不需要加载模型/连接外部服务;没有异常捕获,因为 `.get(..., [])` 已经保证未命中不报错;返回 list 保持和 fallback retriever 的 candidates 字段形状接近,方便上层统一处理。

## 死代码 / 盲肠提醒

- 文件底部有一段三引号注释,解释列表推导式等价写法,属于学习注释,不影响功能。
- 本文件没有明显死代码。
- V9 文档里的示例结构只有 `{abbreviation, expansion}`,V11 真实代码已经多了 `domain`,后续写文档/讲项目时不要漏掉。

## 优化方向(更好 / 更稳)

1. **给候选加 source/priority/frequency**:现在只返回 expansion/domain,没有先验频率。可加 `prior` 或 `frequency`,让 coverage 有更强先验。
2. **候选排序**:目前完全按词典顺序返回。未来如果有频率/科室元数据,可以先按先验排序,但仍保留全部候选。
3. **domain 枚举化**:现在 domain 是自由字符串,建议抽成常量/枚举,避免 `Drug` 写成 `drug` 导致路由失败。
4. **接真实缩写库**:将 `ABBR_CANDIDATES` 替换为 UMLS / MeDAL / Medical Abbreviation Meta-Inventory 等更大来源时,上层接口可以不变。
5. **记录命中来源**:虽然上层会标 `candidate_source="primary"`,也可以在每个 candidate 里补 `source:"local_dict"` 方便日志追踪。
6. **校验词典结构**:启动时或测试中检查每个候选都有 expansion/domain,提前发现脏数据。

## 会被追问 / 诚实局限(主动说)

- **覆盖取决于本地词典**:词典没有的缩写,本层一定召不回来。
- **没有上下文消歧**:多义候选全部返回,不会选 best。
- **没有先验概率**:无法表达 `CP` 在某科室更常见 chest pain 还是 cerebral palsy。
- **domain 质量影响后面**:如果词典 domain 填错,后续 domain_boost / RxNorm 路由也会受影响。
- **它很薄,但薄是设计**:它是候选库的统一接口,不是复杂智能模块。

## 面试怎么说

**合格版(30 秒)**:
> ABBRCandidateRetriever 是缩写候选召回第一层。它把输入缩写 upper/strip 后去本地 `ABBR_CANDIDATES` 查表,返回所有候选 `{abbreviation, expansion, domain}`。它不调用 LLM,不做上下文消歧,查不到就返回空列表,让上层走 fallback。

**优秀版(1 分钟)**:
> 这层体现的是确定性优先。常见医学缩写先走本地候选词典,速度快、零成本、可解释,只有词典没有覆盖时才走 LLM fallback。它对多义缩写不会提前做判断,比如 CP 的多个候选全部返回,因为没有上下文就不该强行消歧;真正选择 best_expansion 是 coverage evaluator 的职责。V11 里我还把候选结构升级成 `{expansion, domain}`,这个 domain 后面会进入 domain_boost,并且 Drug 会路由到 RxNorm,其它走 SNOMED。所以它虽然很薄,但承接了从候选词典到后续多源标准化的关键信号。

## 易错点 / 面试问答

**Q:它和 `abbr_candidates.py` 有什么区别?**  
A:`abbr_candidates.py` 是数据字典,ABBRCandidateRetriever 是读取这个数据的服务接口。一个是数据,一个是服务层。

**Q:它会根据上下文选择候选吗?**  
A:不会。它只返回所有候选。上下文选择在 coverage evaluator。

**Q:查不到会怎样?**  
A:返回空列表,不报错。上层看到空列表后走 LLM fallback。

**Q:为什么不用 LLM 直接召回?**  
A:确定性优先。本地词典更快、更稳、更可解释。LLM 只用于词典覆盖不到的长尾缩写。

**Q:domain 在这里有什么用?**  
A:这里不使用 domain,只透传。后面 MedicalRetriever 会用它做 domain_boost,ABBRService 会用它做 Drug→RxNorm / 其它→SNOMED 路由。

**Q:如果 domain 写错怎么办?**  
A:后续检索排序或路由可能受影响。这个风险应该通过词典结构校验、枚举约束和 benchmark 暴露。

## 一句话总结

> ABBRCandidateRetriever 是 V11 缩写召回的 primary 层:它把缩写归一化后查本地 `ABBR_CANDIDATES`,返回所有受控候选 `{abbreviation, expansion, domain}`,查不到返回空交给 LLM fallback。它不消歧、不看上下文、不调用模型,但负责把词典里的 domain 信号带入后续 domain_boost 和 SNOMED/RxNorm 路由,是"确定性候选优先、LLM 兜底"设计的第一块拼图。

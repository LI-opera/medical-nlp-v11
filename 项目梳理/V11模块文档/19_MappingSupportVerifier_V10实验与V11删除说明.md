# MappingSupportVerifier —— V10 实验模块与 V11 删除说明

> 文件:历史文件 `backend/services/mapping_support_verifier.py`、历史测试 `backend/test_mapping_support_verifier.py`;当前 V11 源码中二者已删除。
> 衔接:第 17 篇 benchmark 暴露当前短板是 `low_context_over_expansion`;第 18 篇 Error Analysis 把失败归为 `Over Expansion / Extra Abbreviation Expansion`。本篇讲一个历史实验:曾经为这个问题做过 `MappingSupportVerifier`,但因为 over-abstention 没进主链路,并在 V11 架构收敛时删除。
> **V11 必看定位**:这不是当前活节点。V11 当前主链路不 import、不初始化、不调用 `MappingSupportVerifier`。`abbr_service.py` 里仍能看到 `mapping_support_results = []`,只是历史出口字段/兼容痕迹,不是实际校验结果。

## 核心速记

> 1. **它想解决什么**:低上下文过度扩写。也就是候选库里有 `LMN/QRS/ABC`,但当前句子上下文不够,系统仍然把它扩了。
> 2. **它怎么做**:让 LLM 判断“当前文本是否足够支持这个 `abbreviation -> expansion` 映射”,prompt 倾向保守,不够就 `supported=false`。
> 3. **为什么没留下**:它确实能挡掉一些低上下文误扩,但太保守,会把本该扩的 `CP -> chest pain` 等也拒掉,造成 over-abstention;benchmark 净收益不成立。
> 4. **V11 当前状态**:`mapping_support_verifier.py` 和对应测试源文件已删;主流程只剩 `coverage_evaluator + mapping 状态机 + verifier + 错误分析`。
> 次要(trivia):当前 `backend/services/__pycache__` 里可能有旧 `.pyc` 残留,不能代表源码仍存在;判断活模块只看 `.py` 源码和 import/call 链。

## 这一段在解决什么

这个模块的出发点很合理。

系统做缩写扩写时,最容易出现一种错误:

```text
The patient was evaluated for LMN.
```

词典或 fallback 能找到:

```text
LMN -> lower motor neuron
```

医学上这确实是一个常见缩写解释,但这句话只说“evaluated for LMN”,上下文并没有给出足够证据证明这里一定是 lower motor neuron。

所以当时想加一个专门的二次判断:

```text
这句话本身,够不够支持这个映射?
```

如果不够,就拒绝扩写。

这就是 `MappingSupportVerifier` 的定位:不是判断某个 expansion 医学上是否存在,而是判断“当前上下文能不能支撑它”。

## V10 实验时它大概处在什么位置

历史设计里,它位于“候选选择之后、最终扩写之前”。

大致链路:

```text
识别缩写
  ↓
候选召回
  ↓
coverage 先选出可能 expansion
  ↓
MappingSupportVerifier 再问:当前上下文够不够支持这个 mapping?
  ↓
supported=true  → 允许进入扩写
supported=false → 拒绝/过滤
```

它和 coverage 的差别在于:

| 模块 | 问的问题 | 结果倾向 |
|---|---|---|
| `coverage_evaluator` | 候选集中有没有被上下文支持的合理扩写 | 保证召回和基本消歧 |
| `MappingSupportVerifier` | 已选中的这个 mapping 是否被当前句子充分支持 | 更保守,专门防低上下文误扩 |
| `abbr_verifier` | 检索回来的标准概念是否忠实于 expansion | V11 中主要管 SNOMED/RxNorm 标准化 |

它真正想补的洞是:

```text
coverage 可能说“有一个常见解释能用”
但 mapping support 想说“这句话给的信息还不够,先别扩”
```

## 历史实现意图

V9 文档中记录的历史接口是:

```python
verify(text, abbreviation, expansion) -> MappingSupportResult
```

结构化结果类似:

```python
class MappingSupportResult(BaseModel):
    supported: bool
    confidence: float
    reason: str
```

调用后期望得到:

```json
{
  "supported": false,
  "confidence": 0.3,
  "reason": "The context is too weak to support this expansion."
}
```

它的 prompt 重点不是:

```text
这个医学缩写是否存在?
```

而是:

```text
当前这句话是否提供了足够上下文支持这个扩写?
```

并且策略偏保守:

```text
上下文不足就拒绝
```

这个设计是针对低上下文场景的刹车。

## 它为什么失败:over-abstention

`MappingSupportVerifier` 的问题不在于“完全没用”,而在于“刹车太狠”。

它能挡住一些该挡的:

```text
The patient was evaluated for LMN.
LMN -> lower motor neuron
```

这种上下文弱,确实应该谨慎。

但它也容易误伤:

```text
The patient denies CP.
CP -> chest pain
```

在临床短句里,`denies CP` 已经足够常见、足够支持 `chest pain`。如果 verifier 仍然因为句子短而拒掉,就从“防过度扩写”变成了“过度弃权”。

这就是 over-abstention:

```text
本该扩写的缩写,被过度保守策略拒绝了。
```

工程上最关键的不是它能不能修一两个低上下文 case,而是:

```text
修掉低上下文误扩带来的收益
是否大于误伤正常缩写带来的损失
```

当时的结论是:净收益不成立。

## V11 为什么删除它

V11 做过一次架构收敛,目标是把主链路压回一条清晰的 `expand_verify_with_retry`。

批次 7 指令里明确写过:

```text
V11 主链路只剩 expand_verify_with_retry 这一条。
彻底清理 V9 遗留:删掉不在主链路的旧方法、它们依赖的服务文件、引用它们的测试。
```

其中列出的删除对象包括:

```text
backend/services/mapping_support_verifier.py
backend/test_mapping_support_verifier.py
```

并且审计结论是:

```text
api/main.py、run_benchmark.py、run_benchmark_parallel.py 都不引用 graph 或任何待删符号;
主链路不用 mapping_support_verifier。
```

所以 V11 里删除它不是误删,而是一次有意的架构收敛:

```text
保留有净收益的主状态机
删除没有进入主链路的实验模块
减少 LLM 判断层数和维护负担
```

## 当前代码里还有什么痕迹

当前 `backend/services/abbr_service.py` 里还能看到:

```python
mapping_support_results = []
```

以及 attempts/final_result 中保留:

```python
"mapping_support_results": mapping_support_results
```

但这个字段现在永远只是空列表。

它的作用更接近:

```text
历史兼容字段 / 调试出口残留
```

不是实际运行的校验结果。

当前主链路并没有:

```python
from services.mapping_support_verifier import MappingSupportVerifier
self.mapping_support_verifier = MappingSupportVerifier()
self.mapping_support_verifier.verify(...)
```

也没有源码文件:

```text
backend/services/mapping_support_verifier.py
```

所以阅读 V11 时要注意:

```text
看到 mapping_support_results 字段 != MappingSupportVerifier 还在工作
```

它只是旧接口形状留下的一块空位。

## V11 用什么替代它

V11 没有把 `MappingSupportVerifier` 原样替换成另一个模块,而是把问题拆到更稳定的位置:

### 1. coverage evaluator 负责前置候选覆盖

第 11 篇讲过,`ABBRCandidateCoverageEvaluator` 在候选召回后判断:

```text
候选集中是否至少存在一个合理解释?
哪个 expansion 最适合当前上下文?
```

这是当前处理“该不该扩”的主要闸门。

### 2. mapping 粒度状态机负责失败隔离

第 14 篇讲过,V11 把每个缩写变成一条独立 record:

```text
NOT_EXPANDED / PENDING / CODED / WITHHELD / ABSTAIN
```

这样一个缩写失败不会拖垮整句。低上下文或候选耗尽时,能留下明确 failure:

```text
ABBR_NOT_EXPANDED
EXPANSION_ABSTAIN
COVERAGE_FAILED
```

### 3. verifier 放到标准化卡点

第 13 篇讲过,V11 的 `ABBRVerifier` 重点不是重复判断“扩写是否该扩”,而是对检索回来的 SNOMED/RxNorm 候选做忠实性选择:

```text
这个标准概念是否忠实表达 expansion?
选不到就 WITHHELD
```

### 4. error analysis 把低上下文问题暴露出来

第 18 篇讲过,当前失败仍集中在:

```text
low_context_over_expansion
```

这说明问题没有被“神奇解决”,但 V11 选择的处理方式是:

```text
先保持主链路简单可测
再通过 benchmark/error analysis 定位低上下文误扩
未来如果重做 support verifier,必须证明净收益
```

这比硬塞一个过度保守的 LLM 校验更稳。

## 为什么不直接再加回来

因为它不是没有成本。

| 成本 | 说明 |
|---|---|
| 额外 LLM 调用 | 每个 mapping 再问一次上下文支持,成本和延迟都会增加 |
| 职责重叠 | coverage 已经在判断候选是否被上下文支持 |
| 保守度难调 | prompt 里的 “be conservative” 没有可靠旋钮 |
| 误伤正常 case | over-abstention 会让本该扩的缩写被拒 |
| benchmark 净收益不稳定 | 不能只看低上下文局部改善,要看全局 accuracy 和具体失败变化 |

所以它的教训是:

```text
不是多一个 verifier 就更安全。
验证模块如果放错位置或阈值不可控,反而会损害整体行为。
```

## 如果未来要重做,应该怎么做

不是简单恢复旧文件,而应该按 V11 的数据流重做。

更合理的方向:

1. **不要一刀切保守**

用可调阈值:

```text
support_score >= threshold 才拦截
```

而不是只靠 prompt 判断。

2. **结合候选先验**

对非常常见、上下文模式强的表达,如:

```text
denies CP
reports SOB
history of HTN
```

不应该和陌生 fallback 缩写同等保守。

3. **只作用于高风险缩写**

例如:

```text
fallback 来源
多义且低上下文
gold 历史中频繁误扩的 abbreviation
```

不要对所有 mapping 再加一层 LLM。

4. **必须用 benchmark 做准入**

至少要证明:

```text
low_context_abbreviation 提升
single/ambiguous/multi/negation/CASI 不下降
总 accuracy 不下降
失败样本数量和类型更合理
```

5. **接入 error analysis**

让 support verifier 的拒绝原因写入 `mapping_states.failure`,这样第 18 篇的错误资产系统能统计:

```text
它拦了哪些?
拦对了还是误伤?
误伤集中在哪些缩写?
```

否则它又会变成一个黑箱 LLM 判断器。

## 与当前低上下文失败的关系

当前 benchmark 失败三例:

| id | 现象 | 旧 MappingSupportVerifier 可能想拦 |
|---|---|---|
| `coverage_003` | 额外扩了 `ABC` | 是 |
| `coverage_005` | 额外扩了 `LMN` | 是 |
| `coverage_006` | 额外扩了 `QRS` | 是 |

所以你可以说:

```text
MappingSupportVerifier 的问题意识仍然成立。
```

但也要接着说:

```text
旧实现方式没有被 V11 采纳,因为它带来的过度弃权成本超过收益。
```

这个区别很重要。

V11 当前保留的是问题意识,不是保留旧模块。

## 数据流对比

```mermaid
flowchart TD
    subgraph Old["V10 实验思路"]
        A["candidate retrieval"] --> B["coverage choose expansion"]
        B --> C["MappingSupportVerifier<br/>context support?"]
        C --> D["allow / reject expansion"]
    end

    subgraph V11["V11 当前主链路"]
        E["candidate retrieval"] --> F["coverage evaluator"]
        F --> G["mapping record 状态机"]
        G --> H["deterministic text replacement"]
        H --> I["SNOMED/RxNorm retrieval"]
        I --> J["ABBRVerifier<br/>standard concept faithfulness"]
        J --> K["CODED / WITHHELD / ABSTAIN"]
        K --> L["benchmark + error analysis"]
    end
```

## 面试怎么讲

可以这样说:

> 我曾经为 low-context over-expansion 做过一个 `MappingSupportVerifier` 实验,专门问“当前句子是否足够支持这个缩写扩写”。它的动机是对的,因为系统确实容易看到候选就扩。但实验发现它过于保守,能拦住 LMN/QRS 这类弱上下文误扩,也会误伤 CP 这种临床短句里本该扩的缩写,造成 over-abstention。最后我没有把它放进 V11 主链路,而是在架构收敛时删除源文件和测试,保留 benchmark/error analysis 继续暴露这个问题。这个取舍说明我不是只堆功能,而是用净指标判断模块是否值得上线。

如果追问“那当前 low-context 还错怎么办”,可以补:

> 当前确实还有 3 条 low-context over-expansion,这在 error analysis 里是明确记录的。下一步如果重做 support verifier,不会恢复旧实现,而会做成可调阈值、只作用高风险 fallback/低上下文缩写,并且把拦截结果写进错误日志,用 benchmark 验证净收益。

## 常见误解

| 误解 | 正确理解 |
|---|---|
| V11 还在使用 MappingSupportVerifier | 不使用,源码文件和测试源文件已删除 |
| `mapping_support_results` 有值说明它在跑 | 当前它只是空列表兼容字段 |
| 删除它说明低上下文问题不存在 | 不对,问题仍存在;删除的是净收益不成立的旧实现 |
| 多加一层 LLM 校验一定更安全 | 不一定,会增加 over-abstention、成本和延迟 |
| 旧 `.pyc` 代表模块还活着 | 不代表,活链路看 `.py` 源码、import 和调用 |

## 一句话总结

`MappingSupportVerifier` 是 V10 为解决低上下文过度扩写做的实验模块,思路是让 LLM 判断当前句子是否足够支持某个缩写扩写;它能拦住部分误扩,但因为过度保守导致 over-abstention,benchmark 净收益不成立。V11 因此删除了源码和测试,只保留 `mapping_support_results=[]` 作为历史出口字段,并把低上下文问题交给 coverage、状态机、benchmark 和 error analysis 继续量化推进。

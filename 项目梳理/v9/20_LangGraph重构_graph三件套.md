# LangGraph 重构（把线性主流程改造成状态机：state + nodes + graph）

> 文件：`backend/graph/abbr_graph_state.py`（36 行）+ `abbr_graph_nodes.py`（173 行）+ `abbr_graph.py`（~50 行）
> 入口：`build_abbr_graph()`；状态对象 `ABBRGraphState`
> 衔接：阶段六收尾、也是项目的**未来方向**。第 14 篇的主流程是一个"大函数 + for 循环",这一篇把它拆成 **4 个节点 + 1 个共享 state** 的状态机。**当前未接入 API、与函数版并存**。这是简历上"LangGraph / Agent"关键词的落点。

## 核心速记
> 1. **Pipeline → StateGraph**：把第 14 篇的线性函数拆成 expand / standardize / verify / reflect 四个节点,用图把它们连起来。
> 2. **共享 state**：所有节点读同一个 `ABBRGraphState`、把结果写回。状态在节点间流转,而不是函数传参——这是 LangGraph 的核心思想。
> 3. **复用 V9、不重写逻辑**：节点内部直接调 `self.service.xxx`(第 14 篇的 ABBRService),只换"组织方式",不换实现。
> 次要(trivia):`TypedDict(total=False)`、`**state` 展开更新、条件边 `should_continue`——扫一眼。

## 这一段在解决什么

大白话:**同样的活(扩写→标准化→校验→反思→重试),第 14 篇用"一个函数 + for 循环"写,这里改用"画流程图"的方式写——每一步是一个节点,节点之间用箭头连。**

```text
第14篇（函数版）：       LangGraph 版（图）：
def expand_verify_      START → expand → standardize → verify
  _with_retry():                              │
  扩写                          ┌─────────────┴── should_continue
  for 循环:                     │（reflect）          │（end）
    标准化→检索→校验            ▼                      ▼
    if 过: return            reflect ──→ standardize   END
    else: reflect            （回环重新校验）
```

## 核心1 · 三件套分工（骨架）

LangGraph 把"一个大函数"拆成三个文件,各管一摊:

```text
state（abbr_graph_state.py）  = 数据载体：一个所有节点共享的 dict
nodes（abbr_graph_nodes.py）  = 每一步的逻辑：4 个节点函数，内部复用 ABBRService
graph（abbr_graph.py）        = 连线编排：把节点用边连成图，定义走向
```

**① state——共享数据袋(`ABBRGraphState`)**

```python
class ABBRGraphState(TypedDict, total=False):
    original_text: str              # 原文
    current_expanded_text: str      # 当前扩写
    current_mappings: list[dict]
    abbreviation_candidates: list
    standardization: dict; mapping_standardizations: list
    verification: dict; reflection_result: dict
    attempt: int; max_retries: int; success: bool; stop_reason: str
    attempts: list[dict]            # 全链路追踪
```

**核心思想**:第 14 篇里那些 `current_expanded_text`、`mappings` 是函数里的局部变量、靠参数传;LangGraph 里它们全放进**一个共享 state**,每个节点"从 state 读、往 state 写"。状态在节点间流动,不再靠函数调用传参。

**② nodes——每个节点复用 V9 能力**

```python
def expand_node(self, state):
    result = self.service.simple_llm_expansion(state["original_text"])  # ← 直接调第11篇
    return {**state, "current_expanded_text": result["expanded_text"], ...}  # 写回 state

def standardize_node(self, state): ... self.service.standardizer/retriever ...  # 第7/5篇
def verify_node(self, state):     ... self.service.verifier.verify_mappings ... # 第12篇
def reflect_node(self, state):    ... self.service.reflector.reflect ...        # 第13篇
```

**关键:节点不重写逻辑,而是调 ABBRService 现成的方法**(`self.service.xxx`)。所以这是"**换编排方式、不换零件**"——内部还是 V9 那套扩写/检索/校验/反思。每个节点 `return {**state, 新字段}`(把旧 state 展开 + 更新自己产出的字段)。

**③ graph——连线 + 条件分支**

```python
workflow.add_edge(START, "expand")
workflow.add_edge("expand", "standardize")
workflow.add_edge("standardize", "verify")
workflow.add_conditional_edges("verify", should_continue, {"reflect": "reflect", "end": END})
workflow.add_edge("reflect", "standardize")   # 反思后回到标准化，重新走一圈
```

`should_continue` 是**条件边**——verify 之后看情况分流:

```python
def should_continue(state):
    if state.get("success") is True:           return "end"     # 成功 → 结束
    if state.get("attempt") > max_retries + 1: return "end"     # 超次 → 结束
    return "reflect"                                            # 否则 → 去反思
```

这就是状态机的"分支":**verify → 成功就 END,否则去 reflect → reflect 回到 standardize 重新校验**,形成和第 14 篇等价的 Verify→Reflect→Retry 循环,只是用"图的边"表达而不是 for 循环。

## 核心2 · 为什么要图化（设计动机,必讲）

第 14 篇的函数版已经能跑,为什么还要 LangGraph?

```text
函数 + for 循环：      流程藏在代码控制流里，加一步要改函数体，状态流转不可视
LangGraph 状态机：     节点和边显式声明 → 可视化、可扩展、符合 Agent 工程范式
```

三个好处:
- **可视化**:节点、边、状态流转一目了然(LangGraph 能画出流程图),不用读 for 循环猜逻辑。
- **可扩展**:将来加一个节点(比如 Medical RAG、知识图谱查询),只要 `add_node` + 连边,不用动主函数。
- **符合趋势**:Agent / ReAct / 多智能体 都用图来组织,LangGraph 是企业级 Agent 的主流框架。**这一步把项目从"带 Agent 雏形的 pipeline"正式抬到"图编排的 Agent workflow"**。

> 回扣第 13 篇:Verify→Reflect→Retry 早就是 Agent 雏形了;LangGraph 只是把这个隐式循环**显式画成状态机**。

## 数据快照：图的一次执行

```text
state = {original_text:"The patient has MS with a diastolic murmur.", max_retries:2}
START → expand_node      → 写入 current_expanded_text(MS→multiple sclerosis)
      → standardize_node → 写入 mapping_standardizations
      → verify_node      → verification.overall_valid=false, success=false, attempts+1
      → should_continue  → "reflect"
      → reflect_node     → 改成 mitral stenosis, attempt=2
      → standardize_node → 重新检索
      → verify_node      → overall_valid=true, success=true
      → should_continue  → "end" → END
```

## 会被追问 / 诚实局限（★主动说）

- **当前未接入 API,与函数版并存**:线上 `/expand/simple` 用的还是第 14 篇的函数版,这个图只是**重构 demo / 实验**,能独立 build 和测试,但没上主链路。
  → 面试这么说:"LangGraph 版我已经实现并能跑测试,但还没接 API——它是我为'把线性流程升级成可视化状态机'做的重构,下一步是替换函数版主链路。诚实说现在是两套并存,有维护成本。"
- **行为和函数版不完全等价**:函数版有 coverage 全失败的**早停**(第 14 篇),但图版的 `standardize_node` 只是跳过没 expansion 的 mapping,**没有整图早停**——无有效扩写时图可能还会空跑标准化/校验/反思。两套控制流没对齐。
  → "我注意到图版还没把函数版的 coverage_failed 早停逻辑搬过来,行为有细微差异,这是迁移没做完的地方。"
- **继承 V9 所有局限**:节点复用 ABBRService,所以整句重来、all 偏严、多轮 LLM 慢这些(第 14 篇)**原样继承**,图化没解决它们——图只改组织,不改实现。
- **`reflect_node` 的 success 判定有点绕**:它用的是反思**前**的旧 verification 判 success,真正的重新校验要等回到 `verify_node`。逻辑能跑但可读性差。
- **这个流程还比较简单,图化收益有限**:LangGraph 真正发力在复杂分支/并行/多智能体。当前是条近乎线性的链 + 一个回环,**为图而图的收益不大**——诚实讲,它的价值更多在"为未来扩展铺路"和"符合工程范式",而非当前就有质变。

## 面试怎么说

**合格版（30 秒）**：
> 我用 LangGraph 把线性主流程重构成状态机:一个共享 state，四个节点 expand/standardize/verify/reflect，verify 后用条件边 should_continue 决定去 reflect 还是 END,reflect 回到 standardize 重新校验。节点内部复用 V9 的 ABBRService,只换编排方式。目的是可视化、可扩展、贴合 Agent 工程范式。当前还没接 API,是重构分支。

**优秀版（1 分钟）**：
> 第 14 篇的主流程本质是函数加 for 循环,Verify→Reflect→Retry 已经是 Agent 雏形。LangGraph 版把它显式画成状态机:状态放进一个共享的 TypedDict,所有节点从 state 读、往 state 写;四个节点直接复用 ABBRService 的方法,不重写逻辑,只是把"控制流"从 for 循环换成"图的边"——START→expand→standardize→verify,verify 用条件边分流到 reflect 或 END,reflect 回 standardize 形成循环。好处是可视化、加节点不动主函数、符合企业级 Agent 趋势,也为将来接 Medical RAG、知识图谱铺路。诚实说几点:它还没接 API、和函数版并存;图版没搬函数版的 coverage 早停,行为有细微差异;而且节点复用 ABBRService,V9 的局限原样继承,图化只改组织不改实现。这个流程目前偏线性,图化的真正收益要等流程变复杂才体现。

## 易错点 / 面试问答

**Q：LangGraph 版和函数版什么关系？** A：同一套逻辑两种组织——函数版是 for 循环(线上在用),图版是状态机(重构 demo,未接 API)。节点复用同一个 ABBRService。

**Q：state 是干嘛的？** A：所有节点共享的数据袋。每个节点从 state 读输入、把产出写回 state,状态在节点间流转,取代函数传参。

**Q：循环怎么在图里实现？** A：条件边 should_continue——verify 后,成功或超次就到 END,否则到 reflect;reflect 再连回 standardize,形成回环。

**Q：为什么要图化，比函数好在哪？** A：可视化、可扩展(加节点不改主函数)、符合 Agent/LangGraph 工程范式。但当前流程偏线性,收益更多在为扩展铺路。

**Q：图化解决了 V9 的问题吗？** A：没有。节点复用 ABBRService,整句重来、多轮慢这些原样继承。图只改编排,不改实现。

## 一句话总结

> LangGraph 重构把第 14 篇的"函数+for 循环"主流程改造成状态机:`ABBRGraphState` 共享数据,`expand/standardize/verify/reflect` 四节点复用 V9 的 ABBRService(只换编排不换实现),`should_continue` 条件边实现 Verify→Reflect→Retry 循环。价值是可视化、可扩展、贴合 Agent 范式,为未来接 RAG/知识图谱铺路。局限是当前未接 API(与函数版并存)、没搬早停逻辑(行为有差异)、继承 V9 全部局限、流程偏线性图化收益有限——是"为未来铺路"的重构而非当前质变。

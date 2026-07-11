# LLM 配置与工厂(换模型只改一行 · 异质判官的基础设施)· V11 🆕

> 文件:`backend/utils/llm_config.py`(声明)+ `backend/utils/llm_factory.py`(按配置造 LLM)
> 衔接:项目里所有"要用大模型"的地方(verify 判忠实、coverage 选唯一、fallback 生成候选、错误 triage),理论上都该从这里拿模型。它和第 02 篇的 Embedding 工厂是**同一套 config+factory 模式**——这次用在 LLM 上。
> **为什么 V11 才有它(批次15新增)**:为了能"**verify 换一个不同厂商的模型**"做异质判官实验——而要做到"换模型零改业务",就得先有这层工厂。

## 核心速记
> 1. **config / factory 分离 + 预设**:`LLMConfig`(provider/model_name/temperature=0/max_retries=2)+ 两个现成预设 `DEEPSEEK_CONFIG`、`QWEN_CONFIG`;`create_llm(config)` 真正造模型。换模型 = 传不同 config,**业务逻辑一行不改**。必背。
> 2. **接口统一是关键**:DeepSeek 走 `ChatDeepSeek`、Qwen 走 `ChatOpenAI` 指向 **DashScope 的 OpenAI 兼容端点**;两者对外都是 langchain 的 `.invoke().content`,所以调用方感知不到差别——这才是"零改业务"能成立的原因。
> 3. **API key 不进 config,由 factory 从环境变量读**(`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY`)。config 只描述"用哪个模型",密钥跟代码/配置解耦。
> 次要(trivia):temperature=0(可复现);Qwen 用 ChatOpenAI+base_url 的"借壳"写法,不引新 SDK。

## 这一段在解决什么

大白话:**给项目一个"换大模型"的开关**。以前想把某一步从 DeepSeek 换成千问,得到处改 `ChatDeepSeek(...)`;现在只要把那一步的 config 从 `DEEPSEEK_CONFIG` 换成 `QWEN_CONFIG`。

```text
ABBVerifier(config=DEEPSEEK_CONFIG)   → 用 DeepSeek 判忠实
ABBVerifier(config=QWEN_CONFIG)       → 用千问判忠实   ← 只换一个参数,verify 逻辑完全没动
```

它本身不"思考",只负责"按你点的牌,造出对应的那台 LLM"。

## 核心1 · config + factory(和 Embedding 同一套,必背)

```python
# llm_config.py
class LLMProvider(str, Enum):
    DEEPSEEK = "deepseek"; QWEN = "qwen"

@dataclass
class LLMConfig:
    provider: LLMProvider = LLMProvider.DEEPSEEK
    model_name: str = "deepseek-chat"
    temperature: float = 0.0
    max_retries: int = 2

DEEPSEEK_CONFIG = LLMConfig(provider=DEEPSEEK, model_name="deepseek-chat")
QWEN_CONFIG     = LLMConfig(provider=QWEN,     model_name="qwen3.6-flash")
```

```python
# llm_factory.py
def create_llm(config):
    if config.provider == DEEPSEEK:
        return ChatDeepSeek(model=config.model_name, api_key=os.getenv("DEEPSEEK_API_KEY"), ...)
    if config.provider == QWEN:
        return ChatOpenAI(model=config.model_name, api_key=os.getenv("DASHSCOPE_API_KEY"),
                          base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", ...)
    raise ValueError(...)
```

要点:
- **预设(DEEPSEEK_CONFIG/QWEN_CONFIG)**:常用配置直接给现成对象,调用方连字段都不用填。
- **借壳 OpenAI 兼容端点**:千问没用专门 SDK,而是用 langchain 的 `ChatOpenAI` + 阿里 DashScope 的 OpenAI 兼容地址——省一个依赖,且接口天然和别人一致。
- **密钥从 env 读**:config 可以安全地写进代码/日志(不含密钥)。

## 核心2 · 它真正解决的痛点:异质判官 + "自生自查"(面试金句)

V11 想治一个隐患:**同一个模型既生成、又自己检查**(自生自查),等于自己改自己的卷子。直觉解法=让"检查者"换一个不同厂商的模型(异质判官)。这层工厂就是为这个实验铺路的。

**实验结论(很重要,诚实)**:把 verify 换成千问,实测 **concept/主 benchmark 完全持平**。为什么持平?——因为 **post-batch8 的 verify 判的是 bge-m3 检索回来的概念(外部数据),不是 DeepSeek 自己生成的东西**,它**本来就不是自生自查**,没有循环可破。所以:

- verify 的真正安全垫是"**只能在真实检索结果里挑、扎根数据**",换谁判都差不多;
- 异质判官的价值在于"治**相关的幻觉**(同模型查自家生成)",治不了"**信息缺失**";
- 后来千问 DashScope **欠费**,verify 又切回 DeepSeek(零质量损失)。**工厂/config 基础设施保留**,充值后改一行 default 就能再切。

面试金句:"**我没有为了'显得多模型'而堆架构;我做了异质 verify 实验、并诚实地发现它在我这处持平——因为 verify 判的是检索结果不是自家生成,本就不是自生自查。这反而让我说清了'异质判官该用在哪、不该用在哪'。**"

## 数据快照

```text
输入:一个 LLMConfig(或预设 DEEPSEEK_CONFIG / QWEN_CONFIG)
输出:一个 langchain chat 模型,对外统一 .invoke(prompt).content
支持:DeepSeek(deepseek-chat)/ Qwen(qwen3.6-flash,走 DashScope OpenAI 兼容端点)
密钥:DEEPSEEK_API_KEY / DASHSCOPE_API_KEY(factory 从 env 读)
当前默认:verify = DEEPSEEK_CONFIG(千问欠费后切回)
```

## 其余细节(次要,一行带过)

【次要】`max_retries=2` 是 langchain 客户端层的网络重试,和"反思重试"是两码事;`temperature=0` 让同输入尽量同输出(但仍有 ±1~2 例噪声地板)。

## 🧹 死代码 / 盲肠提醒

- **工厂只被 `ABBVerifier` 采用;另外 4 处 LLM 仍直接 `ChatDeepSeek(...)` 绕过工厂**:`abbr_service.self.llm`、`abbr_candidate_coverage_evaluator`、`abbr_candidate_fallback_retriever`、`error_triage`。不是 bug,但"工厂没全员落地"。→ 见优化方向 1。
- **`ABBRService.__init__` 的 `self.llm`(57 行)是盲肠**:定义后**全文件再无任何引用**(grep 只命中定义处)。它是 V9 `simple_llm_expansion` 删除后的遗留——V11 主链路扩写已确定性化,主编排器自己不直接调 LLM(都交给 coverage/fallback/verifier 各自的 LLM)。
  → **可安全删除**(连带没用到的 `ChatDeepSeek` import)。
- **千问分支当前休眠**(verify 默认 DeepSeek):**不是死代码**,是"充值即用"的预留,别删。

## 🚀 优化方向(更好 / 更稳)

1. **让所有 LLM 调用点都走工厂**:把 coverage/fallback/error_triage/(以及若保留的)主 LLM 统一改成 `create_llm(config)`。好处:换模型/调温度/统一限流与超时只改一处;也能给"生成端"和"判定端"配**不同**模型(真正落地异质)。
2. **温度/超时/限流进 config**:现在网络重试在 factory 写死;可把 timeout、rate-limit、温度都收进 LLMConfig,集中治理。
3. **JSON 模式 / 结构化输出**:几处都靠"清洗 markdown + json.loads + 兜底"。若模型支持 `response_format=json`,可减少解析失败(各 LLM 篇会提到解析兜底)。
4. **失败可观测**:给 create_llm 出来的模型包一层调用计数/耗时/失败率(对应第 17 篇曾临时打点量化 verify 贡献),长期排查更省事。
5. **模型版本钉死 + 回归**:`qwen3.6-flash`/`deepseek-chat` 是会迭代的远端模型;关键判定步骤建议记录模型版本,换版本时跑一遍 benchmark 防悄悄回归。

## 会被追问 / 诚实局限(★主动说)

- **为什么要这层工厂,不直接 new?** 为了"换模型零改业务",尤其支撑异质 verify 实验;也便于把密钥从代码里拿出来(env 读)。
- **多模型是不是为炫技?** 不是——做了实验、诚实发现 verify 上持平,并讲清原因(判检索非自生自查)。这比"我接了多模型"更有价值。
- **当前其实只跑 DeepSeek?** 是。千问欠费切回,工厂留着随时切。坦白这点 + 能讲"何时该启用异质"才是真懂。
- **密钥安全**:key 只在 env、factory 运行时读,不进 config/日志/git。

## 面试怎么说

**合格版(30 秒)**:
> LLM 也用 config + factory:`LLMConfig` 选 provider/model/温度,`create_llm` 造出对应模型。DeepSeek 用 ChatDeepSeek,千问用 ChatOpenAI 指向 DashScope 的 OpenAI 兼容端点,两者接口一致,所以换模型只改一个 config。密钥从环境变量读。它是我做"verify 换异质模型"实验的基础设施。

**优秀版(1 分钟)**:
> 这层是为异质判官实验做的:我想验证"verify 换个不同厂商的模型能不能减少自生自查"。要做到换模型零改业务,就先把 LLM 抽成 config+factory——千问用 ChatOpenAI + DashScope 兼容端点借壳,接口和 DeepSeek 一致。实验结论很诚实:换千问后 benchmark 完全持平,原因是 post-batch8 的 verify 判的是检索回来的概念、不是模型自家生成的东西,本就不是自生自查、没循环可破。后来千问欠费我切回 DeepSeek,工厂留着随时能切。我还清楚它没全员落地——目前只有 verify 走工厂,coverage/fallback 还直接 new,这是下一步统一的点。

## 易错点 / 面试问答

**Q:千问怎么接的,引了新 SDK 吗?** A:没有。用 langchain 的 ChatOpenAI + DashScope 的 OpenAI 兼容 base_url,接口天然统一,省依赖。

**Q:换模型真能零改业务?** A:对调用方零改——它只拿 `create_llm(config)` 返回的对象调 `.invoke().content`。换的是 config。

**Q:异质判官有用吗?** A:在"同模型查自家生成"的幻觉上有用;但我项目的 verify 判的是外部检索结果,不是自生自查,所以实测持平。价值是我讲清了"该用在哪"。

**Q:现在到底用哪个模型?** A:默认 DeepSeek(千问欠费切回)。基础设施保留,改一行 default 可切。

**Q:为什么 key 不写进 config?** A:安全。config 可能被打印/进 git,密钥只在运行时从 env 读。

## 一句话总结

> LLM 工厂把"用哪个大模型"和"怎么造/怎么调"解耦(同 Embedding 那套):config 选 DeepSeek/千问 + 温度,factory 造出接口统一的 langchain 模型,密钥从 env 读。它是 V11 异质 verify 实验的基础设施——实验诚实地证明 verify 换模型持平(因为它判检索结果、非自生自查)。当前默认 DeepSeek(千问欠费切回),工厂留作随时可切。局限是只有 verify 落地了工厂、其它 LLM 仍直 new;主编排器的 self.llm 是可删盲肠。

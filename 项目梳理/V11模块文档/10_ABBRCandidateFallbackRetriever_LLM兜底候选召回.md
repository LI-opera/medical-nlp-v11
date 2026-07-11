# ABBRCandidateFallbackRetriever —— LLM 兜底候选召回 · V11

> 文件:`backend/services/abbr_candidate_fallback_retriever.py`(约 90 行)
> 衔接:第 09 篇 `ABBRCandidateRetriever` 是 primary 本地词典召回;本篇是 primary 查不到时才启用的 fallback 召回。它让 LLM 结合上下文生成**候选扩写列表**,但不允许 LLM 直接改写原句。
> **V11 必看变化**:fallback 结果在 `ABBRService` 里会被进一步收紧:①用 `NERService.is_medical()` 给每个候选补 domain;②再交给 coverage evaluator 判断;③如果 fallback 的 coverage 不通过或 confidence < 0.8,即使有候选也不采用 `best_expansion`。也就是说 fallback 只是"补候选",不是"放行扩写"。

## 核心速记

> 1. **一句定位**:当本地 `ABBR_CANDIDATES` 没有某个缩写时,它让 LLM 生成可能的医学扩写候选。
> 2. **铁边界**:只生成候选,绝不改写整句。prompt 里明确写了 `You are NOT expanding the full clinical sentence.`
> 3. **V11 更保守**:fallback 不是直接可信源。后面还要过 NER domain 推断、coverage 判断、confidence >= 0.8 闸门、再进入标准概念检索与 verifier。
> 次要(trivia):模型是 `deepseek-chat`,temperature=0;JSON 解析失败时返回空 candidates,不让流程崩。

## 这一段在解决什么

大白话:**词典里没有这个缩写时,问 LLM:"在这句话里,它可能是什么医学全称?"**

例如:

```text
输入文本:
"The patient developed AKX after surgery."

缩写:
"AKX"

本地词典:
查不到

fallback:
让 LLM 返回候选扩写列表,例如:
{
  "abbreviation": "AKX",
  "candidates": [
    {
      "abbreviation": "AKX",
      "expansion": "...",
      "source": "fallback_llm",
      "confidence": 0.4
    }
  ],
  "reason": "..."
}
```

注意:它返回的是候选,不是最终答案。后面还要一层层把关。

## 核心1 · 为什么要有 fallback

本地词典再怎么扩,也会遇到长尾:

```text
新缩写
科室内部缩写
拼写变体
数据集中出现但词典没收录的缩写
```

如果只有 primary 词典:

```text
ABBR_CANDIDATES.get("XYZ", []) → []
```

系统就只能放弃。

fallback 的作用是提高覆盖率:

```text
常见缩写:
  本地词典,确定性、快、可解释

未知缩写:
  LLM fallback,更灵活,但必须更严格把关
```

所以它和第 09 篇组成两层召回:

```text
primary local dictionary
  ↓ 查不到
fallback LLM candidate retriever
```

这不是让 LLM 取代词典,而是让 LLM 补词典的盲区。

## 核心2 · prompt 的铁边界:只产候选,不改句

prompt 里最重要的几句:

```text
You are NOT expanding the full clinical sentence.
You are only generating candidate expansions for the abbreviation.

Do not rewrite the clinical text.
Do not add diagnoses, treatments, symptoms, or assumptions.
```

为什么这么强调?

因为如果 fallback LLM 直接改写整句:

```text
LLM 幻觉扩写
  ↓
直接进入 final expanded_text
  ↓
绕过 coverage / deterministic replacement / verifier
```

风险太大。

V11 的正确纪律是:

```text
LLM fallback 只补候选池
是否采用候选 = coverage 决定
如何替换文本 = deterministic replacement 决定
标准概念是否忠实 = verifier 决定
```

这就是"把 LLM 自由度限制在小任务里"。

## 核心3 · 防幻觉规则

prompt 里有多条规则在压 LLM 幻觉:

```text
1. Return possible medical expansions.
2. Prefer plausible expansions in context.
5. If unclear, return multiple candidates with low confidence.
6. If not plausible medical abbreviation, return empty candidates.
7. Do not create expansions by combining words that merely start with the same letters.
8. Do not invent rare, artificial, unsupported expansions.
9. Only return commonly used medical abbreviations or strongly context-supported candidates.
10. Return only valid JSON.
11. Do not use markdown.
```

几个设计点:

- **允许返回空 candidates**:这是给 LLM 的"不知道"出口;
- **禁止首字母硬拼**:防止把任意大写 token 强行解释成医学短语;
- **禁止罕见/人造扩写**:压低为了回答而回答的倾向;
- **要求 JSON**:方便上层程序解析。

但要诚实说:prompt 护栏不是形式化保证。LLM 仍可能不听话,所以后面还有 coverage 和 verifier。

## 核心4 · 代码执行流程

初始化:

```python
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise ValueError("DEEPSEEK_API_KEY is not set.")

self.llm = ChatDeepSeek(
    model="deepseek-chat",
    api_key=api_key.strip(),
    temperature=0,
    max_retries=2
)
```

调用:

```python
response = self.llm.invoke(prompt)
content = response.content.strip()
content = content.replace("```json", "").replace("```", "").strip()
```

解析:

```python
try:
    parsed = json.loads(content)
except json.JSONDecodeError:
    return {
        "abbreviation": abbreviation,
        "candidates": [],
        "reason": "Fallback retriever did not return valid JSON.",
        "raw_output": content
    }
return parsed
```

含义:

```text
成功解析 → 返回 LLM 的候选 JSON
解析失败 → 返回空候选,记录 raw_output,不让系统崩
```

这是一个保守兜底:格式错了宁可不扩,也不拿脏输出继续跑。

## 核心5 · V11 在 ABBRService 里如何收紧 fallback

fallback retriever 只负责生成候选。真正进入主链路时,`ABBRService._get_abbreviation_candidates()` 还会继续处理。

### 1. primary 查不到才 fallback

```python
candidates = self.candidate_retriever.retrieve(abbr)
candidate_source = "primary"

if not candidates:
    fallback_result = self.fallback_retriever.retrieve(
        abbreviation=abbr,
        context_text=text
    )
    candidates = fallback_result.get("candidates", [])
    candidate_source = "fallback"
```

### 2. fallback 候选补 domain

```python
if candidate_source == "fallback":
    for candidate in candidates:
        _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
        candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)
```

为什么要补 domain?

因为本地词典候选本来就带:

```json
{"expansion": "aspirin", "domain": "Drug"}
```

但 LLM fallback 返回的候选一般只有:

```json
{"expansion": "...", "source": "fallback_llm", "confidence": 0.0}
```

为了让后续 `domain_boost` / `_route_source()` 能继续工作,需要用 NER 给 fallback expansion 推断 domain。

### 3. coverage 再判断候选是否可用

```python
coverage = self.coverage_evaluator.evaluate(
    original_text=text,
    abbreviation=abbr,
    candidates=candidates
)
best = coverage.get("best_expansion")
```

### 4. fallback 额外加 confidence 闸门

```python
if candidate_source == "fallback":
    conf = coverage.get("confidence") or 0.0
    if (not coverage.get("coverage_ok")) or conf < 0.8:
        best = None
```

这句非常重要。

本地词典 primary 候选是人工策展源,相对可信;fallback 候选是 LLM 现造的,所以 V11 更保守:

```text
coverage 不通过 → 不扩
coverage confidence < 0.8 → 不扩
```

也就是说 fallback 并不是"LLM 说有就扩",而是:

```text
LLM 只补候选
coverage 高置信通过才允许 expansion 进入后续流程
```

## 数据快照

### LLM 返回成功

```json
{
  "abbreviation": "XYZ",
  "candidates": [
    {
      "abbreviation": "XYZ",
      "expansion": "example medical expansion",
      "source": "fallback_llm",
      "confidence": 0.62
    }
  ],
  "reason": "brief explanation"
}
```

### JSON 解析失败

```json
{
  "abbreviation": "XYZ",
  "candidates": [],
  "reason": "Fallback retriever did not return valid JSON.",
  "raw_output": "..."
}
```

### 进入 ABBRService 后补 domain

```json
{
  "abbreviation": "XYZ",
  "expansion": "example medical expansion",
  "source": "fallback_llm",
  "confidence": 0.62,
  "domain": "Condition"
}
```

### 低 confidence 被拒绝

```text
coverage_ok = true
coverage confidence = 0.65
candidate_source = fallback

结果:
best = None
status = NOT_EXPANDED
```

## 和 primary retriever 的区别

| 维度 | ABBRCandidateRetriever(primary) | ABBRCandidateFallbackRetriever(fallback) |
|---|---|---|
| 来源 | 本地 `ABBR_CANDIDATES` | LLM |
| 何时调用 | 默认先调用 | primary 返回空时 |
| 是否看上下文 | 不看 | 看 `context_text` |
| 是否稳定 | 完全稳定 | 模型输出仍可能波动 |
| 是否花 token | 不花 | 花 |
| 是否自带 domain | 是,来自词典 | 否,后续用 NER 补 |
| 可信度 | 较高 | 较低,需更严闸门 |
| 是否直接决定扩写 | 否 | 否 |

共同点:

```text
都只提供候选
都不直接改写原句
都要过 coverage
```

## 其余细节(次要,一行带过)

【次要】`load_dotenv(ENV_PATH, override=True)` 会强制用 `backend/.env` 覆盖环境变量;prompt 里 `Clinical text:` 后面多了一个反引号,不影响大意但可清理;`confidence` 是 LLM 自报值,当前真正收紧用的是 coverage 的 confidence,不是 candidate 自己的 confidence。

## 死代码 / 盲肠提醒

- 本文件没有明显死代码。
- `confidence` 在 fallback candidate 里由 LLM 自报,但主链路收紧 fallback 时看的是 `coverage.get("confidence")`,不是每个 candidate 的 confidence。
- `source:"fallback_llm"` 是 prompt 要求 LLM 返回的字段,但代码没有强校验它一定存在。
- 本模块直接实例化 `ChatDeepSeek`,没有复用 `utils.llm_factory.create_llm()`。这和 `ABBVerifier` 不完全统一,后续可收口。

## 优化方向(更好 / 更稳)

1. **使用统一 LLM factory**:改成 `create_llm(DEEPSEEK_CONFIG)` 或可配置 provider,避免 LLM 初始化散落各处。
2. **结构化校验 JSON**:解析后校验 candidates 是否为 list、每个 candidate 是否有 abbreviation/expansion/confidence,不合格就剔除。
3. **缓存 fallback 结果**:同一个 abbreviation + 相似 context 可缓存,减少 token 成本和延迟。
4. **记录 fallback reason 到最终日志**:现在 reason 没有很系统地进入 failure evidence,可增强可追溯性。
5. **candidate confidence 不直接信任**:可以干脆标为 `llm_self_confidence`,避免被误认为校准概率。
6. **清理 prompt 小笔误**:`Clinical text:\`` 多余反引号可以去掉。
7. **加入更强 abstain 约束**:例如要求模型输出 `should_abstain` 或固定空候选条件,让拒答更稳定。
8. **fallback 候选 domain 映射增强**:NER label 可能映射不到 domain,可以结合候选文本规则或药品词典辅助判断 Drug。

## 会被追问 / 诚实局限(主动说)

- **fallback 会幻觉**:这是 LLM 兜底的天然风险。V11 用 prompt 护栏 + coverage 闸门 + confidence 阈值 + verifier 来压风险,但不能说完全消除。
- **LLM 自报 confidence 不可靠**:不能当概率,只能当提示字段。
- **JSON 解析脆弱**:虽然有解析失败返回空候选的兜底,但一次格式错就会漏召回。
- **成本和延迟更高**:所以只在 primary 查不到时调用。
- **domain 是后补的**:fallback 结果不像本地词典那样天然有 domain,后补 domain 可能错。

## 面试怎么说

**合格版(30 秒)**:
> FallbackRetriever 是缩写候选召回的兜底层。本地词典查不到时,它用 DeepSeek 根据上下文生成候选扩写列表。它只产候选,不改写原句,并要求返回 JSON。解析失败就返回空候选,避免脏输出进入主流程。

**优秀版(1 分钟)**:
> 我把缩写召回做成 primary + fallback 两层。常见缩写先查本地候选库,确定性、零成本;查不到才让 LLM fallback 兜底长尾。但 fallback 的职责被严格限制:只允许生成候选扩写,不能改写整句。这样 LLM 产物不会直接进最终结果,而是和词典候选一样进入统一的 coverage → deterministic replacement → retrieval → verifier 流程。V11 还对 fallback 更保守:LLM 候选会先用 NER 补 domain,然后过 coverage,如果 coverage 不通过或 confidence 低于 0.8,就不采用 best expansion。也就是说 fallback 提高覆盖率,但不直接提供最终判断。

## 易错点 / 面试问答

**Q:为什么 fallback 不直接扩写整句?**  
A:直接扩写会绕过 coverage 和 verifier,幻觉可能直接进结果。只产候选可以保证所有候选走同一条把关链路。

**Q:fallback 和 coverage 有什么区别?**  
A:fallback 负责"生成候选";coverage 负责"判断候选集中有没有上下文支持的合理扩写,并选 best_expansion"。

**Q:fallback 的候选有 domain 吗?**  
A:LLM 返回时通常没有。V11 在 ABBRService 里用 `NERService.is_medical()` 推断 label,再映射成 domain。

**Q:fallback 结果什么时候会被拒绝?**  
A:JSON 解析失败会返回空候选;coverage 不通过会拒绝;fallback 的 coverage confidence < 0.8 也会拒绝。

**Q:LLM 返回的 confidence 能信吗?**  
A:不能当真概率。当前主链路更看 coverage evaluator 的 confidence,并且后面还有 verifier。

**Q:为什么还要 LLM fallback,不用大词典一次解决?**  
A:理想生产化可以接更大词典,但长尾和上下文缩写仍可能存在。fallback 是提高覆盖率的补充层,不是替代本地词典。

## 一句话总结

> ABBRCandidateFallbackRetriever 是 primary 词典查不到时的 LLM 候选补充层。它的核心纪律是"只产候选、不改原句":让 LLM 负责补长尾候选,但最终能不能扩、怎么扩、标准概念选哪个,都交给后续 coverage、确定性替换、检索和 verifier。V11 还给 fallback 加了 NER domain 补全和 confidence >= 0.8 的保守闸门,所以它是覆盖率补丁,不是最终裁判。

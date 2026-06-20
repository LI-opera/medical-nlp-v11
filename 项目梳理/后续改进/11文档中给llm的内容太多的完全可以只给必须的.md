- 过滤是"软约束"，不是代码硬截断：注意 `simple_llm_expansion` 把整个结构（candidates + filtered_candidates + coverage）都 dump 进 prompt，靠规则文字让 LLM "优先用 filtered"。代码并没有只把 filtered 传进去。所以"只在支持的候选里选"是靠 LLM 听话，不是强制的。 → 面试这么说："候选过滤目前是 prompt 软约束——我把完整候选和 filtered 都给 LLM，靠规则让它优先用 filtered。更稳的是代码层只传 filtered_candidates，做成硬约束，LLM 想越界都没得选。"这里我没看懂具体是要怎么优化

Thought process

这条优化的本质是:**别让 LLM 看见它不该选的东西。** 现在是"给它看全部,然后嘴上叮嘱它只用 filtered";硬约束是"干脆只给它 filtered,它想越界都没得选"。看代码就清楚。

### 现在的写法(软约束)

`_get_abbreviation_candidates` 产出的每个缩写,结构里**同时有全部候选和过滤后候选**:

python

```python
{
  "abbreviation": "MS",
  "candidates":          [{exp:"multiple sclerosis"}, {exp:"mitral stenosis"}],  # ← 全部
  "filtered_candidates": [{exp:"mitral stenosis"}],                              # ← coverage 留下的
  "coverage": {...}, "candidate_source": "primary"
}
```

然后 `simple_llm_expansion` 把**整个结构**(含 candidates 全部)塞进 prompt,靠规则叮嘱:

python

```python
prompt = f"""...
   Abbreviation candidates: {json.dumps(abbreviation_candidates)}   # ← 全部候选都给了它看
   Rules:
     4. Use filtered_candidates as the primary candidate set.        # ← 只是"请优先用"
"""
```

**问题**:LLM 眼前**同时摆着 `multiple sclerosis` 和 `mitral stenosis`**,规则只说"优先用 filtered"。它**完全可能**还是挑了被 coverage 否掉的 `multiple sclerosis`——因为那个选项就在它眼前,规则约束不是强制的。这就是"软约束(靠听话)"。

### 优化:硬约束,三个层级(越往后越强)

**层级 1 · 只把 filtered 喂进去(最简单,收益最大)**

构造 prompt 前,先把"不该选的"过滤掉,**只给 LLM 看 allowed**:

python

```python
choices = []
for item in abbreviation_candidates:
    # coverage 通过才给候选，否则给空（= 不许扩）
    allowed = item["filtered_candidates"] if item["coverage"]["coverage_ok"] else []
    choices.append({
        "abbreviation": item["abbreviation"],
        "allowed_expansions": [c["expansion"] for c in allowed],
    })

prompt = f"""...
   You may ONLY use the expansions listed in allowed_expansions.
   Allowed: {json.dumps(choices)}
"""
```

现在 LLM **根本看不到** `multiple sclerosis`,物理上没法选它。被 coverage 否掉的候选不进 prompt = 想越界都没选项。这一步几乎零成本,但把"软"变"硬"了。

**层级 2 · 让 LLM 返回"编号"而不是"自己打字"**

更狠一点:别让 LLM 自由打出 expansion 文字(它可能改大小写/措辞,就是第 10 篇那个脆弱点),而是让它**从清单里选编号**,代码再把编号映射回真正的字符串:

python

```python
# 给它带编号的选项
# MS: [0] mitral stenosis
# 要求 LLM 返回 {"abbreviation":"MS", "choice": 0}
chosen = result["choice"]
expansion = allowed[chosen]["expansion"]   # 代码查表，不靠 LLM 复述
```

这样**连字符串漂移都根除了**(顺带解决第 10 篇的精确匹配脆弱问题)——LLM 只负责"选 0 还是 1 还是不选",字符串由代码决定。

**层级 3 · 用结构化输出 / enum 约束解码(最强)**

很多 LLM API 支持 **JSON Schema + enum**(或 function calling),可以规定某字段的值**只能是给定集合里的一个**:

python

```python
# 伪 schema：expansion 字段限定为枚举
{"expansion": {"type": "string", "enum": ["mitral stenosis"]}}
```

这时**模型层面**就被禁止输出集合外的值,连"想生成别的"都做不到。这是最硬的约束。

### 一个要分清的点

注意:LLM 还是要生成**整句扩写后的文本**(`expanded_text`)——那部分是自由文本,改不了。我们硬约束的是**"哪个缩写映射到哪个 expansion"这个选择**(mapping),把"选择"锁死在 allowed 集合里,而"造句"留给 LLM。**约束选择,不约束造句。**

### 面试怎么说

> "现在候选过滤是软约束——我把全部候选都给了 LLM,靠 prompt 规则让它优先用 filtered,但它眼前摆着被否掉的选项,可能还是选错。改成硬约束很简单:构造 prompt 时只把 coverage 通过的 allowed 候选喂进去,被否的根本不进上下文,LLM 想越界都没选项。再进一步可以让它返回候选编号而不是自己打字,代码查表映射,顺带根除字符串漂移;最强的是用 JSON Schema 的 enum 约束解码,模型层面就禁止输出集合外的值。但要注意只约束'选哪个映射',整句扩写文本还是 LLM 自由生成。"

这个回答体现你懂"**约束应该落在代码/解码层,而不是寄希望于 prompt 听话**"——这是 LLM 工程的重要意识,面试加分。
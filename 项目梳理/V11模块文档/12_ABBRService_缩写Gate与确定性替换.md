# ABBRService —— 缩写 Gate 与确定性替换 · V11

> 文件:`backend/services/abbr_service.py`
> 相关函数:`_should_consider_abbreviation()`、`_get_abbreviation_candidates()`、`_build_expanded_text_deterministic()`
> 衔接:第 09-11 篇讲完了"候选从哪里来、coverage 怎么选 best_expansion"。本篇看 `ABBRService` 里两个非常关键但容易被忽略的控制点:①哪些 token 才允许进入缩写候选召回;②选出 expansion 后,为什么不用 LLM 改写整句,而用确定性代码替换原文 token。
> **V11 必看变化**:最终扩写文本不再由 LLM 直接生成。LLM/coverage 只决定 `best_expansion`,真正的 `expanded_text` 由 `_build_expanded_text_deterministic()` 按 token 边界替换,从而减少幻觉、保留否定词和原句结构。

## 核心速记

> 1. **缩写 Gate**:`_should_consider_abbreviation()` 决定一个 token 值不值得进入候选召回。已知缩写大小写都放行;未知缩写只有原文全大写且长度 2-8 才允许 fallback。
> 2. **确定性替换**:`_build_expanded_text_deterministic()` 用正则 `\bABBR\b` 找 token 边界,只替换被 coverage 选中的 abbreviation,不让 LLM 直接改句。
> 3. **安全收益**:不误伤子串(CP 不替 CPR)、多缩写从后往前替避免 offset 错位、否定词/上下文原样保留。
> 次要(trivia):`test_v11_deterministic.py` 已经覆盖否定保留、子串不误伤、多缩写 offset 三个关键行为。

## 这一段在解决什么

大白话:这篇讲的是两个问题:

```text
1. 句子里哪些词值得当作"医学缩写"处理?
2. 确认扩写后,怎么把 CP 替换成 chest pain,又不乱改整句话?
```

例如:

```text
原句:
"Patient denies CP but CPR was performed."

候选/coverage 选中:
CP → chest pain

确定性替换后:
"Patient denies chest pain but CPR was performed."
```

注意:

```text
denies 保留
CP 被替换
CPR 没被误伤
```

这就是 V11 这一步的价值。

## 核心1 · token Gate:先决定谁有资格进入召回

入口在 `_get_abbreviation_candidates()`:

```python
words = text.replace(",", " ").replace(".", " ").split()

for word in words:
    raw_token = word.strip(".,;:()[]{}")
    if not self._should_consider_abbreviation(raw_token, known_abbrs):
        continue
    abbr = raw_token.strip().upper()
```

逻辑分两步:

```text
1. 粗切 token:
   逗号/句号替换为空格,再 split
   每个 word 去掉常见标点

2. 调 gate:
   _should_consider_abbreviation(raw_token, known_abbrs)
```

这个 gate 是为了防止系统把所有英文词都拿去当缩写查:

```text
patient
has
and
with
```

如果这些都进 fallback,LLM 会被迫解释大量普通词,幻觉风险和成本都会暴涨。

## 核心2 · _should_consider_abbreviation 的规则

代码:

```python
def _should_consider_abbreviation(self, raw_token: str, known_abbrs: set[str]) -> bool:
    token = raw_token.strip(".,;:()[]{}")
    if not token:
        return False

    upper_token = token.upper()

    if not upper_token.isalpha():
        return False

    if upper_token in known_abbrs:
        return True

    if len(upper_token) < 2:
        return False

    if token == upper_token and len(upper_token) <= 8:
        return True

    return False
```

翻译成白话:

```text
空 token                         → 跳过
包含数字/符号,不是纯字母          → 跳过
在本地候选库里的已知缩写          → 放行,大小写都可以
未知 token 长度小于 2             → 跳过
未知 token 原文本来就是全大写且<=8 → 放行,允许 fallback
其它                              → 跳过
```

## 核心3 · 已知缩写和未知缩写的策略不同

### 已知缩写

```python
if upper_token in known_abbrs:
    return True
```

含义:

```text
SOB / sob / Sob
HTN / htn / Htn
```

只要转大写后在词典里,gate 就放行。

为什么?

因为已知缩写有本地候选库支撑,风险较低。

### 未知缩写

```python
if token == upper_token and len(upper_token) <= 8:
    return True
```

含义:

```text
未知缩写必须满足:
  原文就是全大写
  长度 2 到 8
```

例如:

```text
AKI   → 可能进入 fallback
XYZ   → 可能进入 fallback
aki   → 不进入 fallback
patient → 不进入 fallback
VERYLONGABBR → 不进入 fallback
```

为什么更严格?

因为未知缩写只能靠 LLM fallback。为了避免普通词误进 LLM,必须加更强 gate。

一句话:

```text
已知缩写: 相对宽松
未知缩写: 必须大写、长度受限、再交给 fallback
```

## 核心4 · 候选召回到 best_expansion 的桥接

Gate 放行后,`_get_abbreviation_candidates()` 会走完整候选流程:

```text
raw_token
  ↓ gate 放行
abbr = raw_token.upper()
  ↓
primary 本地候选召回
  ↓ 若无候选
fallback LLM 候选召回
  ↓
fallback 候选补 domain
  ↓
coverage evaluator
  ↓
best_expansion
  ↓
chosen_domain
```

最后返回的每个 info:

```python
found.append({
    "abbreviation": abbr,
    "candidates": candidates,
    "filtered_candidates": filtered_candidates,
    "coverage": coverage,
    "candidate_source": candidate_source,
    "best_expansion": best,
    "chosen_label": None,
    "chosen_domain": best_domain
})
```

这里的 `best_expansion` 后面会进入 record:

```python
rec = {
    "abbreviation": info.get("abbreviation"),
    "expansion": best if best else None,
    "domain": info.get("chosen_domain"),
    "status": "PENDING" if best else "NOT_EXPANDED",
}
```

所以本篇的 gate 和第 11 篇 coverage 共同决定:

```text
哪些 token 会被考虑
哪些 token 最终有 expansion
哪些 token 会进入后续标准概念检索
```

## 核心5 · 为什么 V11 不让 LLM 直接改写整句

早期系统很容易做成:

```text
把原句交给 LLM
让 LLM 输出扩写后的整句
```

但这样有几个风险:

- LLM 可能改动非缩写部分;
- LLM 可能新增诊断/症状/治疗;
- LLM 可能破坏否定语义;
- LLM 可能把不该扩的词也扩了;
- 很难知道到底哪个 token 被替换了。

V11 改成:

```text
LLM/coverage 只决定 CP → chest pain
原句替换由确定性函数完成
```

这就把"判断"和"改写"拆开:

```text
判断哪个 expansion 合理 = LLM coverage
如何修改字符串 = deterministic code
```

这样更可控。

## 核心6 · _build_expanded_text_deterministic 的真实逻辑

代码:

```python
def _build_expanded_text_deterministic(self, text: str, chosen: list[dict]) -> str:
    if not chosen:
        return text

    spans = []
    for item in chosen:
        abbr = item.get("abbreviation")
        expansion = item.get("expansion")
        if not abbr or not expansion:
            continue
        pattern = re.compile(rf"\b{re.escape(abbr)}\b")
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), expansion))

    spans.sort(key=lambda span: span[0], reverse=True)
    result = text
    for start, end, expansion in spans:
        result = result[:start] + expansion + result[end:]
    return result
```

流程:

```text
chosen records
  ↓
对每个 abbreviation 编译 \bABBR\b 正则
  ↓
在原文中找到 token 边界匹配 span
  ↓
所有 span 按 start 从大到小排序
  ↓
从后往前替换
  ↓
返回 expanded_text
```

## 核心7 · token 边界:CP 不误伤 CPR

关键正则:

```python
pattern = re.compile(rf"\b{re.escape(abbr)}\b")
```

`\b` 是单词边界。

所以:

```text
文本: "CPR was performed"
abbr: "CP"

\bCP\b 不会命中 CPR 里的 CP
```

对应测试:

```python
def test_no_substring_hit():
    out = _build(
        "CPR was performed",
        [{"abbreviation": "CP", "expansion": "chest pain"}],
    )
    assert out == "CPR was performed"
```

这比简单的:

```python
text.replace("CP", "chest pain")
```

安全得多。

## 核心8 · 从后往前替换:避免 offset 错位

如果一句话里有多个缩写:

```text
Patient has CP and MS
```

替换 `CP` 后,字符串长度变了:

```text
CP → chest pain
```

如果从前往后用旧 span 继续替,后面的 `MS` 位置可能错。

所以代码先收集所有 span,再:

```python
spans.sort(key=lambda span: span[0], reverse=True)
```

从后往前替。

对应测试:

```python
def test_multi_abbr_no_offset_error():
    out = _build(
        "Patient has CP and MS",
        [
            {"abbreviation": "CP", "expansion": "chest pain"},
            {"abbreviation": "MS", "expansion": "mitral stenosis"},
        ],
    )
    assert out == "Patient has chest pain and mitral stenosis"
```

这就是防 offset 错位。

## 核心9 · 否定和上下文原样保留

确定性替换只替换缩写 token,不会改其它词。

例如:

```text
Patient denies CP
```

替换后:

```text
Patient denies chest pain
```

`denies` 不会被 LLM 改成别的表达,也不会丢掉。

对应测试:

```python
def test_negation_preserved():
    out = _build(
        "Patient denies CP",
        [{"abbreviation": "CP", "expansion": "chest pain"}],
    )
    assert out == "Patient denies chest pain"
```

这就是 V11 对 negation preservation 的基础保障。

## 数据快照

### 输入

```text
Patient denies SOB but reports CP.
```

### gate + coverage 后 chosen

```json
[
  {"abbreviation": "SOB", "expansion": "shortness of breath"},
  {"abbreviation": "CP", "expansion": "chest pain"}
]
```

### 确定性替换输出

```text
Patient denies shortness of breath but reports chest pain.
```

### 不替换的情况

```text
原文: "CPR was performed."
chosen: [{"abbreviation":"CP","expansion":"chest pain"}]
输出: "CPR was performed."
```

### coverage 拒绝的情况

```text
best_expansion = None
status = NOT_EXPANDED
chosen 里没有该 record
原文 token 保持不变
```

## 它在主状态机里的位置

`expand_verify_with_retry()` 里会多次构造 expanded text:

```python
current_expanded_text = self._build_expanded_text_deterministic(
    text,
    _visible(records)
)
```

其中 `_visible(records)`:

```python
return [
    r for r in recs
    if r["expansion"] and r["status"] != "ABSTAIN"
]
```

含义:

```text
有 expansion
且没有 ABSTAIN
才会显示在 expanded_text 里
```

所以 expanded_text 不是一次性生成后不变。随着 record 状态变化,它会被重新构建。

## 其余细节(次要,一行带过)

【次要】`re.escape(abbr)` 防止缩写里有特殊正则字符;当前 gate 要求纯字母,所以更多是防御式写法;`words = text.replace(",", " ").replace(".", " ").split()` 只特殊处理逗号和句号,其它标点靠 `strip(".,;:()[]{}")`;`chosen_label` 当前一直是 None,不是 gate 的关键字段。

## 死代码 / 盲肠提醒

- `ABBRService.__init__` 里的 `self.abbr_dict` 是 V0 硬编码遗留,当前 gate 用的是 `ABBR_CANDIDATES.keys()`,主链路不读 `self.abbr_dict`。
- `_build_expanded_text_deterministic()` 是纯方法,测试里用 `ABBRService._build_expanded_text_deterministic(None, ...)` 绕过模型加载来测,说明它不依赖实例状态。
- 文件底部的大注释仍在描述早期 "LLM 明确告诉你哪个缩写被扩成什么" 的旧结构,和 V11 当前 coverage → deterministic replacement 的主流程不完全一致。

## 真实边界 / 小坑

### 1. 已知小写缩写 gate 会放行,但替换可能匹配不到

Gate 里:

```python
upper_token = token.upper()
if upper_token in known_abbrs:
    return True
abbr = raw_token.strip().upper()
```

如果原文是:

```text
patient has sob
```

gate 会认为 `sob` 是已知缩写,并把 abbr 设为 `SOB`。

但替换时:

```python
pattern = re.compile(r"\bSOB\b")
```

默认大小写敏感,可能匹配不到原文里的 `sob`。

这就是一个真实边界:gate 说"已知缩写大小写都允许",但替换函数目前没有 `re.IGNORECASE`,也没有保留原 token 形态。

### 2. 非纯字母缩写会被 gate 拒绝

```python
if not upper_token.isalpha():
    return False
```

所以:

```text
O2
H1N1
2D
```

这类带数字的医学表达不会进入缩写候选召回。可能是安全取舍,但会漏一部分真实医学缩写/符号。

### 3. 未知缩写必须全大写且 <=8

这能防普通词误入 fallback,但也会漏掉一些非全大写写法或长缩写。

### 4. 多次出现同一缩写会全部替换

只要 regex 找到多个 span,都会加入 spans:

```text
CP and CP
→ chest pain and chest pain
```

这通常合理,但如果同一句中同一缩写不同含义,当前 record 级别无法区分不同 occurrence。

## 优化方向(更好 / 更稳)

1. **修复大小写不一致问题**:要么 gate 对已知缩写也要求原文形态,要么替换时用 `re.IGNORECASE`,要么 record 保存原始 token。
2. **支持 occurrence-level mapping**:当前一个 abbreviation 在一句里只能对应一个 expansion;如果同句两处 `MS` 不同义,无法区分。
3. **扩展 tokenization**:当前手写 split/strip 简单可控,但对斜杠、连字符、数字缩写支持有限。
4. **允许特定数字缩写白名单**:例如 O2、H1N1 这类医学常见表达,可通过规则或词典白名单放行。
5. **记录 span 到 output**:把替换位置 start/end 返回到 mapping_states,方便调试和前端高亮。
6. **检测重叠 span**:如果未来支持复杂缩写,需要防止两个候选 span 重叠导致替换冲突。
7. **把 gate 规则配置化/测试化**:目前 gate 缺少专门测试,建议补 `test_should_consider_abbreviation`。

## 会被追问 / 诚实局限(主动说)

- **确定性替换不是语义理解**:它只按 token 边界替换,不理解语法;语义选择靠 coverage。
- **大小写边界要诚实说**:已知小写缩写可能 gate 放行但替换不命中,这是可修的小 bug/边界。
- **不支持同缩写多 occurrence 不同义**:同一句中所有 CP 都替成同一个 expansion。
- **不处理带数字/符号缩写**:因为 gate 要求纯字母。
- **tokenization 简单**:足够原型和 benchmark,但生产医学文本可能需要更稳的 tokenizer。

## 面试怎么说

**合格版(30 秒)**:
> V11 里我把缩写判断和文本改写拆开了。`_should_consider_abbreviation` 先做 gate:已知缩写大小写都允许,未知缩写必须原文全大写且长度 2-8,避免普通词进入 fallback。coverage 选出 best_expansion 后,`_build_expanded_text_deterministic` 用 `\bABBR\b` 按 token 边界替换,不让 LLM 直接改整句。

**优秀版(1 分钟)**:
> 这个设计是为了把 LLM 的自由度降到最低。LLM/coverage 只负责判断哪个候选扩写适合上下文,真正改写文本由确定性函数完成。替换时我用 word boundary,所以 CP 不会误伤 CPR;先收集所有 span 再从后往前替,所以多缩写不会因为字符串长度变化导致 offset 错位;否定词和其它上下文也原样保留。gate 这边则区分已知和未知缩写:词典里有的相对宽松,未知缩写必须全大写且短,才允许进入 LLM fallback。诚实说,当前还有边界:小写已知缩写 gate 会放行但替换可能大小写匹配不到,带数字缩写也会被 isalpha 拒绝,这些是后续 tokenizer/gate 可以补的地方。

## 易错点 / 面试问答

**Q:最终 expanded_text 是 LLM 生成的吗?**  
A:不是。LLM/coverage 只选 `best_expansion`;最终文本由 `_build_expanded_text_deterministic()` 确定性替换。

**Q:为什么不用 `text.replace()`?**  
A:`replace` 会误伤子串,比如 CP 命中 CPR。当前用 `\bCP\b` token 边界匹配。

**Q:为什么从后往前替换?**  
A:避免前面替换改变字符串长度后,后面 span 的位置失效。

**Q:未知缩写什么时候会走 fallback?**  
A:必须是纯字母、原文全大写、长度 2-8,且不在本地词典里。

**Q:已知缩写小写能处理吗?**  
A:gate 会放行,但当前替换正则大小写敏感,可能匹配不到小写原文。这是一个需要修复的真实边界。

**Q:同一句里两个 CP 能不能表示不同意思?**  
A:当前不能。一个 abbreviation 在当前句子里会被同一个 expansion 全部替换。

## 一句话总结

> `ABBRService` 的缩写 gate 和确定性替换是 V11 控制幻觉的关键小机关:gate 先限制哪些 token 能进入候选召回,避免普通词滥用 fallback;coverage 只选 best_expansion;最终 expanded_text 由 `_build_expanded_text_deterministic()` 按 token 边界、从后往前稳定替换,保留原句结构和否定语义。它让 LLM 不再直接改整句,但也有大小写、数字缩写、同缩写多义 occurrence 等需要后续增强的边界。

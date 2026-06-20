### 场景

verify_mappings **收到** 3 个待校验的 mapping(输入):

text

```text
输入 mapping_standardizations = [HTN→hypertension, DM→diabetes mellitus, CP→chest pain]
```

prompt 要求 LLM **返回 3 条** mapping_validations(每个 mapping 一条判断)。但 LLM 偶尔会"偷懒/出错",**只返回 2 条**:

text

```text
LLM 返回 mapping_validations = [
   {HTN→hypertension, is_valid:true},
   {DM→diabetes mellitus, is_valid:true}
]   ← CP 那条不见了！LLM 漏了
```

### 问题出在 `all(...)` 只看"列表里有的"

python

```python
overall_valid = (
    句子有效
    and len(mapping_validations) > 0          # = 2 > 0 ✅
    and all(v.is_valid for v in validations)  # all([True, True]) = True ✅
)
# → overall_valid = True 整体通过！
```

`all(...)` 只对**列表里实际存在的元素**判断。CP 那条**根本不在列表里**,`all()` 就当它**不存在**,不会因为"少了一个"而变 False。

**后果**:CP 这个缩写**从头到尾没被校验过**,却因为它"消失"了,系统以为"在场的都通过了 → 整体通过"。**一个没检查的 mapping,蒙混过关了。** 这就是"误判通过"。

> 类比:老师收作业,3 个学生该交,只收到 2 份且都及格,老师却宣布"全班及格"——第 3 个人压根没交,被当成不存在了。

### 修复:代码层加一个"数量必须相等"的断言

不靠 LLM 自觉,代码自己卡一道:

python

```python
if len(mapping_validations) != len(mapping_standardizations):
    # 数量对不上 = LLM 漏返回了，结果不可信
    return {..., "overall_valid": False, "issues": ["validation_count_mismatch"]}
    # 或者：直接触发重试，让 LLM 重新完整判一遍
```

意思:**"我给你 3 个,你必须还我 3 个判断;少一个就说明你没做完,这次结果作废、判失败或重做"**,而不是默默接受残缺的列表。

### 为什么算个真实隐患

- prompt 里虽然写了 "The number of mapping_validations must be exactly the same as input",但**这只是文字叮嘱,LLM 不保证遵守**(回扣前面"软约束 vs 硬约束"那套——又是一个该用代码硬卡、却只靠 prompt 软约束的地方)。
- 而且这种漏检**静默发生、不报错**,比直接崩更危险——你以为校验通过了,其实有缩写没查。

面试这么说:

> "verify 的 overall_valid 用 all() 聚合每个 mapping 的判断,但代码没校验 LLM 返回的判断条数等于输入条数。如果 LLM 漏返回一条,all() 只在剩下的上判断,那个被漏掉的 mapping 就静默通过了。修复很简单——代码层断言返回数量等于输入数量,不一致直接判失败或重试。这又是个'本该代码硬卡、却只靠 prompt 软约束'的点。"
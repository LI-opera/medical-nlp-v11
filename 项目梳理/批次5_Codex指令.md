# 批次 5 · 给 Codex 的指令(可整段复制)· 交付物 standardized_entities

## 背景

V11 批次 1/2/3-rev 已合入。本批是**交付物升级**:出口除 `expanded_text + mappings`,再加 **`standardized_entities`**——每个成功标准化(LOCKED_OK)的扩写对应的 **SNOMED concept_id / concept_code / concept_name / domain_id**。兑现"不止扩写,还给标准编码"的标准化平台定位。

**范围说明(重要)**:原批次 5 还含"verify 瘦身(跳过句子级)"。但**批次 2 之后状态机只读每个 mapping 的 `is_valid`、不再用 `overall_valid`/句子级判定**——句子级已不参与决策,瘦身无收益且有风险。**故本批只做交付物,不动 verify。**

工作在 `medical-refactor`(HEAD 若飘到 `medical` 先 `git switch -f medical-refactor`)。当前最新提交 `7348aff`(batch3-rev)。

## 铁律

1. **先 Read 现状**:`backend/api/schemas.py`、`backend/api/main.py`。下面行号是当前快照。
2. **零准确率风险**:benchmark 走 `expand_verify_with_retry`、**不经过 API**,所以本批**不影响 benchmark、无需重定基线**。
3. **不动**:`abbr_service` / verifier / 状态机 / 检索 / 评测。只改 API 两个文件。
4. **数据来源**:批次 2 的 `final_result["mapping_standardizations"]` 已经是【仅 LOCKED_OK 的 mapping + 各自 SNOMED 检索候选(`candidates`,含 concept_id/concept_code/...)】,直接取用即可,不要重新检索。

## 改动 1 — `backend/api/schemas.py · SimpleExpandResponse`

给类加一个带默认值的字段(默认空列表,向后兼容):

```python
class SimpleExpandResponse(BaseModel):
    """
    简洁版扩写结果。
    """

    success: bool
    expanded_text: str
    mappings: list[dict]
    standardized_entities: list[dict] = []
```

## 改动 2 — `backend/api/main.py · /expand/simple`

在现有 `final_result = result.get("final_result",{})` 之后、`return {...}` 之前,**新增**组装 `standardized_entities` 的逻辑;并在返回 dict 里加上该字段:

```python
    final_result = result.get("final_result", {}) or {}

    # 从每个 LOCKED_OK mapping 的 SNOMED 检索结果取 top-1 概念,作为标准化编码出口
    standardized_entities = []
    for ms in final_result.get("mapping_standardizations", []):
        candidates = ms.get("candidates") or []
        if not candidates:
            continue
        top = candidates[0]
        standardized_entities.append({
            "abbreviation": ms.get("abbreviation"),
            "expansion": ms.get("expansion"),
            "concept_id": top.get("concept_id"),
            "concept_name": top.get("concept_name"),
            "concept_code": top.get("concept_code"),
            "domain_id": top.get("domain_id"),
            "score": top.get("score"),
        })

    return {
        "success": result.get("success", False),
        "expanded_text": final_result.get("expanded_text", request.text),
        "mappings": final_result.get("mappings", []),
        "standardized_entities": standardized_entities,
    }
```

> 说明:`mapping_standardizations` 在批次 2 出口里只含 LOCKED_OK 的 mapping(弃权的不进),所以 `standardized_entities` 天然只给"扩写成功且有 SNOMED 支持"的项。某 mapping 检索为空(候选 0 条)则跳过、不报错。

## 验收

1. **能编译**:`python -m compileall backend/api/schemas.py backend/api/main.py`。
2. **起服务实测**:
   ```bash
   uvicorn api.main:app --app-dir backend --reload
   ```
   另开终端(Milvus 要起着):
   ```bash
   curl -s -X POST http://localhost:8000/expand/simple -H "Content-Type: application/json" -d "{\"text\": \"The patient has SOB and CP.\"}"
   ```
   - 期望响应含 `standardized_entities`,里面每个成功扩写(shortness of breath / chest pain)带 `concept_id`、`concept_code` 等。
   - `success`/`expanded_text`/`mappings` 字段**原样保留**。
3. **benchmark 不受影响**:不用重跑(API 不在 benchmark 路径上);跑也行,数字应和 batch3-rev 一致。
4. **判定**:响应含标准编码 + 原字段没坏 → 合入。

## 提交

```bash
git add -A
git commit -m "V11 batch5: expose standardized_entities (SNOMED codes) in /expand/simple response"
```

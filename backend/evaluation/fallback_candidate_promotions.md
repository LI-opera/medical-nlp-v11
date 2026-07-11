# fallback 成功候选沉淀清单

## 筛选口径

- case 必须是 benchmark 正确案例：`correct = true`。
- record 必须来自 fallback：`source = fallback`。
- record 必须已经成功标准化：`status = CODED`。
- 同一 abbreviation + expansion 必须存在 `chosen_concept`。
- 本文件只展示候选，不写入 primary 候选库。

## 汇总

- 候选总数: `9`
- 新候选数: `9`
- primary 中已存在: `0`

## 新候选

### ABG -> arterial blood gas

- domain: `Procedure`
- support_count: `1`
- case_ids: `["case_fallback_001"]`
- chosen_concepts: `[{"concept_id": "4239236", "concept_name": "Blood gases, arterial measurement", "domain_id": "Measurement", "concept_code": "91308007"}]`
- candidate_to_append: `{"expansion": "arterial blood gas", "domain": "Procedure"}`

示例：

```json
[
  {
    "id": "case_fallback_001",
    "category": "upload_fallback_should_expand",
    "text": "The ABG revealed respiratory acidosis with hypoxemia.",
    "final_expanded_text": "The arterial blood gas revealed respiratory acidosis with hypoxemia."
  }
]
```

### ASD -> Atrial Septal Defect

- domain: `Condition`
- support_count: `1`
- case_ids: `["case_fallback_003"]`
- chosen_concepts: `[{"concept_id": "4289309", "concept_name": "Atrial septal defect", "domain_id": "Condition", "concept_code": "70142008"}]`
- candidate_to_append: `{"expansion": "Atrial Septal Defect", "domain": "Condition"}`

示例：

```json
[
  {
    "id": "case_fallback_003",
    "category": "upload_fallback_should_expand",
    "text": "The ASD was repaired in childhood.",
    "final_expanded_text": "The Atrial Septal Defect was repaired in childhood."
  }
]
```

### BAL -> bronchoalveolar lavage

- domain: `Procedure`
- support_count: `1`
- case_ids: `["case_fallback_002"]`
- chosen_concepts: `[{"concept_id": "4336913", "concept_name": "Bronchoscopic lavage", "domain_id": "Procedure", "concept_code": "232595000"}]`
- candidate_to_append: `{"expansion": "bronchoalveolar lavage", "domain": "Procedure"}`

示例：

```json
[
  {
    "id": "case_fallback_002",
    "category": "upload_fallback_should_expand",
    "text": "The BAL was performed for pneumonia evaluation.",
    "final_expanded_text": "The bronchoalveolar lavage was performed for pneumonia evaluation."
  }
]
```

### BM -> bone marrow

- domain: `Observation`
- support_count: `1`
- case_ids: `["case_fallback_008"]`
- chosen_concepts: `[{"concept_id": "4029619", "concept_name": "Bone marrow structure", "domain_id": "Spec Anatomic Site", "concept_code": "14016003"}]`
- candidate_to_append: `{"expansion": "bone marrow", "domain": "Observation"}`

示例：

```json
[
  {
    "id": "case_fallback_008",
    "category": "upload_fallback_should_expand",
    "text": "The BM biopsy was performed.",
    "final_expanded_text": "The bone marrow biopsy was performed."
  }
]
```

### BP -> blood pressure

- domain: `Procedure`
- support_count: `1`
- case_ids: `["case_fallback_004"]`
- chosen_concepts: `[{"concept_id": "4326744", "concept_name": "Blood pressure", "domain_id": "Measurement", "concept_code": "75367002"}]`
- candidate_to_append: `{"expansion": "blood pressure", "domain": "Procedure"}`

示例：

```json
[
  {
    "id": "case_fallback_004",
    "category": "upload_fallback_should_expand",
    "text": "The BP remained elevated overnight.",
    "final_expanded_text": "The blood pressure remained elevated overnight."
  }
]
```

### DC -> discharge

- domain: `Observation`
- support_count: `1`
- case_ids: `["case_fallback_006"]`
- chosen_concepts: `[{"concept_id": "4294698", "concept_name": "Discharge", "domain_id": "Observation", "concept_code": "75823008"}]`
- candidate_to_append: `{"expansion": "discharge", "domain": "Observation"}`

示例：

```json
[
  {
    "id": "case_fallback_006",
    "category": "upload_fallback_should_expand",
    "text": "The DC summary was reviewed.",
    "final_expanded_text": "The discharge summary was reviewed."
  }
]
```

### ECG -> electrocardiogram

- domain: `Procedure`
- support_count: `1`
- case_ids: `["case_fallback_007"]`
- chosen_concepts: `[{"concept_id": "4163951", "concept_name": "Electrocardiographic procedure", "domain_id": "Procedure", "concept_code": "29303009"}]`
- candidate_to_append: `{"expansion": "electrocardiogram", "domain": "Procedure"}`

示例：

```json
[
  {
    "id": "case_fallback_007",
    "category": "upload_fallback_should_expand",
    "text": "The ECG showed sinus rhythm.",
    "final_expanded_text": "The electrocardiogram showed sinus rhythm."
  }
]
```

### IM -> intramuscular

- domain: `Observation`
- support_count: `1`
- case_ids: `["case_fallback_009"]`
- chosen_concepts: `[{"concept_id": "4116871", "concept_name": "Intramuscular", "domain_id": "Observation", "concept_code": "255559005"}]`
- candidate_to_append: `{"expansion": "intramuscular", "domain": "Observation"}`

示例：

```json
[
  {
    "id": "case_fallback_009",
    "category": "upload_fallback_should_expand",
    "text": "The IM injection was tolerated.",
    "final_expanded_text": "The intramuscular injection was tolerated."
  }
]
```

### RA -> Rheumatoid Arthritis

- domain: `Condition`
- support_count: `1`
- case_ids: `["case_fallback_010"]`
- chosen_concepts: `[{"concept_id": "80809", "concept_name": "Rheumatoid arthritis", "domain_id": "Condition", "concept_code": "69896004"}]`
- candidate_to_append: `{"expansion": "Rheumatoid Arthritis", "domain": "Condition"}`

示例：

```json
[
  {
    "id": "case_fallback_010",
    "category": "upload_fallback_should_expand",
    "text": "The RA symptoms improved with therapy.",
    "final_expanded_text": "The Rheumatoid Arthritis symptoms improved with therapy."
  }
]
```

## 已存在候选

- 无。

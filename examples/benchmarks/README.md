# Benchmark 样例

本目录保存可以直接上传到前端 Benchmark 页面，或作为默认 benchmark 输入的 JSON 样例。

## 文件格式

```json
{
  "description": "说明文字",
  "cases": [
    {
      "id": "single_001",
      "category": "single_meaning",
      "text": "The patient has HTN.",
      "expected_mappings": [
        {
          "abbreviation": "HTN",
          "expansion": "hypertension"
        }
      ]
    }
  ]
}
```

每个 case 至少需要 `id`、`text` 和 `expected_mappings`。`expected_text_contains` 用于验证扩写后的句子是否保留指定语义片段。

## 当前样例

- `abbr_benchmark_cases.json`：V11 默认 74 条缩写 benchmark，包含项目自建案例和 CASI 案例。
- `upload_test_benchmark_cases_50.json`：前端上传流程测试样例。
- `upload_test_benchmark_cases_60.json`：前端动态 Overview、Error Analysis 和 Fallback Promotions 测试样例。

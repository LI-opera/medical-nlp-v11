# L3 · Stage-1 给 Codex 的指令(可整段复制)· 筛 RxNorm + 建第二个 Milvus 库

## 背景与范围

L3 多源路由的第一步:**建第二个知识源 RxNorm**(药品),仿 SNOMED 那套 `build_concept_csv.py` + `rebuild_milvus.py`。**SNOMED 的库 `concepts_only_name` 一律不动**;新建独立 collection `rxnorm_concepts`。本批只造数据+建库,**不碰主链路、不接路由**(路由是后面 Stage)。

**铁律**:只**新增** `tools/build_rxnorm_csv.py`、`tools/rebuild_rxnorm_milvus.py` 两个离线脚本 + gitignore 一行;不改任何现有代码。

工作在 `medical-refactor`。

---

## A · 新建 `backend/tools/build_rxnorm_csv.py`

```python
"""
把 Athena CONCEPT.csv 里的 RxNorm 药品词表,筛成 backend/data/rxnorm_clinical.csv。
仿 build_concept_csv.py(SNOMED 那套)。SNOMED 不动,这是第二个源。
运行时会先打印 RxNorm 数量 + concept_class 分布(顺带当数据验证),再写出 CSV。
跑法:python backend/tools/build_rxnorm_csv.py
"""
import os
import pandas as pd

# ★ 新下载的、含 RxNorm 的 CONCEPT.csv 完整路径(已填好)
INPUT_CSV = r"E:\Work\数据库-medical\vocabulary_download_v5_{c4c88598-d60c-46b2-b609-64fd902cc91c}_1782381867144\CONCEPT.csv"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
OUTPUT_CSV = os.path.join(BACKEND_DIR, "data", "rxnorm_clinical.csv")

MAX_ROWS = None   # 全量(Li 要全量)


def main():
    print(f"读取 {INPUT_CSV} ...(Tab 分隔,全部按字符串读)")
    df = pd.read_csv(INPUT_CSV, sep="\t", dtype=str, keep_default_na=False, na_values=[""])
    print(f"  原始行数: {len(df):,}")

    print(f"  RxNorm 行数: {len(df[df['vocabulary_id'] == 'RxNorm']):,}")

    m = (
        (df["vocabulary_id"] == "RxNorm")
        & (df["standard_concept"] == "S")
        & (df["invalid_reason"].fillna("") == "")
        & (df["domain_id"] == "Drug")
    )
    out = df[m].copy()
    print(f"  标准+有效+Drug 行数: {len(out):,}")
    print("  concept_class 分布(前 15):")
    for cls, n in out["concept_class_id"].value_counts().head(15).items():
        print(f"    {n:>8,}  {cls}")
    ing = out[out["concept_class_id"] == "Ingredient"]["concept_name"].head(10).tolist()
    print(f"  Ingredient 样例: {ing}")

    if MAX_ROWS and len(out) > MAX_ROWS:
        out = out.head(MAX_ROWS)
        print(f"  ★ 截到前 {MAX_ROWS:,} 条")

    out["FSN"] = out["concept_name"]
    out = out[["concept_id", "concept_name", "domain_id", "concept_code", "FSN"]]
    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\n已写出 {OUTPUT_CSV}  共 {len(out):,} 条")
    print("下一步:python backend/tools/rebuild_rxnorm_milvus.py 建第二个库。")


if __name__ == "__main__":
    main()
```

## B · 新建 `backend/tools/rebuild_rxnorm_milvus.py`

```python
"""
用 rxnorm_clinical.csv 建第二个 Milvus collection: rxnorm_concepts。
仿 rebuild_milvus.py;★ SNOMED 的 concepts_only_name 不动,这是另一个独立 collection。
跑法:python backend/tools/rebuild_rxnorm_milvus.py
"""
import os
import sys
import pandas as pd
from pymilvus import MilvusClient, DataType

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(BACKEND_DIR)

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model

CSV_PATH = os.path.join(BACKEND_DIR, "data", "rxnorm_clinical.csv")
COLLECTION_NAME = "rxnorm_concepts"            # ★ 与 SNOMED 的 concepts_only_name 分开
MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
BATCH = 256


def main():
    print(f"读取 {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    names = df["concept_name"].astype(str).tolist()
    print(f"  共 {len(df):,} 条")

    print("加载 embedding 模型(bge-m3)...")
    model = create_embedding_model(EmbeddingConfig())
    dim = len(model.embed_query("test"))
    print("  向量维度:", dim)

    print("连接 Milvus:", MILVUS_URI)
    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(COLLECTION_NAME):
        print("  删除旧 collection", COLLECTION_NAME)
        client.drop_collection(COLLECTION_NAME)

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    for f in [
        {"field_name": "id", "datatype": DataType.INT64, "is_primary": True},
        {"field_name": "concept_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "concept_name", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "domain_id", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "concept_code", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "vector", "datatype": DataType.FLOAT_VECTOR, "dim": dim},
        {"field_name": "FSN", "datatype": DataType.VARCHAR, "max_length": 2048},
    ]:
        schema.add_field(**f)

    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(collection_name=COLLECTION_NAME, schema=schema, index_params=index_params)

    print("批量算向量 + 插入 ...")
    total = len(df)
    for start in range(0, total, BATCH):
        end = min(start + BATCH, total)
        vectors = model.embed_documents(names[start:end])
        rows = []
        for i in range(start, end):
            r = df.iloc[i]
            rows.append({
                "id": i,
                "concept_id": str(r["concept_id"]),
                "concept_name": str(r["concept_name"]),
                "domain_id": str(r["domain_id"]),
                "concept_code": str(r["concept_code"]),
                "FSN": str(r.get("FSN", "")),
                "vector": vectors[i - start],
            })
        client.insert(collection_name=COLLECTION_NAME, data=rows)
        print(f"  {end:,}/{total:,}", end="\r")

    client.flush(collection_name=COLLECTION_NAME)
    client.load_collection(collection_name=COLLECTION_NAME)
    print(f"\n完成,共插入 {total:,} 条到 {COLLECTION_NAME}。")

    print("\n=== 自测 'aspirin' ===")
    qv = model.embed_query("aspirin")
    res = client.search(collection_name=COLLECTION_NAME, data=[qv], anns_field="vector",
                        limit=5, output_fields=["concept_name", "domain_id", "concept_code"])
    for it in res[0]:
        e = it["entity"]
        print(f"  {e['concept_name']!r}  domain={e['domain_id']}  score={round(it['distance'], 4)}")


if __name__ == "__main__":
    main()
```

## C · `.gitignore` 追加(全量 CSV 不进库)

```
backend/data/rxnorm_clinical.csv
rxnorm_clinical.csv
```

---

## 跑法 + 验收(分两步,中间有检查点)

1. **先跑筛库**:`python backend/tools/build_rxnorm_csv.py`
   - 它会打印:RxNorm 总行、标准+有效+Drug 行数、concept_class 分布、Ingredient 样例,并写出 `backend/data/rxnorm_clinical.csv`。
   - **★检查点**:把这段打印贴回来。重点看"标准+有效+Drug"有多少、Ingredient 占多少——确认库够用、且 aspirin/methotrexate 这类成分级概念在内。**确认 OK 再跑第 2 步**(嵌入很慢,先验数据)。
2. **再建库**:`python backend/tools/rebuild_rxnorm_milvus.py`
   - 批量嵌入 + 建 `rxnorm_concepts`;自测 `aspirin` 应返回 'Aspirin'/Drug/高分。
3. **确认 SNOMED 没受影响**:`rebuild_rxnorm_milvus` 只 drop/建 `rxnorm_concepts`,不碰 `concepts_only_name`;主 benchmark 与 concept benchmark 仍照常(本批没接线、它们还查 SNOMED 库)。
4. **判定**:第 1 步数据合理 + 第 2 步自测 aspirin 命中 + SNOMED 库不受影响 → 合入。

## 提交

```bash
git add backend/tools/build_rxnorm_csv.py backend/tools/rebuild_rxnorm_milvus.py .gitignore
git commit -m "V11 L3 stage1: build RxNorm second source (filter RxNorm standard Drug concepts -> rxnorm_clinical.csv + rxnorm_concepts Milvus collection). SNOMED lib untouched; not wired yet."
```
> 这是 L3 第一阶段(只造第二个库)。后续:Stage-2 检索器按源查 → Stage-3 NER domain 路由(药→rxnorm_concepts、病→concepts_only_name)→ Stage-4 词典补药品缩写+concept bench 补药品 gold → Stage-5 量 → Stage-6 可选 LangGraph 收尾。

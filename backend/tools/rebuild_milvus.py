"""
用筛好的 snomed_clinical.csv 重建 Milvus(批量算向量,比 create_milvus_db.py 快几十倍)。
和原库同名同结构(collection = concepts_only_name),所以项目其它代码一行都不用改。

用法:
  1. 先跑 build_concept_csv.py 生成 backend/data/snomed_clinical.csv。
  2. 确认 Milvus 起着(docker)。
  3. python backend/tools/rebuild_milvus.py
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

CSV_PATH = os.path.join(BACKEND_DIR, "data", "snomed_clinical.csv")
COLLECTION_NAME = "concepts_only_name"
MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
BATCH = 256   # 一次算多少条向量(批量,快)


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
        print("  删除旧 collection")
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
        vectors = model.embed_documents(names[start:end])   # ★ 批量,一次一批
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
    print(f"\n完成,共插入 {total:,} 条。")

    # 自测:chest pain 现在该捞到忠实的"胸痛"概念了
    print("\n=== 自测 'chest pain' ===")
    qv = model.embed_query("chest pain")
    res = client.search(collection_name=COLLECTION_NAME, data=[qv], anns_field="vector",
                        limit=5, output_fields=["concept_name", "domain_id", "concept_code"])
    for it in res[0]:
        e = it["entity"]
        print(f"  {e['concept_name']!r}  domain={e['domain_id']}  score={round(it['distance'],4)}")


if __name__ == "__main__":
    main()

# 接收用户输入
#     ↓
# 把输入变成 query vector
#     ↓
# 去 Milvus 里搜索
#     ↓
# 返回最相似医学术语
import os
from pymilvus import MilvusClient

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model

class StdService:
    #因为这个类是用来搜索的所以在初始化时应该保证cllection已经load
    def __init__(self):
        self.collection_name = os.getenv(
            "MILVUS_COLLECTION_NAME",
            "concepts_only_name"
        )

        self.milvus_uri = os.getenv(
            "MILVUS_URI",
            "http://127.0.0.1:19530"
        )

        self.embedding_model = create_embedding_model(EmbeddingConfig())

        self.client = MilvusClient(uri=self.milvus_uri)

        self.client.load_collection(collection_name=self.collection_name)
    def search_similar_terms(self,query:str,limit:int=5):
        query_vector = self.embedding_model.embed_query(query)
        search_result = self.client.search(
            collection_name=self.collection_name,
            data=[query_vector],
            anns_field="vector",
            limit=limit,
            output_fields=[
                "concept_id",
                "concept_name",
                "domain_id",
                "concept_code",
                "FSN"
            ]
        )
        results = []

        for item in search_result[0]:
            entity = item["entity"]
            results.append({
                "input": query,
                "concept_id": entity["concept_id"],
                "concept_name": entity["concept_name"],
                "domain_id": entity["domain_id"],
                "concept_code": entity["concept_code"],
                "FSN":entity["FSN"],
                #round(数字, 保留几位)
                "score": round(item["distance"],4)
            })
        return results
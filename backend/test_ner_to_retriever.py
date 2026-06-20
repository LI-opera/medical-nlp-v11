# 输入一整段医疗文本
#         ↓
# NER 自动抽取实体
#         ↓
# 每个实体调用 MedicalRetriever
#         ↓
# 返回标准医学术语候选

from services.ner_service import NERService
from services.medical_retriever import MedicalRetriever

def main():
    ner_service = NERService()
    retriever = MedicalRetriever()

    text = "The patient has chest pain, shortness of breath, and diabetes."

    entities = ner_service.extract_entities(text)

    print("原始文本:")
    print(text)
    print("="*50)

    for entity in entities:
        entity_text = entity["text"]
        print("识别实体:",entity_text)
        print("实体类型:",entity["label"])
        print("NER分数:",entity["score"])
        docs = retriever.retrieve(
            query = entity_text,
            top_k=10,
            domain_filter=None,
            score_threshold=0.68
        )
        print("标准术语候选:")

        for doc in docs:
            print("concept_name:",doc["metadata"]["concept_name"],
                  "score:",doc["metadata"]["score"],
                  "rerank_score:",doc["metadata"]["rerank_score"]
                  )
        print("-"*50)
if __name__ == "__main__":
    main()
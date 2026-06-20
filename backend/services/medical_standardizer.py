from services.ner_service import NERService
from services.medical_retriever import MedicalRetriever

class MedicalStandardizer:
    """
    医疗术语标准化器
    组合NER + Retriever:
    1.从文本中抽取医学实体
    2.从每个实体检索SNOMED候选术语
    3.返回结构化标准化结果
    """
    def __init__(self):
        self.ner_service = NERService()
        self.retriever = MedicalRetriever()
    #这个函数的作用是返回文本医学实体中所对应的snomed库中的候选资料
    def standardize(self,text:str):
        #拿出文本对应的医学实体
        entities = self.ner_service.extract_entities(text)

        results = []
        #遍历医学实体拿出检索对应snomed中的相关数据
        for entity in entities:
            entity_text = entity["text"]

            docs = self.retriever.retrieve(
                query=entity_text,
                top_k=10,
                domain_filter=None,
                score_threshold=0.6
            )
            #候选列表用来装医学实体检索出来的匹配数据
            candidates = []
            #遍历医学实体从snomed库中检索出来的前三个数据
            for doc in docs[:3]:
                metadata = doc["metadata"]
                #整理每个数据将他们逐一放到候选列表
                candidates.append({
                    "concept_id":metadata["concept_id"],
                    "concept_name":metadata["concept_name"],
                    "domain_id":metadata["domain_id"],
                    "concept_code":metadata["concept_code"],
                    "score":metadata["score"],
                    "rerank_score":metadata.get("rerank_score")
                })
            #每个医学实体对应一个候选列表，对应一组候选数据
            results.append({
                "entity":entity_text,
                "entity_label":entity["label"],
                "entity_score":entity["score"],
                "candidates":candidates
            })
        return {
            "input_text":text,
            "entities":results
        }

# query
#  ↓
# Milvus vector search
#  ↓
# TopK
#  ↓
# rule rerank
#  ↓
# filter
#  ↓
# documents
from services.std_service import StdService

class MedicalRetriever:
    """
    医疗知识检索器。
    这是RAG中的Retriever层。它不负责生成回答，只负责从医学知识库里找到相关内容。
    """
    def __init__(self):
        #StdService()实例化类，根据StdService()类，创建一个真正的对象
        # 已经连接好 Milvus
        # 已经创建好 embedding
        # 已经 load 好 collection
        self.std_service = StdService()
    def _rerank_results(
            self,
            query: str,
            results: list[dict],
            domain_boost: str | None = None
            ):
        """对检索结果进行简单重排。
            规则：
            完全等于 query
            最高优先以 query 开头
            第二优先包含 query
            第三优先包含但太长扣一点分
        """
        #忽略大小写
        query_lower = query.lower()
        #遍历检索结果
        for item in results:
            concept_name = item["concept_name"].lower().strip()
            #初试分数零分
            bonus = 0.0
            #如果concept_name和query完全一样，再额外加0.3分。
            if concept_name == query_lower:
                bonus += 0.5
            #以query开头
            elif concept_name.startswith(query_lower):
                bonus += 0.3
            #concept_name中包含query
            elif query_lower in concept_name:
                bonus += 0.15
            if domain_boost is not None and item.get("domain_id") == domain_boost:
                bonus += 0.2
            #长术语惩罚措施
            word_count = len(concept_name)
            if word_count > 10:
                bonus -= 0.25
            elif word_count > 6:
                bonus -= 0.15
            elif word_count > 4:
                bonus -= 0.08
            
            item["rerank_score"] = item["score"] + bonus

        #排序从大到小排序
        results.sort(
            key=lambda x:x["rerank_score"],
            reverse = True
        )
        return results

    def retrieve(
            self,
            query:str,
            top_k:int=5,
            #表示过滤条件
            domain_filter :str|None = None,
            #表示优先提升的领域，不过滤其他领域
            domain_boost: str | None = None,
            #表示过滤的最低分数
            score_threshold:float | None = None
            ):
        #根据用户数插入检索最相关的医学术语
        results = self.std_service.search_similar_terms(query=query,limit=top_k)
        results = self._rerank_results(query, results, domain_boost)
        documents = []
        for item in results:
            #如果有过滤条件但是条件不匹配就跳过本轮循环
            if domain_filter is not None and item["domain_id"]!=domain_filter:
                continue
            #如果有最低分数限制，分数没达到就跳过
            if score_threshold is not None and item["score"] < score_threshold:
                continue
            content = (
                    f"Concept Name:{item['concept_name']}\n"
                    f"Fully Specified Name:{item.get('FSN', '')}\n"
                    f"Domain:{item['domain_id']}\n"
                    f"Concept Code:{item['concept_code']}"
                )
            documents.append({
                "page_content":content,
                "metadata":{
                    "input":item["input"],
                    "concept_id":item["concept_id"],
                    "concept_name":item["concept_name"],
                    "domain_id":item["domain_id"],
                    "concept_code":item["concept_code"],
                    "score":item["score"],
                    "rerank_score":item["rerank_score"]
                }
            })
        return documents

from services.medical_retriever import MedicalRetriever

def main():
    retriever = MedicalRetriever()
    query = "chest pain"
    #通过retriever的向量相似度匹配先返回10个初筛，然后再使用过滤器，最低分数要求精筛
    docs = retriever.retrieve(query,top_k=10,domain_filter = "Condition",score_threshold=0.7)
    print("查询",query)
    print("="*50)

    for i,doc in enumerate(docs,start=1):
        print(f"Top{i}")
        print("内容:")
        print(doc["page_content"])
        print("元数据:")
        print(doc["metadata"])
        print("-"*50)

if __name__ == "__main__":
    main()
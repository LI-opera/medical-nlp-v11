from services.abbr_service import ABBRService

def main():
    #实例化类
    service = ABBRService()
    text = "The patient has SOB, DM, and HTN"

    result = service.expand_and_standardize(text)

    print("原始文本:")
    print(result["original_text"])
    print("="*50)

    print("扩展后文本:")
    print(result["expanded_text"])
    print("="*50)

    print("标准化结果:")
    #这里的item是text中每个医疗实体的元数据加从snomed数据库检索出来的候选值的属性所组合出来的
    for item in result["standardization"]["entities"]:
        print("实体:",item["entity"])
        print("实体类型:",item["entity_label"])
        print("候选术语:")
        for candidate in item["candidates"]:
            print(
                candidate["concept_name"],
                candidate["score"],
                candidate.get("rerank_score")
            )
        print("-"*50)
   
   #改写词与改写前词与改写词的候选
    print("缩写映射标准化结果:")

    for item in result["mapping_standardizations"]:
        print("缩写:", item["abbreviation"])
        print("扩展:", item["expansion"])
        print("SNOMED候选:")

        for candidate in item["candidates"]:
            print(
                candidate["concept_name"],
                candidate["score"],
                candidate.get("rerank_score")
            )

        print("-" * 50)

if __name__ == "__main__":
    main()
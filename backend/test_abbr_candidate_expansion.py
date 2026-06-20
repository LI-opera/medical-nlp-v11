from services.abbr_service import ABBRService

def main():
    service = ABBRService()

    texts = [
        "The patient has SOB, DM, and HTN.",
        "The patient reports CP.",
        "The child has a history of CP since birth.",
        "The patient has XYZ.",
        "The patient developed AKI after dehydration."
    ]

    for text in texts:
        result = service.simple_llm_expansion(text)

        print("原始文本:")
        print(result["original_text"])
        print("="*50)

        print("候选扩展:")
        for group in result["abbreviation_candidates"]:
            print("缩写:", group["abbreviation"])
            print("候选来源:", group.get("candidate_source"))
            print("原始候选:", group["candidates"])
            print("过滤后候选:", group["filtered_candidates"])
            print("Coverage:", group["coverage"])
            print("-" * 30)

        print("扩展后文本:")
        print(result["expanded_text"])
        print("=" * 50)

        print("映射结果:")
        for item in result["mappings"]:
            print(item)

        print("-" * 80)


if __name__ == "__main__":
    main()
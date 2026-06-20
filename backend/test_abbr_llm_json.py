from services.abbr_service import ABBRService

def main():
    service = ABBRService()

    text = "The patient has SOB, DM, and HTN"

    result = service.simple_llm_expansion(text)

    print("原始文本:")
    print(result["original_text"])
    print("="*50)

    print("扩展后文本:")
    print(result["expanded_text"])
    print("="*50)

    print("缩写映射:")
    for item in result["mappings"]:
        print(item)

if __name__ == "__main__":
    main()
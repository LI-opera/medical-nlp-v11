from services.abbr_service import ABBRService

def main():
    #将类实例化
    service = ABBRService()

    text = "The patient has SOB, DM, and HTN."

    result = service.expand_abbreviations(text)

    print("原始文本:")
    print(result["original_text"])

    print("="*50)

    print("扩展后文本:")
    print(result["expanded_text"])

    print("="*50)

    print("替换详情:")
    for item in result["replacements"]:
        print(item)

if __name__ == "__main__":
    main()
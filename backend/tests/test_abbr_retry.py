from services.abbr_service import ABBRService

def main():
    service = ABBRService()

    texts = [
    "The patient denies SOB.",
    "The patient developed AKI after dehydration.",
    "The patient has XYZ.",
    "The child has a history of CP since birth."
    ]
    for text in texts:
        result = service.expand_verify_with_retry(
            text = text,
            max_retries = 2
        )

        print("原始文本:")
        print(result["original_text"])
        print("="*50)

        print("最终扩写文本:")
        print(result["final_expanded_text"])
        print("="*50)

        print("是否成功:")
        print(result["success"])
        print("="*50)

        print("尝试记录:")

        for attempt in result["attempts"]:
            print("Attempt:", attempt["attempt"])
            print("Expanded:", attempt["expanded_text"])
            print("Overall valid:", attempt["verification"]["overall_valid"])
            print("Verification:", attempt["verification"])
            print("-" * 50)

if __name__ == "__main__":
    main()

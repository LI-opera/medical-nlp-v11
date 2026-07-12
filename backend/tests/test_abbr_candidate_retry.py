from services.abbr_service import ABBRService

def main():
    service = ABBRService()

    texts = [
        "The patient reports CP.",
        "The child has a history of CP since birth.",
        "The patient has SOB, DM, and HTN."
    ]

    for text in texts:
        result = service.expand_verify_with_retry(
            text=text,
            max_retries=2
        )

        print("原始文本:")
        print(result["original_text"])

        print("=" * 50)

        print("最终扩写文本:")
        print(result["final_expanded_text"])

        print("=" * 50)

        print("是否成功:")
        print(result["success"])

        print("=" * 50)

        print("Attempts:")

        for attempt in result["attempts"]:
            print("Attempt:", attempt["attempt"])
            print("Expanded:", attempt["expanded_text"])

            print("候选召回:")
            for candidate_group in attempt["abbreviation_candidates"]:
                print(candidate_group)

            print("Mappings:")
            for mapping in attempt["mappings"]:
                print(mapping)

            print("Verification:")
            print(attempt["verification"])

            print("-" * 50)

        print("=" * 80)

if __name__ == "__main__":
    main()
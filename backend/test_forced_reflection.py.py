from services.abbr_reflection_service import ABBRReflectionService


def main():
    reflector = ABBRReflectionService()

    original_text = "The patient denies SOB."

    wrong_expanded_text = "The patient has shortness of breath."

    fake_verification = {
        "sentence_validity": {
            "is_valid": False,
            "confidence": 0.2,
            "reason": "The expansion changed negation from denies to has.",
            "issues": ["negation_changed", "changed_meaning"]
        },
        "mapping_validations": [
            {
                "abbreviation": "SOB",
                "expansion": "shortness of breath",
                "context_supported": True,
                "snomed_supported": True,
                "is_valid": True,
                "confidence": 0.95,
                "reason": "SOB correctly expands to shortness of breath.",
                "issues": []
            }
        ],
        "overall_valid": False
    }

    result = reflector.reflect(
        original_text=original_text,
        previous_expanded_text=wrong_expanded_text,
        verification=fake_verification
    )

    print("原始文本:")
    print(original_text)

    print("=" * 50)

    print("错误扩写:")
    print(wrong_expanded_text)

    print("=" * 50)

    print("Reflection修正结果:")
    print(result)


if __name__ == "__main__":
    main()
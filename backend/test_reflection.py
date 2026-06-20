from services.abbr_reflection_service import ABBRReflectionService

def main():
    service = ABBRReflectionService()

    original_text =  "The patient denies SOB."

    previous_expanded_text = "The patient has shortness of breath."

    verification = {
        "sentence_validity": {
            "is_valid": False,
            "confidence": 0.2,
            "reason": "The negation was changed from denies to has.",
            "issues": ["negation_changed", "changed_meaning"]
        },
        "mapping_validations": [
            {
                "abbreviation": "SOB",
                "expansion": "shortness of breath",
                "context_supported": True,
                "snomed_supported": True,
                "is_valid": True,
                "confidence": 0.9,
                "reason": "SOB commonly means shortness of breath.",
                "issues": []
            }
        ],
        "overall_valid": False
    }

    result = service.reflect(
        original_text=original_text,
        previous_expanded_text=previous_expanded_text,
        verification=verification
    )
    print(result)

if __name__ == "__main__":
    main()
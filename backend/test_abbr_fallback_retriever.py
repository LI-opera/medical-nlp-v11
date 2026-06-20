from services.abbr_candidate_fallback_retriever import ABBRCandidateFallbackRetriever

def main():
    retriever = ABBRCandidateFallbackRetriever()
    tests = [
        ("XYZ", "The patient has XYZ."),
        ("CAD", "The patient has CAD and chest pain."),
        ("AKI", "The patient developed AKI after dehydration.")
    ]
    
    for abbr, text in tests:
        result = retriever.retrieve(
            abbreviation=abbr,
            context_text=text
        )

        print("原始文本:",text)
        print("缩写:",abbr)
        print("候选兜底:")
        print(result)
        print("-"*50)

if __name__ == "__main__":
    main()
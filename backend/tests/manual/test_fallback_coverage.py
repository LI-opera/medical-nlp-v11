from services.abbr_candidate_fallback_retriever import ABBRCandidateFallbackRetriever
from services.abbr_candidate_coverage_evaluator import ABBRCandidateCoverageEvaluator

def main():
    fallback = ABBRCandidateFallbackRetriever()
    evaluator = ABBRCandidateCoverageEvaluator()

    tests = [
        ("XYZ", "The patient has XYZ."),
        ("CAD", "The patient has CAD and chest pain."),
        ("AKI", "The patient developed AKI after dehydration.")
    ]

    for abbr,text in tests:
        print("原始文本:",text)
        print("缩写:",abbr)
        print("="*50)

        fallback_result = fallback.retrieve(
            abbreviation=abbr,
            context_text=text
        )
        print("Fallback候选:")
        print(fallback_result)
        print("="*50)

        coverage_result = evaluator.evaluate(
            original_text=text,
            abbreviation=abbr,
            candidates=fallback_result["candidates"]
        )
        print("Coverage结果:")
        print(coverage_result)
        print("="*80)

if __name__ == "__main__":
    main()
from services.abbr_candidate_retriever import ABBRCandidateRetriever
from services.abbr_candidate_coverage_evaluator import ABBRCandidateCoverageEvaluator

def main():
    retriever = ABBRCandidateRetriever()
    evaluator = ABBRCandidateCoverageEvaluator()

    texts = [
        ("CP", "The patient reports CP."),
        ("CP", "The child has a history of CP since birth."),
        ("XYZ", "The patient has XYZ."),
    ]

    for abbr,text in texts:
        candidates = retriever.retrieve(abbr)

        result = evaluator.evaluate(
            original_text=text,
            abbreviation=abbr,
            candidates=candidates
        )

        print("原始文本:",text)
        print("缩写:",abbr)
        print("候选:",candidates)
        print("覆盖度评估:",result)
        print("-"*80)

if __name__ == "__main__":
    main()
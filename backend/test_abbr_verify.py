"""
原始文本
  ↓
LLM abbreviation expansion
  ↓
NER + MedicalRetriever
  ↓
SNOMED candidates
  ↓
Verifier LLM
  ↓
is_valid / confidence / reason
"""

from services.abbr_service import ABBRService

def main():
    service = ABBRService()

    text = "The patient has SOB, DM, and HTN."
    
    result = service.expand_standardize_and_verify(text)

    print("原始文本:")
    print(result["original_text"])
    print("="*50)

    print("扩展后文本:")
    print(result["expanded_text"])

    print("=" * 50)

    print("缩写映射:")
    for item in result["mappings"]:
        print(item)
    print("="*50)

    print("逐项校验结果:")
    print(result["verification"])
    print("="*50)

    print("缩写映射标准化结果:")
    for item in result["mapping_standardizations"]:
        print("缩写:",item["abbreviation"])
        print("扩展:",item["expansion"])
        print("SNOMED候选:")

        for candidate in item["candidates"]:
            print(
                candidate["concept_name"],
                candidate["score"],
                candidate.get("rerank_score")
            )
        print("-"*50)

if __name__ == "__main__":
    main()
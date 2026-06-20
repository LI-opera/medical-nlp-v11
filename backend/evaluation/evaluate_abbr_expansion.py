import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from services.abbr_service import ABBRService
#测试题列表
from evaluation.abbr_eval_cases import ABBR_EVAL_CASES

def normalize_text(text):
    #简单文本归一化，统一大小写，去掉首尾空格
    if text is None:
        return None
    return text.strip().lower()

def normalize_mappings(mappings):
    """
    将 mappings 转成统一格式，方便比较。

    输入：
    [
        {"abbreviation": "SOB", "expansion": "shortness of breath"}
    ]

    输出：
    {
        "SOB": "shortness of breath"
    }
    """
    result = {}

    for item in mappings:
        abbr = item.get("abbreviation")
        expansion = item.get("expansion")

        if not abbr or not expansion:
            continue
        result[abbr.upper()] = normalize_text(expansion)
    return result

def compare_mappings(predicted_mappings,expected_mappings):
    """
    比较预测 mapping 和标准答案 mapping。

    返回：
    {
        "correct": True/False,
        "details": [...]
    }
    """
    #将系统输出和标准答案都统一格式
    predicted = normalize_mappings(predicted_mappings)
    expected = normalize_mappings(expected_mappings)

    details = []
    #取字典键的并集
    all_abbrs = set(predicted.keys()) | set(expected.keys())
    #遍历每个缩写的扩写
    for abbr in sorted(all_abbrs):
        pred_expansion = predicted.get(abbr)
        expected_expansion = expected.get(abbr)

        #判断系统生成的扩写和便准答案是否一致
        is_match = pred_expansion == expected_expansion

        #通过details记录每个缩写他们评测结果
        details.append({
            "abbreviation":abbr,
            "predicted":pred_expansion,
            "expected":expected_expansion,
            "match":is_match
        })

    #这一整条case里面所有缩写都对，才算这个case对
    correct = all(item["match"] for item in details)

    return{
        "correct":correct,
        "details":details
    }

def main():
    service = ABBRService()

    total = 0
    correct = 0
    results = []

    for case in ABBR_EVAL_CASES:
        total += 1
        #取出测试题的标准答案
        case_id = case["id"]
        text = case["text"]
        expected_mappings = case["expected_mappings"]
        #让系统作答
        result = service.expand_verify_with_retry(
            text=text,
            max_retries=2
        )
        #取出系统预测结果
        final_result = result.get("final_result",{})
        predicted_mappings = final_result.get("mappings",[])

        #和标准答案比较
        comparsion = compare_mappings(
            predicted_mappings=predicted_mappings,
            expected_mappings=expected_mappings
        )
        #统计正确数
        if comparsion["correct"]:
            correct += 1

        #保留每条结果
        results.append({
            "id":case_id,
            "text":text,
            "success":result.get("success"),
            "predicted_mappings":predicted_mappings,
            "expected_mappings":expected_mappings,
            "correct":comparsion["correct"],
            "details":comparsion["details"]
        })

        #打印每条case
        print("Case:",case_id)
        print("Text:",text)
        print("System success:",result.get("success"))
        print("Correct:",comparsion["correct"])
        print("Details:")
        for detail in comparsion["details"]:
            print(detail)
    
    #计算准确率
    accuracy = correct / total if total else 0

    print("="*80)
    print("Evaluation Summary")
    print("Total:",total)
    print("Correct:",correct)
    print("Accuracy:",round(accuracy,4))

if __name__ == "__main__":
    main()
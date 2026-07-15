import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__)))

from services.abbr_service import ABBRService


def _build(text, chosen):
    # 只调纯方法,不触发 __init__ 里的模型加载
    return ABBRService._build_expanded_text_deterministic(None, text, chosen)


def test_negation_preserved():
    out = _build(
        "Patient denies CP",
        [{"abbreviation": "CP", "expansion": "chest pain"}],
    )
    assert out == "Patient denies chest pain"


def test_no_substring_hit():
    # CP 不应命中 CPR
    out = _build(
        "CPR was performed",
        [{"abbreviation": "CP", "expansion": "chest pain"}],
    )
    assert out == "CPR was performed"


def test_multi_abbr_no_offset_error():
    out = _build(
        "Patient has CP and MS",
        [
            {"abbreviation": "CP", "expansion": "chest pain"},
            {"abbreviation": "MS", "expansion": "mitral stenosis"},
        ],
    )
    assert out == "Patient has chest pain and mitral stenosis"


if __name__ == "__main__":
    test_negation_preserved()
    test_no_substring_hit()
    test_multi_abbr_no_offset_error()
    print("OK")

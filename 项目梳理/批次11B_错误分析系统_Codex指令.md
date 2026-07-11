# 批次 11B · 给 Codex 的指令(可整段复制)· 统一错误分析系统(运行时弃码 + gold 答错,一个库)

## 背景与范围

batch11A 已统一 record(每条带成形 `failure`)。本批建**一个错误库 + 一个分析脚本**,**两类错误都进同一个 JSONL**:
1. **运行时 known-unknowns**(系统自己知道搞不定):没扩 / 弃码 / 弃权 / coverage 失败 —— 从 record.failure 投影,落盘点在主链路。
2. **gold 答错 unknown-unknowns**(系统以为成功、其实判错):benchmark 里 `predicted != gold` 的 case(如 coverage_003/005/006 过度扩写)—— 标 `failure_type=GOLD_MISMATCH`,落盘点在 benchmark。

两套互补、同库同表,`analyze_errors.py` 一并聚合。作废旧的 `批次11_错误分析系统_Codex指令.md`。

工作在 `medical-refactor`。**铁律**:遥测全包 try/except,绝不拖垮主链路/不改判分;主 benchmark 必须仍 71/74=0.9595。

---

## A · 新建 `backend/services/error_collector.py`

```python
"""
统一错误库:两类错误写进同一个 JSONL。失败静默,绝不影响主链路/判分。
  - collect_unresolved:运行时 known-unknowns(record.failure:没扩/弃码/弃权/coverage失败)
  - collect_gold_mismatch:评测 unknown-unknowns(predicted != gold 的"自信答错")
"""
import json
import datetime
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(rows, log_path=None):
    if not rows:
        return
    path = Path(log_path) if log_path else DEFAULT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect_unresolved(text, records, log_path=None):
    """运行时:把统一 record 里带 failure 的(系统知道搞不定的)落盘。"""
    try:
        rows = []
        for r in records or []:
            f = r.get("failure")
            if not f:
                continue
            rows.append({
                "ts": _now(), "text": text,
                "failure_type": f.get("type"), "stage": f.get("stage"),
                "abbreviation": r.get("abbreviation"), "expansion": r.get("expansion"),
                "source": r.get("source"), "reason": f.get("reason"),
                "evidence": f.get("evidence"),
            })
        if records and not any(r.get("expansion") for r in records):
            rows.append({
                "ts": _now(), "text": text,
                "failure_type": "COVERAGE_FAILED", "stage": "coverage",
                "abbreviation": None, "expansion": None, "source": None,
                "reason": "no abbreviation produced a usable expansion",
                "evidence": {"abbreviations": [r.get("abbreviation") for r in records]},
            })
        _append(rows, log_path)
    except Exception:
        pass


def collect_gold_mismatch(text, stage, source, expected, predicted, abbreviation=None, log_path=None):
    """评测:predicted != gold 的"自信答错",写进同一个库(failure_type=GOLD_MISMATCH)。"""
    try:
        _append([{
            "ts": _now(), "text": text,
            "failure_type": "GOLD_MISMATCH", "stage": stage,
            "abbreviation": abbreviation, "expansion": None,
            "source": source, "reason": "predicted != gold",
            "evidence": {"expected": expected, "predicted": predicted},
        }], log_path)
    except Exception:
        pass
```

## B · 接线运行时:`backend/services/abbr_service.py`

`expand_verify_with_retry` 有**两个 `return {`**(早停 coverage_failed + 终态)。在**两处各自之前**插入同一段:

```python
        try:
            from services.error_collector import collect_unresolved
            collect_unresolved(text, records)
        except Exception:
            pass

```
> 两处都要(早停那次才能收 COVERAGE_FAILED)。`records` 两处都在作用域。不改 return 内容。

## C · 接线评测:`backend/evaluation/run_benchmark.py`

在每例 `final_correct = is_correct and text_check["correct"]`(约 107 行)**之后**插入:

```python
        if not final_correct:
            try:
                from services.error_collector import collect_gold_mismatch
                collect_gold_mismatch(
                    text=case["text"], stage="expansion", source="benchmark:main",
                    expected=case["expected_mappings"], predicted=predicted_mappings,
                )
            except Exception:
                pass
```
> 不动判分逻辑,只在判错时旁路记一条。

## C2 ·(可选,对称)`backend/evaluation/run_concept_benchmark.py`

在每例 `passed, canonical, verdict = judge(case, chosen)` 之后插入(标准化层的 gold 答错):

```python
        if case.get("confirmed") and not passed:
            try:
                from services.error_collector import collect_gold_mismatch
                collect_gold_mismatch(
                    text=case["expansion"], stage="standardization", source="benchmark:concept",
                    expected={"prefer": case["prefer"], "accept": case.get("accept", [])},
                    predicted=chosen, abbreviation=case["label"],
                )
            except Exception:
                pass
```
> 当前 concept bench 全 PASS,这段暂不产出,纯为对称/未来。

## D · 新建 `backend/evaluation/analyze_errors.py`

```python
"""
错误分析:读 backend/logs/unresolved_cases.jsonl,聚合两类错误
(运行时弃码/未扩 + gold 答错 GOLD_MISMATCH)。
先跑 `python backend/evaluation/run_benchmark.py` 让两类都产出,再跑本脚本。
"""
import json
from collections import Counter
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def main():
    if not LOG.exists():
        print(f"无日志 {LOG}\n先跑 `python backend/evaluation/run_benchmark.py`。")
        return
    recs = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"共 {len(recs)} 条错误 case\n")

    def dist(title, counter, n=10):
        print(title)
        for k, c in counter.most_common(n):
            print(f"  {c:>4}  {k}")
        print()

    dist("按失败类型(含运行时弃码 + GOLD_MISMATCH 自信答错):",
         Counter(r["failure_type"] for r in recs))
    dist("最常出问题的缩写 top10:",
         Counter(r.get("abbreviation") for r in recs if r.get("abbreviation")))
    dist("最常弃码的扩写 top10 (CODE_WITHHELD):",
         Counter(r.get("expansion") for r in recs
                 if r["failure_type"] == "CODE_WITHHELD" and r.get("expansion")))
    dist("按来源:", Counter(r.get("source") for r in recs))
    dist("按阶段:", Counter(r.get("stage") for r in recs))

    print("各类型一条样例:")
    seen = set()
    for r in recs:
        t = r["failure_type"]
        if t not in seen:
            seen.add(t)
            print(f"  [{t}] abbr={r.get('abbreviation')} exp={r.get('expansion')} src={r.get('source')}")
            print(f"        reason={r.get('reason')}  evidence={r.get('evidence')}")


if __name__ == "__main__":
    main()
```

## E · `.gitignore` 追加

```
backend/logs/
```

---

## 验收

1. **编译+import**:`python -m compileall backend/services backend/evaluation` 通过;`from services.error_collector import collect_unresolved, collect_gold_mismatch` OK。
2. **主链路不变**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74=0.9595**(遥测旁路);跑完 `backend/logs/unresolved_cases.jsonl` 有内容,且**至少含 3 条 GOLD_MISMATCH**(coverage_003/005/006 的过度扩写),以及运行时若有弃码/未扩也在内。
3. **分析脚本**:`python backend/evaluation/analyze_errors.py` 的"按失败类型"里**同时出现 GOLD_MISMATCH 和(若有)CODE_WITHHELD/ABBR_NOT_EXPANDED**,无报错。
4. **判定**:1-3 全过 → 合入;benchmark 掉分或报错 → 回退。

## 提交

```bash
git add backend/services/error_collector.py backend/services/abbr_service.py backend/evaluation/run_benchmark.py backend/evaluation/run_concept_benchmark.py backend/evaluation/analyze_errors.py .gitignore
git commit -m "V11 batch11B: unified error-analysis store. Runtime known-give-ups (record.failure) + benchmark gold-mismatches (GOLD_MISMATCH) into one JSONL + aggregator. Fail-safe sidecars, main benchmark flat 0.9595."
```
> 面试叙事:一个错误库覆盖两类错误——**系统知道自己放弃的(运行时弃码/未扩)+ 系统以为对了其实错的(gold 答错)**;前者靠统一 record 的 failure,后者靠 benchmark 对 gold。聚合后既能看"线上最常在哪步栽",也能看"离线最常答错哪类",一起喂下一轮改进。

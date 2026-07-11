# 批次 13 · 给 Codex 的指令(可整段复制)· 错误源:全收 + 确定性打标 + 读时筛

## 背景与范围

现在错误日志被 benchmark 的乱码负例(XYZ/QQQ 等,系统正确弃权)污染,triage 被带歪。**不硬删错误源**(怕误判把真错也埋了),改为:**全收 → 用 gold 确定性给每条打 `expected` 标签(非 LLM 猜)→ analyze/triage 读时默认只看非预期**。数据一条不丢、可回溯。

`expected` 三态:
- `True` = 该结局符合 gold(如 gold 本就不要求扩它 → 正确弃权,非真错)→ 默认筛掉。
- `False` = 与 gold 不符(真错)→ 保留。
- `None` = 无标准答案(真实流量 / 概念层无 main-gold)→ **永不筛,全留**(你怕"误判拍死"的场景,这里就不动)。

铁律:① 只动错误遥测层(error_collector / 两个 runner / analyze / triage),**不碰主链路 abbr_service**;② 全收不丢、打标用确定性 gold 不用 LLM;③ benchmark 跑时关掉 gold-blind 的运行时收集,改走 gold-aware 收集(避免重复污染)。**主 benchmark 必须仍 71/74=0.9595**(遥测是旁路)。

工作在 `medical-refactor`。

---

## A · 整段替换 `backend/services/error_collector.py`

```python
"""
统一错误库 + 确定性预期标注(全收 / 不丢 / 读时筛)。
原则:错误源全收,绝不在写入端硬丢;只在【有标准答案】时给每条打 expected(确定性,非 LLM 猜)。
  expected=True  该结局符合 gold(如 gold 本就不要求扩它 → 正确弃权,非真错)
  expected=False 与 gold 不符(真错)
  expected=None  无标准答案(真实流量 / 概念层无 main-gold)→ 永不筛
读时(analyze/triage)默认只看 expected != True。失败静默,绝不影响主链路。
"""
import json
import datetime
import os
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def _runtime_on():
    # 真实运行时(API)默认开;benchmark 设 ERROR_LOG_RUNTIME=0 关掉 gold-blind 收集。
    return os.getenv("ERROR_LOG_RUNTIME", "1") != "0"


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


def _expected_for(failure_type, abbreviation, gold_abbrs):
    """有 gold 时确定性判该结局是否符合预期;无 gold→None。"""
    if gold_abbrs is None:
        return None
    abbr = (abbreviation or "").upper()
    if failure_type in ("ABBR_NOT_EXPANDED", "EXPANSION_ABSTAIN", "COVERAGE_FAILED"):
        # 弃权:gold 没要求扩它 → 正确弃权(预期内);gold 要求扩却没扩 → 真错
        return abbr not in gold_abbrs
    # CODE_WITHHELD 等概念层:main benchmark 无概念 gold → 不下定论
    return None


def collect_unresolved(text, records, source="runtime", gold_abbrs=None, log_path=None):
    """全收带 failure 的 record。source='runtime' 且运行时关闭则跳过(benchmark 改走 gold-aware)。"""
    try:
        if source == "runtime" and not _runtime_on():
            return
        rows = []
        for r in records or []:
            f = r.get("failure")
            if not f:
                continue
            ftype = f.get("type")
            rows.append({
                "ts": _now(), "text": text, "source": source,
                "failure_type": ftype, "stage": f.get("stage"),
                "abbreviation": r.get("abbreviation"), "expansion": r.get("expansion"),
                "reason": f.get("reason"), "evidence": f.get("evidence"),
                "expected": _expected_for(ftype, r.get("abbreviation"), gold_abbrs),
            })
        # 整句 coverage 失败(无任何扩写):gold 为空→正确弃权(True);gold 非空→真错(False);无 gold→None
        if records and not any(r.get("expansion") for r in records):
            whole = None if gold_abbrs is None else (len(gold_abbrs) == 0)
            rows.append({
                "ts": _now(), "text": text, "source": source,
                "failure_type": "COVERAGE_FAILED", "stage": "coverage",
                "abbreviation": None, "expansion": None,
                "reason": "no abbreviation produced a usable expansion",
                "evidence": {"abbreviations": [r.get("abbreviation") for r in records]},
                "expected": whole,
            })
        _append(rows, log_path)
    except Exception:
        pass


def collect_gold_mismatch(text, stage, source, expected, predicted, abbreviation=None, log_path=None):
    """评测 predicted != gold 的真错;记录的 expected 字段恒为 False(注:入参 expected 是 gold 值,存进 evidence)。"""
    try:
        _append([{
            "ts": _now(), "text": text, "source": source,
            "failure_type": "GOLD_MISMATCH", "stage": stage,
            "abbreviation": abbreviation, "expansion": None,
            "reason": "predicted != gold",
            "evidence": {"expected": expected, "predicted": predicted},
            "expected": False,
        }], log_path)
    except Exception:
        pass
```

## B · `backend/evaluation/run_benchmark.py`(两处加,不动判分)

**B1.** 文件顶部 import 之后,加一行(benchmark 期间关掉 gold-blind 运行时收集):
```python
import os
os.environ["ERROR_LOG_RUNTIME"] = "0"
```

**B2.** 在每例算出 `final_correct` 之后(已有的 `if not final_correct: collect_gold_mismatch(...)` 那段**附近、紧随其后**),加 gold-aware 收集:
```python
        try:
            from services.error_collector import collect_unresolved
            gold_abbrs = {
                (m.get("abbreviation") or "").upper()
                for m in case["expected_mappings"]
                if m.get("abbreviation")
            }
            collect_unresolved(
                text=case["text"],
                records=final_result.get("mapping_states", []),
                source="benchmark:main",
                gold_abbrs=gold_abbrs,
            )
        except Exception:
            pass
```
> 它读 `final_result.mapping_states`(11A 起每条带 failure),用本例 gold 确定性给每条打 expected。乱码负例→expected=True;真miss→False;CODE_WITHHELD→None。

## C · `backend/evaluation/analyze_errors.py`:读时默认筛掉 expected==True

把 `main()` 改成:默认只统计 `expected != True` 的;支持 `--all` 看全量;并打印筛掉了多少。最小改法:

```python
def main():
    import sys as _sys
    show_all = "--all" in _sys.argv
    if not LOG.exists():
        print(f"无日志 {LOG}\n先跑 `python backend/evaluation/run_benchmark.py`。")
        return
    raw = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    expected_ok = [r for r in raw if r.get("expected") is True]
    recs = raw if show_all else [r for r in raw if r.get("expected") is not True]
    print(f"全量 {len(raw)} 条;预期内(正确弃权,已默认隐藏){len(expected_ok)} 条;"
          f"当前分析 {len(recs)} 条" + ("(--all 全量)" if show_all else "(加 --all 看全量)"))
    print()
    # ……下面原有的 dist(...) 各段不变,但都改用 recs(而非 raw)……
```
> 其余 `dist(...)` 调用保持,只把数据源从原来的全量改成 `recs`。

## D · `backend/evaluation/error_triage.py`:聚类前先筛掉 expected==True

在 `main()` 里 `records = load_records()` 之后、`cluster(records)` 之前,插入:
```python
    raw_n = len(records)
    records = [r for r in records if r.get("expected") is not True]
    hidden = raw_n - len(records)
```
并在报告抬头那段 `lines = [...]` 里,加一行说明(放进现有 `>` 提示区):
```python
        f"> 已自动隐藏 {hidden} 条【预期内】(gold 确定的正确弃权,非真错);全量仍在日志里,可回溯。",
```
> 这样 triage 不再对着乱码负例瞎分析,但数据一条没删。

---

## 验收

1. **编译+import**:`python -m compileall backend/services backend/evaluation` 通过;`from services.error_collector import collect_unresolved, collect_gold_mismatch` OK。
2. **主链路不变**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74=0.9595**(遥测旁路)。
3. **打标生效**:**先删旧日志** `backend/logs/unresolved_cases.jsonl` 再跑 benchmark;跑完日志里每条都带 `expected` 字段,XYZ/QQQ 这类乱码负例的弃权记录 `expected=true`,GOLD_MISMATCH `expected=false`,CODE_WITHHELD `expected=null`。
4. **读时筛生效**:`python backend/evaluation/analyze_errors.py` 默认隐藏"预期内"那批并打印隐藏条数;`--all` 能看到全量(证明没删数据)。`python backend/evaluation/error_triage.py` 抬头显示已隐藏 N 条,且簇里不再出现 XYZ/QQQ 那类乱码。
5. **判定**:1-4 全过 → 合入;主 benchmark 掉分或报错 → 回退。

## 提交

```bash
git add backend/services/error_collector.py backend/evaluation/run_benchmark.py backend/evaluation/analyze_errors.py backend/evaluation/error_triage.py
git commit -m "V11 batch13: collect-all + deterministic 'expected' annotation + read-time filter for the error store. Never drop at source; gold-derived expected (not LLM-guessed) marks correct-abstentions; analyze/triage hide expected=True by default (--all shows everything). Main benchmark flat 0.9595."
```
> 面试叙事:不硬删错误源(怕误判把真错也埋),改"全收+确定性打标+读时筛"——写入端不丢数据,过滤是可逆的读时决策,且标签来自 gold(在抄答案)不是 LLM 猜(避免把判断权交给会自信犯错的模型)。有标准答案处才标、无标准答案(真实流量)处全留——"误判拍死"两头都不会发生。

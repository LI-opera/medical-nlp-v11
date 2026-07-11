# 批次 11 · 给 Codex 的指令(可整段复制)· 运行时错误分析系统(收集"系统搞不定"的 case)

## 背景与范围

给项目加一套**运行时失败遥测**:每次推理,把系统【自己知道搞不定】的 case 结构化落盘成 JSONL,再配一个聚合分析脚本,形成"错误分析系统"。

**"搞不定"在本流程恰好是三个明确出口**(系统自己弃权/弃码,知道自己没处理好):
1. `ABBR_NOT_EXPANDED` —— 缩写没扩:候选里 `best_expansion is None`(coverage/fallback 弃权门没背书)。
2. `CODE_WITHHELD` —— 扩了但弃码:某 state `status=="LOCKED_OK"` 但 `std_concept is None`(标准化没找到忠实概念)。
3. `COVERAGE_FAILED` —— 整句没产出任何 state(`states` 为空)。
   (附:`EXPANSION_ABSTAIN` = state `status=="LOCKED_ABSTAIN"`,当前少见但一并收。)

**取数位置(已核对 `abbr_service.py`)**:`expand_verify_with_retry` 终态 `return`(约 381 行)前,作用域内有:
- `text`(原文)、`current_abbreviation_candidates`(=`candidate_infos`,含 best=None 的没扩项,每项有 `abbreviation/candidates/coverage/candidate_source/best_expansion`)、`states`(每项有 `abbreviation/expansion/source/status/std_cache/std_concept`)。

> **诚实边界(写进文档/面试)**:此遥测只收"系统知道自己没搞定"的弃权/弃码(known-unknowns);**收不到"自信地答错"**(如 ABC 过度扩写、系统以为成功的)——那类只能靠 gold benchmark 抓。两者互补。

工作在 `medical-refactor`(HEAD 飘了先 `git switch -f medical-refactor`)。

## 铁律

1. 先 Read `abbr_service.py` 终态(约 339-387)核对变量名再接线。
2. 遥测**绝不能拖垮主链路**:落盘整体包在 try/except,出错静默跳过;不改任何已有判分/返回结构。
3. 只**新增**:1 个收集模块 + 1 处接线 + 1 个分析脚本 + gitignore;不动 coverage/检索/verify/状态机逻辑。

---

## A · 新建 `backend/services/error_collector.py`

```python
"""
运行时错误遥测:把系统【自己知道搞不定】的 case 落盘成 JSONL,供错误分析聚合。
只收弃权/弃码这类 known-unknowns;收不到"自信答错"(那靠 gold benchmark)。
失败静默,绝不影响主链路。
"""
import json
import datetime
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def _rec(text, failure_type, abbr, expansion, source, stage, reason, evidence):
    return {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "text": text,
        "failure_type": failure_type,
        "abbreviation": abbr,
        "expansion": expansion,
        "source": source,
        "stage": stage,
        "reason": reason,
        "evidence": evidence,
    }


def collect_unresolved(text, candidate_infos, states, log_path=None):
    """终态调用一次:把三类未解决 case 追加到 JSONL。任何异常静默吞掉。"""
    try:
        records = []

        # 3) 整句 coverage 失败:没有任何 state
        if not states:
            records.append(_rec(
                text, "COVERAGE_FAILED", None, None, None, "coverage",
                "no abbreviation produced a usable expansion", {},
            ))

        # 1) 缩写没扩:候选里 best_expansion 为 None
        for info in candidate_infos or []:
            if info.get("best_expansion") is None:
                cov = info.get("coverage") or {}
                records.append(_rec(
                    text, "ABBR_NOT_EXPANDED", info.get("abbreviation"), None,
                    info.get("candidate_source"), "coverage",
                    "coverage withheld expansion (not confident enough)",
                    {
                        "coverage_confidence": cov.get("confidence"),
                        "coverage_ok": cov.get("coverage_ok"),
                        "candidates_seen": [c.get("expansion") for c in (info.get("candidates") or [])],
                    },
                ))

        # 2) 扩了但弃码 / 扩写最终弃权
        for s in states or []:
            status = s.get("status")
            if status == "LOCKED_OK" and s.get("std_concept") is None:
                records.append(_rec(
                    text, "CODE_WITHHELD", s.get("abbreviation"), s.get("expansion"),
                    s.get("source"), "standardization",
                    "no faithful SNOMED concept among retrieved candidates",
                    {"retrieved_top": [c.get("concept_name") for c in (s.get("std_cache") or [])[:5]]},
                ))
            elif status == "LOCKED_ABSTAIN":
                records.append(_rec(
                    text, "EXPANSION_ABSTAIN", s.get("abbreviation"), s.get("expansion"),
                    s.get("source"), "coverage",
                    "expansion candidates exhausted without a lock", {},
                ))

        if not records:
            return
        path = Path(log_path) if log_path else DEFAULT_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 遥测绝不拖垮主链路
```

## B · 接线 `backend/services/abbr_service.py`

在 `expand_verify_with_retry` 终态 `return {` (约 381 行) **之前**插入:

```python
        # 错误遥测:把系统自己搞不定的 case 落盘(失败静默,不影响主链路)
        try:
            from services.error_collector import collect_unresolved
            collect_unresolved(text, current_abbreviation_candidates, states)
        except Exception:
            pass

```
> 放在 `current_expanded_text`/`states`/`final_result` 都已定型之后、`return` 之前。不改 return 内容。

## C · 新建 `backend/evaluation/analyze_errors.py`(聚合分析)

```python
"""
错误分析:读 backend/logs/unresolved_cases.jsonl,聚合"系统搞不定"的 case。
先跑推理/benchmark 让系统产出弃码/未扩,再跑本脚本看分布。
跑法:python backend/evaluation/analyze_errors.py
"""
import json
from collections import Counter
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "logs" / "unresolved_cases.jsonl"


def main():
    if not LOG.exists():
        print(f"无日志 {LOG}\n先跑几次推理或 `python backend/evaluation/run_benchmark.py` 让系统产出弃码/未扩的 case。")
        return
    recs = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"共 {len(recs)} 条未解决 case\n")

    def dist(title, counter, n=10):
        print(title)
        for k, c in counter.most_common(n):
            print(f"  {c:>4}  {k}")
        print()

    dist("按失败类型:", Counter(r["failure_type"] for r in recs))
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
            print(f"  [{t}] abbr={r.get('abbreviation')} exp={r.get('expansion')}")
            print(f"        reason={r.get('reason')}  evidence={r.get('evidence')}")


if __name__ == "__main__":
    main()
```

## D · `.gitignore` 追加(日志是运行产物,不进库)

```
backend/logs/
```

---

## 验收

1. **编译+import**:`python -m compileall backend/services backend/evaluation` 通过;`from services.error_collector import collect_unresolved` OK。
2. **不破坏主链路**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74 = 0.9595**(遥测是旁路,绝不该改判分);跑完 `backend/logs/unresolved_cases.jsonl` 已生成、有内容(benchmark 74 例里那些没扩/弃码的会被收进去)。
3. **分析脚本**:`python backend/evaluation/analyze_errors.py` 打出按类型/缩写/扩写/阶段的分布 + 各类型样例,无报错。
4. **判定**:1-3 全过 → 合入;benchmark 掉分或主链路报错 → 回退。

## 提交

```bash
git add backend/services/error_collector.py backend/services/abbr_service.py backend/evaluation/analyze_errors.py .gitignore
git commit -m "V11 batch11: runtime error-analysis telemetry. Collect system's known give-ups (ABBR_NOT_EXPANDED / CODE_WITHHELD / COVERAGE_FAILED) to JSONL + aggregator. Fail-safe sidecar, main benchmark flat 0.9595."
```
> 面试叙事:给 NLP 管线加**失败遥测**——系统每次弃权/弃码都留结构化痕迹,聚合后能看出"最常在哪步、对哪些缩写栽",直接喂下一轮改进(如高频弃码的扩写→补库/补词典)。诚实边界:它收 known-unknowns(系统知道的放弃),收不到"自信答错",后者靠 gold benchmark——两套互补。

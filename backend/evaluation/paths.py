"""评估脚本共用的输入输出路径。"""

from pathlib import Path
from datetime import datetime
import shutil


EVALUATION_DIR = Path(__file__).resolve().parent
REPO_DIR = EVALUATION_DIR.parents[1]
ARCHIVE_DIR = EVALUATION_DIR / "archive"
RUNTIME_DIR = EVALUATION_DIR / "runtime"
BENCHMARK_CASES_PATH = REPO_DIR / "examples" / "benchmarks" / "abbr_benchmark_cases.json"

BENCHMARK_RESULTS_PATH = RUNTIME_DIR / "benchmark_results.json"
ERROR_ANALYSIS_REPORT_PATH = RUNTIME_DIR / "error_analysis_report.json"
FALLBACK_PROMOTIONS_JSON_PATH = RUNTIME_DIR / "fallback_candidate_promotions.json"
FALLBACK_PROMOTIONS_MD_PATH = RUNTIME_DIR / "fallback_candidate_promotions.md"


def rollover_runtime_to_archive() -> list[str]:
    """把上一工作会话的当前结果移动到带时间戳的历史归档。"""
    if not RUNTIME_DIR.exists():
        return []

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = []
    for source in sorted(RUNTIME_DIR.iterdir()):
        if not source.is_file():
            continue
        target = ARCHIVE_DIR / f"{source.stem}_{stamp}{source.suffix}"
        shutil.move(str(source), str(target))
        moved.append(source.name)
    return moved


def ensure_archive_dir() -> Path:
    """确保评估产物目录存在，并返回该目录。"""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR

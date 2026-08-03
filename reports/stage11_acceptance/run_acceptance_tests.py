"""Run and capture the acceptance-required test scopes."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_acceptance"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

COMMANDS = [
    ("Stage 11", [str(PYTHON), "-m", "pytest", "tests/test_stage11_crypto.py", "-q"]),
    ("Stage 10", [str(PYTHON), "-m", "pytest", "tests/test_stage10_financial.py", "tests/test_stage10_integration.py", "tests/test_stage10_repository.py", "-q"]),
    ("Stage 9", [str(PYTHON), "-m", "pytest", "tests/test_stage9_audit.py", "tests/test_stage9_database_integration.py", "tests/test_stage9_quality.py", "tests/test_stage9_repository.py", "tests/test_stage9_validate_only.py", "tests/test_style_classification.py", "tests/test_style_features.py", "tests/test_false_breakouts.py", "-q"]),
    ("Stage 8", [str(PYTHON), "-m", "pytest", "tests/test_stage8_analysis.py", "tests/test_stage8_audit.py", "tests/test_stage8_database_integration.py", "tests/test_stage8_quality.py", "tests/test_stage8_validate_only.py", "tests/test_limit_event_detection.py", "tests/test_limit_event_repository.py", "tests/test_limit_rules.py", "-q"]),
    ("Stage 7", [str(PYTHON), "-m", "pytest", "tests/test_stage7_audit.py", "tests/test_stage7_database_integration.py", "tests/test_activity_score.py", "tests/test_stock_daily_features.py", "-q"]),
    ("Stage 0", [str(PYTHON), "tests/test_stage0_config.py"]),
    ("Full", [str(PYTHON), "-m", "pytest", "-q"]),
    ("validate-only", [str(PYTHON), "run_pipeline.py", "validate-crypto", "--as-of-date", "2026-07-27", "--config", "config/stage11.yml", "--validate-only"]),
]


def parse_counts(text: str, scope: str) -> dict[str, int]:
    if scope == "Stage 0":
        match = re.search(r"(\d+)/(\d+) checks passed", text)
        passed = int(match.group(1)) if match else 0
        return {"collected": int(match.group(2)) if match else 0, "passed": passed, "failed": 0 if match and match.group(1) == match.group(2) else 1, "skipped": 0, "xfail": 0, "deselected": 0}
    counts = {name: 0 for name in ["passed", "failed", "skipped", "xfailed", "deselected"]}
    for name in counts:
        match = re.search(rf"(\d+) {name}", text)
        counts[name] = int(match.group(1)) if match else 0
    collected = counts["passed"] + counts["failed"] + counts["skipped"] + counts["xfailed"]
    return {"collected": collected, "passed": counts["passed"], "failed": counts["failed"], "skipped": counts["skipped"], "xfail": counts["xfailed"], "deselected": counts["deselected"]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    results, log = [], []
    for scope, command in COMMANDS:
        started = datetime.now(timezone.utc)
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        ended = datetime.now(timezone.utc)
        combined = completed.stdout + completed.stderr
        counts = parse_counts(combined, scope) if scope != "validate-only" else {"collected":0,"passed":0,"failed":0,"skipped":0,"xfail":0,"deselected":0}
        result = {
            "scope": scope, "command": subprocess.list2cmdline(command), **counts,
            "exit_code": completed.returncode, "started_at": started.isoformat(),
            "completed_at": ended.isoformat(), "duration_seconds": (ended-started).total_seconds(),
            "status": "PASS" if completed.returncode == 0 else "FAIL",
        }
        results.append(result)
        log.extend(["="*80, json.dumps(result, ensure_ascii=False), "--- STDOUT ---", completed.stdout, "--- STDERR ---", completed.stderr])
    (OUT / "stage11_test_execution.log").write_text("\n".join(log), encoding="utf-8")
    (OUT / "test_execution_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

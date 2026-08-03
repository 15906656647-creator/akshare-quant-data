from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_reaudit"
SUITES = [
    ("stage11_remediation", ["tests/test_stage11_remediation.py"], True),
    ("stage11", ["tests/test_stage11_crypto.py", "tests/test_stage11_remediation.py"], True),
    ("stage10", sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_stage10_*.py")), True),
    ("stage9", ["tests/test_stage9_audit.py", "tests/test_stage9_database_integration.py", "tests/test_stage9_quality.py", "tests/test_stage9_repository.py", "tests/test_stage9_validate_only.py", "tests/test_style_classification.py", "tests/test_style_features.py", "tests/test_false_breakouts.py"], True),
    ("stage8", ["tests/test_stage8_analysis.py", "tests/test_stage8_audit.py", "tests/test_stage8_database_integration.py", "tests/test_stage8_quality.py", "tests/test_stage8_validate_only.py", "tests/test_limit_event_detection.py", "tests/test_limit_event_repository.py", "tests/test_limit_rules.py"], True),
    ("stage7", ["tests/test_stage7_audit.py", "tests/test_stage7_database_integration.py", "tests/test_activity_score.py", "tests/test_stock_daily_features.py"], True),
    ("stage0", ["tests/test_stage0_config.py"], False),
    ("full", ["tests"], True),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    chunks: list[str] = []
    for name, targets, use_pytest in SUITES:
        command = ([sys.executable, "-m", "pytest", "-q", *targets] if use_pytest
                   else [sys.executable, *targets])
        started = datetime.now().astimezone().isoformat()
        proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        combined = proc.stdout + proc.stderr
        summary = combined.strip().splitlines()[-1] if combined.strip() else ""
        counts = {key: int(value) for value, key in re.findall(r"(\d+) (passed|failed|xfailed|skipped|warnings?)", summary)}
        if not use_pytest:
            match = re.search(r"(\d+) passed, (\d+) failed", combined)
            if match:
                counts = {"passed": int(match.group(1)), "failed": int(match.group(2))}
        records.append({
            "suite": name, "targets": targets, "command": command,
            "started_at": started, "exit_code": proc.returncode,
            "summary": summary, "counts": counts,
        })
        chunks.append(f"===== {name} =====\n$ {' '.join(command)}\n{combined.rstrip()}\n")
        print(f"{name}: exit={proc.returncode} {summary}", flush=True)
    (OUT / "stage11_reaudit_test.log").write_text("\n".join(chunks), encoding="utf-8", newline="\n")
    (OUT / "stage11_reaudit_test_results.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return 0 if all(item["exit_code"] == 0 for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())

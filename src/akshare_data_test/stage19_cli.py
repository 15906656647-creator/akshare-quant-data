"""CLI boundary for Stage 19."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import json
from .stage19_build import build_stage19


def command(args) -> int:
    report = build_stage19(root=Path.cwd(), config_path=Path(args.config),
        as_of_date=date.fromisoformat(args.as_of_date), run_id=args.run_id,
        validate_only=args.validate_only)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["release_gate"]["formal_event_release"]["status"] == "PASS" else 2

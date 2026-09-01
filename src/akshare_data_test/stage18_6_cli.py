"""CLI boundary for Stage 18.6 final acceptance."""
from __future__ import annotations

import json
import sys
from datetime import date

from .logging_config import setup_logging
from .stage18_6_finalize import run_stage18_6


def command(args) -> int:
    setup_logging(level=args.log_level)
    try:
        report, exit_code = run_stage18_6(
            config_path=args.config, as_of_date=date.fromisoformat(args.as_of_date),
            upstream_run_id=args.upstream_run_id, run_id=args.run_id,
            validate_only=args.validate_only, dry_run=args.dry_run,
        )
        if args.validate_only or args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Stage 18 final acceptance: " + report["status"])
            print("  run_id: " + report["run_id"])
            print("  PASS / UNAVAILABLE: " + str(report["feature_pass_count"]) + " / " + str(report["feature_unavailable_count"]))
            print("  Stage 19 authorized: " + str(report["stage19_authorized"]))
            print("  Stage 19 started: " + str(report["stage19_started"]))
        return exit_code
    except Exception as exc:
        if args.debug: raise
        print(f"Stage 18.6 error: {exc}", file=sys.stderr)
        return 1

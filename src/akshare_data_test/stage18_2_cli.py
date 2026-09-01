"""CLI boundary for Stage 18.2 formal fundamental Raw collection."""
from __future__ import annotations

import json
import sys
from datetime import date

from .logging_config import setup_logging
from .stage18_2_collect import run_stage18_2_collection


def command(args) -> int:
    setup_logging(level=args.log_level)
    try:
        report, exit_code = run_stage18_2_collection(
            config_path=args.config,
            as_of_date=date.fromisoformat(args.as_of_date),
            upstream_run_id=args.upstream_run_id,
            run_id=args.run_id,
            validate_only=args.validate_only,
            dry_run=args.dry_run,
        )
        if args.validate_only or args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Stage 18.2 formal fundamental Raw collection: " + report["status"])
            print("  run_id: " + report["run_id"])
            print("  terminal datasets: " + str(report["terminal_dataset_count"]))
            print("  Stage 18.3 authorized: " + str(report["stage18_3_authorized"]))
            print("  Stage 18.3 started: " + str(report["stage18_3_started"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 18.2 error: {exc}", file=sys.stderr)
        return 1

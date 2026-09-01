"""CLI boundary for Stage 18.4 DuckDB persistence."""
from __future__ import annotations

import json
import sys
from datetime import date

from .logging_config import setup_logging
from .stage18_4_load import run_stage18_4_load


def command(args) -> int:
    setup_logging(level=args.log_level)
    try:
        report, exit_code = run_stage18_4_load(
            config_path=args.config, as_of_date=date.fromisoformat(args.as_of_date),
            upstream_run_id=args.upstream_run_id, run_id=args.run_id,
            validate_only=args.validate_only, dry_run=args.dry_run,
        )
        if args.validate_only or args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Stage 18.4 DuckDB load: " + report["status"])
            print("  run_id: " + report["run_id"])
            print("  database: " + report["database_path"])
            print("  total rows: " + str(report["total_row_count"]))
            print("  Stage 18.5 authorized: " + str(report["stage18_5_authorized"]))
        return exit_code
    except Exception as exc:
        if args.debug: raise
        print(f"Stage 18.4 error: {exc}", file=sys.stderr)
        return 1

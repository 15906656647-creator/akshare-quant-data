"""CLI boundary for Stage 18.1."""
from __future__ import annotations

import json
import sys
from datetime import date

from .logging_config import setup_logging
from .stage18_audit import run_stage18_interface_audit


def command(args) -> int:
    setup_logging(level=args.log_level)
    try:
        as_of = date.fromisoformat(args.as_of_date)
        report, exit_code = run_stage18_interface_audit(
            config_path=args.config,
            as_of_date=as_of,
            upstream_run_id=args.upstream_run_id,
            run_id=args.run_id,
            validate_only=args.validate_only,
            dry_run=args.dry_run,
        )
        if args.validate_only or args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Stage 18.1 interface audit: " + report["status"])
            print("  run_id: " + report["run_id"])
            print("  inventory rows: " + str(report["inventory_row_count"]))
            print("  Stage 18.2 planning authorized: " + str(
                report["stage18_2_planning_authorized"]
            ))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 18.1 error: {exc}", file=sys.stderr)
        return 1

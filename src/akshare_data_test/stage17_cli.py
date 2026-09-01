"""Small CLI boundary for Stage 17 to keep the main command registry stable."""
from __future__ import annotations

import json
import sys
from datetime import datetime

from .logging_config import setup_logging
from .stage17_collect import run_stage17


def command(args) -> int:
    setup_logging(level=args.log_level)
    try:
        as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
        report, exit_code = run_stage17(
            config_path=args.config, as_of_date=as_of, run_id=args.run_id,
            validate_only=args.validate_only, dry_run=args.dry_run,
        )
        if args.validate_only or args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("Stage 17 collection: " + report["status"])
            print("  run_id: " + report["run_id"])
            print(
                "  daily nonempty Raw: "
                + str(report["counts"]["daily_nonempty_count"])
                + "/" + str(report["counts"]["daily_expected_count"])
            )
            print(
                "  daily quality PASS: "
                + str(report["counts"]["daily_quality_pass_count"])
                + "/" + str(report["counts"]["daily_expected_count"])
            )
            print(
                "  crypto: " + str(report["counts"]["crypto_success"])
                + "/" + str(report["counts"]["crypto_expected"])
            )
            print("  Stage 18 authorized: " + str(report["stage18_authorized"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 17 error: {exc}", file=sys.stderr)
        return 1

# -*- coding: utf-8 -*-
"""CLI for AKShare data test project."""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from .config import load_metrics, load_universe, resolve_as_of_date
from .doctor import run_doctor
from .logging_config import setup_logging
from .paths import project_root


def _safe_console_print(*values, **kwargs) -> bool:
    """Best-effort console output; closed wrapper pipes never break a run."""
    try:
        print(*values, **kwargs)
        return True
    except (OSError, ValueError, BrokenPipeError):
        return False


def _pool_date_arg(value: str) -> str:
    """Validate an explicit pool date without consulting the system clock."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--pool-date must be a valid date in YYYY-MM-DD format"
        ) from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise argparse.ArgumentTypeError(
            "--pool-date must be a valid date in YYYY-MM-DD format"
        )
    return value


def _cmd_doctor(args):
    setup_logging(level=args.log_level)
    result = run_doctor(cli_date=args.as_of_date)
    print("Doctor check: " + result.status.upper())
    py_ver = result.python.get("version", "").split()[0]
    py_arch = "64bit" if result.python.get("64bit") else "32bit"
    print("  Python: " + py_ver + " (" + py_arch + ")")
    print("  Resolved as_of_date: " + str(result.resolved_as_of_date))
    ok = sum(1 for v in result.packages.values() if v is not None)
    total = len(result.packages)
    print("  Packages: " + str(ok) + "/" + str(total) + " importable")
    passed = sum(1 for v in result.config_checks.values() if v)
    total_cfg = len(result.config_checks)
    print("  Config checks: " + str(passed) + "/" + str(total_cfg))
    passed_fs = sum(1 for v in result.filesystem_checks.values() if v)
    total_fs = len(result.filesystem_checks)
    print("  Filesystem checks: " + str(passed_fs) + "/" + str(total_fs))
    db_ok = result.duckdb_check.get("select_1")
    db_label = "OK" if db_ok else "FAIL"
    print("  DuckDB memory: " + db_label)
    if result.errors:
        print("\n  Errors (" + str(len(result.errors)) + "):")
        for e in result.errors:
            print("    - " + str(e))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        python_report = dict(result.python)
        executable = python_report.get("executable")
        if executable:
            try:
                python_report["executable"] = (
                    Path(executable)
                    .resolve()
                    .relative_to(project_root().resolve())
                    .as_posix()
                )
            except ValueError:
                python_report["executable"] = Path(executable).name
        report = {
            "status": result.status,
            "checked_at": result.checked_at,
            "python": python_report,
            "packages": result.packages,
            "config_checks": result.config_checks,
            "filesystem_checks": result.filesystem_checks,
            "duckdb_check": result.duckdb_check,
            "resolved_as_of_date": result.resolved_as_of_date,
            "errors": result.errors,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print("\n  Full report: " + str(output_path))
    return 0 if result.status == "pass" else 1

def _cmd_show_config(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    universe = load_universe()
    print("Project: " + universe.project_name)
    print("Schema version: " + universe.schema_version)
    print("Timezone: " + universe.timezone)
    print("Base currency: " + universe.base_currency)
    print("Resolved as_of_date: " + str(as_of))
    print("Stock count: " + str(len(universe.stocks)))
    print("Stock symbols:")
    for s in universe.stocks:
        print("  " + s.symbol + " (" + s.exchange + ", " + s.symbol_em + ")")
    if universe.crypto:
        c = universe.crypto[0]
        print("Crypto: " + c.requested_pair + " (exact_match: " + str(c.exact_match_required) + ")")
    return 0

def _cmd_smoke_test(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    only_probes = None
    if getattr(args, "only", None):
        only_probes = [x.strip() for x in args.only.split(",") if x.strip()]
    pool_date = getattr(args, "pool_date", None)
    from .smoke import run_smoke_tests
    results, run_id, overall = run_smoke_tests(
        as_of_date=as_of,
        sample_symbol=args.sample_symbol,
        output_path=getattr(args, "output", None),
        evidence_dir=getattr(args, "evidence_dir", None),
        max_sample_rows=getattr(args, "max_sample_rows", 20),
        only_probes=only_probes,
        pool_date=pool_date,
        strict=getattr(args, "strict", False),
        run_id=getattr(args, "run_id", None),
    )
    print("\nSmoke test complete: run_id=" + run_id)
    print("Overall status: " + overall)
    print("Probes executed: " + str(len(results)))
    status_counts = {}
    for pr in results:
        status_counts[pr.status] = status_counts.get(pr.status, 0) + 1
    for s in ("success", "empty", "failed", "unsupported", "skipped"):
        c = status_counts.get(s, 0)
        if c > 0:
            print("  " + s + ": " + str(c))
    bad = [pr for pr in results if pr.status in ("failed", "unsupported", "skipped")]
    if bad:
        print("\nIssues:")
        for pr in bad:
            emsg = str(pr.error_message)[:120]
            print("  [" + pr.probe_id + "] " + pr.status + ": " + emsg)
    if getattr(args, "output", None):
        _generate_summary_md(results, run_id, overall, str(as_of))
    if getattr(args, "strict", False):
        return 0 if overall == "PASS" else 1
    return 0 if overall != "BLOCKED" else 1


def _cmd_network_check(args):
    setup_logging(level=args.log_level)
    from .network_preflight import run_network_preflight

    report = run_network_preflight(
        timeout=args.timeout,
        output_path=args.output,
        markdown_path=args.markdown_output,
    )
    print("Network preflight: " + report["overall_status"])
    print("  Proxy environment detected: " + str(report["proxy_detected"]))
    print(
        "  CA environment configured: "
        + str(report["ca_environment_configured"])
    )
    for item in report["hosts"]:
        print(
            "  "
            + item["host"]
            + ": DNS="
            + item["dns_status"]
            + " TCP443="
            + item["tcp_443_status"]
            + " TLS="
            + item["tls_status"]
            + " error="
            + (item["error_type"] or "-")
        )
    return 0 if report["overall_status"] == "PASS" else 1


def _cmd_fetch_market(args):
    setup_logging(level=args.log_level)
    compact_end = getattr(args, "end", None)
    compact_start = getattr(args, "start", None)
    if bool(compact_start) != bool(compact_end):
        print(
            "Market fetch error: --start and --end must be provided together in YYYYMMDD format",
            file=sys.stderr,
        )
        return 2
    if compact_end:
        from .stage14_automation import validate_date_range
        start_iso, end_iso = validate_date_range(compact_start, compact_end)
        as_of = resolve_as_of_date(cli_date=end_iso)
    else:
        start_iso = getattr(args, "start_date", None)
        as_of = resolve_as_of_date(cli_date=args.as_of_date)
    if getattr(args, "dry_run", False):
        print(
            "Market fetch dry-run: start="
            + str(start_iso or "configured-default")
            + " end=" + str(as_of)
        )
        return 0
    from .market_fetch import run_market_fetch

    report, exit_code = run_market_fetch(
        as_of_date=as_of,
        run_id=args.run_id,
        output_dir=args.output_dir,
        evidence_dir=args.evidence_dir,
        only_symbol=args.only_symbol,
        skip_spot=args.skip_spot,
        start_date=(
            datetime.strptime(start_iso, "%Y-%m-%d").date()
            if start_iso else None
        ),
    )
    print("Market fetch: " + report["status"])
    print("  run_id: " + report["run_id"])
    print(
        "  daily: "
        + str(report["daily_success_count"])
        + "/"
        + str(report["daily_expected_count"])
    )
    print("  spot targets: " + str(report["spot"]["target_count"]))
    print("  manifest: " + report["manifest_path"])
    return exit_code


def _cmd_fetch_fundamentals(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .financial_fetch import run_financial_fetch

    report, exit_code = run_financial_fetch(
        as_of_date=as_of,
        start_year=args.start_year,
        run_id=args.run_id,
        output_dir=args.output_dir,
        evidence_dir=args.evidence_dir,
        only_symbol=args.only_symbol,
        only_interface=args.only_interface,
        resume=args.resume,
    )
    _safe_console_print("Financial fetch: " + report["status"])
    _safe_console_print("  run_id: " + report["run_id"])
    _safe_console_print(
        "  tasks: "
        + str(report["success_count"])
        + "/"
        + str(report["expected_task_count"])
    )
    _safe_console_print("  manifest: " + report["manifest_path"])
    return exit_code


def _cmd_build_stage5(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .stage5_build import build_stage5, validate_database

    root = project_root()
    database_path = root / args.database_path
    if args.validate_only:
        result = validate_database(database_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    report, exit_code = build_stage5(
        root=root,
        as_of_date=as_of,
        market_run_id=args.market_run_id,
        fundamental_run_id=args.fundamental_run_id,
        transform_run_id=args.transform_run_id,
        clean_output_dir=root / args.clean_output_dir,
        database_path=database_path,
        evidence_dir=root / args.evidence_dir,
    )
    print("Stage 5 build: " + report["status"])
    print("  transform_run_id: " + report["transform_run_id"])
    print("  database: " + report["database"]["path"])
    return exit_code


def _cmd_validate_stage5(args):
    setup_logging(level=args.log_level)
    resolve_as_of_date(cli_date=args.as_of_date)
    from .stage5_build import validate_database

    result = validate_database(project_root() / args.database_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def _cmd_repair_stage5_idempotency(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .stage5_repair import run_stage5_idempotency_repair

    report, exit_code = run_stage5_idempotency_repair(
        root=project_root(),
        as_of_date=as_of,
    )
    print("Stage 5 idempotency repair: " + report["status"])
    print(
        "  formal database modified: "
        + str(report["formal_database_modified"])
    )
    print(
        "  all 12 tables unchanged: "
        + str(report["all_twelve_tables_unchanged"])
    )
    return exit_code


def _cmd_build_stage6(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .stage6_build import build_stage6

    root = project_root()
    report, exit_code = build_stage6(
        root=root,
        as_of_date=as_of,
        source_database=root / args.source_database,
        transform_run_id=args.transform_run_id,
        feature_run_id=args.feature_run_id,
        feature_output_dir=root / args.feature_output_dir,
        feature_database_path=root / args.feature_database_path,
        evidence_dir=root / args.evidence_dir,
    )
    print("Stage 6 build: " + report["status"])
    print("  feature_run_id: " + report["feature_run_id"])
    print("  source database: " + report["source_database"])
    print("  feature database: " + report["database"]["path"])
    return exit_code


def _cmd_validate_stage6(args):
    setup_logging(level=args.log_level)
    resolve_as_of_date(cli_date=args.as_of_date)
    from .stage6_build import validate_stage6_database

    result = validate_stage6_database(
        project_root() / args.feature_database_path
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def _cmd_verify_stage6_idempotency_repair(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .stage6_repair import run_stage6_idempotency_repair_verification

    report, exit_code = run_stage6_idempotency_repair_verification(
        root=project_root(),
        as_of_date=as_of,
    )
    print("Stage 6 idempotency repair verification: " + report["repair_status"])
    print(
        "  second persistence: "
        + report["full_nonempty_replay"]["second_status"]
    )
    print(
        "  formal products unchanged: "
        + str(report["input_immutability"]["status"] == "PASS")
    )
    return exit_code


def _cmd_build_features(args):
    setup_logging(level=args.log_level)
    as_of = resolve_as_of_date(cli_date=args.as_of_date)
    from .stage7_build import build_stage7

    root = project_root()
    report, exit_code = build_stage7(
        root=root,
        as_of_date=as_of,
        source_database=root / args.source_database,
        output_database=root / args.output_database,
        adjust_type=args.adjust,
        lookback_days=args.lookback_days,
        run_id=args.run_id,
    )
    print("Feature build completed")
    print("  input_rows: " + str(report["input_rows"]))
    print("  feature_rows: " + str(report["feature_rows"]))
    print(
        "  symbols: "
        + str(report["symbol_count"])
        + "/"
        + str(report["target_symbol_count"])
    )
    print(
        "  date_range: "
        + report["date_range"]["min"]
        + " to "
        + report["date_range"]["max"]
    )
    print("  activity_profiles: " + str(report["activity_profiles"]))
    print(
        "  quality_checks_passed: "
        + str(report["quality_checks_passed"])
        + "/"
        + str(report["quality_checks_total"])
    )
    print("  run_id: " + report["run_id"])
    return exit_code


def _cmd_analyze_limit_events(args):
    """Run or validate the fully offline Stage 8 event analysis."""
    setup_logging(level=args.log_level)
    try:
        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        import pandas as pd
        from .stage8_build import analyze_stage8, validate_stage8_inputs

        root = project_root()
        config_path = root / args.config
        source_database = root / args.source_database
        output_database = root / args.output_database
        end = pd.Timestamp(as_of).normalize()
        start = (
            pd.Timestamp(args.start_date).normalize()
            if args.start_date
            else end
            - pd.Timedelta(
                days=int(
                    load_metrics().raw["data_ranges"]["limit_event"][
                        "lookback_natural_days"
                    ]
                )
            )
        )
        if args.validate_only:
            result = validate_stage8_inputs(
                config_path=config_path,
                source_database=source_database,
                output_database=output_database,
                start_date=start,
                end_date=end,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = analyze_stage8(
            root=root,
            config_path=config_path,
            source_database=source_database,
            output_database=output_database,
            as_of_date=end,
            start_date=start,
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
        print("Stage 8 limit-event analysis: " + report["run_status"])
        print("  publication_status: " + report["publication_status"])
        print("  formal_events: " + str(report["formal_event_count"]))
        print("  provisional: " + str(report["candidate_count"]))
        print("  unresolved: " + str(report["unresolved_count"]))
        print("  run_id: " + report["run_id"])
        if report["blocking_reasons"]:
            print("  blockers: " + "; ".join(report["blocking_reasons"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 error: {exc}", file=sys.stderr)
        return 1


def _cmd_analyze_style(args):
    """Run or validate the fully offline Stage 9 style analysis."""
    setup_logging(level=args.log_level)
    try:
        import pandas as pd
        from .stage9_build import analyze_stage9, validate_stage9_inputs

        as_of = pd.Timestamp(resolve_as_of_date(cli_date=args.as_of_date)).normalize()
        root = project_root()
        config_path = root / args.config
        input_database = root / args.input_database
        output_database = root / args.output_database
        symbols = [str(item).zfill(6) for item in args.symbols] if args.symbols else None
        windows = list(args.windows) if args.windows else None
        start = pd.Timestamp(args.start_date).normalize() if args.start_date else None
        stage8_database = root / args.stage8_database if args.stage8_database else None
        if args.validate_only:
            result = validate_stage9_inputs(
                config_path=config_path, input_database=input_database,
                output_database=output_database, as_of_date=as_of, symbols=symbols,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = analyze_stage9(
            root=root, config_path=config_path, input_database=input_database,
            output_database=output_database, as_of_date=as_of,
            start_date=start, symbols=symbols, windows=windows,
            stage8_database=stage8_database, run_id=args.run_id,
            dry_run=args.dry_run,
        )
        print("Stage 9 style analysis: " + report["run_status"])
        print("  publication_status: " + report["publication_status"])
        print("  profiles: " + str(report["profile_row_count"]))
        print("  stage8_publication_status: " + report["stage8_publication_status"])
        print("  run_id: " + report["run_id"])
        if report["blocking_reasons"]:
            print("  blockers: " + "; ".join(report["blocking_reasons"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 9 error: {exc}", file=sys.stderr)
        return 1


def _cmd_analyze_fundamental(args):
    """Run or validate the fully offline Stage 10 fundamental analysis."""
    setup_logging(level=args.log_level)
    try:
        import pandas as pd
        from .stage10_build import analyze_stage10, validate_stage10_inputs

        as_of = pd.Timestamp(resolve_as_of_date(cli_date=args.as_of_date)).normalize()
        root = project_root()
        config_path = root / args.config
        input_database = root / args.input_database
        output_database = root / args.output_database
        input_manifest = root / args.input_manifest
        symbols = [str(item).zfill(6) for item in args.symbols] if args.symbols else None
        if args.validate_only:
            if args.asset_type == "crypto":
                report, exit_code = analyze_stage10(
                    root=root, config_path=config_path, input_database=input_database,
                    output_database=output_database, as_of_date=as_of, symbols=symbols,
                    run_id=args.run_id, dry_run=True, input_manifest=input_manifest,
                    asset_type=args.asset_type,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
                return exit_code
            result = validate_stage10_inputs(
                config_path=config_path, input_database=input_database,
                output_database=output_database, as_of_date=as_of, symbols=symbols,
                input_manifest=input_manifest,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = analyze_stage10(
            root=root, config_path=config_path, input_database=input_database,
            output_database=output_database, as_of_date=as_of, symbols=symbols,
            run_id=args.run_id, dry_run=args.dry_run,
            input_manifest=input_manifest,
            asset_type=args.asset_type,
        )
        print("Stage 10 fundamental analysis: " + report["run_status"])
        print("  publication_status: " + report["publication_status"])
        if report.get("status") == "not_applicable":
            print("  reason: " + report["reason"])
            print("  run_id: " + report["run_id"])
            return exit_code
        print("  summaries: " + str(report["summary_row_count"]))
        print("  valuation_scope: " + report["valuation_scope"])
        print("  run_id: " + report["run_id"])
        if report["blocking_reasons"]:
            print("  blockers: " + "; ".join(report["blocking_reasons"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 10 error: {exc}", file=sys.stderr)
        return 1


def _cmd_validate_crypto(args):
    """Validate Stage 11 ETHUSDT support with offline input or explicit live fetch."""
    setup_logging(level=args.log_level)
    try:
        import pandas as pd
        from .stage11_build import analyze_stage11, validate_stage11_inputs

        as_of = pd.Timestamp(resolve_as_of_date(cli_date=args.as_of_date)).normalize()
        root = project_root()
        config_path = root / args.config
        output_database = root / args.output_database
        input_csv = root / args.input_csv if args.input_csv else None
        if args.validate_only:
            reports_dir = root / args.reports_dir
            run_id = args.run_id
            if not run_id:
                run_manifest = reports_dir / "stage11_run.json"
                if run_manifest.is_file():
                    run_id = json.loads(run_manifest.read_text(encoding="utf-8")).get("run_id")
            csv_path = input_csv or reports_dir / "stage11_crypto_price.csv"
            json_path = root / args.input_json if args.input_json else reports_dir / "stage11_crypto_price.json"
            raw_dir = root / args.raw_evidence_dir if args.raw_evidence_dir else root / "data" / "raw" / "crypto_okx_history" / f"run_id={run_id}"
            result = validate_stage11_inputs(
                config_path=config_path, input_csv=csv_path, input_json=json_path,
                output_database=output_database, raw_evidence_dir=raw_dir,
                run_id=run_id, as_of_date=as_of, strict_artifacts=True,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0 if result["status"] == "READY" else 2
        import uuid

        requested_run_id = args.run_id or str(uuid.uuid4())
        capability = None
        if args.probe_akshare:
            from .adapters.crypto_exchange import AkshareCryptoSpotAdapter
            from .crypto_evidence import write_akshare_probe_evidence
            import akshare as ak

            spot_frame, assessed = AkshareCryptoSpotAdapter().fetch()
            capability = {
                "status": assessed.status, "exact_match": assessed.exact_match,
                "eth_matches": list(assessed.eth_matches), "source": assessed.source,
                "row_count": len(spot_frame),
            }
            if not args.dry_run:
                evidence_dir = root / "data" / "raw" / "crypto_js_spot" / f"run_id={requested_run_id}"
                write_akshare_probe_evidence(
                    evidence_dir, run_id=requested_run_id, response=spot_frame,
                    capability=capability, akshare_version=ak.__version__,
                    fetched_at=pd.Timestamp.now(tz="UTC"),
                )
                capability["evidence_path"] = evidence_dir.relative_to(root).as_posix()
        if input_csv is not None:
            frame = pd.read_csv(input_csv)
            source = args.source
            if not args.raw_evidence_dir:
                raise ValueError("--raw-evidence-dir is required with --input-csv")
            raw_evidence_dir = root / args.raw_evidence_dir
        elif args.fetch_live:
            from .adapters.crypto_exchange import BinancePublicKlineAdapter, OkxPublicKlineAdapter
            from .crypto_evidence import write_raw_evidence
            from .crypto_market import identity_contract_from_config, load_stage11_config
            import tempfile

            end = as_of.tz_localize("UTC") + pd.Timedelta(days=1)
            start = pd.Timestamp(args.start_time, tz="UTC") if args.start_time else end - pd.Timedelta(days=40)
            adapter = BinancePublicKlineAdapter() if args.provider == "binance" else OkxPublicKlineAdapter()
            frame = adapter.fetch(
                symbol="ETHUSDT", interval=args.interval,
                start_time=start.to_pydatetime(), end_time=end.to_pydatetime(),
            )
            source = "binance_public_api" if args.provider == "binance" else "okx_public_api"
            identity = identity_contract_from_config(load_stage11_config(config_path)[0])
            if args.dry_run:
                temporary = tempfile.TemporaryDirectory(prefix="stage11-raw-evidence-")
                raw_evidence_dir = Path(temporary.name)
            else:
                raw_evidence_dir = root / "data" / "raw" / "crypto_okx_history" / f"run_id={requested_run_id}"
            write_raw_evidence(
                raw_evidence_dir, run_id=requested_run_id, provider=source,
                endpoint=adapter.endpoint,
                request_parameters={
                    "instId": "ETH-USDT", "bar": "1H",
                    "start_time": start.isoformat(), "end_time": end.isoformat(),
                },
                response=frame, identity=identity,
                fetched_at=pd.Timestamp.now(tz="UTC"),
            )
        else:
            raise ValueError("provide --input-csv or explicitly opt in with --fetch-live")
        report, exit_code = analyze_stage11(
            root=root, as_of_date=as_of, input_frame=frame, interval=args.interval,
            source=source, config_path=config_path, output_database=output_database,
            run_id=requested_run_id, dry_run=args.dry_run,
            akshare_capability=capability,
            raw_evidence_dir=raw_evidence_dir,
        )
        print("Stage 11 crypto validation: " + report["run_status"])
        print("  symbol: " + report["symbol"])
        print("  rows: " + str(report["row_count"]))
        print("  fundamental_analysis: " + report["fundamental_analysis_status"])
        print("  run_id: " + report["run_id"])
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 11 error: {exc}", file=sys.stderr)
        return 1


def _cmd_analyze_stage12(args):
    """Run Stage 12 from explicit local inputs and emit JSON-only stdout."""
    setup_logging(level=args.log_level)
    try:
        import pandas as pd
        from .stage12_analysis import analyze_stage12

        as_of = pd.Timestamp(resolve_as_of_date(cli_date=args.as_of_date)).normalize()
        root = project_root()
        price_path = root / args.price_input
        fundamental_path = root / args.fundamental_input if args.fundamental_input else None
        if not price_path.is_file():
            raise ValueError(f"price input does not exist: {price_path}")
        prices = pd.read_csv(price_path, dtype={"instrument": str, "symbol": str})
        fundamentals = None
        if fundamental_path is not None:
            if not fundamental_path.is_file():
                raise ValueError(f"fundamental input does not exist: {fundamental_path}")
            fundamentals = pd.read_csv(fundamental_path, dtype={"instrument": str, "symbol": str})
        report, exit_code = analyze_stage12(
            root=root, as_of_date=as_of, price_frame=prices,
            fundamental_frame=fundamentals, config_path=root / args.config,
            output_database=root / args.output_database, run_id=args.run_id,
            dry_run=args.dry_run, reports_dir=root / args.reports_dir,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 12 error: {exc}", file=sys.stderr)
        return 1


def _cmd_present_stage13(args):
    """Generate Stage 13 from local read-only databases; stdout is JSON only."""
    try:
        import pandas as pd
        from .stage13_presentation import build_stage13_presentation

        root = project_root()
        as_of = pd.Timestamp(resolve_as_of_date(cli_date=args.as_of_date)).normalize()
        report, exit_code = build_stage13_presentation(
            root=root,
            as_of_date=as_of,
            config_path=root / args.config,
            input_database=root / args.input_database,
            reports_dir=root / args.reports_dir,
            run_id=args.run_id,
            dry_run=args.dry_run,
            symbols=args.symbols,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(json.dumps({"stage": 13, "status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stdout)
        return 2


def _cmd_quality_control(args):
    """Run Stage 15 quality control and risk validation fully offline."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        from .stage15_build import (
            run_stage15_quality_control,
            validate_stage15_inputs,
        )

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        config_path = root / args.config
        input_database = root / args.input_database
        stage8_database = root / args.stage8_database if args.stage8_database else None
        baseline_path = root / args.baseline if args.baseline else None
        output_database = (
            root / args.output_database
            if args.output_database
            else root / "database" / "stage15" / run_id / "stage15_quality.duckdb"
        )
        reports_dir = root / args.reports_dir
        symbols = (
            [str(item).zfill(6) for item in args.cross_validation_symbols]
            if args.cross_validation_symbols
            else None
        )
        if args.validate_only:
            result = validate_stage15_inputs(
                root=root,
                config_path=config_path,
                input_database=input_database,
                output_database=output_database,
                as_of_date=as_of,
                stage8_database=stage8_database,
                baseline=baseline_path,
                cross_validation_symbols=symbols,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = run_stage15_quality_control(
            root=root,
            as_of_date=as_of,
            config_path=config_path,
            input_database=input_database,
            output_database=output_database,
            reports_dir=reports_dir,
            run_id=run_id,
            stage8_database=stage8_database,
            baseline_path=baseline_path,
            cross_validation_symbols=symbols,
            dry_run=args.dry_run,
        )
        print("Stage 15 quality control: " + report["status"])
        print("  run_id: " + report["run_id"])
        print("  as_of_date: " + report["as_of_date"])
        if report.get("outputs_written") is False:
            print("  blockers: " + "; ".join(report.get("blocking_reasons", [])))
            print("  errors: " + "; ".join(report.get("errors", [])))
            return exit_code
        if report.get("status") != "DRY_RUN":
            print(
                "  checks: "
                + str(report["quality_status_counts"]["PASS"])
                + " pass, "
                + str(report["quality_status_counts"]["WARN"])
                + " warn, "
                + str(report["quality_status_counts"]["FAIL"])
                + " fail"
            )
            print("  risk_log_rows: " + str(len(report["risk_log"])))
            print(
                "  cross_validation_rows: "
                + str(len(report["cross_validation"]))
            )
            print(
                "  unavailable_items: "
                + str(report.get("unavailable_count", 0))
            )
            print(
                "  blocked_risks: " + str(report.get("blocked_risk_count", 0))
            )
            if report["status"] == "PASS_WITH_UNAVAILABLE_ITEMS":
                print(
                    "  note: daily quality checks passed; cross-validation "
                    "still has UNAVAILABLE items and Stage 8 blocked risks"
                )
            if report["stage8_blocker_codes"]:
                print(
                    "  stage8_blockers: "
                    + "; ".join(report["stage8_blocker_codes"])
                )
            print("  reports: " + report["outputs"]["reports_dir"])
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 15 error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage8_source_probe(args):
    """Probe authoritative status-history sources and write feasibility report."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        from .adapters.status_probe import (
            probe_plan,
            probe_source_suite,
            write_feasibility_report,
        )

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        if args.validate_only:
            print(
                json.dumps(
                    {
                        "command": "stage8-source-probe",
                        "status": "VALIDATE_ONLY",
                        "run_id": run_id,
                        "as_of_date": as_of.isoformat(),
                        "plan": probe_plan(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        output_dir = root / args.output_dir
        evidence_dir = output_dir / run_id
        manifest = probe_source_suite(
            evidence_dir, as_of_date=as_of, run_id=run_id
        )
        report = write_feasibility_report(
            evidence_dir,
            evidence_dir,
            run_id=run_id,
            as_of_date=as_of,
        )
        for name in ("probe_manifest.json", "source_grade_summary.json",
                     "column_mapping.json"):
            json.loads((evidence_dir / name).read_text(encoding="utf-8-sig"))
        print(
            "Stage 8 source probe: "
            + report["summary"]
            + " (json_parse: OK)"
        )
        print("  run_id: " + run_id)
        print(
            "  interfaces: "
            + ", ".join(sorted(manifest["interfaces_probed"]))
        )
        print(
            "  authoritative_rule_source_ready: "
            + str(report["authoritative_rule_source_ready"])
        )
        print(
            "  authoritative_status_source_ready: "
            + str(report["authoritative_status_source_ready"])
        )
        print(
            "  outputs: "
            + str(evidence_dir)
        )
        return 0
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 source probe error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage8_rules_build(args):
    """Validate and publish the authoritative Stage 8 rule history dataset."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        import pandas as pd
        from .stage8_authoritative import build_rules_manifest

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        end = pd.Timestamp(as_of).normalize()
        start = (
            pd.Timestamp(args.start_date).normalize()
            if args.start_date
            else end
            - pd.Timedelta(
                days=int(
                    load_metrics().raw["data_ranges"]["limit_event"][
                        "lookback_natural_days"
                    ]
                )
            )
        )
        config_path = root / args.config
        rules_path = config_path if config_path.is_file() else None
        report, exit_code = build_rules_manifest(
            rules_path=rules_path,
            dataset_dir=(
                None if rules_path is not None else root / args.dataset_dir
            ),
            output_dir=root / args.output_dir,
            as_of_date=as_of,
            run_id=run_id,
            output_config=(
                root / args.output_config if args.output_config else None
            ),
            base_config=root / args.base_config if args.base_config else None,
            validate_only=args.validate_only,
            coverage_start=start.date(),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 rules build error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage8_status_build(args):
    """Validate and publish the authoritative Stage 8 status-history dataset."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        import pandas as pd
        from .stage8_authoritative import build_status_manifest

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        end = pd.Timestamp(as_of).normalize()
        start = (
            pd.Timestamp(args.start_date).normalize()
            if args.start_date
            else end
            - pd.Timedelta(
                days=int(
                    load_metrics().raw["data_ranges"]["limit_event"][
                        "lookback_natural_days"
                    ]
                )
            )
        )
        config_path = root / args.config
        statuses_path = config_path if config_path.is_file() else None
        report, exit_code = build_status_manifest(
            statuses_path=statuses_path,
            dataset_dir=(
                None if statuses_path is not None else root / args.dataset_dir
            ),
            output_dir=root / args.output_dir,
            as_of_date=as_of,
            run_id=run_id,
            output_config=(
                root / args.output_config if args.output_config else None
            ),
            base_config=root / args.base_config if args.base_config else None,
            validate_only=args.validate_only,
            coverage_start=start.date(),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 status build error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage8_preflight(args):
    """Read-only Stage 8 preflight using the authoritative configuration."""
    setup_logging(level=args.log_level)
    try:
        import tempfile
        import uuid
        import pandas as pd
        import yaml
        from .stage8_build import validate_stage8_inputs
        from .stage8_manual import build_merged_payload, validate_combined_datasets

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        config_path = root / args.config
        source_database = root / args.source_database
        output_database = root / args.output_database
        end = pd.Timestamp(as_of).normalize()
        start = (
            pd.Timestamp(args.start_date).normalize()
            if args.start_date
            else end
            - pd.Timedelta(
                days=int(
                    load_metrics().raw["data_ranges"]["limit_event"][
                        "lookback_natural_days"
                    ]
                )
            )
        )
        if config_path.is_file():
            result = validate_stage8_inputs(
                config_path=config_path,
                source_database=source_database,
                output_database=output_database,
                start_date=start,
                end_date=end,
            )
        else:
            run_id = str(uuid.uuid4())
            combined = validate_combined_datasets(
                rules_dir=root / args.rules_dataset_dir,
                status_dir=root / args.status_dataset_dir,
                as_of_date=as_of,
                coverage_start=start.date(),
                coverage_end=end.date(),
                run_id=run_id,
            )
            if not combined["valid"]:
                print(
                    json.dumps(
                        combined, ensure_ascii=False, indent=2, default=str
                    )
                )
                return {
                    "READY": 0, "BLOCKED": 2, "FAILED": 1
                }[combined["status"]]
            payload = build_merged_payload(
                rules_result=combined["components"]["rules"],
                status_result=combined["components"]["security_status_history"],
                run_id=run_id,
            )
            with tempfile.TemporaryDirectory(
                prefix="stage8_preflight_"
            ) as temporary:
                temp_config = Path(temporary) / "stage8.yml"
                temp_config.write_text(
                    yaml.safe_dump(
                        payload, allow_unicode=True, sort_keys=False
                    ),
                    encoding="utf-8",
                )
                result = validate_stage8_inputs(
                    config_path=temp_config,
                    source_database=source_database,
                    output_database=output_database,
                    start_date=start,
                    end_date=end,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 preflight error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage8_rebuild(args):
    """Rebuild Stage 8 formal limit events with the authoritative dataset."""
    setup_logging(level=args.log_level)
    try:
        import tempfile
        import uuid
        import pandas as pd
        import yaml
        from .stage8_build import analyze_stage8
        from .stage8_manual import build_merged_payload, validate_combined_datasets

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        config_path = root / args.config
        source_database = root / args.source_database
        output_database = (
            root / args.output_database
            if args.output_database
            else root
            / "database"
            / "stage15_s14_fix"
            / run_id
            / "stage8_authoritative.duckdb"
        )
        reports_dir = (
            root / args.reports_dir
            if args.reports_dir
            else root / "reports" / "stage15_s14_fix" / run_id
        )
        end = pd.Timestamp(as_of).normalize()
        start = (
            pd.Timestamp(args.start_date).normalize()
            if args.start_date
            else end
            - pd.Timedelta(
                days=int(
                    load_metrics().raw["data_ranges"]["limit_event"][
                        "lookback_natural_days"
                    ]
                )
            )
        )
        if not config_path.is_file():
            combined = validate_combined_datasets(
                rules_dir=root / args.rules_dataset_dir,
                status_dir=root / args.status_dataset_dir,
                as_of_date=as_of,
                coverage_start=start.date(),
                coverage_end=end.date(),
                run_id=run_id,
            )
            if not combined["valid"]:
                print(
                    json.dumps(
                        combined, ensure_ascii=False, indent=2, default=str
                    )
                )
                return {
                    "READY": 0, "BLOCKED": 2, "FAILED": 1
                }[combined["status"]]
            payload = build_merged_payload(
                rules_result=combined["components"]["rules"],
                status_result=combined["components"]["security_status_history"],
                run_id=run_id,
            )
            if args.validate_only:
                from .stage8_build import validate_stage8_inputs

                with tempfile.TemporaryDirectory(
                    prefix="stage8_validate_"
                ) as temporary:
                    temp_config = Path(temporary) / "stage8.yml"
                    temp_config.write_text(
                        yaml.safe_dump(
                            payload, allow_unicode=True, sort_keys=False
                        ),
                        encoding="utf-8",
                    )
                    result = validate_stage8_inputs(
                        config_path=temp_config,
                        source_database=source_database,
                        output_database=output_database,
                        start_date=start,
                        end_date=end,
                    )
                print(
                    json.dumps(result, ensure_ascii=False, indent=2, default=str)
                )
                return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
            else:
                reports_dir.mkdir(parents=True, exist_ok=True)
                config_path = reports_dir / "stage8_config.yml"
                config_path.write_text(
                    yaml.safe_dump(
                        payload, allow_unicode=True, sort_keys=False
                    ),
                    encoding="utf-8",
                )
        if args.validate_only:
            from .stage8_build import validate_stage8_inputs

            result = validate_stage8_inputs(
                config_path=config_path,
                source_database=source_database,
                output_database=output_database,
                start_date=start,
                end_date=end,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = analyze_stage8(
            root=root,
            config_path=config_path,
            source_database=source_database,
            output_database=output_database,
            as_of_date=end,
            start_date=start,
            run_id=run_id,
            dry_run=args.dry_run,
            reports_dir=reports_dir,
        )
        print("Stage 8 authoritative rebuild: " + report["run_status"])
        print("  publication_status: " + report["publication_status"])
        print("  formal_events: " + str(report["formal_event_count"]))
        print("  rule_count: " + str(report["rule_count"]))
        print("  security_status_count: " + str(report["security_status_count"]))
        print("  run_id: " + report["run_id"])
        if report["blocking_reasons"]:
            print("  blockers: " + "; ".join(report["blocking_reasons"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 8 rebuild error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage15_rerun(args):
    """Re-run Stage 15 quality control against the authoritative Stage 8 DB."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        from .stage15_build import (
            run_stage15_quality_control,
            validate_stage15_inputs,
        )

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        config_path = root / args.config
        input_database = root / args.input_database
        stage8_database = (
            root / args.stage8_database
            if args.stage8_database
            else root
            / "database"
            / "stage15_s14_fix"
            / run_id
            / "stage8_authoritative.duckdb"
        )
        reports_dir = (
            root / args.reports_dir
            if args.reports_dir
            else root / "reports" / "stage15_s14_fix"
        )
        output_database = (
            root / args.output_database
            if args.output_database
            else root
            / "database"
            / "stage15_s14_fix"
            / run_id
            / "stage15_quality.duckdb"
        )
        symbols = (
            [str(item).zfill(6) for item in args.cross_validation_symbols]
            if args.cross_validation_symbols
            else None
        )
        if args.validate_only:
            result = validate_stage15_inputs(
                root=root,
                config_path=config_path,
                input_database=input_database,
                output_database=output_database,
                as_of_date=as_of,
                stage8_database=stage8_database,
                baseline=root / args.baseline if args.baseline else None,
                cross_validation_symbols=symbols,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return {"READY": 0, "BLOCKED": 2, "FAILED": 1}[result["status"]]
        report, exit_code = run_stage15_quality_control(
            root=root,
            as_of_date=as_of,
            config_path=config_path,
            input_database=input_database,
            output_database=output_database,
            reports_dir=reports_dir,
            run_id=run_id,
            stage8_database=stage8_database,
            baseline_path=root / args.baseline if args.baseline else None,
            cross_validation_symbols=symbols,
            dry_run=args.dry_run,
        )
        print("Stage 15 rerun: " + report["status"])
        print("  run_id: " + report["run_id"])
        print(
            "  unavailable_items: " + str(report.get("unavailable_count", 0))
        )
        print(
            "  blocked_risks: " + str(report.get("blocked_risk_count", 0))
        )
        print("  reports: " + report.get("outputs", {}).get("reports_dir", ""))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 15 rerun error: {exc}", file=sys.stderr)
        return 1


def _cmd_stage15_s14_reverify(args):
    """Produce the S15-14 manual cross-validation evidence and verdict."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        from .stage8_authoritative import verify_s14

        as_of = resolve_as_of_date(cli_date=args.as_of_date)
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        report, exit_code = verify_s14(
            stage8_database=root / args.stage8_database,
            stage15_reports_dir=root / args.stage15_reports_dir,
            output_dir=root / args.output_dir,
            as_of_date=as_of,
            run_id=run_id,
            validate_only=args.validate_only,
        )
        print("S15-14 reverify: " + report["status"])
        print("  valid_samples: " + str(report["valid_sample_count"]))
        print("  unavailable: " + str(report["unavailable_count"]))
        print("  run_id: " + report["run_id"])
        print("  outputs: " + report["outputs"]["verification_csv"])
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"S15-14 reverify error: {exc}", file=sys.stderr)
        return 1


def _cmd_final_report(args):
    """Build the fully offline Stage 16 availability and final report."""
    setup_logging(level=args.log_level)
    try:
        import uuid
        import pandas as pd
        from .stage16_report import build_stage16_report

        as_of = pd.Timestamp(
            resolve_as_of_date(cli_date=args.as_of_date)
        ).normalize()
        root = project_root()
        run_id = args.run_id or str(uuid.uuid4())
        uuid.UUID(run_id)
        report, exit_code = build_stage16_report(
            root=root,
            as_of_date=as_of,
            config_path=root / args.config,
            reports_dir=root / args.reports_dir,
            run_id=run_id,
            dry_run=args.dry_run,
            validate_only=args.validate_only,
        )
        print("Stage 16 final report: " + report["status"])
        print("  run_id: " + run_id)
        print("  stocks: " + str(report.get("symbol_count", 0)))
        print("  Hong Kong symbols: " + str(report.get("hong_kong_symbol_count", 0)))
        print("  network_attempts: " + str(report.get("network_attempts", 0)))
        if report.get("outputs"):
            print("  reports: " + report["outputs"]["reports_dir"])
        if report.get("blocking_reasons"):
            print("  blockers: " + "; ".join(report["blocking_reasons"]))
        return exit_code
    except Exception as exc:
        if args.debug:
            raise
        print(f"Stage 16 error: {exc}", file=sys.stderr)
        return 1


def _generate_summary_md(results, run_id, overall, as_of):
    sp = Path("reports/interface_smoke_test_summary.md")
    sl = []
    sl.append("# Stage 2: Interface Smoke Test Summary")
    sl.append("")
    sl.append("- Run ID: `" + run_id + "`")
    sl.append("- Business date: " + as_of)
    sl.append("- Overall status: **" + overall + "**")
    sl.append("- Probes: " + str(len(results)))
    sl.append("")
    sl.append("## Results")
    sl.append("")
    sl.append("| probe_id | status | rows | cols | error_type | elapsed_s |")
    sl.append("|--- |--- |--- |--- |--- |--- |")
    for pr in results:
        rs = str(pr.row_count) if pr.row_count is not None else "-"
        cs = str(pr.column_count) if pr.column_count is not None else "-"
        et = pr.error_type or "-"
        es = "%.2f" % pr.elapsed_seconds
        sl.append("| " + pr.probe_id + " | " + pr.status + " | " + rs + " | " + cs + " | " + et + " | " + es + " |")
    sp.parent.mkdir(parents=True, exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        f.write("\n".join(sl) + "\n")
    print("\nSummary: " + str(sp))


def _cmd_stage14(args):
    """Run one Stage 14 alias or the complete dependency-ordered pipeline."""
    from .stage14_automation import (
        TASK_ORDER, PipelineContext, execute_pipeline, generate_run_id,
        load_stage14_config, render_plan, validate_date_range,
    )
    try:
        load_stage14_config(project_root() / args.config)
        if args.command == "run-all" and (not args.start or not args.end):
            raise ValueError("run-all requires --start and --end in YYYYMMDD format")
        configured_end = resolve_as_of_date(cli_date=None)
        end_value = args.end or configured_end.strftime("%Y%m%d")
        if args.start:
            start_value = args.start
        else:
            years = int(load_metrics().raw["data_ranges"]["stock_daily"]["default_years"])
            try:
                configured_start = configured_end.replace(year=configured_end.year - years)
            except ValueError:
                configured_start = configured_end.replace(year=configured_end.year - years, day=28)
            start_value = configured_start.strftime("%Y%m%d")
        start, end = validate_date_range(start_value, end_value)
        run_id = args.run_id or generate_run_id()
        # Keep compatibility with Stage 2-8 immutable run partitions.
        import uuid
        uuid.UUID(run_id)
        context = PipelineContext(
            root=project_root(), run_id=run_id, start_date=start, end_date=end,
            log_level=args.log_level, force=args.force,
            only_symbol=getattr(args, "only_symbol", None),
            run_all=args.command == "run-all",
        )
        tasks = TASK_ORDER if args.command == "run-all" else (args.command,)
        if args.dry_run:
            print(render_plan(tasks, context))
            return 0
        statuses, exit_code = execute_pipeline(tasks, context)
        for item in statuses:
            print(f"{item.task_name}: {item.status}")
            if item.error_message and item.status == "failed":
                print(f"  {item.error_type}: {item.error_message}", file=sys.stderr)
        print(f"run_id: {run_id}")
        print(f"status: {'success' if exit_code == 0 else 'failed'}")
        return exit_code
    except (ValueError, OSError) as exc:
        print(f"Stage 14 error: {exc}", file=sys.stderr)
        return 2


def _run_stage14_logged_single(task_name, args, handler):
    """Add Stage 14 status/logging to established standalone task commands."""
    if os.environ.get("AKSHARE_STAGE14_CHILD") == "1" or getattr(args, "dry_run", False):
        return handler(args)
    from .stage14_automation import PipelineContext, execute_pipeline, generate_run_id
    run_id = getattr(args, "run_id", None) or generate_run_id()
    if hasattr(args, "run_id"):
        args.run_id = run_id
    end = getattr(args, "end", None) or getattr(args, "as_of_date", None) or "configured"
    start = getattr(args, "start", None) or getattr(args, "start_date", None) or end
    context = PipelineContext(
        root=project_root(), run_id=run_id, start_date=start, end_date=end,
        log_level=getattr(args, "log_level", "INFO"),
        force=getattr(args, "force", False),
        only_symbol=getattr(args, "only_symbol", None),
    )

    # Execute inside the observer so the running transition is durable before
    # the handler starts, and uncaught exceptions receive a traceback.
    caught: list[tuple[BaseException, object]] = []

    def observe(_task, _context):
        try:
            code = int(handler(args))
            return code, "", ""
        except BaseException as exc:
            caught.append((exc, exc.__traceback__))
            raise

    _statuses, exit_code = execute_pipeline([task_name], context, executor=observe)
    if caught and getattr(args, "debug", False):
        exc, original_traceback = caught[0]
        raise exc.with_traceback(original_traceback)
    return exit_code

def main():
    parser = argparse.ArgumentParser(prog="akshare-data-test")
    sub = parser.add_subparsers(dest="command")
    dp = sub.add_parser("doctor", help="Run offline environment check")
    dp.add_argument("--as-of-date", default=None)
    dp.add_argument("--output", default=None)
    dp.add_argument("--log-level", default="INFO")
    sp = sub.add_parser("show-config", help="Show safe config summary")
    sp.add_argument("--as-of-date", default=None)
    sp.add_argument("--log-level", default="INFO")
    sm = sub.add_parser("smoke-test", help="Run interface smoke tests")
    sm.add_argument("--as-of-date", default=None)
    sm.add_argument("--sample-symbol", default="600763")
    sm.add_argument("--pool-date", type=_pool_date_arg, default=None)
    sm.add_argument("--output", default="reports/interface_smoke_test.csv")
    sm.add_argument("--evidence-dir", default="reports/evidence/stage2")
    sm.add_argument("--max-sample-rows", type=int, default=20)
    sm.add_argument("--only", default=None)
    sm.add_argument("--log-level", default="INFO")
    sm.add_argument("--strict", action="store_true", default=False)
    sm.add_argument("--run-id", default=None)
    nc = sub.add_parser(
        "network-check",
        help="Check DNS, TCP 443, and TLS without requesting financial data",
    )
    nc.add_argument("--timeout", type=float, default=5.0)
    nc.add_argument("--output", default="reports/stage2_network_preflight.json")
    nc.add_argument(
        "--markdown-output",
        default="docs/stage2_network_preflight.md",
    )
    nc.add_argument("--log-level", default="INFO")
    fm = sub.add_parser("fetch-market", help="Fetch Stage 3 market Raw data")
    fm.add_argument("--as-of-date", default=None)
    fm.add_argument("--run-id", default=None)
    fm.add_argument("--start-date", default=None, help="Explicit ISO start date")
    fm.add_argument("--start", default=None, help="Explicit start date in YYYYMMDD")
    fm.add_argument("--end", default=None, help="Explicit end date in YYYYMMDD")
    fm.add_argument("--config", default="config/stage14.yml")
    fm.add_argument("--dry-run", action="store_true", default=False)
    fm.add_argument("--force", action="store_true", default=False)
    fm.add_argument("--output-dir", default="data/raw")
    fm.add_argument("--evidence-dir", default="reports/evidence/stage3")
    fm.add_argument("--only-symbol", default=None)
    fm.add_argument("--skip-spot", action="store_true", default=False)
    fm.add_argument("--log-level", default="INFO")
    ff = sub.add_parser(
        "fetch-fundamentals", help="Fetch Stage 4 financial and fund-flow Raw data"
    )
    ff.add_argument("--as-of-date", default=None)
    ff.add_argument("--start-year", default=None)
    ff.add_argument("--run-id", default=None)
    ff.add_argument("--output-dir", default="data/raw")
    ff.add_argument("--evidence-dir", default="reports/evidence/stage4")
    ff.add_argument("--only-symbol", default=None)
    ff.add_argument("--only-interface", default=None)
    ff.add_argument("--resume", action="store_true", default=False)
    ff.add_argument("--log-level", default="INFO")
    b5 = sub.add_parser(
        "build-stage5", help="Build Stage 5 Clean data and DuckDB fully offline"
    )
    b5.add_argument("--as-of-date", required=True)
    b5.add_argument("--market-run-id", required=True)
    b5.add_argument("--fundamental-run-id", required=True)
    b5.add_argument("--transform-run-id", default=None)
    b5.add_argument("--clean-output-dir", default="data/clean")
    b5.add_argument("--database-path", default="database/akshare_data_test.duckdb")
    b5.add_argument("--evidence-dir", default="reports/evidence/stage5")
    b5.add_argument("--rebuild-clean", action="store_true", default=False)
    b5.add_argument("--validate-only", action="store_true", default=False)
    b5.add_argument("--log-level", default="INFO")
    v5 = sub.add_parser("validate-stage5", help="Validate the Stage 5 DuckDB")
    v5.add_argument("--as-of-date", required=True)
    v5.add_argument("--database-path", default="database/akshare_data_test.duckdb")
    v5.add_argument("--log-level", default="INFO")
    r5 = sub.add_parser(
        "repair-stage5-idempotency",
        help="Validate the Stage 5 metadata idempotency repair offline",
    )
    r5.add_argument("--as-of-date", required=True)
    r5.add_argument("--log-level", default="INFO")
    b6 = sub.add_parser(
        "build-stage6",
        help="Build point-in-time-safe Stage 6 features fully offline",
    )
    b6.add_argument("--as-of-date", required=True)
    b6.add_argument("--source-database", required=True)
    b6.add_argument("--transform-run-id", required=True)
    b6.add_argument("--feature-run-id", default=None)
    b6.add_argument("--feature-output-dir", default="data/feature")
    b6.add_argument(
        "--feature-database-path",
        default="database/akshare_features_stage6.duckdb",
    )
    b6.add_argument("--evidence-dir", default="reports/evidence/stage6")
    b6.add_argument("--validate-only", action="store_true", default=False)
    b6.add_argument("--log-level", default="INFO")
    v6 = sub.add_parser(
        "validate-stage6", help="Validate the independent Stage 6 DuckDB"
    )
    v6.add_argument("--as-of-date", required=True)
    v6.add_argument("--feature-database-path", required=True)
    v6.add_argument("--validate-only", action="store_true", default=False)
    v6.add_argument("--log-level", default="INFO")
    r6 = sub.add_parser(
        "verify-stage6-idempotency-repair",
        help="Verify the Stage 6 persistence repair using temporary artifacts",
    )
    r6.add_argument("--as-of-date", required=True)
    r6.add_argument("--log-level", default="INFO")
    b7 = sub.add_parser(
        "build-features",
        help="Build Stage 7 daily features and activity scores fully offline",
    )
    b7.add_argument("--as-of-date", default=None)
    b7.add_argument(
        "--source-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    b7.add_argument(
        "--output-database",
        default="database/akshare_features_stage7.duckdb",
    )
    b7.add_argument("--adjust", choices=["qfq"], default="qfq")
    b7.add_argument("--lookback-days", type=int, default=None)
    b7.add_argument("--run-id", default=None)
    b7.add_argument("--log-level", default="INFO")
    b8 = sub.add_parser(
        "analyze-limit-events",
        help="Analyze Stage 8 daily-limit events from raw prices fully offline",
    )
    b8.add_argument("--as-of-date", required=True)
    b8.add_argument("--start-date", default=None)
    b8.add_argument("--config", default="config/stage8.yml")
    b8.add_argument(
        "--source-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    b8.add_argument(
        "--output-database",
        default="database/akshare_limit_events_stage8.duckdb",
    )
    b8.add_argument("--run-id", default=None)
    mode = b8.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=False)
    mode.add_argument("--validate-only", action="store_true", default=False)
    b8.add_argument("--log-level", default="INFO")
    b8.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show a traceback for Stage 8 internal errors",
    )
    b9 = sub.add_parser(
        "analyze-style",
        help="Analyze Stage 9 sideways and volume-price styles fully offline",
    )
    b9.add_argument("--as-of-date", required=True)
    b9.add_argument("--start-date", default=None)
    b9.add_argument("--config", default="config/stage9.yml")
    b9.add_argument(
        "--input-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    b9.add_argument(
        "--output-database",
        default="database/akshare_style_stage9.duckdb",
    )
    b9.add_argument("--stage8-database", default=None)
    b9.add_argument("--symbols", nargs="+", default=None)
    b9.add_argument("--windows", nargs="+", type=int, default=None)
    b9.add_argument("--run-id", default=None)
    mode9 = b9.add_mutually_exclusive_group()
    mode9.add_argument("--dry-run", action="store_true", default=False)
    mode9.add_argument("--validate-only", action="store_true", default=False)
    b9.add_argument("--log-level", default="INFO")
    b9.add_argument(
        "--debug", action="store_true", default=False,
        help="Show a traceback for Stage 9 internal errors",
    )
    b10 = sub.add_parser(
        "analyze-fundamental",
        help="Analyze Stage 10 fundamentals and current valuation snapshots offline",
    )
    b10.add_argument("--as-of-date", required=True)
    b10.add_argument("--config", default="config/stage10.yml")
    b10.add_argument(
        "--input-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    b10.add_argument(
        "--input-manifest",
        default="reports/stage5_verified_manifest.json",
        help="Verified Stage 5 provenance manifest",
    )
    b10.add_argument(
        "--output-database",
        default="database/akshare_fundamental_stage10.duckdb",
    )
    b10.add_argument("--symbols", nargs="+", default=None)
    b10.add_argument("--run-id", default=None)
    b10.add_argument("--asset-type", choices=["equity", "crypto"], default="equity")
    mode10 = b10.add_mutually_exclusive_group()
    mode10.add_argument("--dry-run", action="store_true", default=False)
    mode10.add_argument("--validate-only", action="store_true", default=False)
    b10.add_argument("--log-level", default="INFO")
    b10.add_argument(
        "--debug", action="store_true", default=False,
        help="Show a traceback for Stage 10 internal errors",
    )
    b11 = sub.add_parser(
        "validate-crypto",
        help="Validate Stage 11 ETHUSDT 24/7 data and indicator adaptation",
    )
    b11.add_argument("--as-of-date", required=True)
    b11.add_argument("--config", default="config/stage11.yml")
    b11.add_argument("--input-csv", default=None)
    b11.add_argument("--input-json", default=None)
    b11.add_argument("--raw-evidence-dir", default=None)
    b11.add_argument("--reports-dir", default="reports")
    b11.add_argument("--source", default="okx_public_api")
    b11.add_argument("--interval", choices=["1h", "1d"], default="1h")
    b11.add_argument("--start-time", default=None)
    b11.add_argument("--fetch-live", action="store_true", default=False)
    b11.add_argument("--provider", choices=["binance", "okx"], default="okx")
    b11.add_argument("--probe-akshare", action="store_true", default=False)
    b11.add_argument("--output-database", default="database/akshare_crypto_stage11.duckdb")
    b11.add_argument("--run-id", default=None)
    mode11 = b11.add_mutually_exclusive_group()
    mode11.add_argument("--dry-run", action="store_true", default=False)
    mode11.add_argument("--validate-only", action="store_true", default=False)
    b11.add_argument("--log-level", default="INFO")
    b11.add_argument("--debug", action="store_true", default=False)
    b12 = sub.add_parser(
        "analyze-stage12",
        help="Run reproducible Stage 12 stock analyses from local CSV inputs",
    )
    b12.add_argument("--as-of-date", required=True)
    b12.add_argument("--config", default="config/stage12.yml")
    b12.add_argument("--price-input", required=True)
    b12.add_argument("--fundamental-input", default=None)
    b12.add_argument("--reports-dir", default="reports")
    b12.add_argument("--output-database", default="database/akshare_stage12.duckdb")
    b12.add_argument("--run-id", default=None)
    b12.add_argument("--dry-run", action="store_true", default=False)
    b12.add_argument("--log-level", default="INFO")
    b12.add_argument("--debug", action="store_true", default=False)
    b13 = sub.add_parser(
        "present-stage13",
        help="Build reproducible Stage 13 charts, tables, SQL, and database inventory offline",
    )
    b13.add_argument("--as-of-date", required=True)
    b13.add_argument("--config", default="config/stage13.yml")
    b13.add_argument("--input-database", default="database/akshare_data_test_stage5_repaired.duckdb")
    b13.add_argument("--reports-dir", default="reports/stage13")
    b13.add_argument("--run-id", required=True)
    b13.add_argument("--symbols", nargs="+", default=None)
    b13.add_argument("--dry-run", action="store_true", default=False)
    b13.add_argument("--log-level", default="INFO")
    b13.add_argument("--debug", action="store_true", default=False)
    b15 = sub.add_parser(
        "quality-control",
        help="Run Stage 15 daily quality checks, cross-validation, and risk log offline",
    )
    b15.add_argument("--as-of-date", required=True)
    b15.add_argument("--config", default="config/stage15.yml")
    b15.add_argument(
        "--input-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    b15.add_argument("--stage8-database", default=None)
    b15.add_argument("--baseline", default=None)
    b15.add_argument("--reports-dir", default="reports/stage15")
    b15.add_argument("--output-database", default=None)
    b15.add_argument("--run-id", default=None)
    b15.add_argument("--cross-validation-symbols", nargs="+", default=None)
    mode15 = b15.add_mutually_exclusive_group()
    mode15.add_argument("--dry-run", action="store_true", default=False)
    mode15.add_argument("--validate-only", action="store_true", default=False)
    b15.add_argument("--log-level", default="INFO")
    b15.add_argument(
        "--debug", action="store_true", default=False,
        help="Show a traceback for Stage 15 internal errors",
    )
    b16 = sub.add_parser(
        "final-report",
        help="Build the Stage 16 final availability report fully offline",
    )
    b16.add_argument("--as-of-date", required=True)
    b16.add_argument("--config", default="config/stage16.yml")
    b16.add_argument("--reports-dir", default="reports/stage16")
    b16.add_argument("--run-id", default=None)
    mode16 = b16.add_mutually_exclusive_group()
    mode16.add_argument("--dry-run", action="store_true", default=False)
    mode16.add_argument("--validate-only", action="store_true", default=False)
    b16.add_argument("--log-level", default="INFO")
    b16.add_argument("--debug", action="store_true", default=False)
    b17 = sub.add_parser(
        "collect-stage17",
        help="Collect and audit Stage 17 A-share, H-share, and ETHUSDT Raw data",
    )
    b17.add_argument("--as-of-date", required=True)
    b17.add_argument("--config", default="config/stage17.yml")
    b17.add_argument("--run-id", default=None)
    mode17 = b17.add_mutually_exclusive_group()
    mode17.add_argument("--dry-run", action="store_true", default=False)
    mode17.add_argument("--validate-only", action="store_true", default=False)
    b17.add_argument("--log-level", default="INFO")
    b17.add_argument("--debug", action="store_true", default=False)
    b18 = sub.add_parser(
        "stage18-interface-audit",
        help="Audit current A-share and H-share fundamental interface capability",
    )
    b18.add_argument("--as-of-date", required=True)
    b18.add_argument("--upstream-run-id", default=None)
    b18.add_argument("--config", default="config/stage18.yml")
    b18.add_argument("--run-id", default=None)
    mode18 = b18.add_mutually_exclusive_group()
    mode18.add_argument("--dry-run", action="store_true", default=False)
    mode18.add_argument("--validate-only", action="store_true", default=False)
    b18.add_argument("--log-level", default="INFO")
    b18.add_argument("--debug", action="store_true", default=False)
    b1812 = sub.add_parser(
        "stage18-valuation-audit",
        help="Audit alternative A/H-share valuation providers and capability equivalence",
    )
    b1812.add_argument("--as-of-date", required=True)
    b1812.add_argument("--upstream-run-id", default=None)
    b1812.add_argument(
        "--config", default="config/stage18_valuation_audit.yml"
    )
    b1812.add_argument("--run-id", default=None)
    mode1812 = b1812.add_mutually_exclusive_group()
    mode1812.add_argument("--dry-run", action="store_true", default=False)
    mode1812.add_argument("--validate-only", action="store_true", default=False)
    b1812.add_argument("--log-level", default="INFO")
    b1812.add_argument("--debug", action="store_true", default=False)
    b1813 = sub.add_parser(
        "stage18-interface-reaudit",
        help="Run the full Stage 18.1 capability re-audit and exit gate",
    )
    b1813.add_argument("--as-of-date", required=True)
    b1813.add_argument("--upstream-run-id", default=None)
    b1813.add_argument("--config", default="config/stage18_reaudit.yml")
    b1813.add_argument("--run-id", default=None)
    mode1813 = b1813.add_mutually_exclusive_group()
    mode1813.add_argument("--dry-run", action="store_true", default=False)
    mode1813.add_argument("--validate-only", action="store_true", default=False)
    b1813.add_argument("--log-level", default="INFO")
    b1813.add_argument("--debug", action="store_true", default=False)
    b182 = sub.add_parser(
        "stage18-fundamental-collect",
        help="Collect formal Stage 18.2 fundamental Raw for all 23 securities",
    )
    b182.add_argument("--as-of-date", required=True)
    b182.add_argument("--upstream-run-id", default=None)
    b182.add_argument("--config", default="config/stage18_2.yml")
    b182.add_argument("--run-id", default=None)
    mode182 = b182.add_mutually_exclusive_group()
    mode182.add_argument("--dry-run", action="store_true", default=False)
    mode182.add_argument("--validate-only", action="store_true", default=False)
    b182.add_argument("--log-level", default="INFO")
    b182.add_argument("--debug", action="store_true", default=False)
    b183 = sub.add_parser(
        "stage18-fundamental-standardize",
        help="Standardize Stage 18.2 formal Raw into Stage 18.3 canonical Clean",
    )
    b183.add_argument("--as-of-date", required=True)
    b183.add_argument("--upstream-run-id", default=None)
    b183.add_argument("--config", default="config/stage18_3.yml")
    b183.add_argument("--run-id", default=None)
    mode183 = b183.add_mutually_exclusive_group()
    mode183.add_argument("--dry-run", action="store_true", default=False)
    mode183.add_argument("--validate-only", action="store_true", default=False)
    b183.add_argument("--log-level", default="INFO")
    b183.add_argument("--debug", action="store_true", default=False)
    b184 = sub.add_parser(
        "stage18-db-load",
        help="Load Stage 18.3 formal Clean into a new validated Stage 18.4 DuckDB",
    )
    b184.add_argument("--as-of-date", required=True)
    b184.add_argument("--upstream-run-id", default=None)
    b184.add_argument("--config", default="config/stage18_4.yml")
    b184.add_argument("--run-id", default=None)
    mode184 = b184.add_mutually_exclusive_group()
    mode184.add_argument("--dry-run", action="store_true", default=False)
    mode184.add_argument("--validate-only", action="store_true", default=False)
    b184.add_argument("--log-level", default="INFO")
    b184.add_argument("--debug", action="store_true", default=False)
    b185 = sub.add_parser(
        "stage18-feature-build",
        help="Build Stage 18.5 PIT fundamental features from the read-only Stage 18.4 DB",
    )
    b185.add_argument("--as-of-date", required=True)
    b185.add_argument("--upstream-run-id", default=None)
    b185.add_argument("--config", default="config/stage18_5.yml")
    b185.add_argument("--run-id", default=None)
    mode185 = b185.add_mutually_exclusive_group()
    mode185.add_argument("--dry-run", action="store_true", default=False)
    mode185.add_argument("--validate-only", action="store_true", default=False)
    b185.add_argument("--log-level", default="INFO")
    b185.add_argument("--debug", action="store_true", default=False)
    b186 = sub.add_parser(
        "stage18-finalize",
        help="Finalize Stage 18 quality, freeze exits, and authorize but do not start Stage 19",
    )
    b186.add_argument("--as-of-date", required=True)
    b186.add_argument("--upstream-run-id", default=None)
    b186.add_argument("--config", default="config/stage18_6.yml")
    b186.add_argument("--run-id", default=None)
    mode186 = b186.add_mutually_exclusive_group()
    mode186.add_argument("--dry-run", action="store_true", default=False)
    mode186.add_argument("--validate-only", action="store_true", default=False)
    b186.add_argument("--log-level", default="INFO")
    b186.add_argument("--debug", action="store_true", default=False)
    probe = sub.add_parser(
        "stage8-source-probe",
        help="Probe authoritative rule/status sources and write feasibility report",
    )
    probe.add_argument("--as-of-date", required=True)
    probe.add_argument(
        "--output-dir", default="reports/stage15_s14_fix/source_probe"
    )
    probe.add_argument("--run-id", default=None)
    probe.add_argument("--validate-only", action="store_true", default=False)
    probe.add_argument("--log-level", default="INFO")
    probe.add_argument(
        "--debug", action="store_true", default=False,
        help="Show a traceback for source-probe internal errors",
    )
    rbuild = sub.add_parser(
        "stage8-rules-build",
        help="Validate and publish the authoritative Stage 8 rule history",
    )
    rbuild.add_argument("--as-of-date", required=True)
    rbuild.add_argument("--start-date", default=None)
    rbuild.add_argument("--config", default="config/stage8_authoritative_rules.yml")
    rbuild.add_argument(
        "--dataset-dir",
        default="data/manual/stage8/limit_rules",
        help="Manual dataset directory used when --config does not exist",
    )
    rbuild.add_argument("--output-dir", default="database/stage15_s14_fix")
    rbuild.add_argument("--output-config", default=None)
    rbuild.add_argument("--base-config", default=None)
    rbuild.add_argument("--run-id", default=None)
    rbuild.add_argument("--log-level", default="INFO")
    rbuild.add_argument("--validate-only", action="store_true", default=False)
    rbuild.add_argument("--debug", action="store_true", default=False)
    sbuild = sub.add_parser(
        "stage8-status-build",
        help="Validate and publish the authoritative Stage 8 status history",
    )
    sbuild.add_argument("--as-of-date", required=True)
    sbuild.add_argument("--start-date", default=None)
    sbuild.add_argument("--config", default="config/stage8_authoritative_status.yml")
    sbuild.add_argument(
        "--dataset-dir",
        default="data/manual/stage8/security_status",
        help="Manual dataset directory used when --config does not exist",
    )
    sbuild.add_argument("--output-dir", default="database/stage15_s14_fix")
    sbuild.add_argument("--output-config", default=None)
    sbuild.add_argument("--base-config", default=None)
    sbuild.add_argument("--run-id", default=None)
    sbuild.add_argument("--log-level", default="INFO")
    sbuild.add_argument("--validate-only", action="store_true", default=False)
    sbuild.add_argument("--debug", action="store_true", default=False)
    preflight = sub.add_parser(
        "stage8-preflight",
        help="Read-only Stage 8 preflight using the authoritative configuration",
    )
    preflight.add_argument("--as-of-date", required=True)
    preflight.add_argument("--start-date", default=None)
    preflight.add_argument("--config", default="config/stage8_s14_fix.yml")
    preflight.add_argument(
        "--source-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    preflight.add_argument(
        "--output-database",
        default="database/stage15_s14_fix/stage8_authoritative.duckdb",
    )
    preflight.add_argument(
        "--rules-dataset-dir",
        default="data/manual/stage8/limit_rules",
    )
    preflight.add_argument(
        "--status-dataset-dir",
        default="data/manual/stage8/security_status",
    )
    preflight.add_argument("--log-level", default="INFO")
    preflight.add_argument("--debug", action="store_true", default=False)
    rebuild = sub.add_parser(
        "stage8-rebuild",
        help="Rebuild Stage 8 formal limit events with the authoritative dataset",
    )
    rebuild.add_argument("--as-of-date", required=True)
    rebuild.add_argument("--start-date", default=None)
    rebuild.add_argument("--config", default="config/stage8_s14_fix.yml")
    rebuild.add_argument(
        "--source-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    rebuild.add_argument("--output-database", default=None)
    rebuild.add_argument("--reports-dir", default=None)
    rebuild.add_argument("--run-id", default=None)
    rebuild.add_argument(
        "--rules-dataset-dir",
        default="data/manual/stage8/limit_rules",
    )
    rebuild.add_argument(
        "--status-dataset-dir",
        default="data/manual/stage8/security_status",
    )
    mode_rebuild = rebuild.add_mutually_exclusive_group()
    mode_rebuild.add_argument("--dry-run", action="store_true", default=False)
    mode_rebuild.add_argument("--validate-only", action="store_true", default=False)
    rebuild.add_argument("--log-level", default="INFO")
    rebuild.add_argument("--debug", action="store_true", default=False)
    rerun = sub.add_parser(
        "stage15-rerun",
        help="Re-run Stage 15 quality control against the authoritative Stage 8 DB",
    )
    rerun.add_argument("--as-of-date", required=True)
    rerun.add_argument("--config", default="config/stage15.yml")
    rerun.add_argument(
        "--input-database",
        default="database/akshare_data_test_stage5_repaired.duckdb",
    )
    rerun.add_argument("--stage8-database", default=None)
    rerun.add_argument("--baseline", default=None)
    rerun.add_argument("--reports-dir", default=None)
    rerun.add_argument("--output-database", default=None)
    rerun.add_argument("--run-id", default=None)
    rerun.add_argument("--cross-validation-symbols", nargs="+", default=None)
    mode_rerun = rerun.add_mutually_exclusive_group()
    mode_rerun.add_argument("--dry-run", action="store_true", default=False)
    mode_rerun.add_argument("--validate-only", action="store_true", default=False)
    rerun.add_argument("--log-level", default="INFO")
    rerun.add_argument("--debug", action="store_true", default=False)
    reverify = sub.add_parser(
        "stage15-s14-reverify",
        help="Produce the S15-14 manual cross-validation evidence and verdict",
    )
    reverify.add_argument("--as-of-date", required=True)
    reverify.add_argument(
        "--stage8-database",
        default="database/stage15_s14_fix/stage8_authoritative.duckdb",
    )
    reverify.add_argument(
        "--stage15-reports-dir",
        default="reports/stage15",
    )
    reverify.add_argument("--output-dir", default="database/stage15_s14_fix")
    reverify.add_argument("--run-id", default=None)
    reverify.add_argument("--log-level", default="INFO")
    reverify.add_argument("--validate-only", action="store_true", default=False)
    reverify.add_argument("--debug", action="store_true", default=False)
    stage14_commands = (
        "fetch-financial", "fetch-event-and-fund-flow", "clean", "load-database",
        "quality-check", "build-report", "run-all",
    )
    for command in stage14_commands:
        automation = sub.add_parser(command, help=f"Stage 14 automation: {command}")
        automation.add_argument("--start", default=None, help="YYYYMMDD; required by run-all")
        automation.add_argument("--end", default=None, help="YYYYMMDD; required by run-all")
        automation.add_argument("--config", default="config/stage14.yml")
        automation.add_argument("--run-id", default=None)
        automation.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
        automation.add_argument("--dry-run", action="store_true", default=False)
        automation.add_argument("--force", action="store_true", default=False)
        automation.add_argument("--only-symbol", default=None)
    args = parser.parse_args()
    if args.command == "doctor":
        sys.exit(_cmd_doctor(args))
    elif args.command == "show-config":
        sys.exit(_cmd_show_config(args))
    elif args.command == "smoke-test":
        sys.exit(_run_stage14_logged_single("smoke-test", args, _cmd_smoke_test))
    elif args.command == "network-check":
        sys.exit(_cmd_network_check(args))
    elif args.command == "fetch-market":
        sys.exit(_run_stage14_logged_single("fetch-market", args, _cmd_fetch_market))
    elif args.command == "fetch-fundamentals":
        sys.exit(_cmd_fetch_fundamentals(args))
    elif args.command == "build-stage5":
        sys.exit(_cmd_build_stage5(args))
    elif args.command == "validate-stage5":
        sys.exit(_cmd_validate_stage5(args))
    elif args.command == "repair-stage5-idempotency":
        sys.exit(_cmd_repair_stage5_idempotency(args))
    elif args.command == "build-stage6":
        if args.validate_only:
            args.feature_database_path = args.feature_database_path
            sys.exit(_cmd_validate_stage6(args))
        sys.exit(_cmd_build_stage6(args))
    elif args.command == "validate-stage6":
        sys.exit(_cmd_validate_stage6(args))
    elif args.command == "verify-stage6-idempotency-repair":
        sys.exit(_cmd_verify_stage6_idempotency_repair(args))
    elif args.command == "build-features":
        sys.exit(_run_stage14_logged_single("build-features", args, _cmd_build_features))
    elif args.command == "analyze-limit-events":
        sys.exit(_run_stage14_logged_single("analyze-limit-events", args, _cmd_analyze_limit_events))
    elif args.command == "analyze-style":
        sys.exit(_run_stage14_logged_single("analyze-style", args, _cmd_analyze_style))
    elif args.command == "analyze-fundamental":
        sys.exit(_cmd_analyze_fundamental(args))
    elif args.command == "validate-crypto":
        sys.exit(_cmd_validate_crypto(args))
    elif args.command == "analyze-stage12":
        sys.exit(_cmd_analyze_stage12(args))
    elif args.command == "present-stage13":
        sys.exit(_cmd_present_stage13(args))
    elif args.command == "quality-control":
        sys.exit(_cmd_quality_control(args))
    elif args.command == "final-report":
        sys.exit(_cmd_final_report(args))
    elif args.command == "collect-stage17":
        from .stage17_cli import command as stage17_command

        sys.exit(stage17_command(args))
    elif args.command == "stage18-interface-audit":
        from .stage18_cli import command as stage18_command

        sys.exit(stage18_command(args))
    elif args.command == "stage18-valuation-audit":
        from .stage18_valuation_cli import command as stage18_valuation_command

        sys.exit(stage18_valuation_command(args))
    elif args.command == "stage18-interface-reaudit":
        from .stage18_reaudit_cli import command as stage18_reaudit_command

        sys.exit(stage18_reaudit_command(args))
    elif args.command == "stage18-fundamental-collect":
        from .stage18_2_cli import command as stage18_2_command

        sys.exit(stage18_2_command(args))
    elif args.command == "stage18-fundamental-standardize":
        from .stage18_3_cli import command as stage18_3_command

        sys.exit(stage18_3_command(args))
    elif args.command == "stage18-db-load":
        from .stage18_4_cli import command as stage18_4_command

        sys.exit(stage18_4_command(args))
    elif args.command == "stage18-feature-build":
        from .stage18_5_cli import command as stage18_5_command

        sys.exit(stage18_5_command(args))
    elif args.command == "stage18-finalize":
        from .stage18_6_cli import command as stage18_6_command

        sys.exit(stage18_6_command(args))
    elif args.command == "stage8-source-probe":
        sys.exit(_cmd_stage8_source_probe(args))
    elif args.command == "stage8-rules-build":
        sys.exit(_cmd_stage8_rules_build(args))
    elif args.command == "stage8-status-build":
        sys.exit(_cmd_stage8_status_build(args))
    elif args.command == "stage8-preflight":
        sys.exit(_cmd_stage8_preflight(args))
    elif args.command == "stage8-rebuild":
        sys.exit(_cmd_stage8_rebuild(args))
    elif args.command == "stage15-rerun":
        sys.exit(_cmd_stage15_rerun(args))
    elif args.command == "stage15-s14-reverify":
        sys.exit(_cmd_stage15_s14_reverify(args))
    elif args.command in stage14_commands:
        sys.exit(_cmd_stage14(args))
    else:
        parser.print_help()
        sys.exit(0)

if __name__ == "__main__":
    main()

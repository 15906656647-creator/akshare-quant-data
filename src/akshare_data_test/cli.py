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
    elif args.command in stage14_commands:
        sys.exit(_cmd_stage14(args))
    else:
        parser.print_help()
        sys.exit(0)

if __name__ == "__main__":
    main()

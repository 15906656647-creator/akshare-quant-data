# -*- coding: utf-8 -*-
"""Stage 2 smoke-test orchestration."""
from __future__ import annotations
import csv
import json
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from akshare_data_test.adapters.akshare_probe import ProbeResult, probe_function
from akshare_data_test.paths import config_dir

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "run_id","probe_id","category","interface_name","function_exists",
    "function_signature","parameters_json","started_at","finished_at",
    "elapsed_seconds","attempt_count","akshare_version","status",
    "capability_result","row_count","column_count","schema_hash",
    "columns_json","dtypes_json","required_columns_present",
    "missing_required_columns_json","coverage_start","coverage_end",
    "sample_path","error_type","exception_class","root_exception_class",
    "error_message","root_error_message","target_host",
    "retry_reason","proxy_detected","http_status_code","pool_date",
    "pool_date_source","notes",
]

def load_interfaces_config():
    path = config_dir() / "interfaces.yml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _probe_to_csv_row(pr):
    """Convert ProbeResult to dict for CSV writing."""
    return {
        "run_id": pr.run_id,
        "probe_id": pr.probe_id,
        "category": pr.category,
        "interface_name": pr.interface_name,
        "function_exists": pr.function_exists,
        "function_signature": pr.function_signature,
        "parameters_json": pr.parameters_json,
        "started_at": pr.started_at,
        "finished_at": pr.finished_at,
        "elapsed_seconds": pr.elapsed_seconds,
        "attempt_count": pr.attempt_count,
        "akshare_version": pr.akshare_version,
        "status": pr.status,
        "capability_result": pr.capability_result,
        "row_count": pr.row_count,
        "column_count": pr.column_count,
        "schema_hash": pr.schema_hash,
        "columns_json": pr.columns_json,
        "dtypes_json": pr.dtypes_json,
        "required_columns_present": pr.required_columns_present,
        "missing_required_columns_json": pr.missing_required_columns_json,
        "coverage_start": pr.coverage_start,
        "coverage_end": pr.coverage_end,
        "sample_path": pr.sample_path,
        "error_type": pr.error_type,
        "exception_class": pr.exception_class,
        "root_exception_class": pr.root_exception_class,
        "error_message": pr.error_message,
        "root_error_message": pr.root_error_message,
        "target_host": pr.target_host,
        "retry_reason": pr.retry_reason,
        "proxy_detected": pr.proxy_detected,
        "http_status_code": pr.http_status_code,
        "pool_date": pr.pool_date,
        "pool_date_source": pr.pool_date_source,
        "notes": pr.notes,
    }


def _resolve_pool_date_from_raw_probe(pr: ProbeResult, as_of_date: date) -> str | None:
    """Use only a successful raw-price date not later than the business date."""
    if pr.probe_id != "stock_daily_raw" or pr.status != "success" or not pr.coverage_end:
        return None
    try:
        candidate = date.fromisoformat(pr.coverage_end)
    except ValueError:
        return None
    if candidate <= as_of_date:
        return candidate.isoformat()
    return None

def _determine_status(results):
    if len(results) == 0:
        return "BLOCKED"
    sm = {pr.probe_id: pr.status for pr in results}
    core_ok = all(
        sm.get(p, "missing") == "success"
        for p in ("stock_daily_qfq", "stock_daily_raw", "stock_spot")
    )
    fin_ok = any(
        sm.get(p, "missing") == "success"
        for p in ("financial_abstract", "financial_indicator",
                 "balance_sheet_report", "profit_sheet_report",
                 "cashflow_sheet_report")
    )
    if core_ok and fin_ok:
        return "PASS"
    elif core_ok:
        return "PARTIAL"
    return "BLOCKED"

def run_smoke_tests(
    as_of_date,
    sample_symbol,
    output_path=None,
    evidence_dir=None,
    max_sample_rows=20,
    only_probes=None,
    pool_date=None,
    strict=False,
    run_id=None,
):
    run_id = run_id or str(uuid.uuid4())
    uuid.UUID(run_id)
    logger.info("run_id=%s as_of_date=%s", run_id, str(as_of_date))
    cfg = load_interfaces_config()
    probe_cfgs = cfg["probes"]
    if only_probes:
        probe_cfgs = [p for p in probe_cfgs if p["probe_id"] in only_probes]
    pool_date_resolved = pool_date
    pool_date_source = "cli" if pool_date else "unresolved"
    results = []
    spot_done = False
    limit_up_done = False
    limit_down_done = False
    for pc in probe_cfgs:
        pid = pc["probe_id"]
        if not pc.get("enabled", True):
            continue
        if pc["scope"] == "full_market":
            if pid == "stock_spot" and spot_done:
                continue
            elif pid == "limit_up_pool" and limit_up_done:
                continue
            elif pid == "limit_down_pool" and limit_down_done:
                continue
        iface = pc.get("interface_name", "?")
        logger.info("Probing [%s] %s...", pid, iface)
        pr = probe_function(
            pc,
            run_id,
            as_of_date,
            pool_date_resolved,
            pool_date_source=pool_date_source,
            max_sample_rows=max_sample_rows,
        )
        results.append(pr)
        logger.info("  -> status=%s rows=%s cols=%s", pr.status, pr.row_count, pr.column_count)
        if pc["scope"] == "full_market":
            if pid == "stock_spot":
                spot_done = True
            elif pid == "limit_up_pool":
                limit_up_done = True
            elif pid == "limit_down_pool":
                limit_down_done = True
        if pid == "stock_daily_raw" and pool_date_resolved is None:
            pool_date_resolved = _resolve_pool_date_from_raw_probe(pr, as_of_date)
            if pool_date_resolved:
                pool_date_source = "stock_daily_raw"
                logger.info(
                    "Resolved pool_date=%s source=stock_daily_raw",
                    pool_date_resolved,
                )
    if evidence_dir:
        ed = Path(evidence_dir) / run_id
        ed.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "as_of_date": str(as_of_date),
            "sample_symbol": sample_symbol,
            "probe_count": len(results),
            "status_counts": {},
            "pool_date": pool_date_resolved or "",
            "pool_date_source": pool_date_source,
            "results": [],
        }
        for pr in results:
            if pr.columns_json:
                sp = ed / (pr.probe_id + ".schema.json")
                sd = {
                    "columns": json.loads(pr.columns_json),
                    "dtypes": json.loads(pr.dtypes_json),
                    "schema_hash": pr.schema_hash,
                }
                sp.write_text(json.dumps(sd, indent=2, ensure_ascii=False, default=str), "utf-8")
            if pr.status == "success" and pr.sample_records_json:
                sample_path = ed / (pr.probe_id + ".sample.json")
                sample_path.write_text(
                    json.dumps(
                        json.loads(pr.sample_records_json),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                pr.sample_path = str(sample_path)
            manifest["results"].append(
                {
                    "probe_id": pr.probe_id,
                    "status": pr.status,
                    "error_type": pr.error_type,
                    "row_count": pr.row_count,
                    "column_count": pr.column_count,
                    "attempt_count": pr.attempt_count,
                    "pool_date": pr.pool_date,
                    "pool_date_source": pr.pool_date_source,
                    "target_host": pr.target_host,
                    "sample_path": pr.sample_path,
                }
            )
        sc = {}
        for pr in results:
            sc[pr.status] = sc.get(pr.status, 0) + 1
        manifest["status_counts"] = sc
        (ed / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), "utf-8")
        logger.info("Evidence saved: %s", ed)
    if output_path:
        op = Path(output_path)
        op.parent.mkdir(parents=True, exist_ok=True)
        with open(op, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for pr in results:
                writer.writerow(_probe_to_csv_row(pr))
        logger.info("CSV: %s", op)
    overall = _determine_status(results)
    return results, run_id, overall

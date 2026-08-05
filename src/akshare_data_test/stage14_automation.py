"""Stage 14 command orchestration over the existing Stage 2-13 CLI.

The orchestrator deliberately does not duplicate collectors or analytics.  It
executes the established commands, records their real exit codes, and stops at
the first failure.
"""
from __future__ import annotations

import importlib.metadata
import csv
import json
import platform
import os
import subprocess
import sys
import time
import uuid
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


TASK_ORDER = (
    "smoke-test",
    "fetch-market",
    "fetch-financial",
    "fetch-event-and-fund-flow",
    "clean",
    "load-database",
    "build-features",
    "analyze-limit-events",
    "analyze-style",
    "quality-check",
    "build-report",
)


def generate_run_id() -> str:
    """Return a path-safe identifier accepted by all existing stage builders."""
    return str(uuid.uuid4())


def parse_compact_date(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYYMMDD") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"invalid date {value!r}; expected YYYYMMDD")
    return parsed


def validate_date_range(start: str, end: str) -> tuple[str, str]:
    start_date = parse_compact_date(start)
    end_date = parse_compact_date(end)
    if start_date > end_date:
        raise ValueError("--start must be earlier than or equal to --end")
    return start_date.date().isoformat(), end_date.date().isoformat()


def load_stage14_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"Stage 14 config does not exist: {path}")
    import yaml
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Stage 14 config must be a mapping: {path}")
    configured = tuple(payload.get("task_order", ()))
    if configured != TASK_ORDER:
        raise ValueError("Stage 14 config task_order does not match the frozen dependency order")
    return payload


@dataclass
class TaskStatus:
    run_id: str
    pipeline_name: str
    task_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    elapsed_seconds: float
    parameters: dict[str, object]
    input_start_date: str
    input_end_date: str
    row_count_read: int | None = None
    row_count_written: int | None = None
    file_count_written: int | None = None
    warning_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    akshare_version: str = "unavailable"
    python_version: str = platform.python_version()
    git_commit: str = "unavailable"


@dataclass(frozen=True)
class PipelineContext:
    root: Path
    run_id: str
    start_date: str
    end_date: str
    log_level: str = "INFO"
    force: bool = False
    only_symbol: str | None = None
    run_all: bool = False


Executor = Callable[[str, PipelineContext], tuple[int, str, str]]


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=False, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "unavailable"


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _task_arguments(task: str, context: PipelineContext) -> list[str] | None:
    end = context.end_date
    run_id = context.run_id
    root = context.root
    stage14_db = f"database/stage14/{run_id}/akshare_data.duckdb"
    feature_db = f"database/stage14/{run_id}/features.duckdb"
    limit_db = f"database/stage14/{run_id}/limit_events.duckdb"
    style_db = f"database/stage14/{run_id}/style.duckdb"
    common = ["--log-level", context.log_level]
    symbol = ["--only-symbol", context.only_symbol] if context.only_symbol else []
    mapping: dict[str, list[str] | None] = {
        "smoke-test": ["smoke-test", "--as-of-date", end, "--run-id", run_id, *common],
        "fetch-market": [
            "fetch-market", "--as-of-date", end, "--start-date", context.start_date,
            "--run-id", run_id, *symbol, *common,
        ],
        # Stage 4's established collector intentionally fetches both financial
        # and fund-flow interfaces into one immutable 96-file manifest.
        "fetch-financial": [
            "fetch-fundamentals", "--as-of-date", end, "--run-id", run_id,
            *symbol, *common,
        ],
        # In run-all this interface is already part of the combined Stage 4
        # manifest. As a standalone recovery command it must do real work.
        "fetch-event-and-fund-flow": None if context.run_all else [
            "fetch-fundamentals", "--as-of-date", end, "--run-id", run_id,
            "--only-interface", "individual_fund_flow", *symbol, *common,
        ],
        # Stage 5 is an intentionally atomic clean + database publication step.
        "clean": [
            "build-stage5", "--as-of-date", end, "--market-run-id", run_id,
            "--fundamental-run-id", run_id, "--transform-run-id", run_id,
            "--database-path", stage14_db, *common,
        ],
        # Stage 5 cannot safely split Clean publication from its database
        # transaction. Standalone load-database reuses that atomic builder.
        "load-database": None if context.run_all else [
            "build-stage5", "--as-of-date", end, "--market-run-id", run_id,
            "--fundamental-run-id", run_id, "--transform-run-id", run_id,
            "--database-path", stage14_db, *common,
        ],
        "build-features": [
            "build-features", "--as-of-date", end, "--source-database", stage14_db,
            "--output-database", feature_db, "--run-id", run_id, *common,
        ],
        "analyze-limit-events": [
            "analyze-limit-events", "--as-of-date", end, "--start-date", context.start_date,
            "--source-database", stage14_db, "--output-database", limit_db,
            "--run-id", run_id, *common,
        ],
        "analyze-style": [
            "analyze-style", "--as-of-date", end, "--start-date", context.start_date,
            "--input-database", stage14_db, "--output-database", style_db,
            "--stage8-database", limit_db, "--run-id", run_id, *common,
        ],
        "quality-check": [
            "validate-stage5", "--as-of-date", end, "--database-path", stage14_db,
            *common,
        ],
        "build-report": [
            "present-stage13", "--as-of-date", end, "--input-database", stage14_db,
            "--run-id", run_id, *common,
        ],
    }
    if task not in mapping:
        raise ValueError(f"unknown Stage 14 task: {task}")
    args = mapping[task]
    if args is None:
        return None
    return [sys.executable, str(root / "run_pipeline.py"), *args]


def subprocess_executor(task: str, context: PipelineContext) -> tuple[int, str, str]:
    arguments = _task_arguments(task, context)
    if arguments is None:
        reason = (
            "covered by fetch-financial (the existing Stage 4 collector publishes one combined manifest)"
            if task == "fetch-event-and-fund-flow"
            else "covered atomically by clean (the existing Stage 5 builder cleans and loads together)"
        )
        return 0, reason, "SKIPPED"
    (context.root / "database" / "stage14" / context.run_id).mkdir(
        parents=True, exist_ok=True
    )
    result = subprocess.run(
        arguments, cwd=context.root, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
        env={**os.environ, "AKSHARE_STAGE14_CHILD": "1"},
    )
    return result.returncode, result.stdout, result.stderr


def execute_pipeline(
    tasks: Sequence[str], context: PipelineContext, *, executor: Executor = subprocess_executor,
    dry_run: bool = False,
) -> tuple[list[TaskStatus], int]:
    """Execute tasks in order and persist status after every transition."""
    for task in tasks:
        if task not in TASK_ORDER:
            raise ValueError(f"unknown Stage 14 task: {task}")
    if dry_run:
        return [
            TaskStatus(
                run_id=context.run_id, pipeline_name="stage14", task_name=task,
                status="pending", started_at=None, finished_at=None, elapsed_seconds=0.0,
                parameters={"dry_run": True, "force": context.force},
                input_start_date=context.start_date, input_end_date=context.end_date,
            ) for task in tasks
        ], 0

    log_dir = context.root / "logs" / context.run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pipeline.log"
    status_path = log_dir / "task_status.json"
    versions = {"akshare": _version("akshare"), "git": _git_commit(context.root)}
    statuses: list[TaskStatus] = []
    failure_exit_code = 1

    def persist() -> None:
        _atomic_json(status_path, {
            "run_id": context.run_id, "pipeline_name": "stage14",
            "status": "failed" if any(x.status == "failed" for x in statuses)
            else "success" if statuses and all(x.status in {"success", "skipped"} for x in statuses)
            else "running",
            "tasks": [asdict(item) for item in statuses],
        })

    with log_path.open("a", encoding="utf-8") as log:
        for task in tasks:
            started = datetime.now(timezone.utc)
            record = TaskStatus(
                run_id=context.run_id, pipeline_name="stage14", task_name=task,
                status="running", started_at=started.isoformat(), finished_at=None,
                elapsed_seconds=0.0,
                parameters={
                    "force": context.force,
                    "only_symbol": context.only_symbol,
                    "run_all": context.run_all,
                },
                input_start_date=context.start_date, input_end_date=context.end_date,
                akshare_version=versions["akshare"], git_commit=versions["git"],
            )
            statuses.append(record); persist()
            log.write(f"{record.started_at} [INFO] task={task} status=running run_id={context.run_id}\n")
            tick = time.perf_counter()
            try:
                code, stdout, stderr = executor(task, context)
                record.elapsed_seconds = round(time.perf_counter() - tick, 6)
                record.finished_at = datetime.now(timezone.utc).isoformat()
                if stderr == "SKIPPED":
                    record.status = "skipped"
                    record.error_message = stdout
                elif code == 0:
                    record.status = "success"
                else:
                    record.status = "failed"
                    failure_exit_code = code
                    record.error_type = "TaskExitError"
                    record.error_message = (stderr or stdout or f"exit code {code}")[-2000:]
                if stdout:
                    log.write(stdout.rstrip() + "\n")
                if stderr and stderr != "SKIPPED":
                    log.write(stderr.rstrip() + "\n")
                log.write(f"{record.finished_at} [INFO] task={task} status={record.status} exit_code={code}\n")
            except Exception as exc:
                record.elapsed_seconds = round(time.perf_counter() - tick, 6)
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.status = "failed"; record.error_type = type(exc).__name__
                record.error_message = str(exc)[:2000]
                log.write(f"{record.finished_at} [ERROR] task={task} {type(exc).__name__}: {exc}\n")
                log.write(traceback.format_exc())
            persist()
            if record.status == "failed":
                failed_dir = context.root / "reports" / "run_status"
                failed_dir.mkdir(parents=True, exist_ok=True)
                failed_path = failed_dir / f"{context.run_id}_failed_items.csv"
                with failed_path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=(
                        "run_id", "task_name", "interface_name", "symbol", "parameters",
                        "error_type", "error_message", "retry_count", "status",
                    ))
                    writer.writeheader()
                    writer.writerow({
                        "run_id": context.run_id, "task_name": task,
                        "interface_name": "", "symbol": context.only_symbol or "",
                        "parameters": json.dumps(record.parameters, ensure_ascii=False),
                        "error_type": record.error_type or "",
                        "error_message": record.error_message or "",
                        "retry_count": 0, "status": "failed",
                    })
                # The executor is not called for downstream work, but every
                # planned step remains explicit in the structured run record.
                remaining = tasks[len(statuses):]
                for skipped_task in remaining:
                    statuses.append(TaskStatus(
                        run_id=context.run_id,
                        pipeline_name="stage14",
                        task_name=skipped_task,
                        status="skipped",
                        started_at=None,
                        finished_at=None,
                        elapsed_seconds=0.0,
                        parameters={
                            "force": context.force,
                            "only_symbol": context.only_symbol,
                            "run_all": context.run_all,
                        },
                        input_start_date=context.start_date,
                        input_end_date=context.end_date,
                        error_type="UpstreamTaskFailed",
                        error_message=f"not executed because {task} failed",
                        akshare_version=versions["akshare"],
                        git_commit=versions["git"],
                    ))
                persist()
                return statuses, failure_exit_code
    return statuses, 0


def render_plan(tasks: Sequence[str], context: PipelineContext) -> str:
    lines = [f"Stage 14 dry-run: run_id={context.run_id}"]
    lines.extend(f"  {index}. {task}" for index, task in enumerate(tasks, 1))
    return "\n".join(lines)

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from akshare_data_test.stage14_automation import (
    TASK_ORDER,
    PipelineContext,
    execute_pipeline,
    generate_run_id,
    load_stage14_config,
    validate_date_range,
    _task_arguments,
)


def context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        root=tmp_path,
        run_id=str(uuid.uuid4()),
        start_date="2025-01-01",
        end_date="2025-01-31",
    )


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2025-01-01", "20250131", "expected YYYYMMDD"),
        ("20250230", "20250301", "expected YYYYMMDD"),
        ("20250201", "20250131", "--start must be earlier"),
    ],
)
def test_date_range_validation(start, end, message):
    with pytest.raises(ValueError, match=message):
        validate_date_range(start, end)


def test_valid_date_range_is_normalized():
    assert validate_date_range("20250101", "20250131") == (
        "2025-01-01", "2025-01-31"
    )


def test_run_id_is_unique_uuid():
    first, second = generate_run_id(), generate_run_id()
    assert first != second
    assert str(uuid.UUID(first)) == first


def test_run_all_order_and_shared_run_id(tmp_path):
    seen = []

    def executor(task, pipeline_context):
        seen.append((task, pipeline_context.run_id))
        if task in {"fetch-event-and-fund-flow", "load-database"}:
            return 0, "covered", "SKIPPED"
        return 0, "ok", ""

    ctx = context(tmp_path)
    statuses, code = execute_pipeline(TASK_ORDER, ctx, executor=executor)
    assert code == 0
    assert [item[0] for item in seen] == list(TASK_ORDER)
    assert {item[1] for item in seen} == {ctx.run_id}
    assert {item.run_id for item in statuses} == {ctx.run_id}
    assert [item.status for item in statuses].count("skipped") == 2


def test_failure_stops_following_tasks_and_returns_nonzero(tmp_path):
    seen = []

    def executor(task, _context):
        seen.append(task)
        return (7, "", "simulated failure") if task == "fetch-market" else (0, "", "")

    ctx = context(tmp_path)
    statuses, code = execute_pipeline(TASK_ORDER, ctx, executor=executor)
    assert code == 7
    assert seen == ["smoke-test", "fetch-market"]
    assert statuses[1].status == "failed"
    assert all(item.status == "skipped" for item in statuses[2:])
    assert statuses[2].error_type == "UpstreamTaskFailed"
    failed = tmp_path / "reports" / "run_status" / f"{ctx.run_id}_failed_items.csv"
    assert failed.is_file()


def test_status_file_records_start_end_and_failure(tmp_path):
    ctx = context(tmp_path)

    def boom(_task, _context):
        raise RuntimeError("fault injection")

    statuses, code = execute_pipeline(["clean"], ctx, executor=boom)
    payload = json.loads(
        (tmp_path / "logs" / ctx.run_id / "task_status.json").read_text("utf-8")
    )
    assert code == 1
    assert statuses[0].error_type == "RuntimeError"
    assert payload["status"] == "failed"
    assert payload["tasks"][0]["started_at"]
    assert payload["tasks"][0]["finished_at"]
    assert "Traceback" in (tmp_path / "logs" / ctx.run_id / "pipeline.log").read_text("utf-8")


def test_dry_run_does_not_call_executor_or_write(tmp_path):
    ctx = context(tmp_path)

    def forbidden(*_args):
        raise AssertionError("executor must not run")

    statuses, code = execute_pipeline(TASK_ORDER, ctx, executor=forbidden, dry_run=True)
    assert code == 0
    assert all(item.status == "pending" for item in statuses)
    assert not (tmp_path / "logs").exists()
    assert not (tmp_path / "database").exists()
    assert not (tmp_path / "data").exists()


def test_config_freezes_order(tmp_path):
    config = tmp_path / "stage14.yml"
    config.write_text(
        "task_order:\n" + "".join(f"  - {task}\n" for task in TASK_ORDER),
        encoding="utf-8",
    )
    assert tuple(load_stage14_config(config)["task_order"]) == TASK_ORDER


def test_invalid_config_order_is_rejected(tmp_path):
    config = tmp_path / "stage14.yml"
    config.write_text("task_order: [clean, smoke-test]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dependency order"):
        load_stage14_config(config)


def test_combined_steps_are_skipped_only_inside_run_all(tmp_path):
    standalone = context(tmp_path)
    assert "--only-interface" in _task_arguments(
        "fetch-event-and-fund-flow", standalone
    )
    assert _task_arguments("load-database", standalone) is not None

    combined = PipelineContext(**{**standalone.__dict__, "run_all": True})
    assert _task_arguments("fetch-event-and-fund-flow", combined) is None
    assert _task_arguments("load-database", combined) is None

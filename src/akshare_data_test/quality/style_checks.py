"""Measured Stage 9 quality checks and persisted-artifact verification."""
from __future__ import annotations

import json
import math
from numbers import Number
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ..storage.style_repository import QUALITY_COLUMNS


ALLOWED_STYLES = {
    "温和箱体型", "高波动震荡型", "放量冲击型", "低活跃盘整型",
    "趋势型", "数据不足", "未分类或混合型",
}

FLOAT_TOLERANCE = 1e-12
PROFILE_COMPARE_COLUMNS = [
    "run_id", "symbol", "as_of_date", "style_label", "confidence",
    "secondary_style_label", "secondary_confidence", "evidence_count",
    "conflicting_evidence_count", "data_coverage", "explanation",
    "model_version", "config_version", "publication_status",
]
FEATURE_COMPARE_COLUMNS = [
    "run_id", "symbol", "as_of_date", "window_size", "box_width",
    "normalized_slope", "regression_r_squared", "atr_ratio", "volatility",
    "volume_spike_frequency", "false_breakout_count", "data_quality_status",
]
QUALITY_COMPARE_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "message",
]
DISTRIBUTION_COMPARE_COLUMNS = [
    "run_id", "style_label", "count", "average_confidence",
]
RISK_STATEMENT = (
    "风格标签只描述横盘震荡风格、量价行为特征、疑似洗盘特征和疑似主力行为特征，\n"
    "不代表确定的主力行为；风格标签不是投资建议，也不构成投资建议。"
)


def render_stage9_validation(report: dict[str, object]) -> str:
    """Render the canonical Markdown whose complete content is write-checked."""
    distribution = report.get("style_distribution") or {}
    labels = "\n".join(
        f"- {label}: {count}" for label, count in sorted(distribution.items())
    ) or "- 无"
    blockers = report.get("blocking_reasons") or []
    blocker_text = ", ".join(str(value) for value in blockers) or "无"
    return f"""# 阶段 9 横盘震荡与疑似洗盘风格分析验证

- run_id：`{report['run_id']}`
- run_status：**{report['run_status']}**
- publication_status：`{report['publication_status']}`
- output_type：`{report['output_type']}`（fixture/implementation validation 不是正式结论）
- 输入：`{report['input_database']}` / `{report['input_table']}`
- 价格口径：`qfq`
- 截止日期：{report['as_of_date']}
- 窗口：20/40/60 个有效交易日
- Stage 8 publication_status：`{report['stage8_publication_status']}`
- Stage 8 正式事件是否使用：{report['stage8_formal_events_used']}
- 特征行数：{report['feature_row_count']}
- 风格档案行数：{report['profile_row_count']}

## 风格分布

{labels}

## 质量门禁

- PASS：{report['quality_passed']}
- FAIL：{report['quality_failed']}
- 阻塞项：{blocker_text}

## 口径声明

Stage 8 为 blocked 或不可用时，正式事件特征保持 null/not_available，绝不填充为 0；
candidate、proxy、gap_proxy、unresolved 分开保存且不作为正式涨跌停统计。
{RISK_STATEMENT}
"""


def _normal_scalar(value: object) -> object:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Number) and not isinstance(value, bool):
        number = float(value)
        if math.isnan(number):
            return None
        if not math.isfinite(number):
            return ("non_finite", str(number))
        return number
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _values_equal(left: object, right: object) -> bool:
    left_value = _normal_scalar(left)
    right_value = _normal_scalar(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    if isinstance(left_value, Number) and isinstance(right_value, Number):
        return math.isclose(
            float(left_value), float(right_value), rel_tol=0, abs_tol=FLOAT_TOLERANCE
        )
    return left_value == right_value


def _compare_frames(
    database: pd.DataFrame,
    artifact: pd.DataFrame,
    *,
    columns: list[str],
    sort_by: list[str],
    date_columns: tuple[str, ...] = (),
) -> tuple[bool, str]:
    missing_database = sorted(set(columns).difference(database.columns))
    missing_artifact = sorted(set(columns).difference(artifact.columns))
    if missing_database or missing_artifact:
        return False, f"missing_db={missing_database};missing_artifact={missing_artifact}"
    left = database[columns].copy()
    right = artifact[columns].copy()
    for frame in (left, right):
        for column in date_columns:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            frame[column] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), None)
        if "symbol" in frame:
            frame["symbol"] = frame["symbol"].astype("string").str.zfill(6)
    left = left.sort_values(sort_by, kind="mergesort", na_position="first").reset_index(drop=True)
    right = right.sort_values(sort_by, kind="mergesort", na_position="first").reset_index(drop=True)
    if len(left) != len(right):
        return False, f"row_count={len(left)}/{len(right)}"
    for index in range(len(left)):
        for column in columns:
            if not _values_equal(left.at[index, column], right.at[index, column]):
                return False, f"mismatch_row={index};column={column}"
    return True, f"rows={len(left)}"


def _feature_projection(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "realized_volatility" in result:
        result["volatility"] = result["realized_volatility"]
    false_columns = {
        "confirmed_false_breakout_up_count",
        "confirmed_false_breakout_down_count",
    }
    if false_columns.issubset(result.columns):
        result["false_breakout_count"] = (
            pd.to_numeric(result["confirmed_false_breakout_up_count"], errors="coerce")
            + pd.to_numeric(result["confirmed_false_breakout_down_count"], errors="coerce")
        )
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(run_id, name, passed, observed, expected, checked_at, *, severity="ERROR", numerator=None, denominator=None, message=""):
    return {
        "run_id": run_id, "check_name": name, "severity": severity,
        "status": "PASS" if passed else "FAIL", "observed_value": str(observed),
        "expected_value": str(expected), "numerator": numerator,
        "denominator": denominator, "message": message, "checked_at": checked_at,
    }


def run_stage9_quality_checks(
    daily: pd.DataFrame, features: pd.DataFrame, profiles: pd.DataFrame, *,
    run_id: str, as_of_date: pd.Timestamp, expected_symbols: list[str],
    expected_windows: list[int], config_hash: str, expected_config_hash: str,
    checked_at: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    add = lambda name, passed, observed, expected, **kw: rows.append(
        _row(run_id, name, passed, observed, expected, checked_at, **kw)
    )
    required = {"symbol", "trade_date", "adjust_type", "open", "high", "low", "close", "volume_share", "amount_cny", "turnover_rate"}
    routes = set(daily["adjust_type"].dropna().astype(str).str.lower()) if "adjust_type" in daily else set()
    add("input_adjust_type_valid", routes == {"qfq"}, sorted(routes), ["qfq"])
    missing = sorted(required.difference(daily.columns))
    add("input_schema_complete", not missing, missing, [])
    duplicates = int(daily.duplicated(["symbol", "trade_date", "adjust_type"]).sum()) if not missing else -1
    add("input_primary_key_unique", duplicates == 0, duplicates, 0)
    actual_symbols = set(daily["symbol"].astype(str).str.zfill(6))
    add("symbol_coverage_complete", actual_symbols == set(expected_symbols), sorted(actual_symbols), sorted(expected_symbols), numerator=len(actual_symbols & set(expected_symbols)), denominator=len(expected_symbols))
    expected_rows = len(expected_symbols) * len(expected_windows)
    sufficient = int(features["data_quality_status"].eq("pass").sum())
    add("window_observation_sufficient", sufficient == expected_rows, sufficient, expected_rows, severity="WARNING", numerator=sufficient, denominator=expected_rows)
    date_order = (
        pd.to_datetime(features["window_start"], errors="coerce")
        <= pd.to_datetime(features["window_end"], errors="coerce")
    ) | features["window_start"].isna()
    invalid_order = int((~date_order).sum())
    add("window_date_order_valid", invalid_order == 0, invalid_order, 0)
    future = int((pd.to_datetime(daily["trade_date"]) > pd.Timestamp(as_of_date)).sum())
    add("no_future_data_leakage", future == 0, future, 0)
    numeric = features.select_dtypes(include=[np.number])
    infinite = int(np.isinf(numeric.to_numpy(dtype=float)).sum())
    add("feature_value_finite", infinite == 0, infinite, 0)
    passed_features = features.loc[features["data_quality_status"].eq("pass")]
    invalid_box = int(((passed_features["rolling_low"] <= 0) | (passed_features["rolling_high"] < passed_features["rolling_low"]) | (passed_features["box_width"] < 0)).sum())
    add("box_bounds_valid", invalid_box == 0, invalid_box, 0)
    bad_confidence = int((~profiles["confidence"].between(0, 1) | ~profiles["secondary_confidence"].between(0, 1)).sum())
    add("confidence_range_valid", bad_confidence == 0, bad_confidence, 0)
    invalid_styles = sorted(set(profiles["style_label"]).difference(ALLOWED_STYLES))
    add("style_label_valid", not invalid_styles, invalid_styles, [])
    invalid_explanation = int((profiles["explanation"].str.len().lt(40) | profiles["explanation"].str.contains("主力正在|庄家操纵|买入信号", regex=True)).sum())
    add("explanation_complete", invalid_explanation == 0, invalid_explanation, 0)
    primary_window = int(profiles["primary_window"].iloc[0]) if not profiles.empty else (40 if 40 in expected_windows else expected_windows[0])
    merged = profiles.merge(features.loc[features.window_size.eq(primary_window), ["symbol", "data_quality_status"]], on="symbol", how="left")
    invalid_insufficient = int((merged["data_quality_status"].ne("pass") & merged["style_label"].ne("数据不足")).sum())
    add("insufficient_history_not_classified", invalid_insufficient == 0, invalid_insufficient, 0)
    blocked = features["stage8_publication_status"].eq("blocked")
    leaked = int(features.loc[blocked, "stage8_formal_event_frequency"].notna().sum())
    add("stage8_blocked_not_treated_as_zero", leaked == 0, leaked, 0)
    add("feature_profile_row_count_consistent", len(features) == expected_rows and len(profiles) == len(expected_symbols), f"{len(features)}/{len(profiles)}", f"{expected_rows}/{len(expected_symbols)}")
    run_ids = set(features["run_id"].astype(str)) | set(profiles["run_id"].astype(str))
    add("run_id_consistent", run_ids == {run_id}, sorted(run_ids), [run_id])
    add("configuration_hash_consistent", config_hash == expected_config_hash, config_hash, expected_config_hash)
    usable = int(profiles["style_label"].ne("数据不足").sum())
    add("usable_profile_exists", usable > 0, usable, ">0", numerator=usable, denominator=len(profiles))
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def run_stage9_post_write_checks(
    database_path: Path, reports_dir: Path, *, run_id: str,
    expected_feature_rows: int, expected_profile_rows: int,
    expected_config_hash: str, checked_at: pd.Timestamp,
) -> pd.DataFrame:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        db_features = connection.execute(
            "SELECT * FROM feature.stage9_style_feature WHERE run_id=?", [run_id]
        ).fetchdf()
        db_profiles = connection.execute(
            "SELECT * FROM analysis.stage9_style_profile WHERE run_id=?", [run_id]
        ).fetchdf()
        db_quality = connection.execute(
            "SELECT * FROM quality.stage9_quality_result WHERE run_id=?", [run_id]
        ).fetchdf()
        audit_frame = connection.execute(
            "SELECT * FROM audit.stage9_run WHERE run_id=?", [run_id]
        ).fetchdf()
        audit_runs = {
            row[0] for row in connection.execute("SELECT run_id FROM audit.stage9_run").fetchall()
        }
        feature_runs = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT run_id FROM feature.stage9_style_feature"
            ).fetchall()
        }
        profile_runs = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT run_id FROM analysis.stage9_style_profile"
            ).fetchall()
        }
        quality_runs = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT run_id FROM quality.stage9_quality_result"
            ).fetchall()
        }
        current_view_runs = {row[0] for row in connection.execute("SELECT DISTINCT run_id FROM analysis.v_latest_stage9_style_profile").fetchall()}
        latest_success = connection.execute(
            "SELECT run_id FROM audit.stage9_run WHERE run_status='PASS' "
            "ORDER BY created_at DESC,run_id DESC LIMIT 1"
        ).fetchone()
    feature_count = len(db_features)
    profile_count = len(db_profiles)
    artifact_match = False
    observed = "missing"
    try:
        manifest = json.loads((reports_dir / "stage9_run.json").read_text(encoding="utf-8"))
        csv_profiles = pd.read_csv(reports_dir / "stage9_style_profile.csv", dtype={"symbol": str, "run_id": str})
        csv_features = pd.read_csv(reports_dir / "stage9_style_feature_sample.csv", dtype={"symbol": str, "run_id": str})
        csv_quality = pd.read_csv(
            reports_dir / "stage9_data_quality.csv",
            dtype={"run_id": str},
            keep_default_na=False,
        )
        csv_distribution = pd.read_csv(
            reports_dir / "stage9_style_distribution.csv", dtype={"run_id": str}
        )
        markdown = (reports_dir / "stage9_validation.md").read_text(encoding="utf-8")
        profile_match, profile_detail = _compare_frames(
            db_profiles, csv_profiles, columns=PROFILE_COMPARE_COLUMNS,
            sort_by=["symbol", "as_of_date"], date_columns=("as_of_date",),
        )
        feature_match, feature_detail = _compare_frames(
            _feature_projection(db_features), _feature_projection(csv_features),
            columns=FEATURE_COMPARE_COLUMNS,
            sort_by=["symbol", "as_of_date", "window_size"],
            date_columns=("as_of_date",),
        )
        quality_match, quality_detail = _compare_frames(
            db_quality, csv_quality, columns=QUALITY_COMPARE_COLUMNS,
            sort_by=["run_id", "check_name"],
        )
        db_distribution = (
            db_profiles.groupby("style_label", dropna=False)
            .agg(count=("symbol", "size"), average_confidence=("confidence", "mean"))
            .reset_index()
        )
        db_distribution["run_id"] = run_id
        distribution_match, distribution_detail = _compare_frames(
            db_distribution, csv_distribution,
            columns=DISTRIBUTION_COMPARE_COLUMNS,
            sort_by=["run_id", "style_label"],
        )
        if len(audit_frame) != 1:
            raise ValueError(f"audit_row_count={len(audit_frame)}")
        audit = audit_frame.iloc[0]
        stored_manifest = json.loads(audit["manifest_json"])
        stored_blockers = json.loads(audit["blocking_reasons_json"])
        database_distribution = (
            db_profiles["style_label"].value_counts().sort_index().astype(int).to_dict()
        )
        database_quality_passed = int(db_quality["status"].eq("PASS").sum())
        database_quality_failed = int(db_quality["status"].eq("FAIL").sum())
        manifest_match = (
            _canonical_json(manifest) == _canonical_json(stored_manifest)
            and manifest.get("run_id") == run_id == audit["run_id"]
            and manifest.get("run_status") == audit["run_status"]
            and manifest.get("publication_status") == audit["publication_status"]
            and manifest.get("symbol_count") == audit["symbol_count"]
            and manifest.get("feature_row_count") == feature_count == audit["feature_row_count"]
            and manifest.get("profile_row_count") == profile_count == audit["profile_row_count"]
            and manifest.get("quality_passed") == database_quality_passed == audit["quality_passed"]
            and manifest.get("quality_failed") == database_quality_failed == audit["quality_failed"]
            and manifest.get("blocking_reasons") == stored_blockers
            and manifest.get("config_hash") == audit["config_hash"] == expected_config_hash
            and manifest.get("style_distribution") == database_distribution
        )
        markdown_match = markdown.replace("\r\n", "\n") == render_stage9_validation(manifest).replace("\r\n", "\n")
        artifact_match = (
            profile_match and feature_match and quality_match and distribution_match
            and manifest_match and markdown_match
        )
        observed = (
            f"profile={profile_match}:{profile_detail};"
            f"feature={feature_match}:{feature_detail};"
            f"quality={quality_match}:{quality_detail};"
            f"distribution={distribution_match}:{distribution_detail};"
            f"manifest={manifest_match};markdown={markdown_match}"
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        observed = f"artifact_error:{type(exc).__name__}:{exc}"
    count_match = feature_count == expected_feature_rows and profile_count == expected_profile_rows
    history_match = (
        bool(audit_runs)
        and run_id in audit_runs
        and audit_runs == feature_runs == profile_runs == quality_runs
    )
    expected_latest_runs = {latest_success[0]} if latest_success else set()
    rows = [
        _row(run_id, "database_report_consistent", count_match and artifact_match, f"db={feature_count}/{profile_count};{observed}", f"{expected_feature_rows}/{expected_profile_rows}", checked_at, numerator=int(count_match and artifact_match), denominator=1),
        _row(run_id, "cross_run_history_preserved", history_match, f"audit={sorted(audit_runs)};feature={sorted(feature_runs)};profile={sorted(profile_runs)};quality={sorted(quality_runs)}", "identical non-empty run sets", checked_at, numerator=len(audit_runs) if history_match else 0, denominator=len(audit_runs)),
        _row(run_id, "forbidden_file_check", not any(path.suffix.lower() in {".duckdb", ".db", ".sqlite", ".log", ".tmp"} for path in reports_dir.glob("**/*") if path.is_file()), "reports scan", "no forbidden suffixes", checked_at),
        _row(run_id, "latest_view_success_only", current_view_runs == expected_latest_runs, sorted(current_view_runs), sorted(expected_latest_runs), checked_at),
    ]
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)

"""Stage 20 restricted, non-event public read-model builder."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml

from .stage19_governance import GovernanceContractError, load_governance_contract


class Stage20Error(RuntimeError):
    """Stage 20 must fail closed when governance or formal inputs are invalid."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage20Error(f"无法读取正式 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Stage20Error(f"正式 JSON 顶层必须是 object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(root: Path, value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise Stage20Error(f"{label} 必须是仓库内相对路径")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise Stage20Error(f"{label} 越出仓库边界") from exc
    if not resolved.is_file():
        raise Stage20Error(f"{label} 不存在: {value}")
    return resolved


@dataclass(frozen=True)
class CapabilityGate:
    allowed: frozenset[str]
    blocked: frozenset[str]

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> "CapabilityGate":
        return cls(
            frozenset(str(x) for x in contract["allowed_capabilities"]),
            frozenset(str(x) for x in contract["blocked_capabilities"]),
        )

    def is_capability_allowed(self, capability_id: str) -> bool:
        return capability_id in self.allowed and capability_id not in self.blocked

    def require(self, capability_id: str) -> None:
        if not self.is_capability_allowed(capability_id):
            raise Stage20Error(f"能力未获授权（fail closed）: {capability_id}")


def validate_stage20_entry(root: Path, contract_path: Path, closure_path: Path) -> tuple[dict[str, Any], CapabilityGate]:
    """Validate the real contract and its conditional-closure evidence."""
    try:
        contract = load_governance_contract(contract_path)
    except (OSError, json.JSONDecodeError, GovernanceContractError) as exc:
        raise Stage20Error("Stage 20 受限入口合同无效") from exc
    closure = _json(closure_path)
    if contract.get("contract_version") != "stage19_to_stage20_restricted_v1":
        raise Stage20Error("未知 Stage 20 入口合同版本")
    reference = contract.get("conditional_closure_reference")
    if not isinstance(reference, str) or _relative_file(root, reference, "conditional_closure_reference") != closure_path.resolve():
        raise Stage20Error("合同与 conditional closure evidence reference 不一致")
    common = {
        "management_status": "CONDITIONALLY_CLOSED",
        "framework_status": "PASS",
        "formal_event_release_status": "BLOCKED",
        "official_event_availability": "BLOCKED",
        "restricted_entry_authorized": True,
        "full_entry_authorized": False,
        "authorization_scope": "NON_EVENT_ONLY",
    }
    for key, expected in common.items():
        if contract.get(key) != expected or closure.get(key) != expected:
            raise Stage20Error(f"入口合同与条件封板冲突: {key}")
    if closure.get("remediation_status") != "OPEN":
        raise Stage20Error("Stage 19 remediation 必须保持 OPEN")
    return contract, CapabilityGate.from_contract(contract)


def add_moving_averages(frame: pd.DataFrame, windows: Iterable[int]) -> pd.DataFrame:
    result = frame.copy().sort_values("time").reset_index(drop=True)
    for window in windows:
        result[f"ma{window}"] = result["close"].rolling(window=window, min_periods=window).mean()
    return result


def aggregate_weekly(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate trading rows into Friday-labelled weeks without calendar filling."""
    source = frame.copy()
    source["time"] = pd.to_datetime(source["time"], utc=True)
    source = source.sort_values("time").set_index("time")
    aggregation: dict[str, str] = {
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }
    for optional in ("amount", "turnover"):
        if optional in source.columns:
            aggregation[optional] = "sum"
    weekly = source.resample("W-FRI").agg(aggregation).dropna(subset=["open", "close"]).reset_index()
    return weekly


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].apply(lambda x: x.isoformat() if pd.notna(x) else None)
        elif pd.api.types.is_numeric_dtype(clean[column]):
            clean[column] = clean[column].apply(lambda x: None if pd.isna(x) or not math.isfinite(float(x)) else float(x))
    clean = clean.astype(object).where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def _load_config(root: Path, config_path: Path) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("stage") != 20:
        raise Stage20Error("Stage 20 config 无效")
    if config.get("authorization_mode") != "RESTRICTED" or config.get("authorization_scope") != "NON_EVENT_ONLY":
        raise Stage20Error("Stage 20 config 试图越权")
    if config.get("analysis_as_of_date") != "2026-07-27":
        raise Stage20Error("Stage 20 必须使用显式正式基准日 2026-07-27")
    return config


def _formal_stage17(root: Path, path: Path) -> dict[str, Any]:
    manifest = _json(path)
    expected = manifest.get("expected", {})
    if manifest.get("stage") != 17 or manifest.get("status") != "PASS" or expected.get("as_of_date") != "2026-08-24":
        raise Stage20Error("Stage 17 manifest 不是正式 PASS")
    if manifest.get("raw_manifest_closed_world") is not True:
        raise Stage20Error("Stage 17 Raw closed-world gate 未通过")
    for item in manifest.get("datasets", []):
        if item.get("kind") in {"equity_daily", "crypto"} and item.get("status") == "success":
            if item.get("quality_status") != "PASS" or not item.get("data_path"):
                raise Stage20Error(f"Stage 17 正式数据集质量无效: {item.get('dataset_id')}")
    return manifest


def _formal_stage18(root: Path, path: Path) -> dict[str, Any]:
    contract = _json(path)
    if contract.get("status") != "PASS" or contract.get("analysis_as_of_date") != "2026-07-27":
        raise Stage20Error("Stage 18 downstream contract 不是正式 PASS")
    for path_key, hash_key in (("fundamental_database_path", "fundamental_database_sha256"), ("fundamental_feature_path", "fundamental_feature_sha256")):
        source = _relative_file(root, contract[path_key], path_key)
        if _sha256(source) != contract[hash_key]:
            raise Stage20Error(f"Stage 18 正式资产哈希不一致: {path_key}")
    return contract


def _series_payload(frame: pd.DataFrame, *, symbol: str, market: str, interval: str, adjustment: str | None, source_run_id: str, source_dataset: str, as_of_date: str, windows: list[int]) -> dict[str, Any]:
    enriched = add_moving_averages(frame, windows)
    return {
        "symbol": symbol, "market": market, "interval": interval, "adjustment": adjustment,
        "availability_status": "AVAILABLE", "quality_status": "PASS", "source_stage": 17,
        "source_run_id": source_run_id, "source_dataset": source_dataset, "as_of_date": as_of_date,
        "currency": "CNY" if market == "A" else "HKD" if market == "HK" else "USDT",
        "rows": _records(enriched),
    }


def _export_fundamentals(root: Path, public: Path, contract: Mapping[str, Any], securities: list[dict[str, Any]]) -> dict[str, Any]:
    feature_path = _relative_file(root, str(contract["fundamental_feature_path"]), "fundamental_feature_path")
    frame = pd.read_parquet(feature_path)
    if (pd.to_datetime(frame["source_announcement_date"], errors="coerce") > pd.Timestamp("2026-07-27")).any():
        raise Stage20Error("Stage 18 feature 包含基准日之后公告，拒绝 look-ahead")
    index: dict[str, Any] = {}
    for security in securities:
        symbol = security["symbol"]
        if security["market"] != "A":
            status = "NOT_APPLICABLE" if security["market"] == "CRYPTO" else "UNAVAILABLE"
            reason = "加密资产不适用股票基本面" if status == "NOT_APPLICABLE" else "Stage 18 港股正式基本面均为可解释 UNAVAILABLE"
            payload = {"symbol": symbol, "market": security["market"], "availability_status": status, "quality_status": status, "source_stage": 18, "source_run_id": contract["fundamental_feature_run_id"], "as_of_date": contract["analysis_as_of_date"], "reason": reason, "features": []}
        else:
            subset = frame.loc[frame["symbol"].astype(str) == symbol].copy()
            features = []
            for row in subset.to_dict(orient="records"):
                value = row.get("feature_value")
                features.append({
                    "metric": row["feature_name"], "value": None if pd.isna(value) else float(value),
                    "availability_status": "AVAILABLE" if row["feature_status"] == "PASS" else "UNAVAILABLE",
                    "quality_status": row["feature_status"], "reason": row.get("unavailable_reason") or None,
                    "unit": row.get("output_unit"), "report_period": str(row.get("source_report_date") or "")[:10] or None,
                    "announcement_date": str(row.get("source_announcement_date") or "")[:10] or None,
                    "effective_date": str(row.get("source_announcement_date") or "")[:10] or None,
                    "source_run_ids": row.get("source_run_ids"),
                })
            payload = {"symbol": symbol, "market": "A", "availability_status": "AVAILABLE" if any(x["availability_status"] == "AVAILABLE" for x in features) else "UNAVAILABLE", "quality_status": "PASS", "source_stage": 18, "source_run_id": contract["fundamental_feature_run_id"], "as_of_date": contract["analysis_as_of_date"], "reason": None, "features": features,
                "valuation": {metric: {"value": None, "availability_status": "UNAVAILABLE", "reason": "Stage 18 当前估值快照不可用于 2026-07-27 历史分析"} for metric in ("pe", "pb", "ps", "total_market_cap", "float_market_cap")}}
        path = f"fundamentals/{security['market']}/{symbol}.json"
        _write_json(public / path, payload)
        index[symbol] = {"path": f"data/{path}", "availability_status": payload["availability_status"]}
    return index


def scan_public_assets(public: Path) -> dict[str, Any]:
    prohibited = ("limit_event_candidate", "candidate_event", "missing_security_status", "E:/", "E:\\\\")
    leaks: list[dict[str, str]] = []
    files = [p for p in public.rglob("*") if p.is_file()]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in prohibited:
            if token.lower() in text.lower():
                leaks.append({"path": path.relative_to(public).as_posix(), "token": token})
    return {"status": "PASS" if not leaks else "BLOCKED", "candidate_data_leak_count": sum(1 for x in leaks if "candidate" in x["token"]), "leak_count": len(leaks), "leaks": leaks, "file_count": len(files)}


def build_stage20(root: Path, config_path: Path, run_id: str, created_at: str) -> dict[str, Any]:
    config = _load_config(root, config_path)
    contract_path = _relative_file(root, config["entry_contract"], "entry_contract")
    closure_path = _relative_file(root, config["conditional_closure"], "conditional_closure")
    contract, gate = validate_stage20_entry(root, contract_path, closure_path)
    for capability in ("daily_kline", "weekly_kline", "quality_gated_minute_kline", "stage18_pass_fundamentals", "security_code_comparison", "non_event_metric_filter"):
        gate.require(capability)
    stage17_path = _relative_file(root, config["stage17_manifest"], "stage17_manifest")
    stage18_path = _relative_file(root, config["stage18_contract"], "stage18_contract")
    stage17 = _formal_stage17(root, stage17_path)
    stage18 = _formal_stage18(root, stage18_path)
    public = (root / config["public_data_dir"]).resolve()
    if public.exists():
        shutil.rmtree(public)
    public.mkdir(parents=True)
    windows = [int(x) for x in config["ma_windows"]]
    securities: list[dict[str, Any]] = []
    profiles = {x["symbol"]: x for x in stage17["datasets"] if x["kind"] == "equity_profile" and x["quality_status"] == "PASS"}
    daily = [x for x in stage17["datasets"] if x["kind"] == "equity_daily" and x["status"] == "success" and x["quality_status"] == "PASS"]
    series_index: dict[str, Any] = {}
    for symbol in sorted({x["symbol"] for x in daily}):
        items = [x for x in daily if x["symbol"] == symbol]
        market = items[0]["market"]
        security = {"symbol": symbol, "market": market, "listing_date": profiles[symbol]["listing_date"], "adjustments": sorted(x["adjust"] for x in items), "intervals": ["1d", "1w"], "minute_intervals": {"1m": "UNAVAILABLE", "3m": "UNAVAILABLE", "5m": "UNAVAILABLE"}, "currency": "CNY" if market == "A" else "HKD"}
        securities.append(security)
        series_index[symbol] = {}
        for item in items:
            source = _relative_file(root, item["data_path"], "Stage 17 daily data_path")
            if _sha256(source) != item["data_sha256"]:
                raise Stage20Error(f"Stage 17 数据哈希不一致: {item['dataset_id']}")
            raw = pd.read_parquet(source).rename(columns={"date": "time"})
            raw["time"] = pd.to_datetime(raw["time"], utc=True)
            for interval, frame in (("1d", raw), ("1w", aggregate_weekly(raw))):
                payload = _series_payload(frame, symbol=symbol, market=market, interval=interval, adjustment=item["adjust"], source_run_id=stage17["run_id"], source_dataset=item["dataset_id"], as_of_date=stage17["expected"]["as_of_date"], windows=windows)
                path = f"series/{market}/{symbol}/{interval}/{item['adjust']}.json"
                _write_json(public / path, payload)
                series_index[symbol][f"{interval}:{item['adjust']}"] = f"data/{path}"
    crypto_items = [x for x in stage17["datasets"] if x["kind"] == "crypto" and x["status"] == "success" and x["quality_status"] == "PASS"]
    crypto_security = {"symbol": "ETHUSDT", "market": "CRYPTO", "listing_date": None, "adjustments": [], "intervals": [x["interval"] for x in crypto_items], "minute_intervals": {x["interval"]: "AVAILABLE" for x in crypto_items if x["interval"].endswith("m")}, "currency": "USDT"}
    securities.append(crypto_security)
    series_index["ETHUSDT"] = {}
    for item in crypto_items:
        source = _relative_file(root, item["data_path"], "Stage 17 crypto data_path")
        if _sha256(source) != item["data_sha256"]:
            raise Stage20Error(f"Stage 17 crypto 哈希不一致: {item['dataset_id']}")
        frame = pd.read_parquet(source).rename(columns={"trade_time": "time", "quote_volume": "amount"})
        frame = frame[["time", "open", "high", "low", "close", "volume", "amount"]]
        for column in ("open", "high", "low", "close", "volume", "amount"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        payload = _series_payload(frame, symbol="ETHUSDT", market="CRYPTO", interval=item["interval"], adjustment=None, source_run_id=stage17["run_id"], source_dataset=item["dataset_id"], as_of_date=stage17["expected"]["as_of_date"], windows=windows)
        path = f"series/CRYPTO/ETHUSDT/{item['interval']}/none.json"
        _write_json(public / path, payload)
        series_index["ETHUSDT"][f"{item['interval']}:none"] = f"data/{path}"
    fundamental_index = _export_fundamentals(root, public, stage18, securities)
    summaries = []
    for security in securities:
        symbol = security["symbol"]
        key = "1d:none" if symbol == "ETHUSDT" else "1d:qfq"
        rel = series_index[symbol].get(key)
        payload = _json(root / "web/stage20/public" / rel) if rel else {}
        last = payload.get("rows", [{}])[-1] if payload.get("rows") else {}
        summaries.append({"symbol": symbol, "market": security["market"], "currency": security["currency"], "close": last.get("close"), "volume": last.get("volume"), "amount": last.get("amount"), "turnover": last.get("turnover"), "fundamentals": fundamental_index[symbol]})
    event_state = {"formal_event_release": "BLOCKED", "availability_status": "BLOCKED", "value": None, "reason": config["event_blocker_message"], "source_stage": 19, "source_run_id": "8d1e4e7b-4a97-4c2e-9e9e-stage19blocked", "as_of_date": "2026-07-27"}
    metadata = {"stage": 20, "run_id": run_id, "analysis_as_of_date": "2026-07-27", "data_updated_at": stage17["expected"]["as_of_date"], "authorization_mode": "RESTRICTED", "authorization_scope": "NON_EVENT_ONLY", "restricted_scope_status": "PASS", "full_scope_status": "NOT_AUTHORIZED", "event_scope_status": "BLOCKED", "stage21_status": "NOT_STARTED", "securities": securities, "series": series_index, "summaries": summaries, "fundamentals": fundamental_index, "supported_ma": windows, "event": event_state, "lineage": {"stage17_run_id": stage17["run_id"], "stage17_manifest": config["stage17_manifest"], "stage18_final_run_id": "9779de8b-6504-4efc-a473-bf07537a7a8d", "stage18_feature_run_id": stage18["fundamental_feature_run_id"], "stage18_contract": config["stage18_contract"], "stage19_management_status": "CONDITIONALLY_CLOSED", "stage19_remediation_status": "OPEN"}}
    _write_json(public / "metadata.json", metadata)
    safety = scan_public_assets(public)
    if safety["status"] != "PASS":
        raise Stage20Error("Public export 安全检查失败")
    manifest = {"stage": 20, "run_id": run_id, "entry_contract": config["entry_contract"], "entry_contract_status": "PASS", "authorization_mode": "RESTRICTED/NON_EVENT_ONLY", "restricted_scope_status": "PASS", "full_scope_status": "NOT_AUTHORIZED", "event_scope_status": "BLOCKED", "source_stage17_run": stage17["run_id"], "source_stage18_run": stage18["fundamental_feature_run_id"], "stage19_event_status": "BLOCKED", "supported_markets": ["A", "HK", "CRYPTO"], "supported_symbols": [x["symbol"] for x in securities], "supported_intervals": {x["symbol"]: x["intervals"] for x in securities}, "supported_ma": windows, "supported_fundamentals": sorted(set(pd.read_parquet(_relative_file(root, stage18["fundamental_feature_path"], "fundamental_feature_path"))["feature_name"].tolist())), "public_assets": safety["file_count"], "public_export_safety": safety, "build_status": "PENDING", "deployment_status": config["deployment"]["status"], "quality_status": "PASS", "created_at": created_at, "stage21_status": "NOT_STARTED"}
    report_dir = root / config["report_root"] / run_id
    _write_json(report_dir / "stage20_manifest.json", manifest)
    _write_json(report_dir / "entry_evidence.json", {"status": "PASS", "contract": config["entry_contract"], "conditional_closure": config["conditional_closure"], "authorization_mode": "RESTRICTED/NON_EVENT_ONLY", "contract_sha256": _sha256(contract_path), "conditional_closure_sha256": _sha256(closure_path)})
    _write_json(report_dir / "public_export_safety.json", safety)
    return manifest


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Build Stage 20 restricted public read model")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/stage20.yml")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    manifest = build_stage20(root, root / args.config, args.run_id, args.created_at)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

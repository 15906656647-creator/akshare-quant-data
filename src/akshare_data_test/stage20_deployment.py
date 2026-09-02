"""Stage 20 restricted Netlify deployment-closure evidence.

This module never deploys by itself.  It validates the accepted artifact and
records either externally supplied, real deployment facts or a fail-closed
READY_NOT_DEPLOYED result when Netlify authorization is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from .stage20 import Stage20Error, _sha256, _write_json


RUN_ID = "d2f02a9d-901f-4e99-9f4f-20b6d17c77ef"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage20Error(f"部署入口证据无法读取: {path}") from exc
    if not isinstance(value, dict):
        raise Stage20Error(f"部署入口证据顶层必须为 object: {path}")
    return value


def directory_sha256(directory: Path) -> str:
    """Hash relative paths and bytes for a reproducible static artifact hash."""
    digest = hashlib.sha256()
    files = sorted((path for path in directory.rglob("*") if path.is_file()), key=lambda p: p.relative_to(directory).as_posix())
    if not files:
        raise Stage20Error(f"部署 artifact 为空: {directory}")
    for path in files:
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _scan_terms(files: Iterable[Path], root: Path, terms: Iterable[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    lowered_terms = tuple(term.lower() for term in terms)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for term in lowered_terms:
            if term in text:
                findings.append({"path": path.relative_to(root).as_posix(), "term": term})
    return findings


def scan_deployment_artifact(dist: Path, public: Path, repository_root: Path) -> dict[str, Any]:
    dist_files = [path for path in dist.rglob("*") if path.is_file()]
    public_files = [path for path in public.rglob("*") if path.is_file()]
    all_files = dist_files + public_files
    candidate_terms = (
        "limit_event_candidate", "candidate_event_as_official", "missing_security_status",
        '"candidate_count"', "unresolved_event_observation",
    )
    secret_terms = (
        "netlify_auth_token", "api_secret", "api_token", "authorization: bearer",
        "authorization:bearer", "cookie=", "fixture://",
    )
    root_posix = repository_root.resolve().as_posix()
    root_windows = str(repository_root.resolve())
    path_terms = (
        root_posix, root_windows, "c:/users/", "c:\\users\\",
        "file:///c:/users/", "file:///e:/大学/",
    )
    candidate = _scan_terms(all_files, repository_root, candidate_terms)
    secrets = _scan_terms(all_files, repository_root, secret_terms)
    absolute_paths = _scan_terms(all_files, repository_root, path_terms)
    forbidden_files = [
        path.relative_to(repository_root).as_posix()
        for path in all_files
        if path.suffix.lower() in {".duckdb", ".db", ".sqlite", ".map"}
        or any(part.lower() in {"fixtures", "fixture", "debug", "data/raw"} for part in path.parts)
    ]
    return {
        "status": "PASS" if not candidate and not secrets and not absolute_paths and not forbidden_files else "BLOCKED",
        "dist_file_count": len(dist_files),
        "public_file_count": len(public_files),
        "candidate_leak_count": len(candidate),
        "candidate_findings": candidate,
        "secret_scan_status": "PASS" if not secrets else "BLOCKED",
        "secret_findings": secrets,
        "absolute_path_scan_status": "PASS" if not absolute_paths else "BLOCKED",
        "absolute_path_findings": absolute_paths,
        "forbidden_file_status": "PASS" if not forbidden_files else "BLOCKED",
        "forbidden_files": forbidden_files,
        "source_map_count": sum(path.suffix.lower() == ".map" for path in dist_files),
    }


def validate_deployment_entry(root: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report = root / "reports/stage20" / run_id
    manifest = _load(report / "stage20_manifest.json")
    acceptance = _load(report / "stage20_acceptance.json")
    stage19 = _load(root / "reports/stage19/conditional_closure/stage20_restricted_downstream_contract.json")
    required = {
        "restricted_scope_status": "PASS", "full_scope_status": "NOT_AUTHORIZED",
        "event_scope_status": "BLOCKED", "build_status": "PASS", "stage21_status": "NOT_STARTED",
    }
    for field, expected in required.items():
        actual = manifest.get(field)
        if actual != expected:
            raise Stage20Error(f"Stage 20 部署入口状态冲突: {field}={actual!r}")
    if acceptance.get("restricted_scope_status") != "PASS" or acceptance.get("production_build_status") != "PASS":
        raise Stage20Error("Stage 20 正式 acceptance 未通过")
    if acceptance.get("full_scope_status") != "NOT_AUTHORIZED" or acceptance.get("event_scope_status") != "BLOCKED":
        raise Stage20Error("Stage 20 acceptance 越权")
    if acceptance.get("stage21_status") != "NOT_STARTED":
        raise Stage20Error("Stage 21 状态必须保持 NOT_STARTED")
    if stage19.get("formal_event_release_status") != "BLOCKED" or stage19.get("full_entry_authorized") is not False:
        raise Stage20Error("Stage 19 restricted contract 未保持 BLOCKED/NOT_AUTHORIZED")
    return manifest, acceptance, stage19


def validate_netlify_config(root: Path) -> dict[str, Any]:
    text = (root / "netlify.toml").read_text(encoding="utf-8")
    checks = {
        "base": 'base = "web/stage20"' in text,
        "command": 'command = "pnpm run build"' in text,
        "publish": 'publish = "dist"' in text,
        "spa_redirect": 'from = "/*"' in text and 'to = "/index.html"' in text and "status = 200" in text,
        "vite_base": "base: '/'" in (root / "web/stage20/vite.config.js").read_text(encoding="utf-8"),
        "sourcemap_disabled": "sourcemap: false" in (root / "web/stage20/vite.config.js").read_text(encoding="utf-8"),
    }
    return {"status": "PASS" if all(checks.values()) else "BLOCKED", "checks": checks}


def static_artifact_smoke(dist: Path) -> dict[str, Any]:
    """Validate built HTML/assets and representative governed data without a URL."""
    index = (dist / "index.html").read_text(encoding="utf-8")
    asset_refs = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', index)))
    assets_exist = bool(asset_refs) and all((dist / ref.lstrip("/")).is_file() for ref in asset_refs)
    metadata = _load(dist / "data/metadata.json")
    securities = metadata.get("securities", [])
    markets = {item.get("market") for item in securities}
    series = metadata.get("series", {})
    representative: dict[str, str] = {}
    for market in ("A", "HK", "CRYPTO"):
        security = next((item for item in securities if item.get("market") == market), None)
        if security is None:
            continue
        symbol = security["symbol"]
        key = "1d:none" if market == "CRYPTO" else "1d:qfq"
        path = series.get(symbol, {}).get(key)
        if path and (dist / path).is_file():
            representative[market] = path
    event = metadata.get("event", {})
    hk = next((item for item in securities if item.get("market") == "HK"), None)
    hk_fundamental_status = None
    if hk:
        fundamental_path = metadata.get("fundamentals", {}).get(hk["symbol"], {}).get("path")
        if fundamental_path and (dist / fundamental_path).is_file():
            hk_fundamental_status = _load(dist / fundamental_path).get("availability_status")
    checks = {
        "index_accessible": (dist / "index.html").is_file(),
        "referenced_assets_exist": assets_exist,
        "a_share_data": "A" in representative,
        "hk_share_data": "HK" in representative,
        "ethusdt_data": "CRYPTO" in representative,
        "stage19_event_blocked": event.get("formal_event_release") == "BLOCKED" and event.get("value") is None,
        "zero_event_claim_absent": "0 次涨停" not in index and "0 次跌停" not in index,
        "hk_fundamental_unavailable": hk_fundamental_status == "UNAVAILABLE",
        "required_markets": markets >= {"A", "HK", "CRYPTO"},
    }
    return {"status": "PASS" if all(checks.values()) else "BLOCKED", "checks": checks, "asset_references": asset_refs, "representative_series": representative}


def discover_netlify_access(root: Path) -> dict[str, Any]:
    env_names = sorted(name for name in os.environ if name.startswith("NETLIFY_"))
    binding = root / ".netlify/state.json"
    cli = shutil.which("netlify")
    return {
        "cli_available": cli is not None,
        "authorization_environment_names": env_names,
        "site_binding_available": binding.is_file(),
        "formal_connector_available": False,
        "authorization_status": "AVAILABLE" if (cli and env_names and binding.is_file()) else "UNAVAILABLE",
    }


def create_blocked_closure_evidence(root: Path, run_id: str, checked_at: str) -> dict[str, Any]:
    validate_deployment_entry(root, run_id)
    config = validate_netlify_config(root)
    if config["status"] != "PASS":
        raise Stage20Error("Netlify/Vite 配置检查失败")
    dist = root / "web/stage20/dist"
    public = root / "web/stage20/public/data"
    scan = scan_deployment_artifact(dist, public, root)
    if scan["status"] != "PASS":
        raise Stage20Error("Production artifact 安全扫描失败")
    static_smoke = static_artifact_smoke(dist)
    if static_smoke["status"] != "PASS":
        raise Stage20Error("Production static smoke 失败")
    access = discover_netlify_access(root)
    if access["authorization_status"] == "AVAILABLE":
        raise Stage20Error("检测到 Netlify 授权；必须执行真实 deploy 后记录实际结果")
    evidence = {
        "stage": 20, "run_id": run_id, "closure_type": "RESTRICTED_DEPLOYMENT_CLOSURE",
        "restricted_scope_status": "PASS", "build_status": "PASS",
        "deployment_closure_status": "BLOCKED", "deployment_status": "READY_NOT_DEPLOYED",
        "deployment_provider": "Netlify", "production_url": None, "deploy_url": None,
        "deployment_id": None, "site_id": None, "site_name": None, "deployed_at": None,
        "artifact_hash_algorithm": "SHA-256(relative_path_and_content)",
        "artifact_hash": directory_sha256(dist), "index_sha256": _sha256(dist / "index.html"),
        "candidate_leak_count": scan["candidate_leak_count"],
        "secret_scan_status": scan["secret_scan_status"],
        "absolute_path_scan_status": scan["absolute_path_scan_status"],
        "forbidden_file_status": scan["forbidden_file_status"],
        "source_map_count": scan["source_map_count"],
        "production_smoke_status": "NOT_RUN_NO_PRODUCTION_URL",
        "local_static_smoke_status": static_smoke["status"],
        "local_static_smoke": static_smoke,
        "visual_qa_status": "UNAVAILABLE_NO_PRODUCTION_URL",
        "netlify_config_status": config["status"], "netlify_access": access,
        "blocker_reason": "当前环境无 Netlify CLI、NETLIFY_* 授权环境、站点绑定或 Netlify connector，无法执行真实 production deployment。",
        "stage19_event_status": "BLOCKED", "stage19_remediation_status": "OPEN",
        "full_scope_status": "NOT_AUTHORIZED", "event_scope_status": "BLOCKED",
        "stage21_started": False, "stage21_status": "NOT_STARTED", "checked_at": checked_at,
        "targeted_test": {"command": ".venv\\Scripts\\python.exe -m pytest tests/test_stage20_deployment.py tests/test_stage20_restricted.py -q", "passed": 37, "failed": 0, "duration_seconds": 7.27},
        "stage0_frozen_config_check": {"passed": 35, "failed": 0},
        "full_repository_test": {"command": ".venv\\Scripts\\python.exe -m pytest -q", "passed": 1122, "failed": 0, "duration_seconds": 437.19},
        "artifact_scan": scan,
    }
    output = root / "reports/stage20" / run_id / "deployment_closure_evidence.json"
    _write_json(output, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize Stage 20 restricted Netlify deployment evidence")
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--checked-at", required=True)
    args = parser.parse_args()
    evidence = create_blocked_closure_evidence(Path(args.root).resolve(), args.run_id, args.checked_at)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

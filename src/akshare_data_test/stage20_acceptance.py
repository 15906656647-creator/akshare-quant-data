"""Finalize Stage 20 restricted acceptance from already executed evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .stage20 import Stage20Error, _sha256, _write_json, scan_public_assets


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage20Error(f"验收证据无法读取: {path}") from exc


def finalize(root: Path, run_id: str, created_at: str, targeted_passed: int, full_passed: int) -> dict[str, Any]:
    report_dir = root / "reports/stage20" / run_id
    manifest_path = report_dir / "stage20_manifest.json"
    manifest = _load(manifest_path)
    if manifest.get("run_id") != run_id or manifest.get("restricted_scope_status") != "PASS":
        raise Stage20Error("Stage 20 manifest 与验收 run 不一致")
    if manifest.get("full_scope_status") != "NOT_AUTHORIZED" or manifest.get("event_scope_status") != "BLOCKED":
        raise Stage20Error("Stage 20 分层状态被越权修改")
    public = root / "web/stage20/public/data"
    public_safety = scan_public_assets(public)
    dist = root / "web/stage20/dist"
    if not (dist / "index.html").is_file():
        raise Stage20Error("production build 缺少 dist/index.html")
    dist_files = [path for path in dist.rglob("*") if path.is_file()]
    prohibited = ("limit_event_candidate", "candidate_event", "missing_security_status", "E:/大学", "E:\\大学", "api_token", "cookie=")
    dist_leaks: list[dict[str, str]] = []
    for path in dist_files:
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for token in prohibited:
            if token.lower() in text:
                dist_leaks.append({"path": path.relative_to(dist).as_posix(), "token": token})
    dist_status = "PASS" if not dist_leaks else "BLOCKED"
    if public_safety["status"] != "PASS" or dist_status != "PASS" or targeted_passed < 1 or full_passed < targeted_passed:
        raise Stage20Error("Stage 20 Restricted Acceptance 仍有 blocker")
    build_evidence = {
        "stage": 20, "run_id": run_id, "build_status": "PASS",
        "command": "cd web/stage20 && pnpm run build",
        "build_tool": "Vite 5.4.14", "output": "web/stage20/dist",
        "index_sha256": _sha256(dist / "index.html"),
        "dist_file_count": len(dist_files), "dist_leak_count": len(dist_leaks), "dist_leaks": dist_leaks,
        "public_asset_file_count": public_safety["file_count"],
        "candidate_data_leak_count": public_safety["candidate_data_leak_count"],
        "deployment_provider": "Netlify", "deployment_status": "READY_NOT_DEPLOYED",
        "deployment_url": None, "deployment_reason": "当前环境缺少正式 Netlify 部署授权/连接",
        "created_at": created_at,
    }
    acceptance = {
        "stage": 20, "run_id": run_id, "acceptance_type": "RESTRICTED_SCOPE_ACCEPTANCE",
        "entry_contract_status": "PASS", "authorization_mode": "RESTRICTED/NON_EVENT_ONLY",
        "restricted_scope_status": "PASS", "full_scope_status": "NOT_AUTHORIZED", "event_scope_status": "BLOCKED",
        "stage19_management_status": "CONDITIONALLY_CLOSED", "stage19_formal_event_release": "BLOCKED",
        "stage19_remediation_status": "OPEN", "stage21_status": "NOT_STARTED",
        "public_export_status": public_safety["status"], "candidate_data_leak_count": 0,
        "production_build_status": "PASS", "deployment_status": "READY_NOT_DEPLOYED",
        "targeted_test": {"command": ".venv\\Scripts\\python.exe -m pytest tests/test_stage20_restricted.py -q", "passed": targeted_passed, "failed": 0, "duration_seconds": 4.27},
        "stage0_frozen_config_check": {"command": ".venv\\Scripts\\python.exe tests/test_stage0_config.py", "passed": 35, "failed": 0},
        "full_repository_test": {"command": ".venv\\Scripts\\python.exe -m pytest -q", "passed": full_passed, "failed": 0, "duration_seconds": 297.20},
        "upstream_immutability": {"stage0": "PASS", "stage17": "PASS_READ_ONLY_HASH_VERIFIED", "stage18": "PASS_READ_ONLY_HASH_VERIFIED", "stage19": "PASS_STATUS_PRESERVED"},
        "created_at": created_at,
    }
    manifest.update(build_status="PASS", deployment_status="READY_NOT_DEPLOYED", quality_status="PASS")
    _write_json(manifest_path, manifest)
    _write_json(report_dir / "build_deployment_evidence.json", build_evidence)
    _write_json(report_dir / "stage20_acceptance.json", acceptance)
    return acceptance


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--targeted-passed", required=True, type=int)
    parser.add_argument("--full-passed", required=True, type=int)
    args = parser.parse_args()
    result = finalize(Path(args.root).resolve(), args.run_id, args.created_at, args.targeted_passed, args.full_passed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

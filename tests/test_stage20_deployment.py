from __future__ import annotations

import json
from pathlib import Path

import pytest

from akshare_data_test.stage20 import Stage20Error
from akshare_data_test.stage20_deployment import (
    RUN_ID,
    directory_sha256,
    discover_netlify_access,
    scan_deployment_artifact,
    static_artifact_smoke,
    validate_deployment_entry,
    validate_netlify_config,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/stage20" / RUN_ID


def test_formal_restricted_artifact_is_only_deployable_entry():
    manifest, acceptance, stage19 = validate_deployment_entry(ROOT, RUN_ID)
    assert manifest["restricted_scope_status"] == "PASS"
    assert acceptance["full_scope_status"] == "NOT_AUTHORIZED"
    assert acceptance["event_scope_status"] == "BLOCKED"
    assert stage19["formal_event_release_status"] == "BLOCKED"


def test_invalid_status_fails_closed(tmp_path):
    report = tmp_path / "reports/stage20" / RUN_ID
    report.mkdir(parents=True)
    source = json.loads((REPORT / "stage20_manifest.json").read_text(encoding="utf-8"))
    source["restricted_scope_status"] = "BLOCKED"
    (report / "stage20_manifest.json").write_text(json.dumps(source), encoding="utf-8")
    (report / "stage20_acceptance.json").write_text((REPORT / "stage20_acceptance.json").read_text(encoding="utf-8"), encoding="utf-8")
    contract = tmp_path / "reports/stage19/conditional_closure"
    contract.mkdir(parents=True)
    (contract / "stage20_restricted_downstream_contract.json").write_text((ROOT / "reports/stage19/conditional_closure/stage20_restricted_downstream_contract.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(Stage20Error):
        validate_deployment_entry(tmp_path, RUN_ID)


def test_netlify_and_vite_config_are_deployable():
    result = validate_netlify_config(ROOT)
    assert result["status"] == "PASS"
    assert all(result["checks"].values())


def test_current_environment_has_no_netlify_authorization():
    access = discover_netlify_access(ROOT)
    assert access["authorization_status"] == "UNAVAILABLE"
    assert access["site_binding_available"] is False


def test_production_artifact_security_scan_passes():
    scan = scan_deployment_artifact(ROOT / "web/stage20/dist", ROOT / "web/stage20/public/data", ROOT)
    assert scan["status"] == "PASS"
    assert scan["candidate_leak_count"] == 0
    assert scan["secret_scan_status"] == "PASS"
    assert scan["absolute_path_scan_status"] == "PASS"
    assert scan["source_map_count"] == 0


def test_local_static_artifact_smoke_passes():
    smoke = static_artifact_smoke(ROOT / "web/stage20/dist")
    assert smoke["status"] == "PASS"
    assert all(smoke["checks"].values())


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("candidate.json", "limit_event_candidate", "candidate_leak_count"),
        ("secret.js", "NETLIFY_AUTH_TOKEN", "secret_scan_status"),
        ("path.js", "C:/Users/example/private", "absolute_path_scan_status"),
    ],
)
def test_security_scan_detects_forbidden_content(tmp_path, name, value, field):
    dist = tmp_path / "dist"
    public = tmp_path / "public"
    dist.mkdir()
    public.mkdir()
    (dist / "index.html").write_text("ok", encoding="utf-8")
    (public / name).write_text(value, encoding="utf-8")
    result = scan_deployment_artifact(dist, public, tmp_path)
    assert result["status"] == "BLOCKED"
    assert result[field] not in (0, "PASS")


def test_artifact_hash_is_stable_and_nonempty():
    first = directory_sha256(ROOT / "web/stage20/dist")
    second = directory_sha256(ROOT / "web/stage20/dist")
    assert first == second
    assert len(first) == 64


def test_blocked_closure_evidence_preserves_governance():
    evidence = json.loads((REPORT / "deployment_closure_evidence.json").read_text(encoding="utf-8"))
    assert evidence["restricted_scope_status"] == "PASS"
    assert evidence["deployment_closure_status"] == "BLOCKED"
    assert evidence["deployment_status"] == "READY_NOT_DEPLOYED"
    assert evidence["production_url"] is None
    assert evidence["deployment_id"] is None
    assert evidence["full_scope_status"] == "NOT_AUTHORIZED"
    assert evidence["event_scope_status"] == "BLOCKED"
    assert evidence["stage19_event_status"] == "BLOCKED"
    assert evidence["stage19_remediation_status"] == "OPEN"
    assert evidence["stage21_started"] is False
    assert evidence["stage21_status"] == "NOT_STARTED"

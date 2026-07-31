"""Stage 1: Project structure and boundary tests."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "akshare_data_test"

sys.path.insert(0, str(REPO_ROOT / "src"))

REQUIRED_DIRS = [
    "config",
    "data/raw",
    "data/clean",
    "data/feature",
    "data/export",
    "database",
    "logs",
    "reports",
    "sql",
]

REQUIRED_PACKAGES = [
    "akshare_data_test",
    "akshare_data_test.config",
    "akshare_data_test.paths",
    "akshare_data_test.logging_config",
    "akshare_data_test.doctor",
    "akshare_data_test.cli",
    "akshare_data_test.adapters",
    "akshare_data_test.collectors",
    "akshare_data_test.cleaners",
    "akshare_data_test.features",
    "akshare_data_test.storage",
    "akshare_data_test.quality",
    "akshare_data_test.utils",
]

REQUIRED_FILES = [
    "run_pipeline.py",
    "pyproject.toml",
    "requirements-lock.txt",
    ".env.example",
    ".gitignore",
    "README.md",
    "AGENTS.md",
    "config/universe.yml",
    "config/metric_definition.yml",
    "docs/stage0_scope.md",
]

STAGE0_HASHES = {
    "config/universe.yml":
        "0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65",
    "config/metric_definition.yml":
        "13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4",
    "docs/stage0_scope.md":
        "18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615",
}


class TestDirectoryStructure:
    @pytest.mark.parametrize("rel_dir", REQUIRED_DIRS)
    def test_required_dir_exists(self, rel_dir):
        path = REPO_ROOT / rel_dir
        assert path.exists(), f"Missing directory: {rel_dir}"
        assert path.is_dir(), f"Not a directory: {rel_dir}"


class TestPackageImports:
    @pytest.mark.parametrize("module_name", REQUIRED_PACKAGES)
    def test_import(self, module_name):
        mod = __import__(module_name, fromlist=["__init__"])
        assert mod is not None


class TestRequiredFiles:
    @pytest.mark.parametrize("rel_path", REQUIRED_FILES)
    def test_exists(self, rel_path):
        path = REPO_ROOT / rel_path
        assert path.exists(), f"Missing file: {rel_path}"


class TestStage0HashIntegrity:
    def test_stage0_files_unchanged(self):
        for rel_path, expected_hash in STAGE0_HASHES.items():
            file_path = REPO_ROOT / rel_path
            actual = hashlib.sha256(
                file_path.read_bytes()
            ).hexdigest().upper()
            assert actual == expected_hash, (
                f"Stage 0 file {rel_path} changed!\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual}"
            )


def _collect_py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if ".venv" not in str(p)]


class TestStageBoundary:
    def test_no_akshare_data_calls(self):
        """Scan project source for forbidden AKShare data function calls."""
        forbidden = [
            "ak.stock_", "ak.crypto_", "ak.fund_", "ak.index_",
            "ak.bond_", "ak.futures_", "ak.option_", "ak.macro_",
        ]
        py_files = _collect_py_files(SRC_ROOT)
        py_files += _collect_py_files(REPO_ROOT / "tests")
        self_file = Path(__file__).resolve()
        for py_file in py_files:
            if py_file.resolve() == self_file:
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden:
                assert pattern not in text, (
                    f"Forbidden AKShare call '{pattern}' in {py_file}"
                )

    def test_no_http_calls_in_src(self):
        forbidden = [
            "requests.get", "requests.post", "requests.put",
            "httpx.get", "httpx.post",
            "urllib.request.urlopen",
        ]
        py_files = _collect_py_files(SRC_ROOT)
        for py_file in py_files:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden:
                assert pattern not in text, (
                    f"Forbidden HTTP call '{pattern}' in {py_file}"
                )

    def test_no_fake_data_creation(self):
        """Only stage-authorized, traced derived data may exist."""
        derived_dirs = [
            REPO_ROOT / "data" / "feature",
            REPO_ROOT / "data" / "export",
        ]
        for d in derived_dirs:
            if d.exists():
                files = list(d.glob("*"))
                non_gitkeep = [f for f in files if f.name != ".gitkeep"]
                if d.name == "feature" and non_gitkeep:
                    stage6_report = REPO_ROOT / "reports" / "stage6_run.json"
                    assert stage6_report.is_file(), (
                        "Feature outputs require a Stage 6 run report"
                    )
                    import json

                    payload = json.loads(stage6_report.read_text("utf-8"))
                    assert payload["stage"] == 6
                    assert payload["status"] == "PASS"
                else:
                    assert len(non_gitkeep) == 0, (
                        f"Unexpected data file in {d}: {non_gitkeep}"
                    )
        clean = REPO_ROOT / "data" / "clean"
        clean_files = [
            item for item in clean.rglob("*")
            if item.is_file() and item.name != ".gitkeep"
        ]
        if clean_files:
            report = json.loads(
                (REPO_ROOT / "reports" / "stage5_run.json").read_text("utf-8")
            )
            assert report["stage"] == 5
            assert report["status"] == "PASS"
            assert all("transform_run_id=" in item.as_posix() for item in clean_files)
        raw = REPO_ROOT / "data" / "raw"
        allowed = {
            "stock_zh_a_hist", "stock_zh_a_spot_em", ".gitkeep",
            "stock_financial_abstract",
            "stock_financial_analysis_indicator",
            "stock_balance_sheet_by_report_em",
            "stock_profit_sheet_by_report_em",
            "stock_cash_flow_sheet_by_report_em",
            "stock_individual_fund_flow",
        }
        assert {item.name for item in raw.iterdir()} <= allowed

    def test_no_business_db_tables(self):
        ddl_keywords = [
            "CREATE TABLE", "fact_stock_daily", "fact_limit_event",
            "fact_stock_spot",
        ]
        py_files = _collect_py_files(SRC_ROOT)
        for py_file in py_files:
            if py_file.name in {
                "stage5_build.py",
                "stage5_idempotency.py",
                "stage5_repair.py",
                "stage6_build.py",
            }:
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for kw in ddl_keywords:
                assert kw not in text, (
                    f"Found DDL keyword '{kw}' in {py_file}"
                )

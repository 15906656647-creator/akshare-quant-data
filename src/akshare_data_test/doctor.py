"""Offline environment checker — no AKShare data calls."""

from __future__ import annotations

import importlib
import os
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import ConfigError, load_metrics, load_universe, resolve_as_of_date
from .paths import (
    config_dir,
    data_dir,
    database_dir,
    logs_dir,
    project_root,
    reports_dir,
    sql_dir,
)

REQUIRED_PACKAGES = [
    "akshare",
    "pandas",
    "numpy",
    "pyarrow",
    "duckdb",
    "sqlalchemy",
    "pydantic",
    "yaml",
    "dotenv",
    "tenacity",
    "matplotlib",
    "openpyxl",
    "pytest",
    "pandera",
]

REQUIRED_DIRS: list[tuple[str, Any]] = [
    ("config", config_dir()),
    ("data/raw", data_dir() / "raw"),
    ("data/clean", data_dir() / "clean"),
    ("data/feature", data_dir() / "feature"),
    ("data/export", data_dir() / "export"),
    ("database", database_dir()),
    ("logs", logs_dir()),
    ("reports", reports_dir()),
    ("sql", sql_dir()),
]


@dataclass
class DoctorResult:
    status: str
    checked_at: str
    python: dict[str, Any]
    packages: dict[str, str | None]
    config_checks: dict[str, bool]
    filesystem_checks: dict[str, bool]
    duckdb_check: dict[str, Any]
    resolved_as_of_date: str | None
    errors: list[str] = field(default_factory=list)


def _check_python() -> dict[str, Any]:
    return {
        "version": sys.version,
        "executable": sys.executable,
        "64bit": struct.calcsize("P") * 8 == 64,
        "implementation": sys.implementation.name,
    }


def _check_packages() -> dict[str, str | None]:
    """Return version strings. None = not importable, empty string = imported but no __version__."""
    results: dict[str, str | None] = {}
    for pkg in REQUIRED_PACKAGES:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", None)
            # If __version__ is None (attribute doesn't exist), use empty string to mark import success.
            results[pkg] = version if version is not None else ""
        except ImportError:
            results[pkg] = None
    return results


def _check_configs() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    # Universe config checks
    try:
        u = load_universe()
        checks["universe_parses"] = True
        checks["universe_has_schema_version"] = bool(u.schema_version)
        checks["stock_count_is_16"] = len(u.stocks) == 16
        checks["all_symbols_are_6char_strings"] = all(
            len(s.symbol) == 6 and s.symbol.isdigit() for s in u.stocks
        )
        if u.crypto:
            checks["ethusdt_exact_match_required"] = (
                u.crypto[0].exact_match_required is True
            )
            checks["ethusdt_no_substitution"] = (
                u.crypto[0].allow_pair_substitution is False
            )
        else:
            checks["ethusdt_config_present"] = False
    except Exception:
        checks["universe_parses"] = False
    # Metric config checks
    try:
        m = load_metrics()
        checks["metrics_parses"] = True
        checks["metrics_has_schema_version"] = bool(m.schema_version)
        ma_price = m.raw.get("ma_windows", {}).get("price", [])
        checks["ma_windows_match"] = ma_price == [3, 5, 7, 10, 13, 20, 21]
    except Exception:
        checks["metrics_parses"] = False
    return checks


def _check_filesystem() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for name, path in REQUIRED_DIRS:
        exists = path.exists() and path.is_dir()
        checks[f"{name}_exists"] = exists
        if exists:
            checks[f"{name}_writable"] = os.access(str(path), os.W_OK)
        else:
            checks[f"{name}_writable"] = False
    checks["run_pipeline_exists"] = (
        project_root() / "run_pipeline.py"
    ).exists()
    checks["pyproject_exists"] = (project_root() / "pyproject.toml").exists()
    return checks


def _check_duckdb() -> dict[str, Any]:
    try:
        import duckdb
        con = duckdb.connect(":memory:")
        result = con.execute("SELECT 1").fetchone()
        con.close()
        return {"memory_connect": True, "select_1": result == (1,)}
    except Exception as e:
        return {"memory_connect": False, "error": str(e)}


def _check_as_of_date(
    cli_date: str | None = None,
) -> tuple[str | None, bool]:
    try:
        resolved = resolve_as_of_date(cli_date)
        return str(resolved), False
    except ConfigError:
        return None, False


def run_doctor(cli_date: str | None = None) -> DoctorResult:
    """Run all offline environment checks and return structured result."""
    errors: list[str] = []
    python_info = _check_python()
    if not python_info["64bit"]:
        errors.append("Python interpreter is not 64-bit")
    if sys.version_info < (3, 9):
        errors.append(
            f"Python {sys.version_info.major}.{sys.version_info.minor} "
            f"is below 3.9"
        )
    packages = _check_packages()
    for pkg, ver in packages.items():
        if ver is None:
            errors.append(f"Package '{pkg}' failed to import")
        elif ver == "":
            # Imported OK but no __version__ attribute.
            pass
    config_checks = _check_configs()
    for check, passed in config_checks.items():
        if not passed:
            errors.append(f"Config check '{check}' failed")
    fs_checks = _check_filesystem()
    for check, passed in fs_checks.items():
        if not passed:
            errors.append(f"Filesystem check '{check}' failed")
    duckdb_check = _check_duckdb()
    if not duckdb_check.get("select_1"):
        errors.append("DuckDB memory SELECT 1 failed")
    resolved_date, came_from_system = _check_as_of_date(cli_date)
    if came_from_system:
        errors.append("as_of_date fell back to system date (forbidden)")
    if resolved_date is None:
        errors.append("as_of_date could not be resolved")
    status = "pass" if not errors else "fail"
    return DoctorResult(
        status=status,
        checked_at=datetime.now(timezone.utc).isoformat(),
        python=python_info,
        packages=packages,
        config_checks=config_checks,
        filesystem_checks=fs_checks,
        duckdb_check=duckdb_check,
        resolved_as_of_date=resolved_date,
        errors=errors,
    )

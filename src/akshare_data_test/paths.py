"""Project path definitions — not dependent on cwd."""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def project_root() -> Path:
    """Return the project root directory."""
    return _PROJECT_ROOT


def config_dir() -> Path:
    return _PROJECT_ROOT / "config"


def data_dir() -> Path:
    return _PROJECT_ROOT / "data"


def database_dir() -> Path:
    return _PROJECT_ROOT / "database"


def logs_dir() -> Path:
    return _PROJECT_ROOT / "logs"


def reports_dir() -> Path:
    return _PROJECT_ROOT / "reports"


def sql_dir() -> Path:
    return _PROJECT_ROOT / "sql"


def universe_path() -> Path:
    return config_dir() / "universe.yml"


def metric_definition_path() -> Path:
    return config_dir() / "metric_definition.yml"

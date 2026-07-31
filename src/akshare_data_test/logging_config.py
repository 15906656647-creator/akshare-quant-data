"""Minimal logging setup — no secrets in logs."""
import logging
import os
import sys

from .paths import logs_dir

_log_initialized = False


class SafeConsoleHandler(logging.StreamHandler):
    """Console handler that tolerates wrapper-owned stream shutdown."""

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (OSError, ValueError, BrokenPipeError)):
            return
        super().handleError(record)


def setup_logging(level: str | None = None, log_to_file: bool = False) -> None:
    """Configure root logger for the akshare_data_test package.

    Safe to call multiple times; duplicate handlers are prevented.
    """
    global _log_initialized
    if _log_initialized:
        return

    resolved_level = level or os.environ.get("AKSHARE_LOG_LEVEL", "INFO")
    numeric_level = getattr(logging, resolved_level.upper(), logging.INFO)

    root_logger = logging.getLogger("akshare_data_test")
    root_logger.setLevel(numeric_level)

    if root_logger.handlers:
        _log_initialized = True
        return

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = SafeConsoleHandler()
    console.setLevel(numeric_level)
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    if log_to_file:
        logs_dir().mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(
            logs_dir() / "pipeline.log", encoding="utf-8"
        )
        fh.setLevel(numeric_level)
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)

    _log_initialized = True

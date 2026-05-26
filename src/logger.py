"""Lightweight stage logger for terminal progress feedback.

A thin wrapper over :mod:`logging` so the rest of the codebase can emit
progress lines without each module having to configure handlers. The CLI
scripts call :func:`setup_logging` once at startup; library code calls
:func:`get_logger` and uses the returned logger.

The logger is intentionally minimal — stdlib only, no colorama or rich. The
format favours readability over machine parsing because the audience is the
end user watching the terminal.
"""
from __future__ import annotations

import logging
import sys

LOGGER_NAME = "tcc"
_DEFAULT_FORMAT = "[%(asctime)s] %(message)s"
_DEFAULT_DATEFMT = "%H:%M:%S"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Install a single stderr handler on the package logger.

    Safe to call multiple times: the handler is only attached if missing.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    """Return the package logger (no handler is installed if absent)."""
    return logging.getLogger(LOGGER_NAME)

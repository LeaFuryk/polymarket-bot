"""logging — Trade and resolution JSONL logging, root logger setup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from polybot.logging.constants import (
    DATE_FORMAT,
    LOG_FILE_EXTENSION,
    RESOLUTION_LOG_PREFIX,
    TRADE_LOG_PREFIX,
)
from polybot.logging.trade_log import TradeLog

if TYPE_CHECKING:
    from polybot.config import AppConfig

__all__ = [
    "DATE_FORMAT",
    "LOG_FILE_EXTENSION",
    "RESOLUTION_LOG_PREFIX",
    "TRADE_LOG_PREFIX",
    "TradeLog",
    "create_logger",
]


def create_logger(
    config: AppConfig,
    name: str = __name__,
    logger: logging.Logger | None = None,
) -> logging.Logger:
    """Set up root logging handlers and return a logger.

    Configures file and optional console handlers on the root logger, then
    returns *logger* if provided or a new logger for *name*.
    """
    _setup_logging(config)
    return logger or logging.getLogger(name)


def _setup_logging(config: AppConfig) -> None:
    """Configure the root logger with a file handler and optional console handler.

    Creates the log directory if needed.  Console output is suppressed when the
    Rich dashboard is enabled (it owns stdout).
    """
    log_dir = Path(config.logging.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(log_dir / "polybot.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (only if dashboard is off — dashboard replaces stdout)
    if not config.logging.dashboard_enabled:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)

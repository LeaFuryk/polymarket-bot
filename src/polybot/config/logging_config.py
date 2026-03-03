"""Logging output, SQLite storage, and dashboard settings.

Named ``logging_config`` to avoid shadowing the stdlib :mod:`logging` module.
"""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_DASHBOARD_REFRESH_RATE,
    DEFAULT_KNOWLEDGE_DIR,
    DEFAULT_LOG_DIR,
    DEFAULT_MARKET_HISTORY_DB_PATH,
    DEFAULT_SQLITE_DB_PATH,
    DEFAULT_WS_PORT,
)


class LoggingConfig(BaseModel):
    """Logging output, SQLite storage, and dashboard settings."""

    log_dir: str = DEFAULT_LOG_DIR
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR
    jsonl_enabled: bool = True
    sqlite_enabled: bool = True
    sqlite_db_path: str = DEFAULT_SQLITE_DB_PATH
    market_history_db_path: str = DEFAULT_MARKET_HISTORY_DB_PATH
    dashboard_enabled: bool = True
    dashboard_refresh_rate: int = DEFAULT_DASHBOARD_REFRESH_RATE
    ws_enabled: bool = True
    ws_port: int = DEFAULT_WS_PORT

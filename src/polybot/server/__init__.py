"""Polybot forensics server — FastAPI real-time API."""

from polybot.server.constants import (
    APP_TITLE,
    DB_ENV_VAR,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    SSE_POLL_INTERVAL_SECONDS,
)
from polybot.server.run import main

__all__ = [
    "APP_TITLE",
    "DB_ENV_VAR",
    "DEFAULT_DB_PATH",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "SSE_HEADERS",
    "SSE_MEDIA_TYPE",
    "SSE_POLL_INTERVAL_SECONDS",
    "main",
]


# Lazy import: app requires FastAPI (optional dependency)
def __getattr__(name: str):
    if name == "app":
        from polybot.server.app import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

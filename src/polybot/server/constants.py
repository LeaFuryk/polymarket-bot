"""Server module constants."""

# Environment variable for database path
DB_ENV_VAR: str = "POLYBOT_DB"

# Default database path
DEFAULT_DB_PATH: str = "logs/polybot.db"

# FastAPI application title
APP_TITLE: str = "Polybot Forensics API"

# SSE poll interval in seconds
SSE_POLL_INTERVAL_SECONDS: float = 2.0

# Default server bind host
DEFAULT_HOST: str = "0.0.0.0"

# Default server bind port
DEFAULT_PORT: int = 8888

# SSE response headers
SSE_MEDIA_TYPE: str = "text/event-stream"
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

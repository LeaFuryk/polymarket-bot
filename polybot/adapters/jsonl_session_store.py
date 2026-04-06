"""Adapter: append session summaries as JSON lines."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path


class JsonlSessionStore:
    """Appends one JSON line per session to a file."""

    def __init__(self, path: str, logger: logging.Logger | None = None) -> None:
        self._path = Path(path)
        self._log = logger or logging.getLogger(__name__)

    async def save_session(self, summary: dict) -> None:
        entry = {**summary, "timestamp": time.time()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._log.info("Session saved to %s", self._path)

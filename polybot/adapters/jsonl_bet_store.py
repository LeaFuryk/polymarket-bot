"""Adapter: append bet records as JSON lines. New file per session."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from polybot.domain.bet_record import BetRecord
from polybot.ports.bet_store import BetStore


class JsonlBetStore(BetStore):
    """Appends one JSON line per bet to a session-specific file."""

    def __init__(self, directory: str = "data/bets", logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger(__name__)
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"bets_{ts}.jsonl"
        self._log.info("Bet store: %s", self._path)

    async def save_bet(self, record: BetRecord) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

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

    async def update_bet(self, candle_id: str, new_outcome: str, new_won: bool, new_pnl: float) -> None:
        """Rewrite the bet for *candle_id* with corrected outcome/pnl."""
        if not self._path.exists():
            self._log.warning("Cannot update bet — file not found: %s", self._path)
            return

        lines = self._path.read_text().splitlines()
        updated = False
        for i, line in enumerate(lines):
            record = json.loads(line)
            if record.get("candle_id") == candle_id:
                record["outcome"] = new_outcome
                record["won"] = new_won
                record["pnl"] = new_pnl
                lines[i] = json.dumps(record)
                updated = True
                break

        if updated:
            self._path.write_text("\n".join(lines) + "\n")
            self._log.info("🔄 Bet updated | %s | outcome=%s pnl=$%+.2f", candle_id, new_outcome, new_pnl)
        else:
            self._log.warning("Cannot update bet — candle_id %s not found in %s", candle_id, self._path)

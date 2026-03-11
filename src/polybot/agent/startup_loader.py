"""Startup data loading — reads persisted state from disk before AgentContext is built."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from polybot.agent.helpers import enrich_iteration_summary
from polybot.utils import read_json, read_jsonl

if TYPE_CHECKING:
    from polybot.config import AppConfig


@dataclass
class StartupData:
    """Data loaded from disk at startup, before AgentContext is built."""

    resolutions_since_reflection: int = 0
    knowledge_state: dict = field(default_factory=dict)
    historical_resolutions: list[dict] = field(default_factory=list)
    historical_trades: list[dict] = field(default_factory=list)
    iteration_summaries: list[dict] = field(default_factory=list)
    iteration_label: str = "iter_001"


class StartupLoader:
    """Loads persisted state from disk before AgentContext is built.

    Reads five sources and packs them into a :class:`StartupData`:
      1. ``agent_state.json``  → resolutions_since_reflection, knowledge_state
      2. ``resolutions_*.jsonl`` → historical_resolutions
      3. ``trades_*.jsonl``      → historical_trades
      4. ``archive/*/summary.json`` → iteration_summaries
      5. ``archive/iter_*`` dirs    → iteration_label
    """

    def __init__(self, config: AppConfig, log: logging.Logger) -> None:
        self._log_dir = Path(config.logging.log_dir)
        self._log = log

    def load(self) -> StartupData:
        """Return a fully-populated :class:`StartupData`."""
        resolutions_since, knowledge = self._load_agent_state()
        return StartupData(
            resolutions_since_reflection=resolutions_since,
            knowledge_state=knowledge,
            historical_resolutions=self._load_resolutions(),
            historical_trades=self._load_trades(),
            iteration_summaries=self._load_iteration_summaries(),
            iteration_label=self._compute_iteration_label(),
        )

    def _load_agent_state(self) -> tuple[int, dict]:
        """Load ``agent_state.json`` from the log directory."""
        raw = read_json(self._log_dir, "agent_state.json", self._log)
        if raw is None:
            return 0, {}
        resolutions = raw.get("resolutions_since_reflection", 0)
        knowledge = raw.get("knowledge", {})
        self._log.info("Loaded agent state: resolutions_since_reflection=%d", resolutions)
        return resolutions, knowledge

    def _load_resolutions(self) -> list[dict]:
        """Parse ``resolutions_*.jsonl`` from the log directory."""
        records = read_jsonl(self._log_dir, "resolutions_*.jsonl", self._log)
        resolutions = [
            {
                "timestamp": datetime.fromtimestamp(r.get("timestamp", 0), tz=UTC).isoformat(),
                "slug": r.get("slug", ""),
                "winner": r.get("winner", ""),
                "btc_open": r.get("btc_open", 0),
                "btc_close": r.get("btc_close", 0),
                "btc_move": r.get("btc_close", 0) - r.get("btc_open", 0),
                "pnl": r.get("total_pnl", 0),
            }
            for r in records
        ]
        if resolutions:
            self._log.info("Loaded %d historical resolutions from logs", len(resolutions))
        return resolutions

    def _load_trades(self) -> list[dict]:
        """Parse ``trades_*.jsonl`` from the log directory."""
        records = read_jsonl(self._log_dir, "trades_*.jsonl", self._log)
        trades = [
            {
                "timestamp": datetime.fromtimestamp(t.get("timestamp", 0), tz=UTC).isoformat(),
                "cycle": t.get("cycle_number", 0),
                "action": t.get("action", "HOLD"),
                "token_side": t.get("token_side", "up"),
                "size": t.get("decision_size", 0),
                "fill_price": t.get("fill_price"),
                "confidence": t.get("confidence", 0),
                "reasoning": t.get("reasoning", ""),
                "market_view": t.get("market_view", ""),
                "candle_slug": t.get("candle_slug", ""),
                "polymarket_url": (
                    f"https://polymarket.com/event/{t.get('candle_slug', '')}" if t.get("candle_slug") else ""
                ),
                "time_remaining_at_trade": t.get("extra", {}).get("time_remaining", 0),
                "risk_blocked": t.get("risk_blocked", False),
                "risk_block_reason": t.get("risk_block_reason", ""),
                "cash": t.get("cash"),
                "portfolio_value": t.get("portfolio_value"),
                "fee": t.get("fee_amount", 0),
                "realized_pnl": t.get("realized_pnl", 0),
                "unrealized_pnl": t.get("unrealized_pnl", 0),
                "ai_cost": t.get("ai_cost", 0),
                "live_order": t.get("extra", {}).get("live_order"),
            }
            for t in records
        ]
        if trades:
            self._log.info("Loaded %d historical trades from logs", len(trades))
        return trades

    def _load_iteration_summaries(self) -> list[dict]:
        """Load and enrich all archived iteration summaries from ``archive/*/summary.json``."""
        archive_dir = self._log_dir.parent / "archive"
        summaries: list[dict] = []
        if not archive_dir.exists():
            return summaries
        for iter_dir in sorted(d for d in archive_dir.iterdir() if d.is_dir()):
            data = read_json(iter_dir, "summary.json", self._log)
            if data is None:
                continue
            dd = read_json(iter_dir / "logs", "dashboard_data.json", self._log)
            if dd is not None:
                enrich_iteration_summary(data, dd, iter_dir)
            summaries.append(data)
        if summaries:
            self._log.info("Loaded %d iteration summaries from archive", len(summaries))
        return summaries

    def _compute_iteration_label(self) -> str:
        """Determine the current iteration label from the ``archive/`` directory."""
        archive_dir = self._log_dir.parent / "archive"
        if not archive_dir.exists():
            return "iter_001"
        existing = sorted(d.name for d in archive_dir.iterdir() if d.is_dir() and d.name.startswith("iter_"))
        if not existing:
            return "iter_001"
        last_num = max(int(d.split("_")[1]) for d in existing)
        return f"iter_{last_num + 1:03d}"

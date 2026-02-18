"""Feedback learning system — loads knowledge files and runs periodic reflection."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import anthropic

from polybot.config import AiConfig
from polybot.models import ResolutionRecord, TradeRecord

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """\
You are reviewing recent trading outcomes for a Polymarket BTC 5-minute candle bot.

Analyze the resolutions and trades below, then produce updated knowledge files.

## Recent Resolutions
{resolutions_table}

## Recent Trades (with fills)
{trades_table}

## Current Knowledge Files
### trading_patterns.md
{trading_patterns}

### self_assessment.md
{self_assessment}

### session_history.md
{session_history}

## Current Feature Config
```json
{feature_config_json}
```

## Instructions
1. Analyze W/L patterns — what market conditions led to wins vs losses?
2. Identify recurring mistakes or biases (overtrading, side preference, confidence miscalibration).
3. Note any market behavior patterns (BTC momentum, spread dynamics, token pricing quirks).
4. Keep each file concise (< 100 lines).
5. For session_history, append ONE new entry summarizing this batch. Keep only the last ~20 entries.
6. Review the feature config above:
   - If an indicator's signal correlates with wins, keep it enabled.
   - If a disabled indicator could help diagnose a pattern you see, enable it.
   - If an indicator seems noisy or uncorrelated with outcomes, disable it.
   - You may adjust param values (e.g. window sizes) if you see a reason.
   - Change at most 2 indicator settings per reflection cycle.

Return valid JSON with these keys:
- "trading_patterns": full updated markdown content for trading_patterns.md
- "self_assessment": full updated markdown content for self_assessment.md
- "session_history": full updated markdown content for session_history.md
- "feature_config": (optional) updated feature config object — only include if you want to change indicator settings

Return ONLY the JSON object, no other text.
"""


class KnowledgeManager:
    """Loads knowledge files and runs periodic Claude reflection to update them."""

    def __init__(self, knowledge_dir: str, ai_config: AiConfig) -> None:
        self._dir = Path(knowledge_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ai_config = ai_config
        self._client = anthropic.AsyncAnthropic(api_key=ai_config.api_key)
        self._feature_config_path = self._dir.parent / "feature_config.json"

        # Cache
        self._cache: str | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 60.0

    def load_knowledge(self) -> str:
        """Read all .md files in knowledge_dir, concatenate, cache for 60s."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        parts: list[str] = []
        for md_file in sorted(self._dir.glob("*.md")):
            try:
                content = md_file.read_text().strip()
                if content:
                    parts.append(content)
            except OSError:
                logger.warning("Could not read knowledge file: %s", md_file)

        self._cache = "\n\n---\n\n".join(parts) if parts else ""
        self._cache_time = now
        return self._cache

    def build_feedback_context(
        self,
        resolutions: list[ResolutionRecord],
        session_wins: int,
        session_losses: int,
        session_pnl: float,
    ) -> str:
        """Combine knowledge files + recent resolutions into a prompt block."""
        knowledge = self.load_knowledge()

        lines: list[str] = []

        # Session stats
        total = session_wins + session_losses
        win_rate = (session_wins / total * 100) if total > 0 else 0.0
        lines.append(f"Session: {session_wins}W/{session_losses}L ({win_rate:.0f}% win rate) | PnL: ${session_pnl:+.4f}")
        lines.append("")

        # Last 10 resolutions as compact table
        if resolutions:
            recent = resolutions[-10:]
            lines.append("Recent resolutions:")
            lines.append("| Slug | Winner | BTC Move | PnL |")
            lines.append("|------|--------|----------|-----|")
            for r in recent:
                btc_move = r.btc_close - r.btc_open
                lines.append(
                    f"| {r.slug[-20:]} | {r.winner} | ${btc_move:+.0f} | ${r.total_pnl:+.4f} |"
                )
            lines.append("")

        # Knowledge from .md files
        if knowledge:
            lines.append("Learnings from past sessions:")
            lines.append(knowledge)

        return "\n".join(lines)

    async def reflect(
        self,
        resolutions: list[ResolutionRecord],
        trades: list[TradeRecord],
    ) -> None:
        """Call Claude to analyze recent outcomes and update knowledge files."""
        if not resolutions:
            return

        logger.info("Running reflection on %d resolutions, %d trades", len(resolutions), len(trades))

        # Build resolution table
        res_lines = ["| Slug | Winner | BTC Open | BTC Close | PnL |"]
        res_lines.append("|------|--------|----------|-----------|-----|")
        for r in resolutions:
            res_lines.append(
                f"| {r.slug} | {r.winner} | ${r.btc_open:.0f} | ${r.btc_close:.0f} | ${r.total_pnl:+.4f} |"
            )
        resolutions_table = "\n".join(res_lines)

        # Build trades table
        trade_lines = ["| Cycle | Action | Side | Size | Confidence | Fill Price | Reasoning |"]
        trade_lines.append("|-------|--------|------|------|------------|------------|-----------|")
        for t in trades[-20:]:
            trade_lines.append(
                f"| {t.cycle_number} | {t.action.value} | {t.token_side.value} | {t.decision_size:.1f} "
                f"| {t.confidence:.2f} | {t.fill_price or 'N/A'} | {t.reasoning[:60]} |"
            )
        trades_table = "\n".join(trade_lines)

        # Read current knowledge files
        trading_patterns = self._read_file("trading_patterns.md")
        self_assessment = self._read_file("self_assessment.md")
        session_history = self._read_file("session_history.md")

        # Read current feature config
        feature_config_json = "{}"
        try:
            if self._feature_config_path.exists():
                feature_config_json = self._feature_config_path.read_text()
        except OSError:
            pass

        prompt = REFLECTION_PROMPT.format(
            resolutions_table=resolutions_table,
            trades_table=trades_table,
            trading_patterns=trading_patterns,
            self_assessment=self_assessment,
            session_history=session_history,
            feature_config_json=feature_config_json,
        )

        try:
            response = await self._client.messages.create(
                model=self._ai_config.model,
                max_tokens=2048,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text
            data = json.loads(text)

            # Write updated files
            if "trading_patterns" in data:
                self._write_file("trading_patterns.md", data["trading_patterns"])
            if "self_assessment" in data:
                self._write_file("self_assessment.md", data["self_assessment"])
            if "session_history" in data:
                self._write_file("session_history.md", data["session_history"])

            # Write updated feature config if returned
            if "feature_config" in data and isinstance(data["feature_config"], dict):
                try:
                    self._feature_config_path.write_text(
                        json.dumps(data["feature_config"], indent=2) + "\n"
                    )
                    logger.info("Reflection updated feature config at %s", self._feature_config_path)
                except OSError:
                    logger.warning("Could not write feature config")

            # Invalidate cache
            self._cache = None
            logger.info("Reflection complete — knowledge files updated")

        except json.JSONDecodeError:
            logger.exception("Reflection returned invalid JSON")
        except Exception:
            logger.exception("Reflection failed")

    def _read_file(self, name: str) -> str:
        path = self._dir / name
        try:
            return path.read_text()
        except OSError:
            return ""

    def _write_file(self, name: str, content: str) -> None:
        path = self._dir / name
        path.write_text(content)
        logger.debug("Updated knowledge file: %s", path)

"""Feedback learning system — structured observations, scorecard, and periodic reflection."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import anthropic

from polybot.config import AiConfig
from polybot.models import (
    Observation,
    ObservationCategory,
    ResolutionRecord,
    Scorecard,
    ScorecardDelta,
    TradeRecord,
)

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """\
You are reviewing recent trading outcomes for a Polymarket BTC 5-minute candle bot.

Your job: produce **descriptive observations** about what happened, NOT rules or imperatives.
Good: "momentum plays at entry 0.30-0.40 won 3/4 times"
Bad: "NEVER trade above 0.40" or "ALWAYS wait for confirmation"

## Scorecard (current batch vs previous)
{scorecard_text}

## Recent Resolutions
{resolutions_table}

## Recent Trades (with fills)
{trades_table}

{side_selection_analysis}

## Active Observations (with age and expiry)
{active_observations}

## Current Feature Config
```json
{feature_config_json}
```

## Instructions

1. Look at the scorecard delta — did things get better or worse? Why?
2. Look at individual resolutions + trades — what patterns explain wins/losses?
3. Pay attention to Side Selection Analysis — did the bot pick the wrong side when a cheap entry existed?
4. Produce 1-5 NEW descriptive observations. Each must be:
   - Descriptive, not imperative (what happened, not what to do)
   - Based on evidence from the data above
   - Categorized: "pattern", "bias", "edge", or "regime"
   - Given an expiry (default 30 resolutions, shorter for uncertain observations)
5. Review active observations — if any are contradicted by new data, expire them by ID.
6. Write a one-line session entry summarizing this batch.
7. Optionally adjust at most 2 indicator settings in feature_config.

## FORBIDDEN
- Do NOT write imperatives ("NEVER", "ALWAYS", "require X threshold")
- Do NOT reference specific dollar PnL amounts or session state
- Do NOT add confidence thresholds or volatility filters

Return valid JSON:
{{
  "observations": [
    {{"category": "pattern|bias|edge|regime", "text": "descriptive observation", "expires_after_resolutions": 30}}
  ],
  "expire_ids": ["id1", "id2"],
  "session_entry": "one-line summary of this batch",
  "feature_config": null
}}

Return ONLY the JSON object, no other text.
"""


def compute_scorecard(
    resolutions: list[ResolutionRecord],
    trades: list[TradeRecord],
) -> Scorecard:
    """Compute quantitative metrics from a batch of resolutions and trades."""
    if not resolutions:
        return Scorecard()

    # Count trades that had actual fills (not HOLDs)
    traded = [t for t in trades if t.fill_price is not None and t.action.value != "HOLD"]
    holds = [t for t in trades if t.action.value == "HOLD" or t.fill_price is None]

    # Win/loss from resolutions (only those with positions)
    wins = [r for r in resolutions if r.total_pnl > 0.001]
    losses = [r for r in resolutions if r.total_pnl < -0.001]
    total_with_position = len(wins) + len(losses)

    win_rate = len(wins) / total_with_position if total_with_position > 0 else 0.0

    # PnL stats
    win_pnls = [r.total_pnl for r in wins]
    loss_pnls = [r.total_pnl for r in losses]
    all_pnls = [r.total_pnl for r in resolutions if abs(r.total_pnl) > 0.001]

    avg_pnl = sum(all_pnls) / len(all_pnls) if all_pnls else 0.0
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

    # Hold rate: fraction of resolutions where we had no position
    flat_count = len(resolutions) - total_with_position
    hold_rate = flat_count / len(resolutions) if resolutions else 0.0

    return Scorecard(
        resolutions=len(resolutions),
        trades_taken=len(traded),
        win_rate=win_rate,
        avg_pnl_per_trade=avg_pnl,
        avg_win_size=avg_win,
        avg_loss_size=avg_loss,
        hold_rate=hold_rate,
    )


def format_scorecard(delta: ScorecardDelta) -> str:
    """Format scorecard with optional delta comparison."""
    c = delta.current
    lines = [
        "### Current Batch",
        f"- Resolutions: {c.resolutions}",
        f"- Trades taken: {c.trades_taken}",
        f"- Win rate: {c.win_rate:.0%}",
        f"- Avg PnL per traded resolution: ${c.avg_pnl_per_trade:+.4f}",
        f"- Avg win size: ${c.avg_win_size:+.4f}",
        f"- Avg loss size: ${c.avg_loss_size:+.4f}",
        f"- Hold rate: {c.hold_rate:.0%}",
    ]

    p = delta.previous
    if p is not None and p.resolutions > 0:
        lines.append("")
        lines.append("### Previous Batch (for comparison)")
        wr_delta = c.win_rate - p.win_rate
        pnl_delta = c.avg_pnl_per_trade - p.avg_pnl_per_trade
        lines.append(f"- Win rate: {p.win_rate:.0%} -> {c.win_rate:.0%} ({wr_delta:+.0%})")
        lines.append(f"- Avg PnL: ${p.avg_pnl_per_trade:+.4f} -> ${c.avg_pnl_per_trade:+.4f} (delta: ${pnl_delta:+.4f})")
        lines.append(f"- Trades taken: {p.trades_taken} -> {c.trades_taken}")
        hr_delta = c.hold_rate - p.hold_rate
        lines.append(f"- Hold rate: {p.hold_rate:.0%} -> {c.hold_rate:.0%} ({hr_delta:+.0%})")
    else:
        lines.append("")
        lines.append("### Previous Batch")
        lines.append("(no previous batch — this is the first reflection)")

    return "\n".join(lines)


class KnowledgeManager:
    """Loads knowledge files and runs periodic Claude reflection with structured observations."""

    def __init__(self, knowledge_dir: str, ai_config: AiConfig) -> None:
        self._dir = Path(knowledge_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ai_config = ai_config
        self._client = anthropic.AsyncAnthropic(api_key=ai_config.api_key)
        self._feature_config_path = self._dir.parent / "feature_config.json"
        self._observations_path = self._dir / "observations.jsonl"
        self._session_history_path = self._dir / "session_history.md"

        # Cache for base knowledge (read-only .md files)
        self._cache: str | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 60.0

        # State persisted across sessions via agent_state.json
        self._previous_scorecard: Scorecard | None = None
        self._total_resolutions: int = 0

        # API cost tracking
        self.last_reflection_cost: float = 0.0
        self.total_api_cost: float = 0.0

    # --- State Persistence ---

    def save_state(self) -> dict:
        """Return state dict for persistence in agent_state.json."""
        return {
            "total_resolutions": self._total_resolutions,
            "previous_scorecard": (
                self._previous_scorecard.model_dump()
                if self._previous_scorecard
                else None
            ),
        }

    def load_state(self, data: dict) -> None:
        """Restore state from agent_state.json."""
        self._total_resolutions = data.get("total_resolutions", 0)
        sc_data = data.get("previous_scorecard")
        if sc_data:
            self._previous_scorecard = Scorecard(**sc_data)
        logger.info(
            "Knowledge state loaded: total_resolutions=%d, has_previous_scorecard=%s",
            self._total_resolutions,
            self._previous_scorecard is not None,
        )

    # --- Base Knowledge (read-only .md files) ---

    def _load_base_knowledge(self) -> str:
        """Read base knowledge .md files (trading_patterns, self_assessment). Cached."""
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        base_files = ["trading_patterns.md", "self_assessment.md"]
        parts: list[str] = []
        for name in base_files:
            path = self._dir / name
            try:
                content = path.read_text().strip()
                if content:
                    parts.append(content)
            except OSError:
                logger.debug("Could not read base knowledge file: %s", path)

        self._cache = "\n\n---\n\n".join(parts) if parts else ""
        self._cache_time = now
        return self._cache

    # --- Observation Management ---

    def load_active_observations(self) -> list[Observation]:
        """Read observations.jsonl, filter out expired ones by resolution count."""
        if not self._observations_path.exists():
            return []

        active: list[Observation] = []
        try:
            text = self._observations_path.read_text().strip()
            if not text:
                return []
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                obs = Observation(**json.loads(line))
                # Check expiry: created_at + expires_after <= current total
                age = self._total_resolutions - obs.resolution_count_at_creation
                if age < obs.expires_after_resolutions:
                    active.append(obs)
        except Exception:
            logger.warning("Could not load observations", exc_info=True)

        return active

    def _append_observation(self, obs: Observation) -> None:
        """Append one observation to observations.jsonl."""
        try:
            with self._observations_path.open("a") as f:
                f.write(obs.model_dump_json() + "\n")
        except OSError:
            logger.warning("Could not append observation")

    def _expire_observations(self, ids: list[str]) -> None:
        """Remove specific observation IDs from the file."""
        if not ids or not self._observations_path.exists():
            return

        id_set = set(ids)
        try:
            lines = self._observations_path.read_text().strip().split("\n")
            kept = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("id") not in id_set:
                    kept.append(line)
            self._observations_path.write_text("\n".join(kept) + "\n" if kept else "")
            logger.info("Expired %d observations by ID", len(id_set) - len(kept) + len(lines) - len(kept))
        except Exception:
            logger.warning("Could not expire observations", exc_info=True)

    def _compact_observations(self) -> None:
        """Remove naturally expired observations from the file."""
        if not self._observations_path.exists():
            return

        try:
            lines = self._observations_path.read_text().strip().split("\n")
            kept = []
            removed = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                age = self._total_resolutions - data.get("resolution_count_at_creation", 0)
                if age < data.get("expires_after_resolutions", 30):
                    kept.append(line)
                else:
                    removed += 1
            if removed > 0:
                self._observations_path.write_text("\n".join(kept) + "\n" if kept else "")
                logger.info("Compacted %d expired observations", removed)
        except Exception:
            logger.warning("Could not compact observations", exc_info=True)

    # --- Session History ---

    def _append_session_history(self, entry: str) -> None:
        """Append one row to session_history.md, keep last 20."""
        try:
            header = "# Session History\n\n| Date | Summary |\n|------|---------|"

            existing_rows: list[str] = []
            if self._session_history_path.exists():
                text = self._session_history_path.read_text().strip()
                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("|") and not line.startswith("| Date") and not line.startswith("|---"):
                        existing_rows.append(line)

            # Add new row
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            new_row = f"| {date_str} | {entry} |"
            existing_rows.append(new_row)

            # Keep last 20
            existing_rows = existing_rows[-20:]

            content = header + "\n" + "\n".join(existing_rows) + "\n"
            self._session_history_path.write_text(content)
        except Exception:
            logger.warning("Could not append session history", exc_info=True)

    # --- Feedback Context (injected into decision prompt) ---

    def build_feedback_context(
        self,
        resolutions: list[ResolutionRecord],
        session_wins: int,
        session_losses: int,
        session_pnl: float,
        calibration_summary: str = "",
        recent_trades: list[TradeRecord] | None = None,
    ) -> str:
        """Combine base knowledge + active observations into a prompt block."""
        if recent_trades is None:
            recent_trades = []
        lines: list[str] = []

        # Session stats
        total = session_wins + session_losses
        win_rate = (session_wins / total * 100) if total > 0 else 0.0
        lines.append(f"Session: {session_wins}W/{session_losses}L ({win_rate:.0f}% win rate) | PnL: ${session_pnl:+.4f}")
        lines.append("")

        # Safeguard #5: Drawdown awareness — rolling drawdown from recent resolutions
        if resolutions:
            recent_10 = resolutions[-10:]
            rolling_pnl = sum(r.total_pnl for r in recent_10)
            if rolling_pnl < -5.0:
                lines.append(
                    f"## SESSION DRAWDOWN ALERT\n"
                    f"Last {len(recent_10)} resolutions: ${rolling_pnl:+.2f} net.\n"
                    f"Consider being more selective — prioritize high-conviction setups and smaller sizes."
                )
                if session_pnl < 0:
                    lines.append(f"Session overall: ${session_pnl:+.2f}")
                lines.append("")

        # Recent trade decisions with outcomes (so AI can learn from its own mistakes)
        if recent_trades:
            # Filter to trades with fills (BUY/SELL) and match to resolutions
            res_by_slug = {r.slug: r for r in resolutions}
            filled_trades = [
                t for t in recent_trades
                if t.action.value in ("BUY", "SELL") and t.fill_price
            ]
            if filled_trades:
                # Show last 10 trade decisions with outcomes
                recent_filled = filled_trades[-10:]
                up_trades = [t for t in filled_trades if t.token_side.value == "up" and t.action.value == "BUY"]
                down_trades = [t for t in filled_trades if t.token_side.value == "down" and t.action.value == "BUY"]
                up_wins = sum(1 for t in up_trades if res_by_slug.get(t.candle_slug, None) and res_by_slug[t.candle_slug].winner == "up")
                down_wins = sum(1 for t in down_trades if res_by_slug.get(t.candle_slug, None) and res_by_slug[t.candle_slug].winner == "down")
                lines.append(f"Your trade record: UP buys {up_wins}W/{len(up_trades)-up_wins}L | DOWN buys {down_wins}W/{len(down_trades)-down_wins}L")

                # Per-side accuracy context (learning, not avoidance)
                up_total = len(up_trades)
                down_total = len(down_trades)
                up_wr = up_wins / up_total if up_total >= 3 else None
                down_wr = down_wins / down_total if down_total >= 3 else None

                if up_wr is not None and up_wr < 0.50:
                    lines.append(f"  Note: UP accuracy is {up_wr:.0%} — review the trades below to find patterns (entry too late? wrong signal?). Do NOT avoid UP trades entirely; fix the entry criteria instead.")
                if down_wr is not None and down_wr < 0.50:
                    lines.append(f"  Note: DOWN accuracy is {down_wr:.0%} — review the trades below to find patterns (entry too late? wrong signal?). Do NOT avoid DOWN trades entirely; fix the entry criteria instead.")

                # Safeguard #8: Losing streak detection from resolved trades
                resolved_buys = [
                    t for t in filled_trades
                    if t.action.value == "BUY" and res_by_slug.get(t.candle_slug)
                ]
                if resolved_buys:
                    streak = 0
                    for t in reversed(resolved_buys):
                        res = res_by_slug[t.candle_slug]
                        if t.token_side.value != res.winner:
                            streak += 1
                        else:
                            break
                    if streak >= 3:
                        lines.append(
                            f"  Note: {streak}-trade losing streak. Review WHY these lost (bad timing? wrong side? weak signal?) "
                            f"and adjust entry criteria. A streak does NOT mean you should stop trading — it means something about your entries needs fixing."
                        )

                lines.append("")
                lines.append("Your recent trades and outcomes:")
                lines.append("| Token | Entry | Opp Ask | Signal | Winner | Result |")
                lines.append("|-------|-------|---------|--------|--------|--------|")
                expensive_side_losses = 0
                expensive_side_total = 0
                for t in recent_filled:
                    res = res_by_slug.get(t.candle_slug)
                    if res:
                        won = t.token_side.value == res.winner
                        result = "WIN" if won else "LOSS"
                    else:
                        result = "pending"
                    opp = t.extra.get("opposite_ask")
                    opp_str = f"${opp:.2f}" if opp is not None else "—"
                    sig = t.extra.get("signal_type", "—")
                    lines.append(
                        f"| {t.action.value} {t.token_side.value.upper()} | {t.fill_price:.4f} "
                        f"| {opp_str} | {sig} | {res.winner if res else '?'} | {result} |"
                    )
                    # Track expensive-side pattern in uncertain/contrarian markets
                    if (
                        t.action.value == "BUY"
                        and t.fill_price > 0.55
                        and opp is not None
                        and opp < 0.40
                        and sig in ("UNCERTAIN", "CONTRARIAN")
                        and res
                    ):
                        expensive_side_total += 1
                        if not won:
                            expensive_side_losses += 1
                lines.append("")
                # Pattern warning: expensive-side buying in uncertain markets
                if expensive_side_total >= 2:
                    lines.append(
                        f"  !! Pattern: {expensive_side_losses}/{expensive_side_total} losses from buying "
                        f"expensive side (>$0.55) when cheap side was <$0.40 in uncertain markets. "
                        f"The cheap side had better EV."
                    )
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

        # Confidence calibration data
        if calibration_summary:
            lines.append(calibration_summary)
            lines.append("")

        # Base knowledge (read-only, human-curated)
        base = self._load_base_knowledge()
        if base:
            lines.append("## Strategy & Bias Notes (reference)")
            lines.append(base)
            lines.append("")

        # Active observations (contextual hints from reflection)
        observations = self.load_active_observations()
        if observations:
            lines.append("## Recent Observations (contextual hints, not hard rules)")
            for obs in observations:
                age = self._total_resolutions - obs.resolution_count_at_creation
                remaining = obs.expires_after_resolutions - age
                lines.append(
                    f"- [{obs.category.value}] {obs.text} "
                    f"(observed {age} resolutions ago, expires in {remaining})"
                )

        return "\n".join(lines)

    # --- Reflection ---

    async def reflect(
        self,
        resolutions: list[ResolutionRecord],
        trades: list[TradeRecord],
    ) -> None:
        """Call Claude to analyze recent outcomes and produce structured observations."""
        if not resolutions:
            return

        logger.info("Running reflection on %d resolutions, %d trades", len(resolutions), len(trades))

        # Update resolution counter
        self._total_resolutions += len(resolutions)

        # Compact expired observations before reflection
        self._compact_observations()

        # Compute scorecard
        current_scorecard = compute_scorecard(resolutions, trades)
        delta = ScorecardDelta(current=current_scorecard, previous=self._previous_scorecard)
        scorecard_text = format_scorecard(delta)

        # Build resolution table
        res_lines = ["| Slug | Winner | BTC Open | BTC Close | PnL |"]
        res_lines.append("|------|--------|----------|-----------|-----|")
        for r in resolutions:
            res_lines.append(
                f"| {r.slug} | {r.winner} | ${r.btc_open:.0f} | ${r.btc_close:.0f} | ${r.total_pnl:+.4f} |"
            )
        resolutions_table = "\n".join(res_lines)

        # Build trades table (with opposite-side context for side-selection learning)
        trade_lines = ["| Cycle | Action | Side | Fill | Opp Ask | Signal | Conf | Reasoning |"]
        trade_lines.append("|-------|--------|------|------|---------|--------|------|-----------|")
        for t in trades[-20:]:
            opp = t.extra.get("opposite_ask")
            opp_str = f"${opp:.2f}" if opp is not None else "—"
            sig = t.extra.get("signal_type", "—")
            trade_lines.append(
                f"| {t.cycle_number} | {t.action.value} | {t.token_side.value} | {t.fill_price or 'N/A'} "
                f"| {opp_str} | {sig} | {t.confidence:.2f} | {t.reasoning[:60]} |"
            )
        trades_table = "\n".join(trade_lines)

        # Side selection analysis — flag trades that bought expensive side
        # when cheap opposite existed in uncertain/contrarian markets
        res_by_slug_refl = {r.slug: r for r in resolutions}
        side_flags = []
        for t in trades[-20:]:
            if t.action.value != "BUY" or t.fill_price is None:
                continue
            opp = t.extra.get("opposite_ask")
            sig = t.extra.get("signal_type")
            rev = t.extra.get("reversal_rate")
            if opp is None or sig is None:
                continue
            if t.fill_price > 0.55 and opp < 0.40 and sig in ("UNCERTAIN", "CONTRARIAN"):
                res = res_by_slug_refl.get(t.candle_slug)
                outcome = "?"
                if res:
                    outcome = "WIN" if t.token_side.value == res.winner else "LOSS"
                rev_str = f"rev={rev:.0%}" if rev is not None else ""
                side_flags.append(
                    f"- BUY {t.token_side.value.upper()} @ ${t.fill_price:.2f} "
                    f"({('DOWN' if t.token_side.value == 'up' else 'UP')} was ${opp:.2f}) "
                    f"| {sig} ({rev_str}) | {outcome}"
                )
        if side_flags:
            side_selection_analysis = (
                "## Side Selection Analysis\n"
                "Trades that bought the expensive side (>$0.55) when the opposite was cheap (<$0.40) "
                "in uncertain/contrarian markets:\n"
                + "\n".join(side_flags)
            )
        else:
            side_selection_analysis = ""

        # Active observations with IDs for possible expiry
        active_obs = self.load_active_observations()
        if active_obs:
            obs_lines = []
            for obs in active_obs:
                age = self._total_resolutions - obs.resolution_count_at_creation
                remaining = obs.expires_after_resolutions - age
                obs_lines.append(
                    f"- ID={obs.id} [{obs.category.value}] {obs.text} "
                    f"(age: {age} resolutions, expires in {remaining})"
                )
            active_observations = "\n".join(obs_lines)
        else:
            active_observations = "(none yet — this is the first reflection)"

        # Read current feature config
        feature_config_json = "{}"
        try:
            if self._feature_config_path.exists():
                feature_config_json = self._feature_config_path.read_text()
        except OSError:
            pass

        prompt = REFLECTION_PROMPT.format(
            scorecard_text=scorecard_text,
            resolutions_table=resolutions_table,
            trades_table=trades_table,
            side_selection_analysis=side_selection_analysis,
            active_observations=active_observations,
            feature_config_json=feature_config_json,
        )

        try:
            response = await self._client.messages.create(
                model=self._ai_config.model,
                max_tokens=4096,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

            # Compute reflection API cost
            input_cost = response.usage.input_tokens * (self._ai_config.input_cost_per_mtok / 1_000_000)
            output_cost = response.usage.output_tokens * (self._ai_config.output_cost_per_mtok / 1_000_000)
            self.last_reflection_cost = input_cost + output_cost
            self.total_api_cost += self.last_reflection_cost
            logger.info(
                "Reflection API cost: $%.4f (total: $%.4f) | tokens: %d in / %d out | stop_reason: %s",
                self.last_reflection_cost, self.total_api_cost,
                response.usage.input_tokens, response.usage.output_tokens,
                response.stop_reason,
            )

            if response.stop_reason == "max_tokens":
                logger.warning("Reflection output was truncated (hit max_tokens). Skipping parse.")
                return

            if not response.content:
                logger.warning("Reflection returned empty content")
                return

            text = response.content[0].text
            logger.debug("Reflection raw response (first 500 chars): %s", text[:500])

            # Strip markdown code fences
            stripped = text.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
                if stripped.endswith("```"):
                    stripped = stripped[:-3].strip()

            # Handle prefix text before JSON
            json_start = stripped.find("{")
            if json_start > 0:
                stripped = stripped[json_start:]

            if not stripped:
                logger.warning("Reflection response was empty after stripping")
                return

            data = json.loads(stripped)

            # Process observations
            new_obs_data = data.get("observations", [])
            added = 0
            for obs_data in new_obs_data[:5]:  # Cap at 5
                try:
                    cat = obs_data.get("category", "pattern")
                    # Validate category
                    if cat not in ("pattern", "bias", "edge", "regime"):
                        cat = "pattern"
                    obs = Observation(
                        category=ObservationCategory(cat),
                        text=obs_data.get("text", ""),
                        based_on_resolutions=len(resolutions),
                        resolution_count_at_creation=self._total_resolutions,
                        expires_after_resolutions=obs_data.get("expires_after_resolutions", 30),
                    )
                    if obs.text:
                        self._append_observation(obs)
                        added += 1
                except Exception:
                    logger.debug("Skipping invalid observation", exc_info=True)

            # Expire old observations
            expire_ids = data.get("expire_ids", [])
            if expire_ids:
                self._expire_observations(expire_ids)

            # Append session history entry
            session_entry = data.get("session_entry", "")
            if session_entry:
                self._append_session_history(session_entry)

            # Update feature config if returned
            fc = data.get("feature_config")
            if fc and isinstance(fc, dict):
                try:
                    self._feature_config_path.write_text(
                        json.dumps(fc, indent=2) + "\n"
                    )
                    logger.info("Updated feature config from reflection")
                except OSError:
                    logger.warning("Could not write feature config")

            # Save current scorecard as previous for next reflection
            self._previous_scorecard = current_scorecard

            # Invalidate cache
            self._cache = None

            logger.info(
                "Reflection complete — added %d observations, expired %d, session_entry=%s",
                added, len(expire_ids), bool(session_entry),
            )

        except json.JSONDecodeError as e:
            logger.error("Reflection returned invalid JSON: %s", e)
            logger.debug("Raw text (first 1000 chars): %s", stripped[:1000] if stripped else "(empty)")
            # Still save scorecard so next reflection has a comparison
            self._previous_scorecard = current_scorecard
        except Exception:
            logger.exception("Reflection failed")
            self._previous_scorecard = current_scorecard

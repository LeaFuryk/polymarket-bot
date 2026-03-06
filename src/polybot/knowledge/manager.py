"""Feedback learning system — structured observations, scorecard, and periodic reflection."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC
from pathlib import Path

import anthropic

from polybot.config import AiConfig
from polybot.knowledge.constants import (
    BASE_KNOWLEDGE_FILES,
    CACHE_TTL_SECONDS,
    CHEAP_SIDE_THRESHOLD,
    DEFAULT_OBSERVATION_EXPIRY,
    DRAWDOWN_ALERT_THRESHOLD,
    EXPENSIVE_SIDE_THRESHOLD,
    FEATURE_CONFIG_FILENAME,
    LOSING_STREAK_THRESHOLD,
    MAX_NEW_OBSERVATIONS,
    MIN_EXPENSIVE_SIDE_TRADES,
    MIN_SIDE_SAMPLES,
    MIN_TRAILING_TRADES,
    OBSERVATIONS_FILENAME,
    RECENT_RESOLUTIONS_WINDOW,
    REFLECTION_MAX_TOKENS,
    REFLECTION_TEMPERATURE,
    SESSION_HISTORY_FILENAME,
    SESSION_HISTORY_MAX_ROWS,
    SIDE_ACCURACY_WARNING,
)
from polybot.knowledge.scorecard import compute_scorecard, format_scorecard
from polybot.models import (
    Observation,
    ObservationCategory,
    ResolutionRecord,
    Scorecard,
    ScorecardDelta,
    TradeRecord,
)

_default_logger = logging.getLogger(__name__)

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


class KnowledgeManager:
    """Loads knowledge files and runs periodic Claude reflection with structured observations."""

    def __init__(
        self,
        knowledge_dir: str,
        ai_config: AiConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dir = Path(knowledge_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ai_config = ai_config
        self._client = anthropic.AsyncAnthropic(api_key=ai_config.api_key)
        self._logger = logger or _default_logger
        self._feature_config_path = self._dir.parent / FEATURE_CONFIG_FILENAME
        self._observations_path = self._dir / OBSERVATIONS_FILENAME
        self._session_history_path = self._dir / SESSION_HISTORY_FILENAME

        # Cache for base knowledge (read-only .md files)
        self._cache: str | None = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = CACHE_TTL_SECONDS

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
            "previous_scorecard": (self._previous_scorecard.model_dump() if self._previous_scorecard else None),
        }

    def load_state(self, data: dict) -> None:
        """Restore state from agent_state.json."""
        self._total_resolutions = data.get("total_resolutions", 0)
        sc_data = data.get("previous_scorecard")
        if sc_data:
            self._previous_scorecard = Scorecard(**sc_data)
        self._logger.info(
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

        parts: list[str] = []
        for name in BASE_KNOWLEDGE_FILES:
            path = self._dir / name
            try:
                content = path.read_text().strip()
                if content:
                    parts.append(content)
            except OSError:
                self._logger.debug("Could not read base knowledge file: %s", path)

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
            self._logger.warning("Could not load observations", exc_info=True)

        return active

    def _append_observation(self, obs: Observation) -> None:
        """Append one observation to observations.jsonl."""
        try:
            with self._observations_path.open("a") as f:
                f.write(obs.model_dump_json() + "\n")
        except OSError:
            self._logger.warning("Could not append observation")

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
            self._logger.info("Expired %d observations by ID", len(id_set) - len(kept) + len(lines) - len(kept))
        except Exception:
            self._logger.warning("Could not expire observations", exc_info=True)

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
                if age < data.get("expires_after_resolutions", DEFAULT_OBSERVATION_EXPIRY):
                    kept.append(line)
                else:
                    removed += 1
            if removed > 0:
                self._observations_path.write_text("\n".join(kept) + "\n" if kept else "")
                self._logger.info("Compacted %d expired observations", removed)
        except Exception:
            self._logger.warning("Could not compact observations", exc_info=True)

    # --- Session History ---

    def _append_session_history(self, entry: str) -> None:
        """Append one row to session_history.md, keep last N rows."""
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
            from datetime import datetime

            date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
            new_row = f"| {date_str} | {entry} |"
            existing_rows.append(new_row)

            # Keep last N
            existing_rows = existing_rows[-SESSION_HISTORY_MAX_ROWS:]

            content = header + "\n" + "\n".join(existing_rows) + "\n"
            self._session_history_path.write_text(content)
        except Exception:
            self._logger.warning("Could not append session history", exc_info=True)

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
        lines.append(
            f"Session: {session_wins}W/{session_losses}L ({win_rate:.0f}% win rate) | PnL: ${session_pnl:+.4f}"
        )
        lines.append("")

        # Safeguard #5: Drawdown awareness — rolling drawdown from recent resolutions
        if resolutions:
            recent_10 = resolutions[-RECENT_RESOLUTIONS_WINDOW:]
            rolling_pnl = sum(r.total_pnl for r in recent_10)
            if rolling_pnl < DRAWDOWN_ALERT_THRESHOLD:
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
            filled_trades = [t for t in recent_trades if t.action.value in ("BUY", "SELL") and t.fill_price]
            if filled_trades:
                # Show last 10 trade decisions with outcomes
                recent_filled = filled_trades[-RECENT_RESOLUTIONS_WINDOW:]

                # Resolved BUY trades (used for trailing records + losing streak)
                resolved_buys = [t for t in filled_trades if t.action.value == "BUY" and res_by_slug.get(t.candle_slug)]
                up_resolved = [t for t in resolved_buys if t.token_side.value == "up"]
                down_resolved = [t for t in resolved_buys if t.token_side.value == "down"]

                # Trailing window: show recent performance first to prevent anchoring on stale cumulative stats
                if len(resolved_buys) >= MIN_TRAILING_TRADES:
                    trailing = resolved_buys[-MIN_TRAILING_TRADES:]
                    t_wins = sum(1 for t in trailing if t.token_side.value == res_by_slug[t.candle_slug].winner)
                    t_losses = len(trailing) - t_wins
                    cum_wins = sum(1 for t in resolved_buys if t.token_side.value == res_by_slug[t.candle_slug].winner)
                    cum_losses = len(resolved_buys) - cum_wins
                    cum_wr = cum_wins / len(resolved_buys) * 100
                    lines.append(
                        f"Recent {MIN_TRAILING_TRADES} trades: {t_wins}W/{t_losses}L "
                        f"({t_wins / MIN_TRAILING_TRADES * 100:.0f}%) "
                        f"| Session: {cum_wins}W/{cum_losses}L ({cum_wr:.0f}%)"
                    )
                    # Per-side trailing (last 5 resolved per side)
                    side_parts = []
                    for label, side_list in [("UP", up_resolved), ("DOWN", down_resolved)]:
                        if side_list:
                            st = side_list[-MIN_TRAILING_TRADES:]
                            sw = sum(1 for t in st if t.token_side.value == res_by_slug[t.candle_slug].winner)
                            sl = len(st) - sw
                            side_parts.append(f"{label} recent {len(st)}: {sw}W/{sl}L ({sw / len(st):.0%})")
                    if side_parts:
                        lines.append(f"  {' | '.join(side_parts)}")
                else:
                    # Fall back to cumulative-only when <5 resolved trades
                    up_trades = [t for t in filled_trades if t.token_side.value == "up" and t.action.value == "BUY"]
                    down_trades = [t for t in filled_trades if t.token_side.value == "down" and t.action.value == "BUY"]
                    up_wins = sum(
                        1
                        for t in up_trades
                        if res_by_slug.get(t.candle_slug) and res_by_slug[t.candle_slug].winner == "up"
                    )
                    down_wins = sum(
                        1
                        for t in down_trades
                        if res_by_slug.get(t.candle_slug) and res_by_slug[t.candle_slug].winner == "down"
                    )
                    lines.append(
                        f"Your trade record: UP buys {up_wins}W/{len(up_trades) - up_wins}L "
                        f"| DOWN buys {down_wins}W/{len(down_trades) - down_wins}L"
                    )

                # Per-side accuracy context (learning, not avoidance)
                # Use trailing WR (last 5 per side) when ≥3 samples, else cumulative
                for label, side_list in [("UP", up_resolved), ("DOWN", down_resolved)]:
                    if len(side_list) >= MIN_SIDE_SAMPLES:
                        st = side_list[-MIN_TRAILING_TRADES:]
                        sw = sum(1 for t in st if t.token_side.value == res_by_slug[t.candle_slug].winner)
                        wr = sw / len(st)
                    else:
                        wr = None
                    if wr is not None and wr < SIDE_ACCURACY_WARNING:
                        lines.append(
                            f"  Note: {label} accuracy is {wr:.0%} (recent {len(side_list[-MIN_TRAILING_TRADES:])}) — review the trades below "
                            f"to find patterns (entry too late? wrong signal?). Do NOT avoid {label} trades entirely; "
                            f"fix the entry criteria instead."
                        )
                if resolved_buys:
                    streak = 0
                    for t in reversed(resolved_buys):
                        res = res_by_slug[t.candle_slug]
                        if t.token_side.value != res.winner:
                            streak += 1
                        else:
                            break
                    if streak >= LOSING_STREAK_THRESHOLD:
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
                    fp = t.fill_price or 0.0
                    lines.append(
                        f"| {t.action.value} {t.token_side.value.upper()} | {fp:.4f} "
                        f"| {opp_str} | {sig} | {res.winner if res else '?'} | {result} |"
                    )
                    # Track expensive-side pattern in uncertain/contrarian markets
                    if (
                        t.action.value == "BUY"
                        and t.fill_price is not None
                        and t.fill_price > EXPENSIVE_SIDE_THRESHOLD
                        and opp is not None
                        and opp < CHEAP_SIDE_THRESHOLD
                        and sig in ("UNCERTAIN", "CONTRARIAN")
                        and res
                    ):
                        expensive_side_total += 1
                        if not won:
                            expensive_side_losses += 1
                    lines.append("")
                # Pattern warning: expensive-side buying in uncertain markets
                if expensive_side_total >= MIN_EXPENSIVE_SIDE_TRADES:
                    lines.append(
                        f"  !! Pattern: {expensive_side_losses}/{expensive_side_total} losses from buying "
                        f"expensive side (>${EXPENSIVE_SIDE_THRESHOLD}) when cheap side was <${CHEAP_SIDE_THRESHOLD} in uncertain markets. "
                        f"The cheap side had better EV."
                    )
                    lines.append("")

        # Last 10 resolutions as compact table
        if resolutions:
            recent = resolutions[-RECENT_RESOLUTIONS_WINDOW:]
            lines.append("Recent resolutions:")
            lines.append("| Slug | Winner | BTC Move | PnL |")
            lines.append("|------|--------|----------|-----|")
            for r in recent:
                btc_move = r.btc_close - r.btc_open
                lines.append(f"| {r.slug[-20:]} | {r.winner} | ${btc_move:+.0f} | ${r.total_pnl:+.4f} |")
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
            lines.append("## Recent Observations (contextual hints — verify AGING observations against recent trades)")
            for obs in observations:
                age = self._total_resolutions - obs.resolution_count_at_creation
                remaining = obs.expires_after_resolutions - age
                freshness = max(0.0, 1.0 - age / obs.expires_after_resolutions)
                aging_tag = "[AGING] " if freshness < 0.50 else ""
                lines.append(
                    f"- {aging_tag}[{obs.category.value}] {obs.text} "
                    f"(freshness: {freshness:.0%} | {age} res ago, expires in {remaining})"
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

        self._logger.info("Running reflection on %d resolutions, %d trades", len(resolutions), len(trades))

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
            if (
                t.fill_price > EXPENSIVE_SIDE_THRESHOLD
                and opp < CHEAP_SIDE_THRESHOLD
                and sig in ("UNCERTAIN", "CONTRARIAN")
            ):
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
                f"Trades that bought the expensive side (>${EXPENSIVE_SIDE_THRESHOLD}) "
                f"when the opposite was cheap (<${CHEAP_SIDE_THRESHOLD}) "
                "in uncertain/contrarian markets:\n" + "\n".join(side_flags)
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
                freshness = max(0.0, 1.0 - age / obs.expires_after_resolutions)
                aging_tag = " [AGING]" if freshness < 0.50 else ""
                obs_lines.append(
                    f"- ID={obs.id}{aging_tag} [{obs.category.value}] {obs.text} "
                    f"(freshness: {freshness:.0%} | age: {age} resolutions, expires in {remaining})"
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
                max_tokens=REFLECTION_MAX_TOKENS,
                temperature=REFLECTION_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )

            # Compute reflection API cost
            input_cost = response.usage.input_tokens * (self._ai_config.input_cost_per_mtok / 1_000_000)
            output_cost = response.usage.output_tokens * (self._ai_config.output_cost_per_mtok / 1_000_000)
            self.last_reflection_cost = input_cost + output_cost
            self.total_api_cost += self.last_reflection_cost
            self._logger.info(
                "Reflection API cost: $%.4f (total: $%.4f) | tokens: %d in / %d out | stop_reason: %s",
                self.last_reflection_cost,
                self.total_api_cost,
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.stop_reason,
            )

            if response.stop_reason == "max_tokens":
                self._logger.warning("Reflection output was truncated (hit max_tokens). Skipping parse.")
                return

            if not response.content:
                self._logger.warning("Reflection returned empty content")
                return

            text = response.content[0].text
            self._logger.debug("Reflection raw response (first 500 chars): %s", text[:500])

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
                self._logger.warning("Reflection response was empty after stripping")
                return

            data = json.loads(stripped)

            # Process observations
            new_obs_data = data.get("observations", [])
            added = 0
            for obs_data in new_obs_data[:MAX_NEW_OBSERVATIONS]:
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
                        expires_after_resolutions=obs_data.get("expires_after_resolutions", DEFAULT_OBSERVATION_EXPIRY),
                    )
                    if obs.text:
                        self._append_observation(obs)
                        added += 1
                except Exception:
                    self._logger.debug("Skipping invalid observation", exc_info=True)

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
                    self._feature_config_path.write_text(json.dumps(fc, indent=2) + "\n")
                    self._logger.info("Updated feature config from reflection")
                except OSError:
                    self._logger.warning("Could not write feature config")

            # Save current scorecard as previous for next reflection
            self._previous_scorecard = current_scorecard

            # Invalidate cache
            self._cache = None

            self._logger.info(
                "Reflection complete — added %d observations, expired %d, session_entry=%s",
                added,
                len(expire_ids),
                bool(session_entry),
            )

        except json.JSONDecodeError as e:
            self._logger.error("Reflection returned invalid JSON: %s", e)
            self._logger.debug("Raw text (first 1000 chars): %s", stripped[:1000] if stripped else "(empty)")
            # Still save scorecard so next reflection has a comparison
            self._previous_scorecard = current_scorecard
        except Exception:
            self._logger.exception("Reflection failed")
            self._previous_scorecard = current_scorecard

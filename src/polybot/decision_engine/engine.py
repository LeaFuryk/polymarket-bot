"""AI decision engine using Claude with structured output."""

from __future__ import annotations

import json
import logging
import time

import anthropic

from polybot.config import AiConfig
from polybot.models import Action, FeatureVector, OrderType, TokenSide, TradingDecision

from .prompts import SCREENING_PROMPT, SYSTEM_PROMPT, format_feature_vector, format_screening_context
from .schemas import SCREENING_DECISION_SCHEMA, TRADING_DECISION_SCHEMA

logger = logging.getLogger(__name__)

HOLD_FALLBACK = TradingDecision(
    action=Action.HOLD,
    order_type=OrderType.MARKET,
    size=0.0,
    confidence=0.0,
    reasoning="Fallback: AI decision unavailable",
    market_view="neutral — unable to assess",
)


class DecisionEngine:
    """Makes trading decisions via Claude API with structured output."""

    def __init__(self, config: AiConfig) -> None:
        self._config = config
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self.session_api_cost: float = 0.0

    async def decide(
        self, features: FeatureVector, feedback_context: str = "",
        indicators_text: str = "",
        ai_cycle_cost: float = 0.0, ai_session_cost: float = 0.0,
        candle_open_btc: float | None = None,
    ) -> tuple[TradingDecision, float, float]:
        """Get a trading decision from Claude.

        Returns:
            Tuple of (decision, latency_ms, api_cost_usd)
        """
        prompt = format_feature_vector(
            features, feedback_context=feedback_context, indicators_text=indicators_text,
            ai_cycle_cost=ai_cycle_cost, ai_session_cost=ai_session_cost,
            candle_open_btc=candle_open_btc,
        )
        start = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "trading_decision",
                    "description": "Submit your trading decision",
                    "input_schema": TRADING_DECISION_SCHEMA,
                }],
                tool_choice={"type": "tool", "name": "trading_decision"},
            )

            latency_ms = (time.monotonic() - start) * 1000

            # Compute API cost
            input_cost = response.usage.input_tokens * (self._config.input_cost_per_mtok / 1_000_000)
            output_cost = response.usage.output_tokens * (self._config.output_cost_per_mtok / 1_000_000)
            api_cost = input_cost + output_cost
            self.session_api_cost += api_cost

            # Extract structured data from tool_use block
            data = None
            for block in response.content:
                if block.type == "tool_use":
                    data = block.input
                    break
            if data is None:
                raise ValueError("No tool_use block in response")

            decision = TradingDecision(
                action=Action(data["action"]),
                token_side=TokenSide(data.get("token_side", "up")),
                order_type=OrderType(data["order_type"]),
                size=float(data["size"]),
                limit_price=data.get("limit_price") or None,
                ttl_seconds=int(data.get("ttl_seconds", 300)),
                confidence=float(data["confidence"]),
                reasoning=data.get("reasoning", ""),
                market_view=data.get("market_view", ""),
                hypothetical_direction=data.get("hypothetical_direction", ""),
                confidence_drivers=data.get("confidence_drivers", ""),
            )

            logger.info(
                "AI decision: %s %s %.2f @ confidence=%.2f (%.0fms, cost=$%.4f)",
                decision.action.value,
                decision.order_type.value,
                decision.size,
                decision.confidence,
                latency_ms,
                api_cost,
            )

            return decision, latency_ms, api_cost

        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception("AI decision failed, using HOLD fallback")
            return HOLD_FALLBACK, latency_ms, 0.0

    async def screen(
        self, features: FeatureVector, indicators_text: str = "",
        candle_open_btc: float | None = None,
    ) -> tuple[bool, str, float]:
        """Pass-1 screen: quick check via Haiku if there's a trade setup.

        Returns:
            Tuple of (should_trade, reason, api_cost_usd)
        """
        prompt = format_screening_context(features, indicators_text, candle_open_btc=candle_open_btc)
        start = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self._config.screen_model,
                max_tokens=200,
                temperature=0.0,
                system=SCREENING_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "screening_decision",
                    "description": "Should we call the full AI for a trade decision?",
                    "input_schema": SCREENING_DECISION_SCHEMA,
                }],
                tool_choice={"type": "tool", "name": "screening_decision"},
            )

            latency_ms = (time.monotonic() - start) * 1000

            # Compute cost using screen model pricing
            input_cost = response.usage.input_tokens * (self._config.screen_input_cost_per_mtok / 1_000_000)
            output_cost = response.usage.output_tokens * (self._config.screen_output_cost_per_mtok / 1_000_000)
            api_cost = input_cost + output_cost
            self.session_api_cost += api_cost

            data = None
            for block in response.content:
                if block.type == "tool_use":
                    data = block.input
                    break
            if data is None:
                raise ValueError("No tool_use block in screening response")

            should_trade = bool(data.get("should_trade", False))
            reason = data.get("reason", "")

            logger.info(
                "Screen: %s — %s (%.0fms, cost=$%.4f)",
                "TRADE" if should_trade else "HOLD",
                reason[:80],
                latency_ms,
                api_cost,
            )

            return should_trade, reason, api_cost

        except Exception:
            logger.exception("Screening failed, defaulting to full AI call")
            return True, "Screening failed", 0.0

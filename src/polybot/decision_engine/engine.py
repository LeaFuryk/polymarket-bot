"""AI decision engine using Claude with structured output."""

from __future__ import annotations

import json
import logging
import time

import anthropic

from polybot.config import AiConfig
from polybot.models import Action, FeatureVector, OrderType, TokenSide, TradingDecision

from .prompts import SYSTEM_PROMPT, format_feature_vector
from .schemas import TRADING_DECISION_SCHEMA

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

    async def decide(
        self, features: FeatureVector, feedback_context: str = "",
        indicators_text: str = "",
    ) -> tuple[TradingDecision, float]:
        """Get a trading decision from Claude.

        Returns:
            Tuple of (decision, latency_ms)
        """
        prompt = format_feature_vector(features, feedback_context=feedback_context, indicators_text=indicators_text)
        start = time.monotonic()

        try:
            response = await self._client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "trading_decision",
                        "strict": True,
                        "schema": TRADING_DECISION_SCHEMA,
                    },
                },
            )

            latency_ms = (time.monotonic() - start) * 1000

            # Extract JSON from response
            text = response.content[0].text
            data = json.loads(text)

            decision = TradingDecision(
                action=Action(data["action"]),
                token_side=TokenSide(data.get("token_side", "up")),
                order_type=OrderType(data["order_type"]),
                size=float(data["size"]),
                limit_price=data.get("limit_price"),
                ttl_seconds=int(data.get("ttl_seconds", 300)),
                confidence=float(data["confidence"]),
                reasoning=data.get("reasoning", ""),
                market_view=data.get("market_view", ""),
            )

            logger.info(
                "AI decision: %s %s %.2f @ confidence=%.2f (%.0fms)",
                decision.action.value,
                decision.order_type.value,
                decision.size,
                decision.confidence,
                latency_ms,
            )

            return decision, latency_ms

        except Exception:
            latency_ms = (time.monotonic() - start) * 1000
            logger.exception("AI decision failed, using HOLD fallback")
            return HOLD_FALLBACK, latency_ms

"""Tests for the decision_engine package — constants, injectable logger, re-exports."""

from __future__ import annotations

import logging

from polybot.decision_engine.constants import (
    HOLD_FALLBACK,
    SCREEN_MAX_TOKENS,
    SCREEN_TEMPERATURE,
)
from polybot.models import Action, OrderType


class TestConstants:
    """Verify constants have expected types and reasonable values."""

    def test_hold_fallback_action(self):
        assert HOLD_FALLBACK.action == Action.HOLD

    def test_hold_fallback_order_type(self):
        assert HOLD_FALLBACK.order_type == OrderType.MARKET

    def test_hold_fallback_zero_size(self):
        assert HOLD_FALLBACK.size == 0.0

    def test_hold_fallback_zero_confidence(self):
        assert HOLD_FALLBACK.confidence == 0.0

    def test_hold_fallback_has_reasoning(self):
        assert "Fallback" in HOLD_FALLBACK.reasoning

    def test_hold_fallback_neutral_view(self):
        assert "neutral" in HOLD_FALLBACK.market_view

    def test_screen_max_tokens_positive(self):
        assert isinstance(SCREEN_MAX_TOKENS, int)
        assert SCREEN_MAX_TOKENS > 0

    def test_screen_temperature_zero(self):
        assert isinstance(SCREEN_TEMPERATURE, float)
        assert SCREEN_TEMPERATURE == 0.0


class TestInjectableLogger:
    """Verify DecisionEngine accepts an injectable logger."""

    def test_default_logger(self):
        from polybot.config import AiConfig
        from polybot.decision_engine.engine import DecisionEngine

        engine = DecisionEngine(config=AiConfig(api_key="test"))
        assert isinstance(engine._log, logging.Logger)
        assert engine._log.name == "polybot.decision_engine.engine"

    def test_custom_logger(self):
        from polybot.config import AiConfig
        from polybot.decision_engine.engine import DecisionEngine

        custom = logging.getLogger("test.custom")
        engine = DecisionEngine(config=AiConfig(api_key="test"), logger=custom)
        assert engine._log is custom


class TestReExports:
    """Verify __init__.py re-exports all public names."""

    def test_decision_engine_class(self):
        from polybot.decision_engine import DecisionEngine

        assert DecisionEngine is not None

    def test_hold_fallback(self):
        from polybot.decision_engine import HOLD_FALLBACK

        assert HOLD_FALLBACK.action == Action.HOLD

    def test_screen_constants(self):
        from polybot.decision_engine import SCREEN_MAX_TOKENS, SCREEN_TEMPERATURE

        assert SCREEN_MAX_TOKENS > 0
        assert SCREEN_TEMPERATURE == 0.0

    def test_prompts(self):
        from polybot.decision_engine import (
            SCREENING_PROMPT,
            SYSTEM_PROMPT,
            format_feature_vector,
            format_screening_context,
        )

        assert isinstance(SYSTEM_PROMPT, str)
        assert isinstance(SCREENING_PROMPT, str)
        assert callable(format_feature_vector)
        assert callable(format_screening_context)

    def test_schemas(self):
        from polybot.decision_engine import (
            SCREENING_DECISION_SCHEMA,
            TRADING_DECISION_SCHEMA,
        )

        assert isinstance(TRADING_DECISION_SCHEMA, dict)
        assert isinstance(SCREENING_DECISION_SCHEMA, dict)

    def test_all_list(self):
        import polybot.decision_engine as de

        assert hasattr(de, "__all__")
        assert "DecisionEngine" in de.__all__
        assert "HOLD_FALLBACK" in de.__all__

"""Tests for the decision_engine package — constants, helpers, injectable deps, re-exports."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from polybot.config import AiConfig
from polybot.decision_engine.constants import (
    HOLD_FALLBACK,
    SCREEN_MAX_TOKENS,
    SCREEN_TEMPERATURE,
)
from polybot.decision_engine.engine import DecisionEngine, compute_cost, extract_tool_data
from polybot.models import Action, FeatureVector, MarketSnapshot, OrderType, PositionState, RiskState


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
        assert "compute_cost" in de.__all__
        assert "extract_tool_data" in de.__all__


# --- Helpers for building mock responses ---


def _make_tool_response(tool_input: dict, input_tokens: int = 100, output_tokens: int = 50):
    """Build a mock anthropic Message with a tool_use block."""
    tool_block = SimpleNamespace(type="tool_use", input=tool_input)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[tool_block], usage=usage)


def _make_text_response(text: str = "Hello", input_tokens: int = 100, output_tokens: int = 50):
    """Build a mock anthropic Message with only a text block (no tool_use)."""
    text_block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[text_block], usage=usage)


def _make_features() -> FeatureVector:
    """Build a minimal FeatureVector for testing."""
    return FeatureVector(
        market=MarketSnapshot(condition_id="test-cond"),
        position=PositionState(),
        risk=RiskState(),
        portfolio_cash=100.0,
        portfolio_total_value=100.0,
    )


class TestExtractToolData:
    """Tests for extract_tool_data helper."""

    def test_extracts_tool_input(self):
        resp = _make_tool_response({"action": "BUY"})
        assert extract_tool_data(resp) == {"action": "BUY"}

    def test_raises_on_no_tool_block(self):
        resp = _make_text_response()
        with pytest.raises(ValueError, match="No tool_use block"):
            extract_tool_data(resp)

    def test_returns_first_tool_block(self):
        block1 = SimpleNamespace(type="text", text="hi")
        block2 = SimpleNamespace(type="tool_use", input={"first": True})
        block3 = SimpleNamespace(type="tool_use", input={"second": True})
        resp = SimpleNamespace(content=[block1, block2, block3], usage=None)
        assert extract_tool_data(resp) == {"first": True}


class TestComputeCost:
    """Tests for compute_cost helper."""

    def test_zero_tokens(self):
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        assert compute_cost(usage, 3.0, 8.0) == 0.0

    def test_known_values(self):
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = compute_cost(usage, 3.0, 8.0)
        assert cost == pytest.approx(11.0)  # 3 + 8

    def test_typical_call(self):
        usage = SimpleNamespace(input_tokens=500, output_tokens=200)
        cost = compute_cost(usage, 3.0, 8.0)
        expected = 500 * 3.0 / 1_000_000 + 200 * 8.0 / 1_000_000
        assert cost == pytest.approx(expected)


class TestInjectableClient:
    """Verify DecisionEngine accepts an injectable AI client."""

    def test_custom_client_used(self):
        mock_client = AsyncMock()
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        assert engine._client is mock_client

    def test_default_client_created(self):
        engine = DecisionEngine(config=AiConfig(api_key="test"))
        assert engine._client is not None

    async def test_decide_uses_injected_client(self):
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_tool_response(
            {
                "action": "BUY",
                "token_side": "up",
                "order_type": "MARKET",
                "size": 50,
                "limit_price": 0,
                "ttl_seconds": 300,
                "confidence": 0.7,
                "reasoning": "test",
                "market_view": "bullish",
                "hypothetical_direction": "up",
                "confidence_drivers": "momentum",
            }
        )
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        decision, latency, cost = await engine.decide(_make_features())

        assert decision.action == Action.BUY
        assert decision.confidence == pytest.approx(0.7)
        assert latency > 0
        assert cost > 0
        mock_client.messages.create.assert_called_once()

    async def test_screen_uses_injected_client(self):
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_tool_response(
            {"should_trade": True, "reason": "Strong BTC move"}
        )
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        should_trade, reason, cost = await engine.screen(_make_features())

        assert should_trade is True
        assert reason == "Strong BTC move"
        assert cost > 0
        mock_client.messages.create.assert_called_once()

    async def test_decide_fallback_on_error(self):
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError("API down")
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        decision, latency, cost = await engine.decide(_make_features())

        assert decision.action == Action.HOLD
        assert decision.confidence == 0.0
        assert cost == 0.0

    async def test_screen_fallback_on_error(self):
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = RuntimeError("API down")
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        should_trade, reason, cost = await engine.screen(_make_features())

        assert should_trade is True  # defaults to calling full AI
        assert "failed" in reason.lower()
        assert cost == 0.0

    async def test_session_cost_accumulates(self):
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = _make_tool_response(
            {"should_trade": False, "reason": "No signal"},
            input_tokens=1000,
            output_tokens=500,
        )
        engine = DecisionEngine(config=AiConfig(api_key="test"), client=mock_client)
        assert engine.session_api_cost == 0.0

        await engine.screen(_make_features())
        first_cost = engine.session_api_cost
        assert first_cost > 0

        await engine.screen(_make_features())
        assert engine.session_api_cost == pytest.approx(first_cost * 2)

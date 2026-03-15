"""Tests for IndicatorResults container."""

from __future__ import annotations

import pytest

from polybot.indicators.core import IndicatorResult
from polybot.indicators.results import IndicatorResults


class TestIndicatorResults:
    def test_empty_results(self):
        results = IndicatorResults()
        assert results.results == []

    def test_get_existing(self):
        r = IndicatorResult(name="Test", value=1.5, label="good")
        results = IndicatorResults(results=[r])
        assert results.get("Test") is r

    def test_get_missing(self):
        results = IndicatorResults()
        assert results.get("Nonexistent") is None

    def test_get_value_existing(self):
        r = IndicatorResult(name="Metric", value=42.0, label="")
        results = IndicatorResults(results=[r])
        assert results.get_value("Metric") == pytest.approx(42.0)

    def test_get_value_missing_uses_default(self):
        results = IndicatorResults()
        assert results.get_value("Missing", default=-1.0) == pytest.approx(-1.0)

    def test_to_dict(self):
        results = IndicatorResults(
            results=[
                IndicatorResult(name="A", value=1.0, label="a_label"),
                IndicatorResult(name="B", value=2.0, label="b_label"),
            ]
        )
        d = results.to_dict()
        assert d == {
            "A": {"value": 1.0, "label": "a_label"},
            "B": {"value": 2.0, "label": "b_label"},
        }

    def test_to_dict_empty(self):
        assert IndicatorResults().to_dict() == {}

    def test_format_markdown_empty(self):
        assert IndicatorResults().format_markdown() == ""

    def test_format_markdown(self):
        results = IndicatorResults(
            results=[
                IndicatorResult(name="A", value=1.0, label="a_label"),
                IndicatorResult(name="B", value=2.0, label="b_label"),
            ]
        )
        text = results.format_markdown()
        assert "## Computed Indicators" in text
        assert "- A: a_label" in text
        assert "- B: b_label" in text

"""Tests for polybot.analysis.deep_report — report builder and rendering."""

from __future__ import annotations

import io
import json

from rich.console import Console

from polybot.analysis.deep_report import build_deep_report, render_deep_report


def _create_archive(tmp_path, trades=None, resolutions=None, summary=None):
    """Create a minimal archive directory structure for testing."""
    iter_dir = tmp_path / "iter_001"
    logs_dir = iter_dir / "logs"
    logs_dir.mkdir(parents=True)

    if trades:
        trades_file = logs_dir / "trades_20260306.jsonl"
        trades_file.write_text("\n".join(json.dumps(t) for t in trades))

    if resolutions:
        res_file = logs_dir / "resolutions_20260306.jsonl"
        res_file.write_text("\n".join(json.dumps(r) for r in resolutions))

    if summary is not None:
        (iter_dir / "summary.json").write_text(json.dumps(summary))

    return iter_dir


class TestBuildDeepReport:
    def test_empty_archive(self, tmp_path):
        iter_dir = _create_archive(tmp_path)
        report = build_deep_report(iter_dir)
        assert report["iteration"] == "iter_001"
        assert report["summary"]["total_trades"] == 0
        assert report["entry_quality"]["total_buys"] == 0
        assert report["recommendations"] == []

    def test_with_trades_and_resolutions(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.50,
                "confidence": 0.7,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "test",
                "fee": 0.01,
            },
            {
                "action": "HOLD",
                "fill_price": None,
                "confidence": None,
                "token_side": "UP",
                "candle_slug": "s2",
                "risk_blocked": False,
                "reasoning": "hold",
                "fee": 0,
            },
        ]
        resolutions = [
            {"slug": "s1", "winner": "UP", "btc_move": 80.0, "pnl": 0.10},
            {"slug": "s2", "winner": "DOWN", "btc_move": -60.0, "pnl": 0},
        ]
        summary = {"label": "iter_031", "win_rate": 0.6, "total_pnl": 0.10}

        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary=summary)
        report = build_deep_report(iter_dir)

        assert report["iteration"] == "iter_031"
        assert report["summary"]["total_trades"] == 2
        assert report["summary"]["total_resolutions"] == 2
        assert report["entry_quality"]["total_buys"] == 1
        assert "UP" in report["side_accuracy"]
        assert report["missed_opportunities"]["missed_candles"] == 1

    def test_with_iterations_for_trends(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.50,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "x",
                "fee": 0.01,
            }
        ]
        resolutions = [{"slug": "s1", "winner": "UP", "btc_move": 50.0, "pnl": 0.05}]
        summary = {"label": "iter_003", "win_rate": 0.7, "total_pnl": 0.20}

        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary=summary)

        iterations = [
            {"win_rate": 0.5, "total_pnl": 0.05, "trade_analysis": {"avg_fill_price": 0.55, "hold_rate": 0.3}},
            {"win_rate": 0.6, "total_pnl": 0.10, "trade_analysis": {"avg_fill_price": 0.50, "hold_rate": 0.2}},
            summary,
        ]
        report = build_deep_report(iter_dir, iterations=iterations)
        assert len(report["trends"]["win_rate"]["values"]) == 3

    def test_report_has_all_sections(self, tmp_path):
        iter_dir = _create_archive(tmp_path, summary={"label": "test"})
        report = build_deep_report(iter_dir)
        expected_keys = [
            "iteration",
            "summary",
            "entry_quality",
            "side_accuracy",
            "losses",
            "flips",
            "missed_opportunities",
            "timing",
            "trends",
            "recommendations",
        ]
        for key in expected_keys:
            assert key in report, f"Missing key: {key}"

    def test_json_serializable(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.45,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "x",
                "fee": 0.01,
            }
        ]
        resolutions = [{"slug": "s1", "winner": "UP", "btc_move": 100.0, "pnl": 0.15}]
        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary={"label": "test"})
        report = build_deep_report(iter_dir)
        # Should not raise
        json.dumps(report)

    def test_missing_logs_dir(self, tmp_path):
        iter_dir = tmp_path / "iter_empty"
        iter_dir.mkdir()
        report = build_deep_report(iter_dir)
        assert report["summary"]["total_trades"] == 0


class TestLoadHelpers:
    def test_load_jsonl_missing_file(self, tmp_path):
        from polybot.analysis.deep_report import _load_jsonl

        result = _load_jsonl(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_load_json_missing_file(self, tmp_path):
        from polybot.analysis.deep_report import _load_json

        result = _load_json(tmp_path / "nonexistent.json")
        assert result == {}

    def test_find_file_no_match(self, tmp_path):
        from polybot.analysis.deep_report import _find_file

        result = _find_file(tmp_path, "*.xyz")
        assert result is None


class TestRenderDeepReport:
    def test_renders_without_error(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.50,
                "confidence": 0.7,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "test",
                "fee": 0.01,
            },
        ]
        resolutions = [{"slug": "s1", "winner": "UP", "btc_move": 80.0, "pnl": 0.10}]
        summary = {"label": "iter_test", "win_rate": 0.6, "total_pnl": 0.10}

        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary=summary)
        report = build_deep_report(iter_dir)

        console = Console(file=io.StringIO(), force_terminal=True, width=120)
        render_deep_report(report, console)

    def test_renders_empty_report(self, tmp_path):
        iter_dir = _create_archive(tmp_path)
        report = build_deep_report(iter_dir)

        console = Console(file=io.StringIO(), force_terminal=True, width=120)
        render_deep_report(report, console)

    def test_renders_with_losses_and_flips(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.55,
                "confidence": 0.7,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "bullish",
                "fee": 0.01,
                "time_remaining_at_trade": 250,
            },
            {
                "action": "SELL",
                "fill_price": 0.45,
                "confidence": 0.6,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "exit",
                "fee": 0.01,
                "time_remaining_at_trade": 200,
            },
        ]
        resolutions = [{"slug": "s1", "winner": "DOWN", "btc_move": -80.0, "pnl": -0.10}]
        summary = {"label": "test_full", "win_rate": 0.3, "total_pnl": -0.10}

        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary=summary)
        report = build_deep_report(iter_dir)

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        render_deep_report(report, console)

        output = buf.getvalue()
        assert "Losses" in output
        assert "Flips" in output

    def test_renders_timing_and_missed(self, tmp_path):
        trades = [
            {
                "action": "BUY",
                "fill_price": 0.50,
                "token_side": "UP",
                "candle_slug": "s1",
                "risk_blocked": False,
                "reasoning": "x",
                "fee": 0.01,
                "time_remaining_at_trade": 270,
            },
            {"action": "HOLD", "candle_slug": "s2", "risk_blocked": False, "reasoning": "hold"},
        ]
        resolutions = [
            {"slug": "s1", "winner": "UP", "btc_move": 80.0, "pnl": 0.10},
            {"slug": "s2", "winner": "DOWN", "btc_move": -90.0, "pnl": 0},
        ]
        summary = {"label": "test_timing", "win_rate": 0.5, "total_pnl": 0.10}

        iter_dir = _create_archive(tmp_path, trades=trades, resolutions=resolutions, summary=summary)
        report = build_deep_report(iter_dir)

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        render_deep_report(report, console)

        output = buf.getvalue()
        assert "Timing" in output
        assert "Missed" in output

    def test_renders_recommendations(self, tmp_path):
        report = {
            "iteration": "test",
            "summary": {"total_trades": 10, "total_resolutions": 5, "win_rate": 0.4, "total_pnl": -0.5},
            "entry_quality": {"total_fills": 0},
            "side_accuracy": {},
            "losses": [],
            "flips": [],
            "missed_opportunities": {"missed_candles": 0},
            "timing": {},
            "trends": {},
            "recommendations": [
                {"severity": "high", "category": "test", "message": "Test recommendation", "evidence": "Test evidence"},
            ],
        }

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        render_deep_report(report, console)

        output = buf.getvalue()
        assert "Test recommendation" in output

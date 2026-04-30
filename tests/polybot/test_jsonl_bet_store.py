"""Tests for JsonlBetStore."""

import json

import pytest
from polybot.adapters.jsonl_bet_store import JsonlBetStore
from polybot.domain.bet_record import BetEntry, BetRecord


@pytest.fixture
def store(tmp_path):
    return JsonlBetStore(directory=str(tmp_path))


class TestSaveBet:
    @pytest.mark.asyncio
    async def test_appends_record(self, store):
        record = BetRecord(
            candle_id="c1",
            direction="UP",
            outcome="UP",
            won=True,
            entries=[BetEntry(price=0.60, amount_usd=20.0, elapsed_pct=0.1, confidence=0.7, checkpoint=1)],
            pnl=13.33,
            timestamp=1000.0,
        )
        await store.save_bet(record)

        lines = store._path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["candle_id"] == "c1"
        assert data["won"] is True


class TestUpdateBet:
    @pytest.mark.asyncio
    async def test_updates_matching_record(self, store):
        r1 = BetRecord(candle_id="c1", direction="UP", outcome="UP", won=True, pnl=10.0, timestamp=1.0)
        r2 = BetRecord(candle_id="c2", direction="DOWN", outcome="DOWN", won=True, pnl=5.0, timestamp=2.0)
        await store.save_bet(r1)
        await store.save_bet(r2)

        await store.update_bet("c1", new_outcome="DOWN", new_won=False, new_pnl=-20.0)

        lines = store._path.read_text().strip().splitlines()
        assert len(lines) == 2
        updated = json.loads(lines[0])
        assert updated["candle_id"] == "c1"
        assert updated["outcome"] == "DOWN"
        assert updated["won"] is False
        assert updated["pnl"] == -20.0

        # c2 unchanged
        unchanged = json.loads(lines[1])
        assert unchanged["candle_id"] == "c2"
        assert unchanged["won"] is True

    @pytest.mark.asyncio
    async def test_missing_candle_id_logs_warning(self, store):
        r1 = BetRecord(candle_id="c1", direction="UP", outcome="UP", won=True, pnl=10.0, timestamp=1.0)
        await store.save_bet(r1)

        await store.update_bet("c99", new_outcome="DOWN", new_won=False, new_pnl=-10.0)

        # c1 unchanged
        lines = store._path.read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert data["candle_id"] == "c1"
        assert data["won"] is True

    @pytest.mark.asyncio
    async def test_preserves_entries_and_other_fields(self, store):
        entry = BetEntry(price=0.60, amount_usd=20.0, elapsed_pct=0.1, confidence=0.7, checkpoint=1)
        r1 = BetRecord(
            candle_id="c1",
            direction="UP",
            outcome="UP",
            won=True,
            entries=[entry],
            pnl=13.33,
            timestamp=1000.0,
        )
        await store.save_bet(r1)

        await store.update_bet("c1", new_outcome="DOWN", new_won=False, new_pnl=-20.0)

        lines = store._path.read_text().strip().splitlines()
        data = json.loads(lines[0])
        assert data["direction"] == "UP"  # unchanged
        assert data["timestamp"] == 1000.0  # unchanged
        assert len(data["entries"]) == 1  # preserved
        assert data["entries"][0]["price"] == 0.60

"""Tests for JsonlSessionStore."""

import json
import tempfile
from pathlib import Path

from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.ports.session_store import SessionStore


class TestJsonlSessionStore:
    def test_implements_protocol(self):
        store = JsonlSessionStore("/tmp/test.jsonl")
        assert isinstance(store, SessionStore)

    async def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 5, "losses": 3})
            assert path.exists()

    async def test_save_appends_json_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 5})
            await store.save_session({"wins": 10})
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2
            assert json.loads(lines[0])["wins"] == 5
            assert json.loads(lines[1])["wins"] == 10

    async def test_save_adds_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 1})
            data = json.loads(path.read_text().strip())
            assert "timestamp" in data
            assert isinstance(data["timestamp"], float)

"""Tests for the server module (constants, helpers, CLI)."""

from __future__ import annotations

import importlib.util
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from polybot.server.constants import (
    APP_TITLE,
    DB_ENV_VAR,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    SSE_POLL_INTERVAL_SECONDS,
)

_has_fastapi = importlib.util.find_spec("fastapi") is not None

_needs_fastapi = pytest.mark.skipif(not _has_fastapi, reason="FastAPI not installed")


# ── Constants ──────────────────────────────────────────────────────────


class TestConstants:
    def test_db_env_var(self):
        assert DB_ENV_VAR == "POLYBOT_DB"

    def test_default_db_path(self):
        assert DEFAULT_DB_PATH == "logs/polybot.db"

    def test_app_title(self):
        assert APP_TITLE == "Polybot Forensics API"

    def test_sse_poll_interval(self):
        assert SSE_POLL_INTERVAL_SECONDS == 2.0

    def test_default_host(self):
        assert DEFAULT_HOST == "0.0.0.0"

    def test_default_port(self):
        assert DEFAULT_PORT == 8888

    def test_sse_media_type(self):
        assert SSE_MEDIA_TYPE == "text/event-stream"

    def test_sse_headers(self):
        assert "Cache-Control" in SSE_HEADERS
        assert SSE_HEADERS["Cache-Control"] == "no-cache"
        assert SSE_HEADERS["Connection"] == "keep-alive"
        assert SSE_HEADERS["X-Accel-Buffering"] == "no"


# ── app helpers (require FastAPI) ──────────────────────────────────────


@_needs_fastapi
class TestGetDbPath:
    """Test _get_db_path helper."""

    def test_returns_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv(DB_ENV_VAR, raising=False)
        from polybot.server.app import _get_db_path

        assert _get_db_path() == DEFAULT_DB_PATH

    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv(DB_ENV_VAR, "/custom/path.db")
        from polybot.server.app import _get_db_path

        assert _get_db_path() == "/custom/path.db"


@_needs_fastapi
class TestSerialize:
    """Test _serialize helper."""

    def test_serialize_dict(self):
        from polybot.server.app import _serialize

        result = _serialize({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_serialize_pydantic_model(self):
        from polybot.server.app import _serialize

        model = MagicMock()
        model.model_dump.return_value = {"field": 42}
        result = _serialize(model)
        assert json.loads(result) == {"field": 42}

    def test_serialize_list(self):
        from polybot.server.app import _serialize

        result = _serialize([1, 2, 3])
        assert json.loads(result) == [1, 2, 3]


# ── run.py CLI ─────────────────────────────────────────────────────────


class TestRunMain:
    """Test the CLI entry point."""

    @patch("polybot.server.run.argparse.ArgumentParser.parse_args")
    def test_main_sets_env_and_starts_uvicorn(self, mock_parse):
        mock_parse.return_value = MagicMock(
            db="/tmp/test.db",
            host="127.0.0.1",
            port=9999,
        )
        import types

        mock_uvicorn = MagicMock()
        mock_app = MagicMock()
        fake_app_module = types.ModuleType("polybot.server.app")
        fake_app_module.app = mock_app  # type: ignore[attr-defined]

        # Pre-seed sys.modules so the import inside main() finds our fakes
        with patch.dict(
            "sys.modules",
            {"polybot.server.app": fake_app_module, "uvicorn": mock_uvicorn},
        ):
            from polybot.server.run import main

            main()
            assert os.environ.get(DB_ENV_VAR) == "/tmp/test.db"
            mock_uvicorn.run.assert_called_once()
            call_args = mock_uvicorn.run.call_args
            assert call_args[0][0] is mock_app
            assert call_args[1]["host"] == "127.0.0.1"
            assert call_args[1]["port"] == 9999

    @patch("polybot.server.run.argparse.ArgumentParser.parse_args")
    def test_main_uvicorn_missing_exits(self, mock_parse, monkeypatch):
        mock_parse.return_value = MagicMock(
            db="logs/polybot.db",
            host="0.0.0.0",
            port=8888,
        )
        # Simulate uvicorn not being importable
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("no uvicorn")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from polybot.server.run import main

        with pytest.raises(SystemExit, match="1"):
            main()


# ── __init__.py re-exports ─────────────────────────────────────────────


class TestReExports:
    """Verify __init__.py re-exports."""

    @_needs_fastapi
    def test_app_reexported(self):
        from polybot.server import app

        assert app is not None

    def test_main_reexported(self):
        from polybot.server import main

        assert callable(main)

    def test_constants_reexported(self):
        from polybot.server import DEFAULT_DB_PATH, DEFAULT_PORT

        assert DEFAULT_DB_PATH == "logs/polybot.db"
        assert DEFAULT_PORT == 8888

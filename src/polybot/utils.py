"""Shared I/O utilities for reading structured log files."""

from __future__ import annotations

import json
import logging
from pathlib import Path


def read_json(directory: Path, filename: str, log: logging.Logger) -> dict | None:
    """Read a single JSON file from *directory*. Returns ``None`` if missing or corrupt."""
    path = directory / filename
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        log.warning("Could not load %s", filename)
    return None


def read_jsonl(directory: Path, pattern: str, log: logging.Logger) -> list[dict]:
    """Read all JSONL records matching a glob *pattern* inside *directory*."""
    records: list[dict] = []
    for filepath in sorted(directory.glob(pattern)):
        try:
            for line in filepath.read_text().strip().split("\n"):
                if line.strip():
                    records.append(json.loads(line))
        except Exception:
            log.debug("Could not load %s", filepath, exc_info=True)
    return records

"""CLI entry point for polybot-forensics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .aggregate import build_report
from .db import connect
from .render import render_report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="polybot-forensics",
        description="Forensic analysis of order execution from polybot.db",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="logs/polybot.db",
        help="Path to polybot.db (default: logs/polybot.db)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of Rich tables",
    )
    parser.add_argument(
        "--feature",
        type=str,
        default=None,
        help="Run only specific feature(s), comma-separated (A,B,C,D,E,F)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = connect(db_path)

    try:
        report = build_report(conn, str(db_path))
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report.model_dump(), indent=2, default=str))
        return

    features = None
    if args.feature:
        features = {f.strip().upper() for f in args.feature.split(",")}

    render_report(report, features)


if __name__ == "__main__":
    main()

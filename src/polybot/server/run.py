"""CLI entry point for polybot-server."""

from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="polybot-server",
        description="Run the Polybot forensics API server",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="logs/polybot.db",
        help="Path to polybot.db (default: logs/polybot.db)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Bind port (default: 8888)",
    )
    args = parser.parse_args()

    # Set DB path for the app module to pick up
    os.environ["POLYBOT_DB"] = args.db

    try:
        import uvicorn
    except ImportError as err:
        print("uvicorn not installed. Install with: uv pip install -e '.[server]'")
        raise SystemExit(1) from err

    from polybot.server.app import app

    print(f"Starting Polybot forensics server on {args.host}:{args.port}")
    print(f"DB: {args.db}")
    print(f"API docs: http://localhost:{args.port}/docs")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

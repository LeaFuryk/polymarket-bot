"""CLI entry point for polybot-server."""

from __future__ import annotations

import argparse
import os

from polybot.server.constants import DB_ENV_VAR, DEFAULT_DB_PATH, DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="polybot-server",
        description="Run the Polybot forensics API server",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"Path to polybot.db (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Bind host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    # Set DB path for the app module to pick up
    os.environ[DB_ENV_VAR] = args.db

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

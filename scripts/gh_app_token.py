#!/usr/bin/env python3
"""Generate a GitHub App installation token for tars-bot-01.

Reads GH_APP_ID, GH_INSTALLATION_ID, and GH_APP_PRIVATE_KEY_PATH from .env,
creates a JWT, and exchanges it for a short-lived installation access token.

Usage:
    python3 scripts/gh_app_token.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    import jwt
    import requests
except ImportError:
    print("ERROR: Install dependencies first: pip install pyjwt cryptography requests")
    sys.exit(1)

from dotenv import load_dotenv


def main() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    app_id = os.environ.get("GH_APP_ID", "")
    installation_id = os.environ.get("GH_INSTALLATION_ID", "")
    key_path = os.environ.get("GH_APP_PRIVATE_KEY_PATH", "")

    if not all([app_id, installation_id, key_path]):
        print("ERROR: Set GH_APP_ID, GH_INSTALLATION_ID, GH_APP_PRIVATE_KEY_PATH in .env", file=sys.stderr)
        sys.exit(1)

    # Resolve key path relative to project root
    key_file = Path(key_path)
    if not key_file.is_absolute():
        key_file = Path(__file__).resolve().parent.parent / key_file

    if not key_file.exists():
        print(f"ERROR: Private key not found: {key_file}", file=sys.stderr)
        sys.exit(1)

    private_key = key_file.read_text()

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": app_id,
    }

    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    resp.raise_for_status()

    print(resp.json()["token"])


if __name__ == "__main__":
    main()

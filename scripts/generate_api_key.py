#!/usr/bin/env python3
"""Generate Polymarket CLOB API credentials from a wallet private key.

Reads POLYBOT_TRADING_PRIVATE_KEY from .env, derives API creds via
py-clob-client, and prints them for adding to .env.

Usage:
    uv run python scripts/generate_api_key.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    # Load .env from project root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    private_key = os.environ.get("POLYBOT_TRADING_PRIVATE_KEY", "")
    if not private_key:
        print("ERROR: POLYBOT_TRADING_PRIVATE_KEY not set in .env")
        print("Add your Polygon wallet private key (from MetaMask) to .env:")
        print("  POLYBOT_TRADING_PRIVATE_KEY=0x...")
        sys.exit(1)

    chain_id = int(os.environ.get("POLYBOT_TRADING_CHAIN_ID", "137"))
    host = os.environ.get("POLYBOT_CLOB_HOST", "https://clob.polymarket.com")

    print(f"Host: {host}")
    print(f"Chain ID: {chain_id}")
    print()

    from py_clob_client.client import ClobClient

    # Create Level 1 client
    client = ClobClient(host=host, chain_id=chain_id, key=private_key)

    print(f"Wallet address: {client.get_address()}")
    print()

    # Derive or create API key
    print("Deriving API credentials...")
    try:
        creds = client.derive_api_key()
    except Exception:
        print("derive_api_key() failed, trying create_or_derive_api_creds()...")
        creds = client.create_or_derive_api_creds()

    print()
    print("=== Add these to your .env file ===")
    print()
    print(f"POLYBOT_TRADING_API_KEY={creds.api_key}")
    print(f"POLYBOT_TRADING_API_SECRET={creds.api_secret}")
    print(f"POLYBOT_TRADING_API_PASSPHRASE={creds.api_passphrase}")
    print()

    # Verify credentials by checking balance
    print("Verifying credentials...")
    try:
        from py_clob_client.clob_types import ApiCreds as ClobApiCreds

        full_client = ClobClient(
            host=host,
            chain_id=chain_id,
            key=private_key,
            creds=ClobApiCreds(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
            ),
        )

        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = full_client.get_balance_allowance(params)
        balance = float(result.get("balance", 0)) if isinstance(result, dict) else 0.0
        print(f"Wallet USDC balance: ${balance:.2f}")
        print()
        print("Auth verified successfully!")
    except Exception as e:
        print(f"Balance check failed (auth may still work): {e}")


if __name__ == "__main__":
    main()

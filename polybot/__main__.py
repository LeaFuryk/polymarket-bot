"""Bot entry point -- connects to collector WebSocket for live market data."""

import asyncio
import logging

from polybot.adapters.collector_client import CollectorClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def print_snapshots(client: CollectorClient) -> None:
    """Print latest snapshot every 30 seconds."""
    await asyncio.sleep(3)  # wait for first snapshot
    while True:
        snap = client.snapshot
        if snap:
            print(
                f"BTC ${snap['btc_price']:,.2f} | "
                f"YES {snap.get('up_last_trade', 'n/a')} | "
                f"NO {snap.get('down_last_trade', 'n/a')} | "
                f"elapsed {snap.get('elapsed_pct', 0) * 100:.0f}% | "
                f"candle {snap.get('candle_id', '?')}"
            )
        else:
            print("Waiting for collector data...")
        await asyncio.sleep(30)


async def main() -> None:
    client = CollectorClient()
    try:
        await asyncio.gather(
            client.run(),
            print_snapshots(client),
        )
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())

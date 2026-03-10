"""Entry point: python -m polybot"""

import asyncio
import sys

from polybot.agent import TradingAgent
from polybot.config import load_config


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(config_path)

    if not config.ai.api_key:
        print("ERROR: Set POLYBOT_AI_API_KEY in .env or environment")
        sys.exit(1)

    if not config.market.series_slug:
        print("ERROR: Set a valid series_slug in config or POLYBOT_MARKET_SERIES_SLUG")
        sys.exit(1)

    agent = TradingAgent(config)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()

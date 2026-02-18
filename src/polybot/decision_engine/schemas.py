"""JSON schema for Claude structured output (constrained decoding)."""

TRADING_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["BUY", "SELL", "HOLD"],
            "description": "Trading action to take",
        },
        "token_side": {
            "type": "string",
            "enum": ["up", "down"],
            "description": "Which token to trade: 'up' (BTC goes up) or 'down' (BTC goes down)",
        },
        "order_type": {
            "type": "string",
            "enum": ["MARKET", "LIMIT"],
            "description": "Order type: MARKET for immediate execution, LIMIT for price-conditional",
        },
        "size": {
            "type": "number",
            "minimum": 0,
            "description": "Number of shares to trade (0 for HOLD)",
        },
        "limit_price": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
            "description": "Limit price for LIMIT orders (null for MARKET)",
        },
        "ttl_seconds": {
            "type": "integer",
            "minimum": 30,
            "maximum": 3600,
            "description": "Time-to-live for limit orders in seconds",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in this decision (0=no confidence, 1=certain)",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of the trading rationale",
        },
        "market_view": {
            "type": "string",
            "description": "Market thesis: bullish/bearish/neutral with brief explanation",
        },
    },
    "required": [
        "action",
        "token_side",
        "order_type",
        "size",
        "limit_price",
        "ttl_seconds",
        "confidence",
        "reasoning",
        "market_view",
    ],
    "additionalProperties": False,
}

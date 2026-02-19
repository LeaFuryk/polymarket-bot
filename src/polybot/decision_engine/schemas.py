"""JSON schema for Claude structured output (constrained decoding)."""

# Pass-1 screening schema (Haiku — fast & cheap)
SCREENING_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "should_trade": {
            "type": "boolean",
            "description": "True if there is a plausible trade setup, False if HOLD is the best action",
        },
        "reason": {
            "type": "string",
            "description": "Brief 1-2 sentence explanation",
        },
    },
    "required": ["should_trade", "reason"],
    "additionalProperties": False,
}

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
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Limit price for LIMIT orders (0 for MARKET)",
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

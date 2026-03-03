"""AI model selection, token limits, and cost tracking."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_AI_MODEL,
    DEFAULT_INPUT_COST_PER_MTOK,
    DEFAULT_MAX_TOKENS,
    DEFAULT_OUTPUT_COST_PER_MTOK,
    DEFAULT_SCREEN_INPUT_COST_PER_MTOK,
    DEFAULT_SCREEN_MODEL,
    DEFAULT_SCREEN_OUTPUT_COST_PER_MTOK,
)


class AiConfig(BaseModel):
    """AI model selection, token limits, and cost tracking."""

    model: str = DEFAULT_AI_MODEL
    screen_model: str = DEFAULT_SCREEN_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.0
    api_key: str = ""
    input_cost_per_mtok: float = DEFAULT_INPUT_COST_PER_MTOK
    output_cost_per_mtok: float = DEFAULT_OUTPUT_COST_PER_MTOK
    screen_input_cost_per_mtok: float = DEFAULT_SCREEN_INPUT_COST_PER_MTOK
    screen_output_cost_per_mtok: float = DEFAULT_SCREEN_OUTPUT_COST_PER_MTOK
    two_pass_enabled: bool = True

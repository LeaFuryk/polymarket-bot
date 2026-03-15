"""Indicator protocol — interface for all indicator implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from polybot.indicators.context import IndicatorContext
    from polybot.indicators.core import IndicatorResult


@runtime_checkable
class Indicator(Protocol):
    """Protocol that all indicator implementations must satisfy."""

    name: str
    display_name: str

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None: ...

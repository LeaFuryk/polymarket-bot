"""IndicatorResults — container for one tick's indicator computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.indicators.core import IndicatorResult


@dataclass
class IndicatorResults:
    """Container for all computed indicators from a single tick."""

    results: list[IndicatorResult] = field(default_factory=list)

    def get(self, name: str) -> IndicatorResult | None:
        """Look up a result by display name."""
        for r in self.results:
            if r.name == name:
                return r
        return None

    def get_value(self, name: str, default: float = 0.0) -> float:
        """Get the numeric value of a named result."""
        r = self.get(name)
        return r.value if r is not None else default

    def to_dict(self) -> dict[str, dict[str, object]]:
        """Serialize all results to a flat dict keyed by name."""
        return {r.name: {"value": r.value, "label": r.label} for r in self.results}

    def format_markdown(self) -> str:
        """Format results as a markdown block for the AI prompt."""
        if not self.results:
            return ""
        lines = ["## Computed Indicators"]
        for r in self.results:
            lines.append(f"- {r.name}: {r.label}")
        return "\n".join(lines)

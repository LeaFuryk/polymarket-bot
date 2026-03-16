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
    _index: dict[str, IndicatorResult] = field(default_factory=dict, repr=False)

    def _ensure_index(self) -> dict[str, IndicatorResult]:
        if not self._index and self.results:
            self._index = {r.name: r for r in self.results}
        return self._index

    def get(self, name: str) -> IndicatorResult | None:
        """Look up a result by name (accepts str or Indicator enum)."""
        return self._ensure_index().get(name)

    def get_value(self, name: str, default: float = 0.0) -> float:
        """Get the numeric value of a named result."""
        r = self.get(name)
        return r.value if r is not None else default

    def get_extra(self, name: str, key: str, default: float | str = 0.0) -> float | str:
        """Get an extras value from a named result."""
        r = self.get(name)
        if r is not None:
            return r.extras.get(key, default)
        return default

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

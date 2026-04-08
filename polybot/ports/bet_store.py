"""Port: bet record persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from polybot.domain.bet_record import BetRecord


@runtime_checkable
class BetStore(Protocol):
    """Persists individual bet records."""

    async def save_bet(self, record: BetRecord) -> None: ...

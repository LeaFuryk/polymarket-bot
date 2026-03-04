"""Protocols for pluggable forensics investigations."""

from __future__ import annotations

import sqlite3
from typing import Protocol, TypeVar, runtime_checkable

T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class Investigator(Protocol[T_co]):
    """A pluggable forensics investigation.

    Each investigation loads data from the database, runs analysis, and returns
    typed results.  Implementations should be stateless — all state lives in the
    database and the returned result objects.

    Type parameter ``T_co`` is the investigation's result type (e.g. a tuple of
    per-item list and aggregate model, or a plain list).

    Example usage::

        class MyInvestigator:
            @property
            def name(self) -> str:
                return "my_investigation"

            def analyze(self, conn: sqlite3.Connection) -> list[MyResult]:
                ...
    """

    @property
    def name(self) -> str:
        """Short, unique identifier for this investigation (e.g. ``'execution'``)."""
        ...

    def analyze(self, conn: sqlite3.Connection) -> T_co:
        """Run the investigation against *conn* and return typed results."""
        ...

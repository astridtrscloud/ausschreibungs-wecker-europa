"""Basis-Interface für alle Ausschreibungsquellen."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class TenderRaw:
    """Rohdaten einer Ausschreibung von einer Quelle."""
    external_id: str
    title: str
    description: str = ""
    buyer: str = ""
    country: str = ""           # ISO-2 (DE, CH, FR, ...)
    language: str = ""          # ISO-2 (de, fr, it, ...)
    cpv_codes: list[str] = field(default_factory=list)
    region: str = ""            # NUTS-Code wenn vorhanden
    deadline: datetime | None = None
    published_at: datetime | None = None
    url: str = ""
    currency: str | None = None     # "CHF", "EUR"
    estimated_value: float | None = None
    raw_json: dict = field(default_factory=dict)


class SourceProtocol(Protocol):
    """Protokoll das jede Quelle implementieren muss."""
    name: str
    async def fetch(self) -> list[TenderRaw]: ...

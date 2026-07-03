"""SQLModel-Datenmodelle für Ausschreibungs-Wecker Europa.

Erweiterungen gegenüber Basis-Version:
- Tender: country, language, currency, estimated_value
- CompanyProfile: countries (ISO-2), languages_ok (ISO-2)
"""
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint
from typing import Optional, TYPE_CHECKING
import json

if TYPE_CHECKING:
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Tender(SQLModel, table=True):
    """Eine Ausschreibung aus einer öffentlichen Vergabeplattform."""

    __tablename__ = "tender"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uix_tender_source_external_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True, description="Quell-Name: ted, simap_ch, bund_de")
    external_id: str = Field(index=True, description="ID bei der Quelle")
    title: str = Field(description="Titel der Ausschreibung")
    description: str = Field(default="", description="Volltext-Beschreibung")
    buyer: str = Field(default="", description="Vergabestelle")
    country: str = Field(default="", index=True, description="Land ISO-2: DE, CH, FR, ...")
    language: str = Field(default="", description="Sprache ISO-2: de, fr, it, ...")
    cpv_codes: str = Field(default="[]", description="CPV-Codes als JSON-Liste")
    region: str = Field(default="", description="Region/NUTS-Code")
    deadline: Optional[datetime] = Field(default=None, description="Abgabefrist")
    published_at: Optional[datetime] = Field(default=None, description="Veröffentlichungsdatum")
    url: str = Field(default="", description="Link zur Original-Ausschreibung")
    currency: Optional[str] = Field(default=None, description="Währung: CHF, EUR")
    estimated_value: Optional[float] = Field(default=None, description="Geschätzter Auftragswert")
    raw_json: str = Field(default="{}", description="Rohdaten als JSON")
    created_at: datetime = Field(default_factory=utc_now, description="Eintragszeitpunkt")

    matches: list["Match"] = Relationship(back_populates="tender")

    def get_cpv_codes(self) -> list[str]:
        try:
            return json.loads(self.cpv_codes)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_raw_json(self) -> dict:
        try:
            return json.loads(self.raw_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    def __repr__(self) -> str:
        return f"<Tender({self.source}:{self.external_id} | {self.country} | {self.title[:40]}...)>"


class CompanyProfile(SQLModel, table=True):
    """Firmenprofil für das mehrsprachige Matching."""

    __tablename__ = "companyprofile"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="Firmenname")
    description: str = Field(default="", description="Beschreibung der Kernleistungen")
    keywords: str = Field(default="[]", description="Keywords als JSON-Liste")
    cpv_whitelist: str = Field(default="[]", description="Erwünschte CPV-Codes als JSON")
    countries: str = Field(default="[]", description="Erwünschte Länder ISO-2 als JSON, leer = alle")
    regions: str = Field(default="[]", description="Erwünschte Regionen/NUTS als JSON")
    languages_ok: str = Field(default='["de","en"]', description="Sprachen in denen die Firma anbietet")
    min_deadline_days: int = Field(default=7, description="Min. Tage bis Deadline")
    created_at: datetime = Field(default_factory=utc_now)

    matches: list["Match"] = Relationship(back_populates="profile")

    def get_keywords(self) -> list[str]:
        try:
            return json.loads(self.keywords)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_cpv_whitelist(self) -> list[str]:
        try:
            return json.loads(self.cpv_whitelist)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_countries(self) -> list[str]:
        try:
            return json.loads(self.countries)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_regions(self) -> list[str]:
        try:
            return json.loads(self.regions)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_languages_ok(self) -> list[str]:
        try:
            return json.loads(self.languages_ok)
        except (json.JSONDecodeError, TypeError):
            return ["de", "en"]


class Match(SQLModel, table=True):
    """Match-Ergebnis zwischen Tender und Firmenprofil."""

    __tablename__ = "match"

    id: Optional[int] = Field(default=None, primary_key=True)
    tender_id: int = Field(foreign_key="tender.id")
    profile_id: int = Field(foreign_key="companyprofile.id")
    score: int = Field(description="LLM-Score 0-100")
    reasoning: str = Field(default="", description="LLM-Begründung")
    status: str = Field(default="new", description="new/notified/dismissed/saved")
    created_at: datetime = Field(default_factory=utc_now)

    tender: Optional[Tender] = Relationship(back_populates="matches")
    profile: Optional[CompanyProfile] = Relationship(back_populates="matches")

    def __repr__(self) -> str:
        return f"<Match(id={self.id}, score={self.score}, status={self.status})>"

"""Tests fuer SQLModel-Datenmodelle."""
import pytest
from sqlmodel import SQLModel, create_engine, Session, select

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.models.models import Tender, CompanyProfile, Match, utc_now


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


class TestTender:
    def test_create_with_country_language(self, session):
        tender = Tender(
            source="ted",
            external_id="TEST-123",
            title="Bauarbeiten",
            country="DE",
            language="de",
            currency="EUR",
            estimated_value=500000.0,
            cpv_codes='["45110000"]',
        )
        session.add(tender)
        session.commit()
        session.refresh(tender)
        assert tender.id is not None
        assert tender.country == "DE"
        assert tender.language == "de"
        assert tender.currency == "EUR"
        assert tender.estimated_value == 500000.0

    def test_cpv_parsing(self, session):
        tender = Tender(source="ted", external_id="CPV-1", title="Test", cpv_codes='["45110000", "45220000"]')
        assert tender.get_cpv_codes() == ["45110000", "45220000"]

    def test_unique_constraint(self, session):
        t1 = Tender(source="ted", external_id="DUP-1", title="Erster", country="FR")
        t2 = Tender(source="ted", external_id="DUP-1", title="Zweiter", country="FR")
        session.add(t1)
        session.commit()
        session.add(t2)
        with pytest.raises(Exception):
            session.commit()

    def test_swiss_tender(self, session):
        tender = Tender(
            source="simap_ch",
            external_id="CH-001",
            title="Bau Schulhaus Zuerich",
            country="CH",
            language="de",
            currency="CHF",
            estimated_value=2500000.0,
            region="ZH",
        )
        session.add(tender)
        session.commit()
        assert tender.currency == "CHF"
        assert tender.country == "CH"


class TestCompanyProfile:
    def test_profile_with_countries_languages(self, session):
        profile = CompanyProfile(
            name="Musterbau GmbH",
            description="Bauunternehmen",
            keywords='["Bau", "Tiefbau"]',
            cpv_whitelist='["45110000"]',
            countries='["DE", "CH", "AT"]',
            languages_ok='["de", "fr", "en"]',
            min_deadline_days=14,
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        assert profile.get_countries() == ["DE", "CH", "AT"]
        assert profile.get_languages_ok() == ["de", "fr", "en"]

    def test_empty_countries_means_all(self, session):
        profile = CompanyProfile(name="Global Corp", countries='[]')
        assert profile.get_countries() == []


class TestMatch:
    def test_create_match(self, session):
        tender = Tender(source="ted", external_id="M-1", title="Test", country="DE")
        profile = CompanyProfile(name="Test-Firma")
        session.add(tender)
        session.add(profile)
        session.commit()
        match = Match(tender_id=tender.id, profile_id=profile.id, score=85, reasoning="Gut", status="new")
        session.add(match)
        session.commit()
        assert match.score == 85

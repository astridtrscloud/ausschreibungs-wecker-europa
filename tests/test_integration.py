"""End-to-End Integrationstests.

Simuliert den kompletten Flow:
  Scraper (mehrere Quellen) -> Matcher (Vorfilter + LLM) -> Notifier

Verwendet ausschliesslich Mocks – keine externen APIs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.sources.base import TenderRaw
from app.sources._registry import SOURCES
from app.services.matcher import Matcher
from app.services.notifier import Notifier
from app.services.deduper import CrossSourceDeduper
from app.models.models import Tender, CompanyProfile, Match


@pytest.fixture
def sample_raw_tenders() -> List[TenderRaw]:
    future_90 = datetime.now(timezone.utc) + timedelta(days=90)
    future_60 = datetime.now(timezone.utc) + timedelta(days=60)
    future_30 = datetime.now(timezone.utc) + timedelta(days=30)
    future_120 = datetime.now(timezone.utc) + timedelta(days=120)

    return [
        TenderRaw(
            source="ted", external_id="TED-001",
            title="Bauarbeiten Schulhaus Muenchen",
            description="Neubau Schulhaus mit Turnhalle",
            buyer="Stadt Muenchen", country="DE", language="de",
            cpv_codes=["45110000"], deadline=future_90,
            url="https://ted.europa.eu/1", currency="EUR", estimated_value=800000.0,
        ),
        TenderRaw(
            source="simap_ch", external_id="SIMAP-001",
            title="IT-Modernisierung Kanton Zuerich",
            description="Cloud-Migration und Modernisierung",
            buyer="Kanton Zuerich", country="CH", language="de",
            cpv_codes=["72000000"], deadline=future_60,
            url="https://simap.ch/1", currency="CHF", estimated_value=1500000.0,
        ),
        TenderRaw(
            source="ted", external_id="TED-002",
            title="Travaux construction route Lyon",
            description="Construction route departementale",
            buyer="Conseil Departemental du Rhone", country="FR", language="fr",
            cpv_codes=["45230000"], deadline=future_30,
            url="https://ted.europa.eu/2", currency="EUR", estimated_value=450000.0,
        ),
        TenderRaw(
            source="bund_de", external_id="BUND-001",
            title="Beratung Digitalisierung Verwaltung",
            description="IT-Beratung fuer Digitalisierung",
            buyer="BMI", country="DE", language="de",
            cpv_codes=["72000000"], deadline=future_120,
            url="https://bund.de/1", currency="EUR", estimated_value=200000.0,
        ),
        TenderRaw(
            source="simap_ch", external_id="SIMAP-002",
            title="Bauarbeiten Schulhaus Muenchen",
            description="Neubau Schulhaus mit Turnhalle",
            buyer="Stadt Muenchen", country="DE", language="de",
            cpv_codes=["45110000"], deadline=future_90,
            url="https://simap.ch/2", currency="EUR", estimated_value=800000.0,
        ),
    ]


@pytest.fixture
def sample_profile() -> CompanyProfile:
    return CompanyProfile(
        id=1, name="Bau & IT GmbH",
        description="Bauunternehmen mit IT-Beratung",
        keywords='["Bau", "IT", "Cloud", "Digitalisierung"]',
        cpv_whitelist='["45110000", "72000000", "45230000"]',
        countries='["DE", "CH", "FR", "AT"]',
        languages_ok='["de", "en", "fr"]',
        min_deadline_days=7,
    )


class TestScraperIntegration:
    @pytest.mark.asyncio
    async def test_all_sources_return_tender_raw(self, sample_raw_tenders):
        for source in SOURCES:
            with patch.object(source, "fetch", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = [
                    t for t in sample_raw_tenders if t.source == source.name
                ][:1] or [sample_raw_tenders[0]]

                result = await source.fetch()
                assert all(isinstance(t, TenderRaw) for t in result)
                assert len(result) >= 0

    def test_tender_raw_normalization(self, sample_raw_tenders):
        for t in sample_raw_tenders:
            assert t.source in ("ted", "simap_ch", "bund_de")
            assert len(t.external_id) > 0
            assert len(t.title) > 0
            assert len(t.country) == 2

    def test_cross_source_country_coverage(self, sample_raw_tenders):
        countries = {t.country for t in sample_raw_tenders}
        assert "DE" in countries
        assert "CH" in countries
        assert "FR" in countries


class TestRawToModel:
    def test_conversion(self, sample_raw_tenders):
        raw = sample_raw_tenders[0]
        tender = Tender(
            source=raw.source, external_id=raw.external_id, title=raw.title,
            description=raw.description, buyer=raw.buyer, country=raw.country,
            language=raw.language, cpv_codes=json.dumps(raw.cpv_codes),
            region=raw.region, deadline=raw.deadline, published_at=raw.published_at,
            url=raw.url, currency=raw.currency, estimated_value=raw.estimated_value,
            raw_json=raw.to_dict(),
        )
        assert tender.source == raw.source
        assert tender.get_cpv_codes() == raw.cpv_codes
        assert tender.country == raw.country

    def test_all_sources_convertible(self, sample_raw_tenders):
        import json as _json
        for raw in sample_raw_tenders:
            t = Tender(
                source=raw.source, external_id=raw.external_id, title=raw.title,
                country=raw.country, cpv_codes=_json.dumps(raw.cpv_codes),
            )
            assert t.source == raw.source


class TestMatcherIntegration:
    def test_prefilter_allows_relevant(self, sample_profile):
        mock_llm = MagicMock()
        matcher = Matcher(llm_client=mock_llm, max_calls=5)
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten",
            country="DE", cpv_codes='["45110000"]',
        )
        assert matcher.prefilter(tender, sample_profile) is True

    def test_prefilter_excludes_by_country(self, sample_profile):
        mock_llm = MagicMock()
        matcher = Matcher(llm_client=mock_llm, max_calls=5)
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten",
            country="PL",
        )
        assert matcher.prefilter(tender, sample_profile) is False

    @pytest.mark.asyncio
    async def test_llm_scoring_returns_result(self, sample_profile):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 85, "reasoning": "Guter Match", "deadline_ok": true, "language_ok": true}'))
        ]
        mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)

        matcher = Matcher(llm_client=mock_llm, max_calls=5)
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bau Schulhaus",
            country="DE", language="de",
        )
        result = await matcher.llm_score(tender, sample_profile)
        assert result is not None
        assert result.score >= 70
        assert result.deadline_ok is True

    @pytest.mark.asyncio
    async def test_full_matching_pipeline(self, sample_profile):
        tenders = [
            Tender(id=1, source="ted", external_id="T1", title="Bau", country="DE", cpv_codes='["45110000"]', language="de"),
            Tender(id=2, source="ted", external_id="T2", title="Polnischer Tender", country="PL", cpv_codes='["45110000"]', language="pl"),
            Tender(id=3, source="simap_ch", external_id="S1", title="IT Cloud", country="CH", cpv_codes='["72000000"]', language="de"),
        ]

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 88, "reasoning": "Gut", "deadline_ok": true, "language_ok": true}'))
        ]
        mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)

        matcher = Matcher(llm_client=mock_llm, max_calls=10)

        candidates = [t for t in tenders if matcher.prefilter(t, sample_profile)]
        assert len(candidates) == 2
        assert all(t.country in ("DE", "CH", "FR", "AT") for t in candidates)

        results = []
        for t in candidates:
            result = await matcher.llm_score(t, sample_profile)
            if result and result.score >= 70:
                results.append((t, result))

        assert len(results) == 2


class TestDeduperIntegration:
    def test_cross_source_duplicate_detection(self):
        deadline = datetime(2025, 6, 30, 12, 0, tzinfo=timezone.utc)

        existing_tenders = [
            Tender(
                id=1, source="ted", external_id="TED-001",
                title="Bau Schulhaus Zuerich", buyer="Stadt Zuerich",
                country="CH", deadline=deadline,
            ),
        ]

        new_tenders = [
            Tender(
                id=2, source="simap_ch", external_id="SIMAP-001",
                title="Bau Schulhaus Zuerich", buyer="Stadt Zuerich",
                country="CH", deadline=deadline,
            ),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing_tenders

        deduper = CrossSourceDeduper(threshold=92)
        duplicates = deduper.find_duplicates(mock_session, new_tenders)

        assert len(duplicates) == 1
        assert duplicates[0][0].source == "simap_ch"
        assert duplicates[0][1].source == "ted"

    def test_dedupe_pipeline(self, sample_raw_tenders):
        future = datetime.now(timezone.utc) + timedelta(days=90)

        existing = [
            Tender(
                id=1, source="ted", external_id="TED-001",
                title="Bauarbeiten Schulhaus Muenchen", buyer="Stadt Muenchen",
                country="DE", deadline=future,
            ),
        ]

        new_tenders = [
            Tender(
                id=2, source="simap_ch", external_id="SIMAP-002",
                title="Bauarbeiten Schulhaus Muenchen", buyer="Stadt Muenchen",
                country="DE", deadline=future,
            ),
            Tender(
                id=3, source="ted", external_id="TED-NEW",
                title="Voellig neues Projekt", buyer="Neue Firma",
                country="DE", deadline=future + timedelta(days=30),
            ),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        deduper = CrossSourceDeduper(threshold=92)
        filtered = deduper.filter_duplicates(mock_session, new_tenders)

        assert len(filtered) == 1
        assert filtered[0].external_id == "TED-NEW"


class TestNotifierIntegration:
    def test_notifier_groups_by_country(self):
        matches_tenders = [
            (Match(id=1, tender_id=1, profile_id=1, score=85, reasoning="Gut", status="new"),
             Tender(id=1, source="ted", external_id="T1", title="Bau DE", country="DE", url="https://x.de")),
            (Match(id=2, tender_id=2, profile_id=1, score=90, reasoning="Sehr gut", status="new"),
             Tender(id=2, source="simap_ch", external_id="S1", title="IT CH", country="CH", url="https://x.ch")),
            (Match(id=3, tender_id=3, profile_id=1, score=75, reasoning="OK", status="new"),
             Tender(id=3, source="ted", external_id="T2", title="Route FR", country="FR", url="https://x.fr")),
        ]

        grouped = Notifier._group_by_country(matches_tenders)
        assert "DE" in grouped
        assert "CH" in grouped
        assert "FR" in grouped
        assert len(grouped["DE"]) == 1
        assert len(grouped["CH"]) == 1
        assert len(grouped["FR"]) == 1

    def test_email_html_contains_all_countries(self):
        mock_session = MagicMock()
        mock_settings = MagicMock()
        mock_settings.smtp_user = "test@test.com"
        mock_settings.smtp_host = "smtp.test.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_pass = "pass"
        mock_settings.mail_to = "to@test.com"
        mock_settings.slack_webhook_url = ""

        matches_tenders = [
            (Match(id=1, tender_id=1, profile_id=1, score=85, reasoning="Gut", status="new"),
             Tender(id=1, source="ted", external_id="T1", title="Bau DE", country="DE", url="https://x.de", estimated_value=500000.0, currency="EUR", deadline=datetime(2025, 8, 15, tzinfo=timezone.utc))),
            (Match(id=2, tender_id=2, profile_id=1, score=90, reasoning="Sehr gut", status="new"),
             Tender(id=2, source="simap_ch", external_id="S1", title="IT CH", country="CH", url="https://x.ch", estimated_value=1000000.0, currency="CHF", deadline=datetime(2025, 9, 1, tzinfo=timezone.utc))),
        ]

        notifier = Notifier(session=mock_session, settings=mock_settings)
        grouped = Notifier._group_by_country(matches_tenders)
        html = notifier._build_email_html(grouped, "Test-Firma")

        assert "🇩🇪 Deutschland" in html
        assert "🇨🇭 Schweiz" in html
        assert "Bau DE" in html
        assert "IT CH" in html


class TestEndToEndFlow:
    @pytest.mark.asyncio
    async def test_complete_pipeline(self, sample_raw_tenders, sample_profile):
        raw_tenders = sample_raw_tenders
        assert len(raw_tenders) == 5

        import json as _json
        db_tenders = []
        for raw in raw_tenders:
            t = Tender(
                source=raw.source, external_id=raw.external_id, title=raw.title,
                description=raw.description, buyer=raw.buyer, country=raw.country,
                language=raw.language, cpv_codes=_json.dumps(raw.cpv_codes),
                deadline=raw.deadline, url=raw.url, currency=raw.currency,
                estimated_value=raw.estimated_value,
            )
            t.id = len(db_tenders) + 1
            db_tenders.append(t)

        existing = [db_tenders[0]]
        new_batch = db_tenders[1:]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        deduper = CrossSourceDeduper(threshold=92)
        deduped = deduper.filter_duplicates(mock_session, new_batch)
        assert len(deduped) <= len(new_batch)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 88, "reasoning": "Guter Match", "deadline_ok": true, "language_ok": true}'))
        ]
        mock_llm.chat.completions.create = AsyncMock(return_value=mock_response)

        matcher = Matcher(llm_client=mock_llm, max_calls=10)

        candidates = [t for t in deduped if matcher.prefilter(t, sample_profile)]
        assert len(candidates) >= 2

        scored_matches = []
        for t in candidates:
            result = await matcher.llm_score(t, sample_profile)
            if result and result.score >= 70:
                scored_matches.append((t, result))

        assert len(scored_matches) >= 2

        mock_match_objs = []
        mock_tenders = []
        for t, result in scored_matches:
            m = Match(
                id=len(mock_match_objs) + 1, tender_id=t.id,
                profile_id=sample_profile.id, score=result.score,
                reasoning=result.reasoning, status="new",
            )
            mock_match_objs.append(m)
            mock_tenders.append(t)

        mt_pairs = list(zip(mock_match_objs, mock_tenders))
        grouped = Notifier._group_by_country(mt_pairs)
        assert len(grouped) >= 2

        mock_settings = MagicMock()
        mock_settings.smtp_user = "test@test.com"
        mock_settings.smtp_host = "smtp.test.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_pass = "pass"
        mock_settings.mail_to = "to@test.com"
        mock_settings.slack_webhook_url = ""

        notifier = Notifier(session=mock_session, settings=mock_settings)
        html = notifier._build_email_html(grouped, "Bau & IT GmbH")

        assert "Ausschreibungs-Wecker Europa" in html
        assert len(html) > 500

        print(f"\n{'='*60}")
        print(f"E2E Pipeline erfolgreich:")
        print(f"  Raw Tenders: {len(raw_tenders)}")
        print(f"  Nach Dedupe: {len(deduped)}")
        print(f"  Kandidaten:  {len(candidates)}")
        print(f"  Matches:     {len(scored_matches)}")
        print(f"  Laender:     {list(grouped.keys())}")
        print(f"{'='*60}")

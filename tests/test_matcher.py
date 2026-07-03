"""Tests fuer den LLM-Matcher.

Testet den zweistufigen Matching-Prozess:
1. Vorfilter (CPV, Keywords, Land, Deadline) – synchron, kein LLM
2. LLM-Scoring – asynchron, mit Mock-LLM
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.services.matcher import Matcher, MatchResult
from app.models.models import Tender, CompanyProfile


@pytest.fixture
def matcher():
    mock_llm = MagicMock()
    mock_llm.chat = MagicMock()
    mock_llm.chat.completions = MagicMock()
    return Matcher(llm_client=mock_llm, max_calls=10)


@pytest.fixture
def profile_de():
    return CompanyProfile(
        id=1,
        name="Musterbau GmbH",
        description="Bauunternehmen fuer Tief- und Hochbau",
        keywords='["Bau", "Tiefbau", "Hochbau", "Ingenieurbau"]',
        cpv_whitelist='["45110000", "45220000", "45120000"]',
        countries='["DE", "CH", "AT"]',
        languages_ok='["de", "en"]',
        min_deadline_days=7,
    )


@pytest.fixture
def profile_it():
    return CompanyProfile(
        id=2,
        name="Tech Solutions SRL",
        description="Software-Entwicklung und IT-Beratung",
        keywords='["Software", "IT", "Cloud", "Beratung"]',
        cpv_whitelist='["72000000", "72510000"]',
        countries='["IT", "DE", "CH"]',
        languages_ok='["it", "en", "de"]',
        min_deadline_days=14,
    )


class TestPrefilter:
    def test_land_filter_excludes_wrong_country(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten", country="PL",
        )
        assert matcher.prefilter(tender, profile_de) is False

    def test_land_filter_includes_matching_country(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten", country="DE",
        )
        assert matcher.prefilter(tender, profile_de) is True

    def test_empty_countries_means_all(self, matcher):
        profile = CompanyProfile(id=3, name="Global Corp", countries='[]')
        tender = Tender(id=1, source="ted", external_id="T1", title="X", country="XX")
        assert matcher.prefilter(tender, profile) is True

    def test_deadline_filter_excludes_too_short(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten",
            country="DE",
            deadline=datetime.now(timezone.utc) + timedelta(days=2),
        )
        assert matcher.prefilter(tender, profile_de) is False

    def test_deadline_filter_includes_sufficient(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten",
            country="DE",
            deadline=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert matcher.prefilter(tender, profile_de) is True

    def test_cpv_match_passes_immediately(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Bauarbeiten",
            country="DE", cpv_codes='["45110000"]',
        )
        assert matcher.prefilter(tender, profile_de) is True

    def test_keyword_match_passes(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Tiefbau Brueckenbau",
            country="DE", cpv_codes='["99999999"]',
        )
        assert matcher.prefilter(tender, profile_de) is True

    def test_no_cpv_no_keywords_profile_allows_all(self, matcher):
        profile = CompanyProfile(id=4, name="Open", keywords='[]', cpv_whitelist='[]', countries='[]')
        tender = Tender(id=1, source="ted", external_id="T1", title="X", country="XX")
        assert matcher.prefilter(tender, profile) is True

    def test_swiss_tender_with_german_profile(self, matcher, profile_de):
        tender = Tender(
            id=1, source="simap_ch", external_id="S1", title="Bau Schulhaus Zuerich",
            country="CH", cpv_codes='["45110000"]', language="de",
        )
        assert matcher.prefilter(tender, profile_de) is True

    def test_french_tender_with_no_french_language(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="Travaux de construction",
            country="CH", language="fr", cpv_codes='["45110000"]',
        )
        assert matcher.prefilter(tender, profile_de) is True


class TestLLMScoring:
    @pytest.mark.asyncio
    async def test_llm_score_returns_match_result(self, matcher, profile_de):
        tender = Tender(id=1, source="ted", external_id="T1", title="Bauarbeiten", country="DE")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 85, "reasoning": "Guter Match", "deadline_ok": true, "language_ok": true}'))
        ]
        matcher.llm.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await matcher.llm_score(tender, profile_de)

        assert result is not None
        assert result.score == 85
        assert result.deadline_ok is True
        assert result.language_ok is True

    @pytest.mark.asyncio
    async def test_llm_score_respects_max_calls(self, matcher, profile_de):
        matcher._calls_made = matcher.max_calls
        tender = Tender(id=1, source="ted", external_id="T1", title="X")
        result = await matcher.llm_score(tender, profile_de)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_score_retry_on_error(self, matcher, profile_de):
        tender = Tender(id=1, source="ted", external_id="T1", title="Bau")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"score": 75, "reasoning": "OK", "deadline_ok": true, "language_ok": true}'))
        ]
        matcher.llm.chat.completions.create = AsyncMock(
            side_effect=[Exception("Timeout"), mock_response]
        )

        result = await matcher.llm_score(tender, profile_de)
        assert result is not None
        assert result.score == 75


class TestPromptBuilding:
    def test_build_prompt_contains_all_fields(self, matcher, profile_de):
        tender = Tender(
            id=1, source="ted", external_id="T1", title="IT-Modernisierung",
            description="Modernisierung der IT-Infrastruktur",
            buyer="Bundesministerium", country="DE", language="de",
            cpv_codes='["72000000"]',
            deadline=datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
            estimated_value=500000.0, currency="EUR", region="DE212",
        )
        prompt = matcher._build_prompt(tender, profile_de)
        assert "Musterbau GmbH" in prompt
        assert "IT-Modernisierung" in prompt
        assert "500,000" in prompt or "500000" in prompt or "500.000" in prompt
        assert "DE" in prompt
        assert "15.06.2025" in prompt

    def test_build_prompt_no_deadline(self, matcher, profile_de):
        tender = Tender(id=1, source="ted", external_id="T1", title="Test")
        prompt = matcher._build_prompt(tender, profile_de)
        assert "nicht angegeben" in prompt


class TestResponseParsing:
    def test_parse_valid_json(self, matcher):
        raw = '{"score": 88, "reasoning": "Sehr guter Match", "deadline_ok": true, "language_ok": true}'
        result = matcher._parse_response(raw)
        assert result is not None
        assert result.score == 88
        assert result.reasoning == "Sehr guter Match"
        assert result.deadline_ok is True

    def test_parse_json_in_markdown_codeblock(self, matcher):
        raw = 'Hier ist das Ergebnis:\n```json\n{"score": 72, "reasoning": "OK", "deadline_ok": true, "language_ok": false}\n```'
        result = matcher._parse_response(raw)
        assert result is not None
        assert result.score == 72

    def test_parse_malformed_response_returns_none(self, matcher):
        raw = "Das ist kein JSON"
        result = matcher._parse_response(raw)
        assert result is None

    def test_parse_partial_json(self, matcher):
        raw = 'Der Score ist {\n  "score": 65,\n  "reasoning": "Mittel",\n  "deadline_ok": true,\n  "language_ok": true\n} fuer diesen Tender.'
        result = matcher._parse_response(raw)
        assert result is not None
        assert result.score == 65

    def test_parse_invalid_score_type(self, matcher):
        raw = '{"score": "invalid", "reasoning": "x", "deadline_ok": true, "language_ok": true}'
        result = matcher._parse_response(raw)
        assert result is None

    def test_parse_empty_response(self, matcher):
        assert matcher._parse_response("") is None
        assert matcher._parse_response("   ") is None


class TestMatchResult:
    def test_creation(self):
        mr = MatchResult(score=85, reasoning="Gut", deadline_ok=True, language_ok=True)
        assert mr.score == 85
        assert mr.reasoning == "Gut"
        assert mr.deadline_ok is True

    def test_score_zero(self):
        mr = MatchResult(score=0, reasoning="Nichts", deadline_ok=False, language_ok=False)
        assert mr.score == 0

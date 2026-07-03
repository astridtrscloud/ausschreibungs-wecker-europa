"""Tests fuer Ausschreibungsquellen (TED, simap.ch, bund.de).

Verwendet ausschliesslich Mocks – keine echten HTTP-Requests.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.sources.base import TenderRaw
from app.sources._registry import SOURCES
from app.sources.ted import TEDSource
from app.sources.simap_ch import SIMAPSource
from app.sources.bund_de import BundDeSource


def _make_ted_notice(
    pub_num: str = "2024-123456",
    title: Dict[str, List[str]] | None = None,
    country_iso3: str = "DEU",
    deadline: str = "2025-06-30T23:59:59+02:00",
) -> Dict[str, Any]:
    """Baut ein minimal gueltiges TED-Notice-Dict."""
    return {
        "publication-number": pub_num,
        "notice-title": title or {"deu": ["Bauarbeiten Schulhaus"]},
        "description-glo": {"deu": ["Bauarbeiten fuer ein neues Schulhaus."]},
        "buyer-name": {"deu": ["Stadt Muenchen"]},
        "place-of-performance": [country_iso3],
        "deadline": deadline,
        "publication-date": "2024-01-15T08:00:00+01:00",
        "links": {"html": {"DEU": f"https://ted.europa.eu/en/notice/-/detail/{pub_num}"}},
        "BT-262-Lot": ["45110000"],
        "BT-27-Procedure": {"amount": 500000, "currency": "EUR"},
        "BT-27-Procedure-Currency": "EUR",
    }


class TestRegistry:
    def test_registry_has_all_sources(self):
        names = [s.name for s in SOURCES]
        assert "ted" in names
        assert "simap_ch" in names
        assert "bund_de" in names
        assert len(SOURCES) >= 3

    def test_registry_sources_are_callable(self):
        for source in SOURCES:
            assert hasattr(source, "fetch")
            assert hasattr(source, "name")
            assert isinstance(source.name, str)


class TestTenderRaw:
    def test_basic_creation(self):
        t = TenderRaw(source="ted", external_id="TEST-001", title="Bauarbeiten")
        assert t.source == "ted"
        assert t.external_id == "TEST-001"
        assert t.title == "Bauarbeiten"
        assert t.cpv_codes == []
        assert t.country == ""

    def test_to_dict_serialisation(self):
        t = TenderRaw(
            source="ted",
            external_id="T-1",
            title="IT-Dienstleistungen",
            description="Software-Entwicklung",
            buyer="Bundesagentur",
            country="DE",
            language="de",
            cpv_codes=["72000000"],
            deadline=datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
            published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            url="https://example.com/tender/1",
            currency="EUR",
            estimated_value=250000.0,
        )
        d = t.to_dict()
        assert d["source"] == "ted"
        assert d["country"] == "DE"
        assert d["deadline"] == "2025-06-15T12:00:00+00:00"
        assert d["estimated_value"] == 250000.0

    def test_swiss_tender_raw(self):
        t = TenderRaw(
            source="simap_ch",
            external_id="simap-abc-123",
            title="Bau Schulhaus Zuerich",
            buyer="Stadt Zuerich",
            country="CH",
            language="de",
            currency="CHF",
            estimated_value=1200000.0,
            region="ZH",
        )
        assert t.currency == "CHF"
        assert t.country == "CH"
        assert t.region == "ZH"


class TestTEDSource:
    @pytest.fixture
    def ted(self):
        return TEDSource(
            api_url="https://api.ted.europa.eu/v3/notices/search",
            countries=["DE", "FR", "CH"],
            max_pages=1,
            page_size=5,
            timeout=10,
            retries=2,
            rate_limit_delay=0.0,
        )

    @pytest.mark.asyncio
    async def test_fetch_normalizes_tender(self, ted):
        notice = _make_ted_notice(
            pub_num="2024-999999",
            title={"deu": ["IT-Modernisierung Behoerde"]},
            country_iso3="DEU",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"notices": [notice]}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=mock_response)

            tenders = await ted.fetch()

        assert len(tenders) == 1
        t = tenders[0]
        assert t.source == "ted"
        assert t.external_id == "2024-999999"
        assert t.country == "DE"
        assert t.language == "de"
        assert t.currency == "EUR"
        assert t.estimated_value == 500000.0

    @pytest.mark.asyncio
    async def test_fetch_filters_by_country(self, ted):
        notices = [
            _make_ted_notice(pub_num="N1", country_iso3="DEU"),
            _make_ted_notice(pub_num="N2", country_iso3="FRA"),
            _make_ted_notice(pub_num="N3", country_iso3="USA"),
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"notices": notices}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=mock_response)

            tenders = await ted.fetch()

        countries = [t.country for t in tenders]
        assert "DE" in countries
        assert "FR" in countries
        assert "US" not in countries

    @pytest.mark.asyncio
    async def test_fetch_empty_response(self, ted):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"notices": []}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=mock_response)

            tenders = await ted.fetch()

        assert tenders == []

    @pytest.mark.asyncio
    async def test_fetch_http_error_with_retry(self, ted):
        import httpx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(
                side_effect=[
                    httpx.HTTPStatusError(
                        "500",
                        request=MagicMock(),
                        response=MagicMock(status_code=500),
                    ),
                    MagicMock(
                        raise_for_status=MagicMock(),
                        json=MagicMock(return_value={"notices": []}),
                    ),
                ]
            )

            tenders = await ted.fetch()
            assert tenders == []
            assert mock_client.post.call_count == 2

    def test_normalize_multilingual_title(self, ted):
        notice = _make_ted_notice(
            title={"deu": ["Deutscher Titel"], "fra": ["Titre français"], "eng": ["English Title"]},
        )
        t = ted._normalize(notice)
        assert t.title == "Deutscher Titel"
        assert t.language == "de"

    def test_normalize_french_title_fallback(self, ted):
        notice = _make_ted_notice(title={"fra": ["Titre français"]})
        t = ted._normalize(notice)
        assert t.title == "Titre français"
        assert t.language == "fr"

    def test_extract_country_from_iso3(self, ted):
        assert ted._resolve_country_from_field("DEU") == "DE"
        assert ted._resolve_country_from_field("FRA") == "FR"
        assert ted._resolve_country_from_field("CHE") == "CH"
        assert ted._resolve_country_from_field("UNKNOWN") == ""

    def test_parse_datetime_various_formats(self, ted):
        dt1 = ted._parse_datetime("2025-06-30T23:59:59+02:00")
        assert dt1 is not None
        assert dt1.year == 2025

        dt2 = ted._parse_datetime("2025-06-30T23:59:59Z")
        assert dt2 is not None

        dt3 = ted._parse_datetime("2025-06-30")
        assert dt3 is not None
        assert dt3.day == 30

        dt4 = ted._parse_datetime("")
        assert dt4 is None

        dt5 = ted._parse_datetime(None)
        assert dt5 is None

    def test_parse_datetime_offset_only(self, ted):
        dt = ted._parse_datetime("2016-07-09+02:00")
        assert dt is not None
        assert dt.year == 2016
        assert dt.month == 7
        assert dt.day == 9

    def test_extract_value_currency(self, ted):
        notice = _make_ted_notice()
        currency, value = ted._extract_value_currency(notice)
        assert currency == "EUR"
        assert value == 500000.0

    def test_extract_url(self, ted):
        notice = _make_ted_notice()
        url = ted._extract_url(notice, language="de")
        assert "ted.europa.eu" in url

    def test_iso3_to_iso2_coverage(self, ted):
        from app.sources.ted import _ISO3_TO_ISO2
        assert _ISO3_TO_ISO2["DEU"] == "DE"
        assert _ISO3_TO_ISO2["CHE"] == "CH"
        assert _ISO3_TO_ISO2["FRA"] == "FR"
        assert _ISO3_TO_ISO2["GBR"] == "GB"
        assert len(_ISO3_TO_ISO2) >= 30


class TestSIMAPSource:
    @pytest.fixture
    def simap(self):
        return SIMAPSource()

    @pytest.mark.asyncio
    async def test_fetch_parses_html(self, simap):
        html = """
        <html><body>
        <table class="data_table"><tbody>
        <tr onclick="/shabforms/123">
            <td><a href="/en/project-detail/abc-123">Bau Schulhaus Zuerich</a></td>
            <td>Stadt Zuerich</td>
            <td>ZH</td>
            <td>15.08.2025</td>
        </tr>
        </tbody></table>
        </body></html>
        """

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = html
        mock_response.headers = {"Content-Type": "text/html"}

        with patch.object(simap.client, "get", AsyncMock(return_value=mock_response)):
            tenders = await simap.fetch()

        assert len(tenders) >= 1
        t = tenders[0]
        assert t.source == "simap_ch"
        assert t.country == "CH"
        assert t.currency == "CHF"
        assert t.language == "de"

    def test_detect_language_german(self, simap):
        text = "Bauarbeiten fuer Schulhaus in Zuerich, Kanton Zuerich"
        assert simap._detect_language(text) == "de"

    def test_detect_language_french(self, simap):
        text = "Travaux de construction pour ecole à Lausanne, canton Vaud"
        assert simap._detect_language(text) == "fr"

    def test_detect_language_italian(self, simap):
        text = "Lavori di costruzione scuola a Lugano, Ticino"
        assert simap._detect_language(text) == "it"

    def test_parse_swiss_date(self, simap):
        dt1 = simap._parse_swiss_date("15.08.2025")
        assert dt1 is not None
        assert dt1.day == 15
        assert dt1.month == 8

        dt2 = simap._parse_swiss_date("2025-08-15T12:00:00+02:00")
        assert dt2 is not None

        dt3 = simap._parse_swiss_date("")
        assert dt3 is None

    def test_extract_id_from_href(self, simap):
        assert "simap-" in (simap._extract_id("/project-detail/abc-123") or "")
        assert simap._extract_id("/irrelevant") is None

    def test_canonicalize_region(self, simap):
        assert simap._canonicalize_region("Z\u00dcRICH") == "ZH"
        assert simap._canonicalize_region("ZH") == "ZH"
        assert simap._canonicalize_region("") == ""

    def test_extract_localized_text(self, simap):
        val = {"de": "Deutscher Text", "fr": "Texte français"}
        assert simap._extract_localized_text(val) == "Deutscher Text"

        val2 = {"fr": "Texte français"}
        assert simap._extract_localized_text(val2) == "Texte français"

        val3 = "Einfacher String"
        assert simap._extract_localized_text(val3) == "Einfacher String"

    @pytest.mark.asyncio
    async def test_close(self, simap):
        await simap.close()


class TestBundDeSource:
    @pytest.fixture
    def bund(self):
        return BundDeSource()

    @pytest.mark.asyncio
    async def test_fetch_parses_rss(self, bund):
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
        <item>
            <title>IT-Dienstleistungen Bundesministerium</title>
            <description>Beschreibung der Ausschreibung. Vergabestelle: BMI</description>
            <guid>https://www.service.bund.de/Ausschreibung-123</guid>
            <link>https://www.service.bund.de/Ausschreibung-123</link>
            <pubDate>Mon, 15 Jan 2025 08:00:00 GMT</pubDate>
        </item>
        <item>
            <title>Bauarbeiten Klinikum</title>
            <description>Bau von Neubau. Vergabestelle: Bundesbaublatt</description>
            <guid>https://www.service.bund.de/Ausschreibung-456</guid>
            <link>https://www.service.bund.de/Ausschreibung-456</link>
            <pubDate>Tue, 16 Jan 2025 10:30:00 GMT</pubDate>
        </item>
        </channel></rss>
        """

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = rss_xml

        with patch.object(bund.client, "get", AsyncMock(return_value=mock_response)):
            tenders = await bund.fetch()

        assert len(tenders) == 2
        t1 = tenders[0]
        assert t1.source == "bund_de"
        assert t1.country == "DE"
        assert t1.language == "de"

    @pytest.mark.asyncio
    async def test_fetch_empty_rss(self, bund):
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel></channel></rss>
        """

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = rss_xml

        with patch.object(bund.client, "get", AsyncMock(return_value=mock_response)):
            tenders = await bund.fetch()

        assert tenders == []

    @pytest.mark.asyncio
    async def test_fetch_http_error(self, bund):
        import httpx

        with patch.object(
            bund.client,
            "get",
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "404",
                    request=MagicMock(),
                    response=MagicMock(status_code=404),
                )
            ),
        ):
            tenders = await bund.fetch()
            assert tenders == []

    def test_parse_rfc822_date(self, bund):
        dt = bund._parse_rfc822("Mon, 15 Jan 2025 08:00:00 GMT")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15

        dt2 = bund._parse_rfc822("")
        assert dt2 is None

    def test_buyer_extraction(self, bund):
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item>
            <title>Test</title>
            <description>Blah. Vergabestelle: Bundesagentur fuer Arbeit</description>
            <guid>G1</guid>
            <link>https://example.com/1</link>
        </item>
        </channel></rss>
        """
        tenders = bund._parse_rss(rss_xml)
        assert len(tenders) == 1
        assert "Bundesagentur" in tenders[0].buyer

    @pytest.mark.asyncio
    async def test_close(self, bund):
        await bund.close()

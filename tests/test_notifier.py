"""Tests fuer den Notifier (E-Mail + Slack).

Testet Laender-Gruppierung, HTML-Bau, Slack-Block-Bau und
Formatierungshilfsmethoden – alles mit Mocks, keine echten E-Mails.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.services.notifier import (
    Notifier,
    _country_emoji,
    _country_name_de,
    COUNTRY_EMOJI,
)
from app.models.models import Tender, Match


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.exec = MagicMock()
    session.commit = MagicMock()
    return session


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.smtp_host = "smtp.gmail.com"
    settings.smtp_port = 587
    settings.smtp_user = "test@example.com"
    settings.smtp_pass = "testpass"
    settings.mail_to = "empfaenger@example.com"
    settings.slack_webhook_url = "https://hooks.slack.com/services/TEST"
    return settings


@pytest.fixture
def sample_tenders() -> List[Tender]:
    return [
        Tender(
            id=1, source="ted", external_id="T1", title="Bau Schulhaus Muenchen",
            buyer="Stadt Muenchen", country="DE", language="de",
            cpv_codes='["45110000"]',
            deadline=datetime(2025, 8, 15, 12, 0, tzinfo=timezone.utc),
            estimated_value=500000.0, currency="EUR", url="https://ted.europa.eu/1",
        ),
        Tender(
            id=2, source="simap_ch", external_id="S1", title="IT-Modernisierung Kanton Zuerich",
            buyer="Kanton Zuerich", country="CH", language="de",
            cpv_codes='["72000000"]',
            deadline=datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc),
            estimated_value=1200000.0, currency="CHF", url="https://simap.ch/1",
        ),
        Tender(
            id=3, source="ted", external_id="T2", title="Travaux route Paris",
            buyer="Ville de Paris", country="FR", language="fr",
            cpv_codes='["45230000"]',
            deadline=datetime(2025, 7, 20, 12, 0, tzinfo=timezone.utc),
            estimated_value=300000.0, currency="EUR", url="https://ted.europa.eu/2",
        ),
        Tender(
            id=4, source="bund_de", external_id="B1", title="Beratung Digitalisierung",
            buyer="BMI", country="DE", language="de",
            cpv_codes='["72000000"]',
            deadline=datetime(2025, 10, 1, 12, 0, tzinfo=timezone.utc),
            estimated_value=150000.0, currency="EUR", url="https://bund.de/1",
        ),
    ]


@pytest.fixture
def sample_matches(sample_tenders) -> List[Tuple[Match, Tender]]:
    matches = [
        Match(id=1, tender_id=1, profile_id=1, score=92, reasoning="Hervorragender Match", status="new"),
        Match(id=2, tender_id=2, profile_id=1, score=88, reasoning="Sehr guter Match", status="new"),
        Match(id=3, tender_id=3, profile_id=1, score=75, reasoning="Guter Match", status="new"),
        Match(id=4, tender_id=4, profile_id=1, score=70, reasoning="OK Match", status="new"),
    ]
    return list(zip(matches, sample_tenders))


class TestHelperFunctions:
    def test_country_emoji_known(self):
        assert _country_emoji("DE") == "🇩🇪"
        assert _country_emoji("CH") == "🇨🇭"
        assert _country_emoji("FR") == "🇫🇷"

    def test_country_emoji_unknown(self):
        assert _country_emoji("XX") == "🌍"
        assert _country_emoji("") == "🌍"

    def test_country_name_de(self):
        assert _country_name_de("DE") == "Deutschland"
        assert _country_name_de("CH") == "Schweiz"
        assert _country_name_de("FR") == "Frankreich"
        assert _country_name_de("AT") == "Österreich"

    def test_country_name_de_unknown(self):
        assert _country_name_de("XX") == "XX"

    def test_country_emoji_coverage(self):
        for code in ["DE", "CH", "FR", "AT", "IT", "ES", "NL", "BE", "PL", "SE"]:
            assert code in COUNTRY_EMOJI


class TestGrouping:
    def test_group_by_country(self, sample_matches):
        grouped = Notifier._group_by_country(sample_matches)
        assert "DE" in grouped
        assert "CH" in grouped
        assert "FR" in grouped
        assert len(grouped["DE"]) == 2
        assert len(grouped["CH"]) == 1
        assert len(grouped["FR"]) == 1

    def test_group_sorted_by_score(self, sample_matches):
        grouped = Notifier._group_by_country(sample_matches)
        de_matches = grouped["DE"]
        scores = [m.score for m, _ in de_matches]
        assert scores == sorted(scores, reverse=True)

    def test_group_empty(self):
        grouped = Notifier._group_by_country([])
        assert grouped == {}

    def test_group_single_country(self):
        tender = Tender(id=1, source="ted", external_id="T1", title="X", country="DE")
        match = Match(id=1, tender_id=1, profile_id=1, score=80, status="new")
        grouped = Notifier._group_by_country([(match, tender)])
        assert len(grouped) == 1
        assert "DE" in grouped


class TestFormatting:
    def test_format_value_with_currency(self):
        assert "CHF" in Notifier._format_value(1200000.0, "CHF")
        assert "EUR" in Notifier._format_value(500000.0, "EUR")

    def test_format_value_none(self):
        assert Notifier._format_value(None, "EUR") == "–"
        assert Notifier._format_value(0, "EUR") == "–"
        assert Notifier._format_value(-1, "EUR") == "–"

    def test_format_deadline(self):
        dt = datetime(2025, 8, 15, 12, 0, tzinfo=timezone.utc)
        assert Notifier._format_deadline(dt) == "15.08.2025"

    def test_format_deadline_none(self):
        assert Notifier._format_deadline(None) == "–"

    def test_escape_html(self):
        assert "&lt;script&gt;" in Notifier._escape("<script>alert('xss')</script>")
        assert "&amp;" in Notifier._escape("A & B")

    def test_score_class(self):
        assert Notifier._score_class(85) == "score-high"
        assert Notifier._score_class(60) == "score-mid"
        assert Notifier._score_class(30) == "score-low"


class TestEmailHTML:
    def test_build_email_html_structure(self, mock_session, mock_settings, sample_matches):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        grouped = Notifier._group_by_country(sample_matches)
        html = notifier._build_email_html(grouped, "Musterbau GmbH")

        assert "<!DOCTYPE html>" in html
        assert "Ausschreibungs-Wecker Europa" in html
        assert "Musterbau GmbH" in html
        assert "4</strong> neue passende" in html
        assert "🇩🇪 Deutschland" in html
        assert "🇨🇭 Schweiz" in html
        assert "🇫🇷 Frankreich" in html

    def test_email_contains_match_cards(self, mock_session, mock_settings, sample_matches):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        grouped = Notifier._group_by_country(sample_matches)
        html = notifier._build_email_html(grouped, "Test")

        assert "match-card" in html
        assert "Bau Schulhaus Muenchen" in html
        assert "score-high" in html or "score-mid" in html

    def test_email_no_xss(self, mock_session, mock_settings):
        tender = Tender(
            id=99, source="ted", external_id="X1",
            title="<script>alert(1)</script>",
            buyer="<b>Evil</b>", country="DE", url="https://example.com",
        )
        match = Match(id=99, tender_id=99, profile_id=1, score=80, reasoning="<i>test</i>", status="new")
        grouped = Notifier._group_by_country([(match, tender)])

        notifier = Notifier(session=mock_session, settings=mock_settings)
        html = notifier._build_email_html(grouped, "Test")

        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestSlackBlocks:
    def test_build_slack_blocks(self, mock_session, mock_settings, sample_matches):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        grouped = Notifier._group_by_country(sample_matches)
        blocks = notifier._build_slack_blocks(grouped, "Musterbau GmbH")

        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        assert "divider" in [b["type"] for b in blocks]

    def test_slack_blocks_limit_50(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)

        many_matches = []
        for i in range(30):
            t = Tender(id=i, source="ted", external_id=f"T{i}", title=f"Tender {i}", country="DE")
            m = Match(id=i, tender_id=i, profile_id=1, score=80, reasoning="OK", status="new")
            many_matches.append((m, t))

        grouped = Notifier._group_by_country(many_matches)
        blocks = notifier._build_slack_blocks(grouped, "Test")
        assert len(blocks) <= 50

    def test_match_slack_blocks(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        tender = Tender(
            id=1, source="ted", external_id="T1", title="IT-Dienstleistungen",
            buyer="BMI", country="DE", estimated_value=500000.0, currency="EUR",
            deadline=datetime(2025, 8, 15, tzinfo=timezone.utc), url="https://example.com/t1",
        )
        match = Match(id=1, tender_id=1, profile_id=1, score=85, reasoning="Guter Match", status="new")
        blocks = notifier._match_slack_blocks(match, tender)

        assert len(blocks) == 2
        assert blocks[0]["type"] == "section"
        assert blocks[1]["type"] == "context"


class TestEmailSending:
    def test_send_email_success(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

            result = notifier.send_email("Test Subject", "<html><body>Test</body></html>")
            assert result is True
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once()

    def test_send_email_no_smtp_user(self, mock_session, mock_settings):
        mock_settings.smtp_user = ""
        notifier = Notifier(session=mock_session, settings=mock_settings)
        result = notifier.send_email("Subject", "Body")
        assert result is False

    def test_send_email_failure(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = Exception("Connection refused")
            result = notifier.send_email("Subject", "Body")
            assert result is False


class TestSlackSending:
    def test_send_slack_success(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b"ok"
            mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Test"}}]
            result = notifier.send_slack(blocks)
            assert result is True

    def test_send_slack_no_webhook(self, mock_session, mock_settings):
        mock_settings.slack_webhook_url = ""
        notifier = Notifier(session=mock_session, settings=mock_settings)
        result = notifier.send_slack([])
        assert result is False

    def test_send_slack_http_error(self, mock_session, mock_settings):
        notifier = Notifier(session=mock_session, settings=mock_settings)
        with patch("urllib.request.urlopen") as mock_urlopen:
            from urllib.error import HTTPError
            mock_urlopen.side_effect = HTTPError(
                url="https://hooks.slack.com/test", code=400, msg="Bad Request",
                hdrs={}, fp=MagicMock(),
            )
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Test"}}]
            result = notifier.send_slack(blocks)
            assert result is False


class TestNotifyMain:
    def test_notify_no_pending_matches(self, mock_session, mock_settings):
        mock_session.exec.return_value.all.return_value = []
        notifier = Notifier(session=mock_session, settings=mock_settings)
        result = notifier.notify("Test-Firma")
        assert result == {"email": False, "slack": False}

    def test_notify_with_matches(self, mock_session, mock_settings, sample_matches):
        mock_rows = []
        for match, tender in sample_matches:
            row = MagicMock()
            row.Match = match
            row.Tender = tender
            mock_rows.append(row)
        mock_session.exec.return_value.all.return_value = mock_rows

        notifier = Notifier(session=mock_session, settings=mock_settings)

        with patch.object(notifier, "send_email", return_value=True) as mock_email, \
             patch.object(notifier, "send_slack", return_value=True) as mock_slack:
            result = notifier.notify("Musterbau GmbH")

        assert result["email"] is True
        assert result["slack"] is True

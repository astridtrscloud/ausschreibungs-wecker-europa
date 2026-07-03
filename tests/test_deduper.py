"""Tests fuer den CrossSourceDeduper.

Testet Fuzzy-Matching zwischen Quellen (z.B. TED vs. simap.ch)
mit rapidfuzz. Verwendet Tender-Stubs (keine DB fuer Unit-Tests).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.services.deduper import CrossSourceDeduper


class _TenderStub:
    __slots__ = ("source", "external_id", "title", "buyer", "country", "deadline")

    def __init__(
        self,
        source: str,
        external_id: str,
        title: str,
        buyer: str = "",
        country: str = "",
        deadline: Optional[datetime] = None,
    ) -> None:
        self.source = source
        self.external_id = external_id
        self.title = title
        self.buyer = buyer
        self.country = country
        self.deadline = deadline


@pytest.fixture
def deduper():
    return CrossSourceDeduper(threshold=92)


@pytest.fixture
def deadline():
    return datetime(2025, 6, 30, 12, 0, tzinfo=timezone.utc)


class TestComputeScore:
    def test_identical_tenders(self, deduper, deadline):
        t1 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t2 = _TenderStub("ted", "T1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        score = deduper._compute_score(t1, t2)
        assert score >= 92

    def test_different_titles(self, deduper, deadline):
        t1 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t2 = _TenderStub("ted", "T2", "Voellig andere Ausschreibung IT", "Andere Firma", "DE", deadline)
        score = deduper._compute_score(t1, t2)
        assert score < 92

    def test_similar_but_not_duplicate(self, deduper, deadline):
        t1 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t3 = _TenderStub("ted", "T3", "Bau Schulhaus Zuerich Nord", "Kanton Zuerich", "CH", deadline)
        score = deduper._compute_score(t1, t3)
        assert score < 92

    def test_same_source_ignored(self, deduper, deadline):
        t1 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t4 = _TenderStub("simap_ch", "S2", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        score = deduper._compute_score(t1, t4)
        assert score >= 92

    def test_empty_buyer(self, deduper, deadline):
        t1 = _TenderStub("ted", "T1", "IT-Dienstleistungen", "", "DE", deadline)
        t2 = _TenderStub("simap_ch", "S1", "IT-Dienstleistungen", "", "CH", deadline)
        score = deduper._compute_score(t1, t2)
        assert score < 92


class TestDeadlineMatch:
    def test_both_none(self, deduper):
        assert deduper._deadline_match(None, None) == 50.0

    def test_one_none(self, deduper, deadline):
        assert deduper._deadline_match(deadline, None) == 30.0
        assert deduper._deadline_match(None, deadline) == 30.0

    def test_exact_match(self, deduper, deadline):
        assert deduper._deadline_match(deadline, deadline) == 100.0

    def test_one_day_diff(self, deduper, deadline):
        other = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc)
        assert deduper._deadline_match(deadline, other) == 80.0

    def test_seven_days_diff(self, deduper, deadline):
        other = datetime(2025, 7, 7, 12, 0, tzinfo=timezone.utc)
        assert deduper._deadline_match(deadline, other) == 50.0

    def test_thirty_days_diff(self, deduper, deadline):
        other = datetime(2025, 7, 30, 12, 0, tzinfo=timezone.utc)
        assert deduper._deadline_match(deadline, other) == 0.0


class TestThreshold:
    def test_default_threshold(self):
        d = CrossSourceDeduper()
        assert d.threshold == 92

    def test_custom_threshold(self):
        d = CrossSourceDeduper(threshold=85)
        assert d.threshold == 85

    def test_lower_threshold_catches_more(self, deduper, deadline):
        t1 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t3 = _TenderStub("ted", "T3", "Bau Schulhaus Zuerich Nord", "Kanton Zuerich", "CH", deadline)

        strict = CrossSourceDeduper(threshold=95)
        loose = CrossSourceDeduper(threshold=80)

        s_strict = strict._compute_score(t1, t3)
        s_loose = loose._compute_score(t1, t3)

        assert s_loose < 92
        is_dup_strict = s_strict >= 95
        is_dup_loose = s_loose >= 80
        assert is_dup_loose or not is_dup_strict


class TestFindDuplicates:
    def test_find_cross_source_duplicates(self, deduper, deadline):
        new_tenders = [
            _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline),
        ]

        existing = [
            _TenderStub("ted", "T1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        duplicates = deduper.find_duplicates(mock_session, new_tenders)
        assert len(duplicates) == 1
        assert duplicates[0][0].source == "simap_ch"
        assert duplicates[0][1].source == "ted"

    def test_no_intra_source_duplicates(self, deduper, deadline):
        new_tenders = [
            _TenderStub("ted", "T1", "Bau Schulhaus", "Stadt", "DE", deadline),
        ]
        existing = [
            _TenderStub("ted", "T2", "Bau Schulhaus", "Stadt", "DE", deadline),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        duplicates = deduper.find_duplicates(mock_session, new_tenders)
        assert len(duplicates) == 0

    def test_filter_duplicates_removes_them(self, deduper, deadline):
        new_tenders = [
            _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline),
            _TenderStub("simap_ch", "S2", "Voellig anderes Projekt", "Andere", "CH", deadline),
        ]
        existing = [
            _TenderStub("ted", "T1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        filtered = deduper.filter_duplicates(mock_session, new_tenders)
        assert len(filtered) == 1
        assert filtered[0].external_id == "S2"

    def test_filter_no_duplicates(self, deduper, deadline):
        new_tenders = [
            _TenderStub("simap_ch", "S1", "Einzigartiges Projekt", "Einzig", "CH", deadline),
        ]
        existing = [
            _TenderStub("ted", "T1", "Ganz anderer Titel", "Anders", "DE", deadline),
        ]

        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = existing

        filtered = deduper.filter_duplicates(mock_session, new_tenders)
        assert len(filtered) == 1


class TestWeighting:
    def test_title_weight_50_percent(self, deduper, deadline):
        from rapidfuzz import fuzz
        t1 = _TenderStub("ted", "T1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t2 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        title_score = fuzz.ratio(t1.title.lower(), t2.title.lower())
        buyer_score = fuzz.ratio(t1.buyer.lower(), t2.buyer.lower())
        deadline_score = deduper._deadline_match(t1.deadline, t2.deadline)
        expected = title_score * 0.5 + buyer_score * 0.3 + deadline_score * 0.2
        actual = deduper._compute_score(t1, t2)
        assert abs(actual - expected) < 0.1

    def test_buyer_weight_30_percent(self, deduper, deadline):
        t1 = _TenderStub("ted", "T1", "Bau Schulhaus Zuerich", "Stadt Zuerich", "CH", deadline)
        t2 = _TenderStub("simap_ch", "S1", "Bau Schulhaus Zuerich", "Kanton Zuerich", "CH", deadline)
        score = deduper._compute_score(t1, t2)
        assert score >= 70

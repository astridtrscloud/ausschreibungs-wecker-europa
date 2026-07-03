"""Cross-Source-Deduplizierung mit Fuzzy-Matching.

Schweizer Ausschreibungen über dem Schwellenwert erscheinen auf
simap.ch UND TED. Dieses Modul erkennt solche Duplikate via
rapidfuzz Fuzzy-Matching (Titel + Buyer + Deadline).
"""
import logging
from datetime import datetime
from typing import Optional

from rapidfuzz import fuzz
from sqlmodel import Session, select

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.models.models import Tender

logger = logging.getLogger("app.services.deduper")
FUZZY_THRESHOLD = 92


class CrossSourceDeduper:
    """Erkennt Cross-Source-Duplikate via Fuzzy-Matching."""

    def __init__(self, threshold: int = FUZZY_THRESHOLD) -> None:
        self.threshold = threshold

    def find_duplicates(self, session: Session, new_tenders: list[Tender]) -> list[tuple[Tender, Tender]]:
        duplicates: list[tuple[Tender, Tender]] = []
        existing = session.exec(select(Tender)).all()

        for new in new_tenders:
            for exist in existing:
                if new.source == exist.source:
                    continue
                if self._is_duplicate(new, exist):
                    duplicates.append((new, exist))
                    logger.info(
                        f"Cross-Source-Duplikat: {new.source}:{new.external_id} ≈ {exist.source}:{exist.external_id}",
                        extra={"source": "deduper"}
                    )
        return duplicates

    def _is_duplicate(self, a: Tender, b: Tender) -> bool:
        return self._compute_score(a, b) >= self.threshold

    def _compute_score(self, a: Tender, b: Tender) -> float:
        title_score = fuzz.ratio(a.title.lower(), b.title.lower())
        buyer_a = (a.buyer or "").lower()
        buyer_b = (b.buyer or "").lower()
        buyer_score = fuzz.ratio(buyer_a, buyer_b) if buyer_a and buyer_b else 0
        deadline_score = self._deadline_match(a.deadline, b.deadline)
        return (title_score * 0.5) + (buyer_score * 0.3) + (deadline_score * 0.2)

    @staticmethod
    def _deadline_match(da: Optional[datetime], db: Optional[datetime]) -> float:
        if da is None and db is None:
            return 50.0
        if da is None or db is None:
            return 30.0
        diff_days = abs((da - db).total_seconds() / 86400)
        if diff_days == 0:
            return 100.0
        if diff_days <= 1:
            return 80.0
        if diff_days <= 7:
            return 50.0
        return 0.0

    def filter_duplicates(self, session: Session, new_tenders: list[Tender]) -> list[Tender]:
        duplicates = self.find_duplicates(session, new_tenders)
        duplicate_ids = {id(d[0]) for d in duplicates}
        filtered = [t for t in new_tenders if id(t) not in duplicate_ids]
        removed = len(new_tenders) - len(filtered)
        if removed > 0:
            logger.info(f"Cross-Source-Dedupe: {removed} Duplikate entfernt", extra={"source": "deduper"})
        return filtered


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    deduper = CrossSourceDeduper()
    t1 = Tender(source="simap_ch", external_id="S1", title="Bau Schulhaus Zürich", buyer="Stadt Zürich", country="CH")
    t2 = Tender(source="ted", external_id="T1", title="Bau Schulhaus Zürich", buyer="Stadt Zürich", country="CH")
    t3 = Tender(source="ted", external_id="T2", title="Völlig andere Ausschreibung", buyer="Andere Firma", country="DE")

    print(f"\n{'='*60}")
    print("DEDUPER-TEST")
    print(f"Gleicher Titel: Score = {deduper._compute_score(t1, t2):.1f} → Duplikat: {deduper._is_duplicate(t1, t2)}")
    print(f"Anderer Titel:  Score = {deduper._compute_score(t1, t3):.1f} → Duplikat: {deduper._is_duplicate(t1, t3)}")

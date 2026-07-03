"""APScheduler-Setup + Scraping-Loop mit Deduplizierung.

Nutzt die Plug-in-Registry (sources/_registry.py) für neue Quellen.
"""
import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import select

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.core.config import settings
from app.core.database import init_db, get_session
from app.models.models import Tender
from app.sources._registry import SOURCES
from app.services.deduper import CrossSourceDeduper

logger = logging.getLogger("app.scheduler")


async def run_scraper() -> dict:
    """Führt alle Quellen aus, dedupliziert und speichert."""
    stats = {}
    deduper = CrossSourceDeduper()

    for source in SOURCES:
        source_name = source.name
        source_stats = {"fetched": 0, "saved": 0, "duplicates_removed": 0, "errors": 0}

        try:
            logger.info(f"Quelle '{source_name}' wird abgerufen...", extra={"source": source_name})
            tenders_raw = await source.fetch()
            source_stats["fetched"] = len(tenders_raw)

            saved, dupes = await _save_tenders(tenders_raw, source_name, deduper)
            source_stats["saved"] = saved
            source_stats["duplicates_removed"] = dupes

            logger.info(f"Quelle '{source_name}': {len(tenders_raw)} geholt, {saved} gespeichert, {dupes} Duplikate entfernt",
                       extra={"source": source_name})
        except Exception as e:
            logger.error(f"Quelle '{source_name}' fehlgeschlagen: {e}", extra={"source": source_name})
            source_stats["errors"] += 1
        finally:
            if hasattr(source, 'close'):
                try:
                    await source.close()
                except Exception:
                    pass

        stats[source_name] = source_stats

    return stats


async def _save_tenders(tenders_raw, source_name, deduper):
    """Speichert TenderRaw mit Intra- und Cross-Source-Deduplizierung."""
    import json as json_mod

    saved_count = 0
    dupe_count = 0
    new_tenders = []

    with get_session() as session:
        for raw in tenders_raw:
            try:
                existing = session.exec(
                    select(Tender).where(Tender.source == source_name, Tender.external_id == raw.external_id)
                ).first()
                if existing:
                    continue

                tender = Tender(
                    source=source_name,
                    external_id=raw.external_id,
                    title=raw.title,
                    description=raw.description,
                    buyer=raw.buyer,
                    country=raw.country,
                    language=raw.language,
                    cpv_codes=json_mod.dumps(raw.cpv_codes),
                    region=raw.region,
                    deadline=raw.deadline,
                    published_at=raw.published_at,
                    url=raw.url,
                    currency=raw.currency,
                    estimated_value=raw.estimated_value,
                    raw_json=json_mod.dumps(raw.raw_json, ensure_ascii=False),
                )
                new_tenders.append(tender)
            except Exception as e:
                logger.warning(f"Fehler beim Konvertieren {raw.external_id}: {e}", extra={"source": source_name})
                continue

        if new_tenders:
            filtered = deduper.filter_duplicates(session, new_tenders)
            dupe_count = len(new_tenders) - len(filtered)
            for tender in filtered:
                session.add(tender)
                saved_count += 1

    return saved_count, dupe_count


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    interval = max(settings.scrape_interval_minutes, 5)
    scheduler.add_job(
        run_scraper,
        trigger=IntervalTrigger(minutes=interval),
        id="scraper",
        name="Ausschreibungs-Scraper Europa",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info(f"Scheduler: alle {interval} Min, {len(SOURCES)} Quellen", extra={"source": "scheduler"})
    return scheduler


async def run_once() -> dict:
    init_db()
    return await run_scraper()

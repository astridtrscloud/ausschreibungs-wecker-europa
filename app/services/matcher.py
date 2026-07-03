"""LLM-basiertes mehrsprachiges Matching von Ausschreibungen zum Firmenprofil.

Zweistufig:
1. Vorfilter (kein LLM): CPV (primär) + Keyword + Land + Sprache
2. LLM-Scoring: OpenAI-kompatible API, mehrsprachig

Kosten-Schutz: max. 200 LLM-Calls pro Lauf.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from openai import AsyncOpenAI
from sqlmodel import select

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.core.config import settings
from app.core.database import get_session
from app.models.models import Tender, CompanyProfile, Match

logger = logging.getLogger("app.services.matcher")

LLM_MAX_CALLS = 200
LLM_TIMEOUT = 60.0
LLM_SYSTEM_PROMPT = (
    "Du bist Vergabe-Analyst fuer europaeische oeffentliche Beschaffung. "
    "Die Ausschreibung kann in einer beliebigen europaeischen Sprache sein – "
    "verstehe sie unabhaengig von der Sprache. Bewerte, wie gut sie zum Firmenprofil passt. "
    "Pruefe auch, ob die Ausschreibungssprache zu den Angebotssprachen der Firma passt. "
    "Antworte NUR mit validem JSON: "
    '{"score": 0-100, "reasoning": "max 2 Saetze auf Deutsch, nenne das Land", '
    '"deadline_ok": true/false, "language_ok": true/false}. '
    "Score >=70 nur wenn die Firma die Kernleistung realistisch erbringen kann UND die Sprache passt."
)


@dataclass
class MatchResult:
    score: int
    reasoning: str
    deadline_ok: bool
    language_ok: bool


class Matcher:
    """Zweistufiges mehrsprachiges Matching."""

    def __init__(self, llm_client: Optional[AsyncOpenAI] = None, max_calls: int = LLM_MAX_CALLS) -> None:
        self.llm = llm_client or AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=httpx.Timeout(LLM_TIMEOUT, connect=10.0),
        )
        self.max_calls = max_calls
        self._calls_made = 0

    def prefilter(self, tender: Tender, profile: CompanyProfile) -> bool:
        """Schneller Vorfilter. CPV ist primär (sprachunabhängig)."""
        profile_countries = [c.upper() for c in profile.get_countries()]
        if profile_countries and tender.country.upper() not in profile_countries:
            return False

        tender_cpvs = set(tender.get_cpv_codes())
        profile_cpvs = set(profile.get_cpv_whitelist())
        if profile_cpvs and tender_cpvs:
            if tender_cpvs & profile_cpvs:
                return True

        tender_text = f"{tender.title} {tender.description}".lower()
        profile_keywords = [k.lower() for k in profile.get_keywords()]
        for keyword in profile_keywords:
            if keyword in tender_text:
                return True

        profile_regions = [r.lower() for r in profile.get_regions()]
        tender_region = tender.region.lower()
        if profile_regions and tender_region:
            for region in profile_regions:
                if region in tender_region:
                    return True

        if not profile_cpvs and not profile_keywords:
            return True
        return False

    async def llm_score(self, tender: Tender, profile: CompanyProfile) -> Optional[MatchResult]:
        if self._calls_made >= self.max_calls:
            logger.warning(f"LLM-Limit erreicht ({self.max_calls})", extra={"source": "matcher"})
            return None

        user_content = self._build_prompt(tender, profile)

        for attempt in range(2):
            try:
                self._calls_made += 1
                response = await self.llm.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": LLM_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.3,
                    max_tokens=250,
                )
                raw = response.choices[0].message.content or "{}"
                return self._parse_response(raw)
            except Exception as e:
                logger.warning(f"LLM Fehler (Attempt {attempt+1}/2): {e}", extra={"source": "matcher"})
                if attempt == 0:
                    await asyncio.sleep(2)
                continue
        return None

    def _build_prompt(self, tender: Tender, profile: CompanyProfile) -> str:
        deadline_str = tender.deadline.strftime("%d.%m.%Y") if tender.deadline else "nicht angegeben"
        cpvs = ", ".join(tender.get_cpv_codes()) if tender.get_cpv_codes() else "keine"
        value_str = f"{tender.estimated_value:,.0f} {tender.currency}" if tender.estimated_value and tender.currency else "nicht angegeben"
        return (
            f"## Firmenprofil\n"
            f"Name: {profile.name}\n"
            f"Beschreibung: {profile.description}\n"
            f"Keywords: {', '.join(profile.get_keywords())}\n"
            f"CPV-Codes: {', '.join(profile.get_cpv_whitelist())}\n"
            f"Laender: {', '.join(profile.get_countries()) or 'alle'}\n"
            f"Angebotssprachen: {', '.join(profile.get_languages_ok())}\n"
            f"Min. Deadline-Tage: {profile.min_deadline_days}\n"
            f"\n"
            f"## Ausschreibung\n"
            f"Titel: {tender.title}\n"
            f"Beschreibung: {tender.description[:500]}\n"
            f"Land: {tender.country}\n"
            f"Sprache: {tender.language}\n"
            f"CPV-Codes: {cpvs}\n"
            f"Deadline: {deadline_str}\n"
            f"Geschätzter Wert: {value_str}\n"
            f"Vergabestelle: {tender.buyer}\n"
            f"Region: {tender.region}\n"
        )

    def _parse_response(self, raw: str) -> Optional[MatchResult]:
        try:
            result = json.loads(raw.strip())
            return MatchResult(
                score=int(result.get("score", 0)),
                reasoning=str(result.get("reasoning", "")),
                deadline_ok=bool(result.get("deadline_ok", False)),
                language_ok=bool(result.get("language_ok", False)),
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        import re
        m = re.search(r'\{[^}]*"score"[^}]*\}', raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
                return MatchResult(
                    score=int(result.get("score", 0)),
                    reasoning=str(result.get("reasoning", "")),
                    deadline_ok=bool(result.get("deadline_ok", False)),
                    language_ok=bool(result.get("language_ok", False)),
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        logger.warning(f"LLM Parse-Fehler: {raw[:200]}", extra={"source": "matcher"})
        return None

    async def match_all(self, tenders: list[Tender], profile: CompanyProfile) -> list[Match]:
        logger.info(f"Matching: {len(tenders)} Tenders vs '{profile.name}'", extra={"source": "matcher"})
        candidates = [t for t in tenders if self.prefilter(t, profile)]
        logger.info(f"Vorfilter: {len(candidates)}/{len(tenders)} Kandidaten", extra={"source": "matcher"})
        if not candidates:
            return []

        semaphore = asyncio.Semaphore(5)
        tasks = [self._score_with_semaphore(t, profile, semaphore) for t in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        matches_saved = []
        with get_session() as session:
            for tender, result in zip(candidates, results):
                if isinstance(result, Exception) or result is None:
                    continue
                if result.score < 70 or not result.deadline_ok or not result.language_ok:
                    continue
                existing = session.exec(
                    select(Match).where(Match.tender_id == tender.id, Match.profile_id == profile.id)
                ).first()
                if existing:
                    continue
                match = Match(
                    tender_id=tender.id,
                    profile_id=profile.id,
                    score=result.score,
                    reasoning=result.reasoning,
                    status="new",
                )
                session.add(match)
                matches_saved.append(match)
                logger.info(f"Neuer Match: {tender.title[:50]}... Score={result.score}", extra={"source": "matcher"})

        logger.info(f"Matching abgeschlossen: {len(matches_saved)} neue Matches", extra={"source": "matcher"})
        return matches_saved

    async def _score_with_semaphore(self, tender, profile, semaphore):
        async with semaphore:
            return await self.llm_score(tender, profile)

    def get_calls_made(self) -> int:
        return self._calls_made

"""TED (Tenders Electronic Daily) EU-Quelle – Search API v3.

TED deckt ALLE EU/EWR-Länder ab (eine Quelle = ganz Europa).
Doku: https://docs.api.ted.europa.eu/
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.sources.base import TenderRaw
from app.core.config import settings

logger = logging.getLogger("app.sources.ted")

TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
REQUEST_TIMEOUT = 30.0
USER_AGENT = "Ausschreibungs-Wecker-Europa/1.0 (Open Source Tender Monitoring)"

# Mapping von Länderbezeichnungen zu ISO-2
_COUNTRY_MAP = {
    "AT": "AT", "Austria": "AT", "Osterreich": "AT", "Autriche": "AT",
    "BE": "BE", "Belgium": "BE", "Belgique": "BE", "Belgien": "BE",
    "BG": "BG", "Bulgaria": "BG", "Bulgarie": "BG",
    "CH": "CH", "Switzerland": "CH", "Suisse": "CH", "Schweiz": "CH", "Svizzera": "CH",
    "CY": "CY", "Cyprus": "CY",
    "CZ": "CZ", "Czech Republic": "CZ", "Czechia": "CZ",
    "DE": "DE", "Germany": "DE", "Allemagne": "DE", "Deutschland": "DE",
    "DK": "DK", "Denmark": "DK", "Danemark": "DK", "Danmark": "DK",
    "EE": "EE", "Estonia": "EE", "Estonie": "EE",
    "EL": "EL", "GR": "EL", "Greece": "EL", "Grece": "EL",
    "ES": "ES", "Spain": "ES", "Espagne": "ES", "Espana": "ES",
    "FI": "FI", "Finland": "FI", "Finlande": "FI",
    "FR": "FR", "France": "FR",
    "HR": "HR", "Croatia": "HR", "Croatie": "HR", "Kroatien": "HR",
    "HU": "HU", "Hungary": "HU", "Hongrie": "HU", "Ungarn": "HU",
    "IE": "IE", "Ireland": "IE", "Irlande": "IE",
    "IS": "IS", "Iceland": "IS", "Islande": "IS",
    "IT": "IT", "Italy": "IT", "Italie": "IT", "Italia": "IT",
    "LI": "LI", "Liechtenstein": "LI",
    "LT": "LT", "Lithuania": "LT", "Lituanie": "LT",
    "LU": "LU", "Luxembourg": "LU", "Luxemburg": "LU",
    "LV": "LV", "Latvia": "LV", "Lettonie": "LV",
    "MT": "MT", "Malta": "MT",
    "NL": "NL", "Netherlands": "NL", "Pays-Bas": "NL", "Niederlande": "NL",
    "NO": "NO", "Norway": "NO", "Norvege": "NO",
    "PL": "PL", "Poland": "PL", "Pologne": "PL", "Polen": "PL",
    "PT": "PT", "Portugal": "PT",
    "RO": "RO", "Romania": "RO", "Roumanie": "RO", "Rumänien": "RO",
    "SE": "SE", "Sweden": "SE", "Suede": "SE", "Schweden": "SE", "Sverige": "SE",
    "SI": "SI", "Slovenia": "SI", "Slovenie": "SI",
    "SK": "SK", "Slovakia": "SK", "Slovaquie": "SK",
}

# CPV-Code zu Sprachen (Häufige Mappings)
_CPV_LANGUAGE_HINTS = {
    "30": "de", "31": "nl", "32": "fr", "33": "es", "34": "it",
    "35": "pt", "36": "sv", "37": "da", "38": "fi", "39": "el",
}


class TEDSource:
    """TED EU-Ausschreibungen via offizieller Search API v3."""

    name: str = "ted"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json"},
            follow_redirects=True,
        )

    async def fetch(self, limit: int = 50) -> list[TenderRaw]:
        """Holt aktuelle Ausschreibungen von TED."""
        all_tenders: list[TenderRaw] = []
        page = 1
        max_pages = 5
        country_filter = settings.ted_country_list

        while page <= max_pages:
            logger.info(f"TED API Seite {page} wird abgerufen...", extra={"source": "ted"})

            body = {
                "query": "",
                "fields": [
                    "notice-id", "publication-number", "contact-name",
                    "BT-24-Lot", "BT-21-Procedure",
                    "cpv-names", "place-of-performance", "buyer-country",
                    "submission-deadline", "publication-date", "notice-url",
                    "BT-262-Lot", "BT-118-NoticeResult", "BT-271-Lot", "BT-27-Procedure"
                ],
                "limit": min(limit, 100),
                "page": page,
                "sort": {"field": "publication-date", "order": "DESC"}
            }

            try:
                tenders = await self._fetch_page(body)
                if not tenders:
                    break

                for t in tenders:
                    if country_filter and t.country and t.country.upper() not in country_filter:
                        continue
                    all_tenders.append(t)

                await asyncio.sleep(1.0)
                page += 1

            except Exception as e:
                logger.error(f"TED Seite {page} fehlgeschlagen: {e}", extra={"source": "ted"})
                break

        logger.info(f"TED: {len(all_tenders)} Ausschreibungen (alle Laender)", extra={"source": "ted"})
        return all_tenders

    async def _fetch_page(self, body: dict) -> list[TenderRaw]:
        for attempt in range(3):
            try:
                response = await self.client.post(TED_SEARCH_URL, json=body)
                response.raise_for_status()
                data = response.json()
                notices = data.get("notices", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                return [self._parse_notice(n) for n in notices if self._parse_notice(n)]
            except httpx.HTTPStatusError as e:
                logger.warning(f"TED HTTP {e.response.status_code} (Attempt {attempt+1}/3)", extra={"source": "ted"})
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except httpx.RequestError as e:
                logger.warning(f"TED Request Error: {e} (Attempt {attempt+1}/3)", extra={"source": "ted"})
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        return []

    def _parse_notice(self, notice: dict) -> TenderRaw | None:
        try:
            notice_id = str(notice.get("notice-id") or notice.get("publication-number", "unknown"))

            title = self._extract_multilingual_text(notice, "BT-24-Lot", "notice-title")
            description = self._extract_multilingual_text(notice, "BT-21-Procedure", "procedure-description")
            buyer = notice.get("contact-name", "") or ""

            country = self._extract_country(notice)
            language = self._detect_language(notice, country)

            cpv_field = notice.get("cpv-names", [])
            cpv_codes = self._parse_cpv(cpv_field)

            region = self._extract_region(notice)

            deadline = self._parse_datetime(notice.get("submission-deadline"))
            published_at = self._parse_datetime(notice.get("publication-date"))
            url = notice.get("notice-url", "") or ""

            currency, estimated_value = self._extract_value(notice)

            return TenderRaw(
                external_id=notice_id,
                title=title,
                description=description,
                buyer=buyer,
                country=country,
                language=language,
                cpv_codes=cpv_codes,
                region=region,
                deadline=deadline,
                published_at=published_at,
                url=url,
                currency=currency,
                estimated_value=estimated_value,
                raw_json=notice,
            )
        except Exception as e:
            logger.warning(f"TED Notice Parse-Fehler: {e}", extra={"source": "ted"})
            return None

    def _extract_multilingual_text(self, notice: dict, primary_field: str, fallback_field: str) -> str:
        value = notice.get(primary_field, "")
        if isinstance(value, dict):
            for lang in ["deu", "ger", "de", "eng", "en", "fra", "fr"]:
                if lang in value and value[lang]:
                    text = value[lang]
                    return text[0] if isinstance(text, list) else str(text)
            for v in value.values():
                if v:
                    return v[0] if isinstance(v, list) else str(v)
            return "(Kein Titel)"
        if isinstance(value, list) and value:
            return str(value[0])
        if value:
            return str(value)
        fallback = notice.get(fallback_field, "")
        return str(fallback) if fallback else "(Kein Titel)"

    def _extract_country(self, notice: dict) -> str:
        buyer_country = notice.get("buyer-country", "")
        if buyer_country:
            iso = _COUNTRY_MAP.get(buyer_country.upper())
            if iso:
                return iso
        place = notice.get("place-of-performance", "")
        if isinstance(place, str) and place:
            parts = [p.strip() for p in place.replace(";", ",").split(",")]
            for part in reversed(parts):
                iso = _COUNTRY_MAP.get(part.upper())
                if iso:
                    return iso
        return ""

    def _detect_language(self, notice: dict, country: str) -> str:
        bt24 = notice.get("BT-24-Lot", {})
        if isinstance(bt24, dict):
            lang_map = {"deu": "de", "ger": "de", "eng": "en", "fra": "fr", "ita": "it", "spa": "es", "por": "pt", "nld": "nl", "swe": "sv", "dan": "da", "fin": "fi", "ell": "el", "gre": "el", "pol": "pl", "hrv": "hr", "slv": "sl", "slk": "sk", "cze": "cs", "hun": "hu", "est": "et", "lav": "lv", "lit": "lt", "mlt": "mt", "gle": "ga", "rum": "ro", "bul": "bg"}
            for key, iso in lang_map.items():
                if key in bt24 and bt24[key]:
                    return iso
        country_lang = {"DE": "de", "AT": "de", "CH": "de", "FR": "fr", "IT": "it", "ES": "es", "PT": "pt", "NL": "nl", "BE": "nl", "SE": "sv", "DK": "da", "FI": "fi", "GR": "el", "PL": "pl", "HR": "hr", "SI": "sl", "SK": "sk", "CZ": "cs", "HU": "hu", "EE": "et", "LV": "lv", "LT": "lt", "MT": "mt", "IE": "en", "RO": "ro", "BG": "bg", "IS": "is", "NO": "no", "LI": "de", "LU": "de", "CY": "el"}
        return country_lang.get(country.upper(), "")

    @staticmethod
    def _parse_cpv(cpv_field: Any) -> list[str]:
        if isinstance(cpv_field, str):
            return [c.strip() for c in cpv_field.split(",") if c.strip()]
        elif isinstance(cpv_field, list):
            return [str(c).strip() for c in cpv_field if str(c).strip()]
        return []

    def _extract_region(self, notice: dict) -> str:
        place = notice.get("place-of-performance", "")
        if isinstance(place, str):
            return place
        if isinstance(place, list):
            return ", ".join(str(p) for p in place)
        return ""

    def _extract_value(self, notice: dict) -> tuple[Optional[str], Optional[float]]:
        for field in ["BT-118-NoticeResult", "BT-271-Lot", "BT-262-Lot", "BT-27-Procedure"]:
            value = notice.get(field)
            if value and isinstance(value, dict):
                amount = value.get("amount") or value.get("value")
                curr = value.get("currency") or value.get("cur")
                if amount is not None:
                    try:
                        return (curr or "EUR", float(amount))
                    except (ValueError, TypeError):
                        continue
            elif value and isinstance(value, (int, float)):
                return ("EUR", float(value))
        return (None, None)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(str(value), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    async def close(self) -> None:
        await self.client.aclose()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def test():
        source = TEDSource()
        try:
            tenders = await source.fetch(limit=10)
            print(f"\n{'='*60}")
            print(f"TED EUROPA TEST: {len(tenders)} Ausschreibungen")
            countries = {}
            for t in tenders:
                c = t.country or "UNBEKANNT"
                countries[c] = countries.get(c, 0) + 1
            print(f"Laender: {dict(sorted(countries.items()))}")
            print(f"{'='*60}")
            for i, t in enumerate(tenders[:3], 1):
                print(f"\n--- #{i} [{t.country}] ---")
                print(f"Titel: {t.title[:80]}")
                print(f"Land: {t.country} | Sprache: {t.language}")
                if t.estimated_value:
                    print(f"Wert: {t.estimated_value:,.0f} {t.currency}")
        finally:
            await source.close()

    asyncio.run(test())

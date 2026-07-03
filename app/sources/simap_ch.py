"""simap.ch – Schweizer Vergabeplattform (Bund, Kantone, Gemeinden).

URLs:
- Suche: https://www.simap.ch/shabforms/COMMON/search/searchResult.jsp
- Detail: https://www.simap.ch/shabforms/servlet/Search?searchid=...

Sprachen: DE/FR/IT
Währung: CHF
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.sources.base import TenderRaw

logger = logging.getLogger("app.sources.simap_ch")

SIMAP_BASE = "https://www.simap.ch"
SIMAP_SEARCH = "https://www.simap.ch/shabforms/COMMON/search/searchResult.jsp"
REQUEST_TIMEOUT = 30.0
USER_AGENT = "Ausschreibungs-Wecker-Europa/1.0 (Open Source Tender Monitoring)"


class SIMAPSource:
    """simap.ch – Schweizer Vergabeplattform."""

    name: str = "simap_ch"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-CH,de;q=0.9,fr;q=0.8,it;q=0.7,en;q=0.6",
            },
            follow_redirects=True,
        )

    async def fetch(self) -> list[TenderRaw]:
        """Holt Ausschreibungen von simap.ch. HTTP zuerst, Playwright als Fallback."""
        logger.info("simap.ch wird abgerufen...", extra={"source": "simap_ch"})

        # Versuch 1: Normales HTTP
        for attempt in range(3):
            try:
                response = await self.client.get(SIMAP_SEARCH)
                response.raise_for_status()
                tenders = self._parse_html(response.text)
                if tenders:
                    return tenders
                break
            except httpx.HTTPStatusError as e:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    break

        # Versuch 2: Playwright für JS-Rendering
        logger.info("simap.ch: HTTP lieferte 0 Ergebnisse, verwende Playwright...", extra={"source": "simap_ch"})
        try:
            return await self._fetch_with_playwright()
        except ImportError:
            logger.warning("simap.ch: Playwright nicht installiert, überspringe", extra={"source": "simap_ch"})
            return []
        except Exception as e:
            logger.error(f"simap.ch Playwright-Fehler: {e}", extra={"source": "simap_ch"})
            return []

    def _parse_html(self, html: str) -> list[TenderRaw]:
        tenders: list[TenderRaw] = []
        try:
            tree = HTMLParser(html)
            rows = tree.css("table.data_table tbody tr, .result-item, .search-result, tr[onclick]")

            if not rows:
                links = tree.css('a[href*="searchid"], a[href*="detail"], a[href*="notice"]')
                seen = set()
                for link in links:
                    href = link.attributes.get("href", "")
                    if not href or href in seen:
                        continue
                    seen.add(href)
                    full_url = urljoin(SIMAP_BASE, href)
                    title = link.text(strip=True)
                    if not title or len(title) < 5:
                        continue
                    tenders.append(TenderRaw(
                        external_id=self._extract_id(href) or f"simap-{hash(title) & 0xFFFFFFFF:08x}",
                        title=title,
                        country="CH",
                        language="de",
                        currency="CHF",
                        url=full_url,
                        raw_json={"method": "http", "href": href},
                    ))
            else:
                for row in rows:
                    try:
                        tender = self._parse_row(row)
                        if tender:
                            tenders.append(tender)
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"simap.ch Parse-Fehler: {e}", extra={"source": "simap_ch"})

        logger.info(f"simap.ch: {len(tenders)} Ausschreibungen", extra={"source": "simap_ch"})
        return tenders

    def _parse_row(self, row) -> TenderRaw | None:
        cells = row.css("td")
        if len(cells) < 2:
            return None
        link = cells[0].css_first("a")
        title = link.text(strip=True) if link else cells[0].text(strip=True)
        href = link.attributes.get("href", "") if link else ""
        if not title or len(title) < 3:
            return None
        buyer = cells[1].text(strip=True) if len(cells) > 1 else ""
        region = cells[2].text(strip=True) if len(cells) > 2 else ""
        deadline = self._parse_swiss_date(cells[3].text(strip=True)) if len(cells) > 3 else None
        return TenderRaw(
            external_id=self._extract_id(href) or f"simap-{hash(title) & 0xFFFFFFFF:08x}",
            title=title,
            buyer=buyer,
            country="CH",
            language=self._detect_language(title),
            currency="CHF",
            region=region,
            deadline=deadline,
            url=urljoin(SIMAP_BASE, href) if href else "",
            raw_json={"cells": [c.text(strip=True) for c in cells]},
        )

    async def _fetch_with_playwright(self) -> list[TenderRaw]:
        from playwright.async_api import async_playwright
        tenders: list[TenderRaw] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT, viewport={"width": 1280, "height": 800})
            try:
                await page.goto(SIMAP_SEARCH, wait_until="networkidle", timeout=30000)
                selectors = ["table tbody tr", ".result-item", ".search-result", "[class*='result']", "[class*='tender']"]
                found = None
                for sel in selectors:
                    try:
                        await page.wait_for_selector(sel, timeout=5000)
                        found = sel
                        break
                    except:
                        continue
                if found:
                    rows = await page.query_selector_all(found)
                    for row in rows:
                        try:
                            t = await self._parse_pw_row(row)
                            if t:
                                tenders.append(t)
                        except Exception:
                            continue
                else:
                    links = await page.query_selector_all("a")
                    seen = set()
                    for link in links:
                        href = await link.get_attribute("href") or ""
                        title = await link.inner_text()
                        if ("searchid" in href or "notice" in href) and title and len(title.strip()) > 5 and href not in seen:
                            seen.add(href)
                            tenders.append(TenderRaw(
                                external_id=self._extract_id(href) or f"simap-{hash(title) & 0xFFFFFFFF:08x}",
                                title=title.strip(),
                                country="CH",
                                language="de",
                                currency="CHF",
                                url=urljoin(SIMAP_BASE, href),
                                raw_json={"method": "playwright", "href": href},
                            ))
            finally:
                await browser.close()
        logger.info(f"simap.ch Playwright: {len(tenders)} Ausschreibungen", extra={"source": "simap_ch"})
        return tenders

    async def _parse_pw_row(self, row) -> TenderRaw | None:
        cells = await row.query_selector_all("td")
        if len(cells) < 2:
            return None
        texts = []
        for cell in cells:
            texts.append(await cell.inner_text())
        link_el = await cells[0].query_selector("a")
        title = texts[0]
        href = await link_el.get_attribute("href") if link_el else ""
        if not title or len(title) < 3:
            return None
        return TenderRaw(
            external_id=self._extract_id(href) or f"simap-{hash(title) & 0xFFFFFFFF:08x}",
            title=title,
            buyer=texts[1] if len(texts) > 1 else "",
            country="CH",
            language=self._detect_language(title),
            currency="CHF",
            region=texts[2] if len(texts) > 2 else "",
            deadline=self._parse_swiss_date(texts[3]) if len(texts) > 3 else None,
            url=urljoin(SIMAP_BASE, href) if href else "",
            raw_json={"method": "playwright", "cells": texts},
        )

    @staticmethod
    def _extract_id(href: str) -> str | None:
        m = re.search(r'searchid[=:](\d+)', href)
        if m:
            return f"simap-{m.group(1)}"
        m = re.search(r'[?&]id=(\d+)', href)
        if m:
            return f"simap-{m.group(1)}"
        return None

    @staticmethod
    def _parse_swiss_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        for fmt in ["%d.%m.%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d"]:
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _detect_language(text: str) -> str:
        t = text.lower()
        fr = sum(1 for w in ['travaux', 'marché', 'public', 'canton', 'vd', 'ge', 'ne', 'fr', 'ju', 'vs'] if w in t)
        it = sum(1 for w in ['lavori', 'appalto', 'canton', 'ti'] if w in t)
        de = sum(1 for w in ['bauarbeiten', 'ausschreibung', 'vergabe', 'kanton', 'zh', 'be', 'basel', 'zürich', 'bern'] if w in t)
        if it > fr and it > de:
            return "it"
        if fr > de:
            return "fr"
        return "de"

    async def close(self) -> None:
        await self.client.aclose()

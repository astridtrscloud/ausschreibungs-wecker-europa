"""bund.de Ausschreibungen via RSS-Feed."""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.sources.base import TenderRaw

logger = logging.getLogger("app.sources.bund_de")

BUND_RSS_URL = "https://www.service.bund.de/Content/DE/Ausschreibungen/Suche/Rss/Rss_PSAJ.xml"
REQUEST_TIMEOUT = 30.0
USER_AGENT = "Ausschreibungs-Wecker-Europa/1.0 (Open Source Tender Monitoring)"


class BundDeSource:
    """bund.de Ausschreibungen via RSS-Feed."""

    name: str = "bund_de"

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
            follow_redirects=True,
        )

    async def fetch(self) -> list[TenderRaw]:
        logger.info("bund.de RSS wird abgerufen...", extra={"source": "bund_de"})
        for attempt in range(3):
            try:
                response = await self.client.get(BUND_RSS_URL)
                response.raise_for_status()
                return self._parse_rss(response.text)
            except httpx.HTTPStatusError as e:
                logger.warning(f"bund.de HTTP {e.response.status_code} (Attempt {attempt+1}/3)", extra={"source": "bund_de"})
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return []
            except Exception as e:
                logger.error(f"bund.de Error: {e}", extra={"source": "bund_de"})
                return []

    def _parse_rss(self, xml_content: str) -> list[TenderRaw]:
        tenders: list[TenderRaw] = []
        try:
            tree = HTMLParser(xml_content)
            items = tree.css("item")
            logger.info(f"bund.de: {len(items)} RSS-Items", extra={"source": "bund_de"})
            for item in items:
                try:
                    t = self._parse_item(item)
                    if t:
                        tenders.append(t)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"bund.de Parse-Fehler: {e}", extra={"source": "bund_de"})
        return tenders

    def _parse_item(self, item) -> TenderRaw | None:
        title_el = item.css_first("title")
        title = title_el.text(strip=True) if title_el else "(Kein Titel)"
        link_el = item.css_first("link")
        url = link_el.text(strip=True) if link_el else ""
        desc_el = item.css_first("description")
        description = desc_el.text(strip=True) if desc_el else ""
        guid_el = item.css_first("guid")
        external_id = guid_el.text(strip=True) if guid_el else url
        pubdate_el = item.css_first("pubDate")
        published_at = self._parse_rfc822(pubdate_el.text(strip=True)) if pubdate_el else None
        buyer = ""
        if "Vergabestelle:" in description:
            parts = description.split("Vergabestelle:")
            if len(parts) > 1:
                buyer = parts[1].split("\n")[0].strip()
        return TenderRaw(
            external_id=external_id or f"bund-{hash(title) & 0xFFFFFFFF:08x}",
            title=title,
            description=description,
            buyer=buyer,
            country="DE",
            language="de",
            region="Deutschland",
            published_at=published_at,
            url=url,
            raw_json={"rss_guid": external_id},
        )

    @staticmethod
    def _parse_rfc822(date_str: str) -> datetime | None:
        if not date_str:
            return None
        for fmt in ["%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"]:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
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
        source = BundDeSource()
        try:
            tenders = await source.fetch()
            print(f"\nBUND.DE: {len(tenders)} Ausschreibungen")
            for t in tenders[:3]:
                print(f"  - {t.title[:60]} [{t.country}]")
        finally:
            await source.close()

    asyncio.run(test())

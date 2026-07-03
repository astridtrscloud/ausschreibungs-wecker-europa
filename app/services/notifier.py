"""E-Mail und Slack Benachrichtigungen.

Sendet Digest-Benachrichtigungen für neue Matches.
Gruppiert nach Land, zeigt CHF/EUR, mit Länder-Emojis.
"""
import asyncio
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib
import httpx

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.core.config import settings
from app.core.database import get_session
from app.models.models import Match, Tender, CompanyProfile

logger = logging.getLogger("app.services.notifier")

COUNTRY_EMOJI = {
    "DE": "🇩🇪", "CH": "🇨🇭", "AT": "🇦🇹", "FR": "🇫🇷", "IT": "🇮🇹",
    "ES": "🇪🇸", "NL": "🇳🇱", "BE": "🇧🇪", "PL": "🇵🇱", "SE": "🇸🇪",
    "DK": "🇩🇰", "FI": "🇫🇮", "NO": "🇳🇴", "IE": "🇮🇪", "PT": "🇵🇹",
    "CZ": "🇨🇿", "HU": "🇭🇺", "RO": "🇷🇴", "BG": "🇧🇬", "HR": "🇭🇷",
    "SI": "🇸🇮", "SK": "🇸🇰", "LT": "🇱🇹", "LV": "🇱🇻", "EE": "🇪🇪",
    "LU": "🇱🇺", "MT": "🇲🇹", "CY": "🇨🇾", "GR": "🇬🇷", "IS": "🇮🇸",
    "LI": "🇱🇮",
}


def _get_emoji(country: str) -> str:
    return COUNTRY_EMOJI.get(country.upper(), f"[{country}]")


class Notifier:
    """Sendet Digest-Benachrichtigungen für neue Matches."""

    def __init__(self) -> None:
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_pass = settings.smtp_pass
        self.mail_to = settings.mail_to
        self.slack_webhook_url = settings.slack_webhook_url
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def send_digest(self, matches: list[Match]) -> None:
        if not matches:
            return

        logger.info(f"Sende Digest für {len(matches)} Matches...", extra={"source": "notifier"})

        if self.mail_to and self.smtp_host:
            try:
                await self._send_email(matches)
                logger.info("E-Mail Digest gesendet", extra={"source": "notifier"})
            except Exception as e:
                logger.error(f"E-Mail Fehler: {e}", extra={"source": "notifier"})

        if self.slack_webhook_url:
            try:
                await self._send_slack(matches)
                logger.info("Slack Digest gesendet", extra={"source": "notifier"})
            except Exception as e:
                logger.error(f"Slack Fehler: {e}", extra={"source": "notifier"})

        self._mark_notified(matches)

    def _group_by_country(self, matches: list[Match]) -> dict[str, list[Match]]:
        groups: dict[str, list[Match]] = {}
        for m in matches:
            c = m.tender.country.upper() if m.tender.country else "UN"
            groups.setdefault(c, []).append(m)
        return groups

    def _build_email_html(self, matches: list[Match]) -> str:
        groups = self._group_by_country(matches)
        parts = [
            "<!DOCTYPE html>",
            "<html><head><meta charset='utf-8'><style>",
            "body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }",
            ".container { max-width: 650px; margin: 0 auto; padding: 20px; }",
            ".header { background: #1a5276; color: white; padding: 20px; border-radius: 8px 8px 0 0; }",
            ".country-section { margin: 16px 0; }",
            ".country-header { font-size: 18px; font-weight: bold; padding: 10px; background: #f0f2f5; border-radius: 6px; }",
            ".match { background: #f8f9fa; border-left: 4px solid #1a5276; padding: 15px; margin: 10px 0; }",
            ".score { font-size: 22px; font-weight: bold; color: #1a5276; }",
            ".title { font-size: 15px; font-weight: bold; margin: 8px 0; }",
            ".meta { color: #666; font-size: 12px; }",
            ".value { color: #27ae60; font-weight: bold; }",
            ".button { display: inline-block; background: #1a5276; color: white; padding: 8px 16px; text-decoration: none; border-radius: 5px; margin-top: 8px; }",
            ".footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; }",
            "</style></head><body>",
            "<div class='container'>",
            f"<div class='header'><h1>Ausschreibungs-Wecker Europa</h1><p>{len(matches)} neue Treffer in {len(groups)} Ländern</p></div>",
        ]

        for country, cmatches in sorted(groups.items()):
            emoji = _get_emoji(country)
            parts.append(f"<div class='country-section'><div class='country-header'>{emoji} {country} – {len(cmatches)} Treffer</div>")
            for match in cmatches:
                t = match.tender
                deadline_str = t.deadline.strftime("%d.%m.%Y") if t.deadline else "n/a"
                value_str = f"{t.estimated_value:,.0f} {t.currency}" if t.estimated_value and t.currency else ""
                parts.extend([
                    f"<div class='match'>",
                    f"<div class='score'>{match.score}/100</div>",
                    f"<div class='title'>{self._escape_html(t.title)}</div>",
                    f"<div class='meta'>",
                    f"<strong>Vergabestelle:</strong> {self._escape_html(t.buyer) or 'n/a'}<br>",
                    f"<strong>Deadline:</strong> {deadline_str}<br>",
                    f"<strong>Region:</strong> {self._escape_html(t.region) or 'n/a'}",
                    f"{f'<br><span class=\"value\">Geschätzter Wert: {value_str}</span>' if value_str else ''}",
                    f"</div>",
                    f"<p><em>{self._escape_html(match.reasoning)}</em></p>",
                    f"<a href='{t.url}' class='button'>Ausschreibung öffnen</a>",
                    f"</div>",
                ])
            parts.append("</div>")

        parts.extend([
            "<div class='footer'>",
            f"<p>Ausschreibungs-Wecker Europa &bull; {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>",
            "</div></div></body></html>",
        ])
        return "\n".join(parts)

    def _build_slack_blocks(self, matches: list[Match]) -> dict:
        groups = self._group_by_country(matches)
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"Ausschreibungs-Wecker Europa: {len(matches)} Treffer in {len(groups)} Ländern", "emoji": True}},
            {"type": "divider"},
        ]

        for country, cmatches in sorted(groups.items())[:5]:
            emoji = _get_emoji(country)
            for match in cmatches[:3]:
                t = match.tender
                deadline_str = t.deadline.strftime("%d.%m.%Y") if t.deadline else "n/a"
                value_str = f" | Wert: {t.estimated_value:,.0f} {t.currency}" if t.estimated_value and t.currency else ""
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{emoji} *Score: {match.score}/100* – {t.title[:70]}\n"
                            f"Vergabestelle: {t.buyer or 'n/a'} | Deadline: {deadline_str}{value_str}\n"
                            f"_{match.reasoning[:80]}_"
                        ),
                    }
                })
                if t.url:
                    blocks.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Öffnen"}, "url": t.url}]})
                blocks.append({"type": "divider"})

        return {"blocks": blocks}

    async def _send_email(self, matches: list[Match]) -> None:
        html = self._build_email_html(matches)
        text = self._build_email_text(matches)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Ausschreibungs-Wecker Europa: {len(matches)} neue Treffer"
        msg["From"] = self.smtp_user or "ausschreibungs-wecker@localhost"
        msg["To"] = self.mail_to
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        await aiosmtplib.send(msg, hostname=self.smtp_host, port=self.smtp_port,
                              username=self.smtp_user, password=self.smtp_pass,
                              start_tls=True if self.smtp_port == 587 else False)

    def _build_email_text(self, matches: list[Match]) -> str:
        groups = self._group_by_country(matches)
        lines = ["Ausschreibungs-Wecker Europa", f"{len(matches)} Treffer in {len(groups)} Ländern", "=" * 50, ""]
        for country, cmatches in sorted(groups.items()):
            emoji = _get_emoji(country)
            lines.append(f"\n{emoji} {country}")
            for m in cmatches:
                t = m.tender
                val = f" | Wert: {t.estimated_value:,.0f} {t.currency}" if t.estimated_value and t.currency else ""
                lines.extend([
                    f"  Score: {m.score}/100 | {t.title[:70]}",
                    f"  Deadline: {t.deadline.strftime('%d.%m.%Y') if t.deadline else 'n/a'}{val}",
                    f"  {m.reasoning}",
                    f"  {t.url or 'n/a'}",
                    "  -" * 20,
                ])
        return "\n".join(lines)

    async def _send_slack(self, matches: list[Match]) -> None:
        payload = self._build_slack_blocks(matches)
        response = await self.client.post(self.slack_webhook_url, json=payload)
        response.raise_for_status()

    def _mark_notified(self, matches: list[Match]) -> None:
        with get_session() as session:
            for match in matches:
                session.add(match)
                match.status = "notified"

    @staticmethod
    def _escape_html(text: str | None) -> str:
        if not text:
            return ""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    async def close(self) -> None:
        await self.client.aclose()

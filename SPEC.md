# SPEC.md – Ausschreibungs-Wecker Europa

## Architektur
FastAPI + APScheduler + SQLModel + OpenAI-kompatible LLM. Jinja2+HTMX Dashboard.
Plug-in-Architektur fuer Quellen: jedes Modul in `sources/` implementiert `SourceProtocol`.

## Module

### app/core/
- `config.py` – Pydantic-Settings
- `database.py` – SQLModel-Engine + Session
- `logging_config.py` – JSON-Logging

### app/models/
- `models.py` – Tender, CompanyProfile, Match

### app/sources/
- `base.py` – TenderRaw, SourceProtocol
- `ted.py` – TED Search API v3 (EU/EWR)
- `simap_ch.py` – simap.ch (Schweiz)
- `bund_de.py` – bund.de RSS (Deutschland)
- `_registry.py` – Quellen-Registry fuer Plug-in-System

### app/services/
- `matcher.py` – Vorfilter + LLM-Scoring (mehrsprachig)
- `notifier.py` – E-Mail + Slack
- `deduper.py` – Cross-Source-Fuzzy-Dedupe (rapidfuzz)

### app/api/
- `main.py` – FastAPI App
- `dashboard.py` – Jinja2 + HTMX
- `auth.py` – HTTP-Basic-Auth

### app/templates/ + app/static/css/
- Jinja2-Templates mit Laender-/Sprachfilter

## Datenmodell

### Tender (table=True)
- id: int PK
- source: str (ted/simap_ch/bund_de)
- external_id: str
- title: str
- description: str
- buyer: str
- country: str (ISO-2, e.g. "CH", "DE", "FR")
- language: str (ISO-2, e.g. "de", "fr")
- cpv_codes: str (JSON)
- region: str (NUTS-Code wenn vorhanden)
- deadline: datetime | null
- published_at: datetime | null
- url: str
- currency: str | null ("CHF", "EUR")
- estimated_value: float | null
- raw_json: str (JSON)
- created_at: datetime

**UNIQUE(source, external_id)**

### CompanyProfile (table=True)
- id: int PK
- name: str
- description: str
- keywords: str (JSON-Liste)
- cpv_whitelist: str (JSON)
- countries: str (JSON-Liste ISO-2, leer = ganz Europa)
- regions: str (JSON, NUTS-Codes)
- languages_ok: str (JSON, z.B. ["de","fr","en"])
- min_deadline_days: int (default 7)
- created_at: datetime

### Match (table=True)
- id: int PK
- tender_id: int FK
- profile_id: int FK
- score: int (0-100)
- reasoning: str
- status: str (new/notified/dismissed/saved)
- created_at: datetime

## Plug-in-System
Neue Quelle = neues Modul in `sources/` + Eintrag in `sources/_registry.py`.
Kerncode bleibt unveraendert.

## Cross-Source-Dedupe
- UNIQUE(source, external_id) fuer Intra-Source
- rapidfuzz Fuzzy-Match (Titel+Buyer+Deadline, Ratio > 92) fuer Inter-Source (simap<->TED)

## Qualitaetsregeln
1. Timeout 30s, 3 Retries, User-Agent
2. Rate-Limit: max 1 req/s pro Quelle
3. JSON-Logging, niemals silent fail
4. Max 200 LLM-Calls pro Lauf
5. UTC in DB, Europe/Zurich in Anzeige
6. Kein Global State – Dependency Injection
7. Neue Quellen als Plug-in-Module

# Ausschreibungs-Wecker Europa

> Automatischer Ausschreibungs-Monitor fuer europaeische und schweizerische Vergabeplattformen. Mit mehrsprachigem LLM-Matching, Cross-Source-Deduplizierung und gruppierten Benachrichtigungen.

---

## Features

- **3 integrierte Datenquellen**: TED (EU/EWR), simap.ch (Schweiz), bund.de (Deutschland)
- **Mehrsprachig**: Unterstuetzt Deutsch, Franzoesisch, Italienisch, Englisch und weitere europaeische Sprachen
- **LLM-basiertes Matching**: Zweistufiger Prozess – Vorfilter (CPV/Keywords/Land) + LLM-Scoring (OpenAI-kompatibel)
- **Cross-Source-Deduplizierung**: Erkennt Duplikate zwischen Quellen via rapidfuzz Fuzzy-Matching (z.B. TED vs. simap.ch)
- **Laender-gruppierte Benachrichtigungen**: E-Mail (HTML) und Slack mit Emoji-Flaggen und Waehrungsformatierung
- **Plug-in-System**: Neue Quellen einfach per Python-Modul hinzufuegen
- **Web-Dashboard**: FastAPI-basiert mit Health-Checks, Statistiken und manuellem Scraping
- **Production-Ready**: Docker, Healthchecks, Retry-Logik, Rate-Limiting

---

## Tech-Stack

| Komponente | Technologie |
|------------|-------------|
| API-Framework | FastAPI + Uvicorn |
| Datenbank | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLModel |
| Scraping | httpx + selectolax + Playwright (Fallback) |
| LLM-Matching | OpenAI-kompatible API (Moonshot, OpenAI, Ollama) |
| Deduplizierung | rapidfuzz |
| Benachrichtigungen | SMTP (E-Mail) + Slack Webhook |
| Scheduling | APScheduler |
| Templates | Jinja2 |
| Tests | pytest + pytest-asyncio |

---

## Schnellstart (< 10 Minuten)

### 1. Repository klonen

```bash
git clone <repo-url>
cd ausschreibungs-wecker-europa
```

### 2. Virtuelle Umgebung & Abhaengigkeiten

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 3. Umgebungsvariablen

```bash
cp .env.example .env
# .env anpassen – mindestens LLM_API_KEY und MAIL_TO
```

### 4. Tests ausfuehren

```bash
python -m pytest tests/ -v --tb=short
```

### 5. Anwendung starten

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Dashboard: http://localhost:8000  
Health-Check: http://localhost:8000/api/health

---

## LLM-Konfiguration

### Moonshot AI (empfohlen, default)

```env
LLM_BASE_URL=https://api.moonshot.ai/v1
LLM_API_KEY=sk-dein-key-hier
LLM_MODEL=kimi-latest
```

### OpenAI

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-dein-openai-key
LLM_MODEL=gpt-4o-mini
```

### Ollama (lokal, kostenlos)

```bash
# Ollama installieren und Modell laden
ollama pull llama3.2
```

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

---

## Datenquellen

### TED (EU/EWR) – `app/sources/ted.py`

- **API**: TED Search API v3 – `api.ted.europa.eu/v3/notices/search`
- **Umfang**: Alle EU/EWR-Mitgliedstaaten + Schweiz, Norwegen, Island, Liechtenstein
- **Laenderfilter**: Komma-separierte ISO-2-Codes in `TED_COUNTRIES`
- **Mehrsprachig**: Titel/Beschreibungen in DE, FR, IT, EN, ES, NL, PL, ...
- **Felder**: CPV-Codes, NUTS-Regionen, geschaetzter Wert + Waehrung, Deadline

```env
TED_COUNTRIES=DE,FR,CH,AT,IT,ES,NL,BE,PL,SE
TED_MAX_PAGES=5
TED_PAGE_SIZE=20
```

### simap.ch (Schweiz) – `app/sources/simap_ch.py`

- **URL**: `simap.ch` – Bund, Kantone, Gemeinden
- **Sprachen**: DE, FR, IT (automatisch erkannt)
- **Waehrung**: CHF
- **Features**: Kantons-Erkennung, Playwright-Fallback fuer JS-Rendering
- **De-/Aktivierung**: `SIMAP_ENABLED=true/false`

```env
SIMAP_ENABLED=true
```

### bund.de (Deutschland) – `app/sources/bund_de.py`

- **URL**: `service.bund.de` – RSS-Feed
- **Sprache**: Deutsch
- **Waehrung**: EUR
- **Parsing**: RSS-XML mit selectolax

---

## Dashboard

### Seiten

| Seite | URL | Beschreibung |
|-------|-----|--------------|
| Dashboard (Uebersicht) | `/` | Statistiken, neueste Ausschreibungen |
| Ausschreibungen | `/tenders` | Alle Tenders filtern und durchsuchen |
| Matches | `/matches` | Gefundene Matches mit Scores |
| Profil | `/profile` | Firmenprofil bearbeiten |
| Health (JSON) | `/api/health` | System-Health mit DB-Statistiken |

### Authentifizierung

Basic Auth via `DASHBOARD_USER` / `DASHBOARD_PASS`.

---

## Plug-in-System

Neue Quellen in 3 Schritten hinzufuegen:

### 1. Modul erstellen

```python
# app/sources/mein_portal.py
from app.sources.base import TenderRaw

class MeinPortalSource:
    name: str = "mein_portal"

    async def fetch(self) -> list[TenderRaw]:
        # Implementierung hier
        return [TenderRaw(source=self.name, external_id="...", title="...")]
```

### 2. In Registry eintragen

```python
# app/sources/_registry.py
from app.sources.mein_portal import MeinPortalSource

SOURCES = [
    TEDSource(),
    SIMAPSource(),
    BundDeSource(),
    MeinPortalSource(),  # <-- neu
]
```

### 3. Fertig

Die neue Quelle wird automatisch beim naechsten Scraping-Durchlauf abgefragt.

---

## API-Endpunkte

| Methode | Endpunkt | Beschreibung | Auth |
|---------|----------|--------------|------|
| GET | `/api/health` | Health-Check + Statistiken | Basic |
| POST | `/api/scrape` | Manuelles Scraping starten | Basic |
| POST | `/api/matches/{id}/status` | Match-Status aendern | Basic |
| GET | `/` | Dashboard (HTML) | Basic |
| GET | `/tenders` | Ausschreibungen (HTML) | Basic |
| GET | `/matches` | Matches (HTML) | Basic |
| GET | `/profile` | Profil (HTML) | Basic |

---

## Tests

### Alle Tests ausfuehren

```bash
python -m pytest tests/ -v --tb=short
```

### Test-Abdeckung

| Datei | Beschreibung |
|-------|--------------|
| `test_models.py` | SQLModel-Modelle (Tender, CompanyProfile, Match) |
| `test_sources.py` | TED, simap.ch, bund.de mit HTTP-Mocks |
| `test_matcher.py` | Vorfilter, LLM-Scoring, Prompt-Bau, Response-Parsing |
| `test_notifier.py` | Laender-Gruppierung, HTML/Slack-Bau, Versand-Mocks |
| `test_deduper.py` | rapidfuzz Fuzzy-Matching, Cross-Source-Dedupe |
| `test_integration.py` | E2E: Scraper -> Matcher -> Notifier |

---

## Docker-Deployment

### Docker Compose (empfohlen)

```bash
# .env anpassen, dann:
docker-compose up -d

# Logs ansehen
docker-compose logs -f app

# Health-Check
curl -u admin:changeme http://localhost:8000/api/health
```

---

## Projektstruktur

```
ausschreibungs-wecker-europa/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
├── .env.example
├── README.md
├── SPEC.md
├── app/
│   ├── __init__.py
│   ├── scheduler.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── auth.py
│   │   └── dashboard.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── logging_config.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── models.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── _registry.py
│   │   ├── ted.py
│   │   ├── simap_ch.py
│   │   └── bund_de.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── matcher.py
│   │   ├── notifier.py
│   │   └── deduper.py
│   ├── static/
│   │   └── css/
│   │       └── style.css
│   └── templates/
│       ├── base.html
│       ├── health.html
│       ├── matches.html
│       ├── profile.html
│       └── tenders.html
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_sources.py
│   ├── test_matcher.py
│   ├── test_notifier.py
│   ├── test_deduper.py
│   └── test_integration.py
└── data/
```

---

## Lizenz

MIT License

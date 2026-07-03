"""FastAPI-Hauptanwendung."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.core.database import init_db
from app.core.logging_config import setup_logging
from app.scheduler import setup_scheduler, run_scraper
from app.api import dashboard

logger = logging.getLogger("app.api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    logger.info("Datenbank initialisiert")
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler gestartet")
    yield
    scheduler.shutdown()
    logger.info("Scheduler gestoppt")


app = FastAPI(
    title="Ausschreibungs-Wecker Europa",
    description="KI-Agent für öffentliche Ausschreibungen in Europa und der Schweiz",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/scrape")
async def trigger_scrape():
    stats = await run_scraper()
    return {"status": "completed", "stats": stats}

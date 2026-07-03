"""Zentrales JSON-Logging Setup."""
import logging
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formatiert Log-Einträge als JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "source"):
            log_entry["source"] = record.source
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging() -> None:
    """Konfiguriert JSON-Logging für die gesamte App."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    for name in ["app", "app.sources", "app.services", "app.api"]:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.handlers = []
        logger.addHandler(handler)
        logger.propagate = False

    logging.getLogger("app").info("Logging konfiguriert (JSON-Format)")


def get_logger(name: str) -> logging.Logger:
    """Holt einen Logger mit JSON-Formatierung."""
    return logging.getLogger(name)

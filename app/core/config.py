"""Zentrale Konfiguration aus Umgebungsvariablen."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Alle App-Einstellungen via .env oder Umgebungsvariablen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # LLM
    llm_base_url: str = "https://api.moonshot.ai/v1"
    llm_api_key: str = ""
    llm_model: str = "kimi-latest"

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_to: str = ""

    # Slack
    slack_webhook_url: str = ""

    # Dashboard Auth
    dashboard_user: str = "admin"
    dashboard_pass: str = "changeme"

    # Scheduler
    scrape_interval_minutes: int = 30

    # Database
    database_url: str = "sqlite:///./data/ausschreibungen.db"

    # Source-Config
    ted_countries: str = ""  # Komma-getrennte ISO-2 Liste, leer = alle
    simap_enabled: bool = True

    @property
    def ted_country_list(self) -> list[str]:
        """TED-Laender als Liste."""
        if self.ted_countries:
            return [c.strip().upper() for c in self.ted_countries.split(",") if c.strip()]
        return []


# Singleton-Instanz
settings = Settings()

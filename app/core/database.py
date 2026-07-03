"""SQLModel-Datenbank-Setup."""
from sqlmodel import SQLModel, create_engine, Session
from contextlib import contextmanager
from .config import settings

# Engine mit SQLite-Konfiguration
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)


def init_db() -> None:
    """Erstellt alle Tabellen."""
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session():
    """Kontextmanager für DB-Sessions."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_dependency():
    """FastAPI Dependency für DB-Sessions."""
    with get_session() as session:
        yield session

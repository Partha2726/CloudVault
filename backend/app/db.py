from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# pool_pre_ping survives Neon compute auto-suspend (doc 11.1). Statement and pool timeouts
# keep a stuck query from blocking requests (doc 09.3). Sessions run in UTC (doc 04).
engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    pool_timeout=10,
    connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000 -c timezone=UTC"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

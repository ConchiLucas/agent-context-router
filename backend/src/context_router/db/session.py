from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from context_router.config import settings


def build_engine(database_url: str = settings.database_url):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def ensure_sqlite_schema(database_engine: Engine = engine) -> None:
    if database_engine.url.get_backend_name() != "sqlite":
        return

    from context_router.db.models import Base

    Base.metadata.create_all(database_engine)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

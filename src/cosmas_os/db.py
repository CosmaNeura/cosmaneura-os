from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from cosmas_os.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    return create_engine(url or settings.database_url, pool_pre_ping=True)


def make_session_factory(engine=None):
    eng = engine or make_engine()
    return sessionmaker(bind=eng, autoflush=False, autocommit=False, class_=Session)

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseSessionFactory:
    """Creates short-lived SQLAlchemy sessions for repository operations."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

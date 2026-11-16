from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.postgresql.models.project_model import ProjectModel


class DatabaseSessionFactory:
    """Creates short-lived SQLAlchemy sessions for repository operations."""

    transactional = True

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self._active: ContextVar[Session | None] = ContextVar(
            f"postgresql_unit_of_work_{id(self)}", default=None,
        )
        self._active_mode: ContextVar[str | None] = ContextVar(
            f"postgresql_transaction_mode_{id(self)}", default=None,
        )
        self._after_commit: ContextVar[list[Callable[[], None]] | None] = ContextVar(
            f"postgresql_after_commit_{id(self)}", default=None,
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        active = self._active.get()
        if active is not None:
            yield active
            # Repositories normally commit on exit. Flush instead while an
            # activation owns the transaction, surfacing write failures now.
            active.flush()
            return
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def activation(self, project_id: str) -> Iterator[Session]:
        """Serialize method activation per project and share one SQL transaction.

        The project row lock makes the idempotency check and inserts one
        indivisible operation. A later Activity insert can use this session.
        """
        active = self._active.get()
        if self._active_mode.get() == "consistent_read":
            raise RuntimeError("activation cannot be nested inside consistent_read")
        if active is not None:
            yield active
            return
        session = self._session_factory()
        token = self._active.set(session)
        callbacks: list[Callable[[], None]] = []
        callback_token = self._after_commit.set(callbacks)
        committed = False
        try:
            project = session.execute(
                select(ProjectModel.id)
                .where(ProjectModel.id == project_id)
                .with_for_update()
            ).scalar_one_or_none()
            if project is None:
                raise ValueError("Project not found")
            yield session
            session.flush()
            session.commit()
            committed = True
        except BaseException:
            session.rollback()
            raise
        finally:
            self._active.reset(token)
            self._after_commit.reset(callback_token)
            session.close()
        if committed:
            for callback in callbacks:
                callback()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Share one commit for a new project and its first study."""
        active = self._active.get()
        if self._active_mode.get() == "consistent_read":
            raise RuntimeError("transaction cannot be nested inside consistent_read")
        if active is not None:
            yield active
            return
        session = self._session_factory()
        token = self._active.set(session)
        callbacks: list[Callable[[], None]] = []
        callback_token = self._after_commit.set(callbacks)
        committed = False
        try:
            yield session
            session.flush()
            session.commit()
            committed = True
        except BaseException:
            session.rollback()
            raise
        finally:
            self._active.reset(token)
            self._after_commit.reset(callback_token)
            session.close()
        if committed:
            for callback in callbacks:
                callback()

    @contextmanager
    def consistent_read(self) -> Iterator[Session]:
        """Run repository reads in one PostgreSQL repeatable-read snapshot.

        This boundary is deliberately incompatible with an already active
        transaction: silently reusing it could lose the isolation/read-only
        guarantees promised by this API.
        """
        if self._active.get() is not None:
            raise RuntimeError("consistent_read cannot be nested inside an active transaction")
        connection = self._engine.connect()
        transaction = None
        session = None
        token = None
        mode_token = None
        rolled_back = False
        try:
            connection = connection.execution_options(
                isolation_level="REPEATABLE READ",
            )
            transaction = connection.begin()
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            session = self._session_factory(bind=connection)
            token = self._active.set(session)
            mode_token = self._active_mode.set("consistent_read")
            yield session
        except BaseException:
            if transaction is not None and not rolled_back:
                transaction.rollback()
                rolled_back = True
            raise
        else:
            transaction.rollback()
            rolled_back = True
        finally:
            if transaction is not None and not rolled_back:
                transaction.rollback()
            if token is not None:
                self._active.reset(token)
            if mode_token is not None:
                self._active_mode.reset(mode_token)
            if session is not None:
                session.close()
            connection.close()

    def defer_until_commit(self, callback: Callable[[], None]) -> bool:
        callbacks = self._after_commit.get()
        if callbacks is None:
            return False
        callbacks.append(callback)
        return True

    def record_activity(self, **kwargs) -> None:
        from infrastructure.persistence.postgresql.project_activity import record_activity
        with self.session() as session:
            record_activity(session, **kwargs)

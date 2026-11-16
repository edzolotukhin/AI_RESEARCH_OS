from __future__ import annotations

import unittest
from unittest.mock import Mock

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase


TABLE = "_f4b4b2b_consistent_read"


class PostgreSQLConsistentReadTests(PostgreSQLIntegrationTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        with cls._class_engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE IF NOT EXISTS {TABLE} (id integer primary key, value text not null)"))

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._class_engine is not None:
            with cls._class_engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        with self.engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {TABLE}"))
            connection.execute(text(f"INSERT INTO {TABLE} (id, value) VALUES (1, 'before')"))

    def test_repeatable_read_and_read_only_write_rejection(self) -> None:
        factory = DatabaseSessionFactory(self.engine)
        with factory.consistent_read() as session:
            first = session.execute(text(f"SELECT value FROM {TABLE} WHERE id=1")).scalar_one()
            with self.engine.begin() as writer:
                writer.execute(text(f"UPDATE {TABLE} SET value='after' WHERE id=1"))
            second = session.execute(text(f"SELECT value FROM {TABLE} WHERE id=1")).scalar_one()
            self.assertEqual((first, second), ("before", "before"))
            with self.assertRaises(DBAPIError):
                session.execute(text(f"UPDATE {TABLE} SET value='illegal' WHERE id=1"))
        self.assertIsNone(factory._active.get())

    def test_repository_style_session_reuses_consistent_read_session(self) -> None:
        factory = DatabaseSessionFactory(self.engine)
        with factory.consistent_read() as session:
            with factory.session() as nested:
                self.assertIs(session, nested)
                self.assertEqual(nested.execute(text("SELECT 1")).scalar_one(), 1)
        self.assertIsNone(factory._active.get())

    def test_cleanup_after_exception_and_incompatible_nesting(self) -> None:
        factory = DatabaseSessionFactory(self.engine)
        with self.assertRaises(RuntimeError):
            with factory.consistent_read():
                with factory.transaction():
                    pass
        self.assertIsNone(factory._active.get())
        with self.assertRaises(RuntimeError):
            with factory.transaction():
                with factory.consistent_read():
                    pass
        self.assertIsNone(factory._active.get())
        with self.assertRaises(ValueError):
            with factory.consistent_read():
                raise ValueError("rollback")
        self.assertIsNone(factory._active.get())

    def test_initialization_failures_close_connection(self) -> None:
        class Connection:
            def __init__(self, *, fail_at=None):
                self.fail_at = fail_at
                self.closed = False
                self.rolled_back = False

            def execution_options(self, **_kwargs):
                if self.fail_at == "isolation":
                    raise RuntimeError("isolation setup failed")
                return self

            def begin(self):
                if self.fail_at == "begin":
                    raise RuntimeError("begin failed")
                return self

            def exec_driver_sql(self, _sql):
                return None

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        for failure in ("isolation", "begin", "session"):
            with self.subTest(failure=failure):
                connection = Connection(fail_at=failure if failure != "session" else None)
                engine = Mock()
                engine.connect.return_value = connection
                factory = DatabaseSessionFactory(engine)
                if failure == "session":
                    factory._session_factory = Mock(side_effect=RuntimeError("session failed"))
                with self.assertRaises(RuntimeError):
                    with factory.consistent_read():
                        pass
                self.assertTrue(connection.closed)
                if failure == "session":
                    self.assertTrue(connection.rolled_back)
                self.assertIsNone(factory._active.get())
if __name__ == "__main__":
    unittest.main()

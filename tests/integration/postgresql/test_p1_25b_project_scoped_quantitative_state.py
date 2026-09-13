from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from application.ports.quantitative_state_repository import QuantitativeStateRecord
from infrastructure.persistence.postgresql.repositories.postgresql_quantitative_state_repository import PostgreSQLQuantitativeStateRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, create_test_engine, dispose_test_engine


class P125BProjectScopedQuantitativeStateTests(PostgreSQLIntegrationTestCase):
    @staticmethod
    def _record(project_id: str, payload_value: str) -> QuantitativeStateRecord:
        return QuantitativeStateRecord(
            "s3-brief-v1",
            project_id,
            f"run-{project_id}",
            "test.P125BRecord",
            {"value": payload_value},
            f"checksum-{payload_value}",
            f"authority-{payload_value}",
            None,
            None,
            True,
            "ql-1",
        )

    def _create_projects(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, status, created_at, updated_at, version) "
                    "VALUES "
                    "('project-a', 'Project A', 'ACTIVE', '', '', 0), "
                    "('project-b', 'Project B', 'ACTIVE', '', '', 0)"
                )
            )

    def test_cross_project_identity_reload_uniqueness_and_list_isolation(self):
        self._create_projects()
        repository = PostgreSQLQuantitativeStateRepository(self.session_factory)
        record_a = self._record("project-a", "a")
        record_b = self._record("project-b", "b")

        repository.create(record_a)
        repository.create(record_b)
        with self.assertRaisesRegex(ValueError, "already exists"):
            repository.create(self._record("project-a", "replacement"))

        self.engine.dispose()
        restarted_engine = create_test_engine()
        self.addCleanup(dispose_test_engine, restarted_engine)
        restarted = PostgreSQLQuantitativeStateRepository(
            DatabaseSessionFactory(restarted_engine)
        )
        self.assertEqual(
            restarted.get_for_project("s3-brief-v1", project_id="project-a"),
            record_a,
        )
        self.assertEqual(
            restarted.get_for_project("s3-brief-v1", project_id="project-b"),
            record_b,
        )
        self.assertEqual(
            restarted.list_for_run("run-project-a", project_id="project-a"),
            (record_a,),
        )
        self.assertEqual(
            restarted.list_for_run("run-project-b", project_id="project-b"),
            (record_b,),
        )

    def test_schema_uses_composite_primary_key_without_global_record_unique(self):
        schema = inspect(self.engine)
        self.assertEqual(
            schema.get_pk_constraint("quantitative_state_records")["constrained_columns"],
            ["project_id", "record_id"],
        )
        unique_columns = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("quantitative_state_records")
        }
        self.assertNotIn(("record_id",), unique_columns)
        self.assertNotIn(("project_id", "record_id"), unique_columns)
        foreign_keys = schema.get_foreign_keys("quantitative_state_records")
        self.assertTrue(
            any(
                item["constrained_columns"] == ["project_id"]
                and item["referred_table"] == "projects"
                for item in foreign_keys
            )
        )


class P125BMigrationPreservationTests(PostgreSQLIntegrationTestCase):
    def test_downgrade_fails_closed_when_cross_project_duplicates_exist(self):
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, name, status, created_at, updated_at, version) "
                    "VALUES "
                    "('project-a', 'Project A', 'ACTIVE', '', '', 0), "
                    "('project-b', 'Project B', 'ACTIVE', '', '', 0)"
                )
            )
        repository = PostgreSQLQuantitativeStateRepository(self.session_factory)
        repository.create(P125BProjectScopedQuantitativeStateTests._record("project-a", "a"))
        repository.create(P125BProjectScopedQuantitativeStateTests._record("project-b", "b"))

        with self.assertRaisesRegex(RuntimeError, "cross-project duplicate exists"):
            command.downgrade(Config("alembic.ini"), "011_q1_15_quantitative_state")
        self.assertEqual(
            inspect(self.engine).get_pk_constraint("quantitative_state_records")[
                "constrained_columns"
            ],
            ["project_id", "record_id"],
        )
    def test_existing_011_row_survives_upgrade_unchanged(self):
        config = Config("alembic.ini")
        command.downgrade(config, "011_q1_15_quantitative_state")
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO projects (id, name, status, created_at, updated_at, version) "
                        "VALUES ('migration-project', 'Migration', 'ACTIVE', '', '', 0)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO quantitative_state_records "
                        "(record_id, project_id, run_id, record_type, authority_fingerprint, "
                        "payload_checksum, codec_version, accepted, payload) VALUES "
                        "('existing-record', 'migration-project', 'migration-run', 'test.Record', "
                        "'authority-before', 'checksum-before', 'ql-1', true, "
                        "CAST('{\"value\": \"before\"}' AS json))"
                    )
                )
            command.upgrade(config, "head")
            with self.engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT project_id, record_id, run_id, record_type, "
                        "authority_fingerprint, payload_checksum, codec_version, accepted, payload "
                        "FROM quantitative_state_records WHERE project_id='migration-project' "
                        "AND record_id='existing-record'"
                    )
                ).mappings().one()
            self.assertEqual(row["project_id"], "migration-project")
            self.assertEqual(row["record_id"], "existing-record")
            self.assertEqual(row["run_id"], "migration-run")
            self.assertEqual(row["record_type"], "test.Record")
            self.assertEqual(row["authority_fingerprint"], "authority-before")
            self.assertEqual(row["payload_checksum"], "checksum-before")
            self.assertEqual(row["codec_version"], "ql-1")
            self.assertTrue(row["accepted"])
            self.assertEqual(row["payload"], {"value": "before"})
        finally:
            command.upgrade(config, "head")

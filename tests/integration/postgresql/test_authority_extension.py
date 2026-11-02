from __future__ import annotations

import unittest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from application.authority_extension import AuthorityCompositionError, ComposedAuthorityReader, build_composition
from domain.research_authority import ResearchAuthorityExtension
from infrastructure.persistence.postgresql.repositories.postgresql_authority_extension_repository import PostgreSQLAuthorityExtensionRepository, PostgreSQLComposedAuthorityRepository
from infrastructure.persistence.postgresql.session import DatabaseSessionFactory
from tests.integration.postgresql.helpers import PostgreSQLIntegrationTestCase, integration_tests_enabled


@unittest.skipUnless(integration_tests_enabled(), "isolated PostgreSQL integration database required")
class PostgreSQLAuthorityExtensionTests(PostgreSQLIntegrationTestCase):
    def setUp(self):
        super().setUp()
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('project','P','ACTIVE','','',1)"))
            connection.execute(text("INSERT INTO projects (id,name,status,created_at,updated_at,version) VALUES ('foreign-project','F','ACTIVE','','',1)"))
            for run_id, project_id in (("parent", "project"), ("extension", "project"),
                                       ("wrong-design", "project"), ("foreign", "foreign-project")):
                connection.execute(text("INSERT INTO workflow_runs (id,project_id,workflow_template_id,status,dependency_graph,task_results,version) VALUES (:id,:project_id,'template','completed',CAST('{}' AS jsonb),CAST('{}' AS jsonb),0)"), {"id": run_id, "project_id": project_id})

    def test_extension_and_composition_round_trip_and_idempotency(self):
        extensions = PostgreSQLAuthorityExtensionRepository(self.session_factory)
        extension = ResearchAuthorityExtension("ext", "project", "design", "parent", "extension", ("in1", "in2"), "gap", "idem", "now")
        self.assertEqual(extensions.create_or_get(extension), extension)
        self.assertEqual(extensions.create_or_get(extension).extension_id, "ext")
        fresh_extensions = PostgreSQLAuthorityExtensionRepository(DatabaseSessionFactory(self.engine))
        self.assertEqual(fresh_extensions.get_by_id("ext"), extension)

        value = build_composition(composition_id="composition", project_id="project", research_design_id="design", parent_source_workflow_run_id="parent", member_workflow_run_ids=("parent", "extension"), selected_information_need_ids=("in1", "in2"), created_at="now")
        compositions = PostgreSQLComposedAuthorityRepository(self.session_factory)
        self.assertEqual(compositions.create_or_get(value), value)
        self.assertEqual(compositions.create_or_get(value).composition_digest, value.composition_digest)
        fresh = PostgreSQLComposedAuthorityRepository(DatabaseSessionFactory(self.engine)).get_by_id("composition")
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.composition_digest, value.composition_digest)
        self.assertEqual(set(fresh.member_workflow_run_ids), {"parent", "extension"})
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM research_authority_extensions")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM composed_research_authorities")).scalar_one(), 1)
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM composed_research_authority_members")).scalar_one(), 2)

    def test_composition_rejects_foreign_lineage_and_reader_preserves_owners(self):
        extensions = PostgreSQLAuthorityExtensionRepository(self.session_factory)
        extensions.create_or_get(ResearchAuthorityExtension(
            "ext", "project", "design", "parent", "extension", ("in1",),
            "gap", "idem", "now",
        ))
        extensions.create_or_get(ResearchAuthorityExtension(
            "wrong", "project", "other-design", "parent", "wrong-design", ("in1",),
            "gap", "wrong-idem", "now",
        ))
        compositions = PostgreSQLComposedAuthorityRepository(self.session_factory)
        valid = build_composition(
            composition_id="composition", project_id="project", research_design_id="design",
            parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "extension"),
            selected_information_need_ids=("in1",), created_at="now",
        )
        compositions.create_or_get(valid)
        loaded = PostgreSQLComposedAuthorityRepository(
            DatabaseSessionFactory(self.engine),
        ).get_by_id("composition")

        class Item:
            def __init__(self, run_id):
                self.project_id = "project"
                self.workflow_run_id = run_id

        class Repo:
            def list_for_project(self, project_id, *, workflow_run_id=None, **kwargs):
                return [Item(workflow_run_id)] if workflow_run_id in {"parent", "extension"} else []

        reader = ComposedAuthorityReader(Repo(), Repo(), Repo(), Repo())
        self.assertEqual(
            {item.workflow_run_id for item in reader.list_findings(loaded)},
            {"parent", "extension"},
        )
        with self.assertRaises(AuthorityCompositionError):
            reader.validate_member(
                loaded, project_id="project", research_design_id="design",
                workflow_run_id="non-member",
            )

        wrong_design = build_composition(
            composition_id="wrong-design-composition", project_id="project",
            research_design_id="design", parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "wrong-design"),
            selected_information_need_ids=("in1",), created_at="now",
        )
        with self.assertRaises(ValueError):
            compositions.create_or_get(wrong_design)

        cross_project = build_composition(
            composition_id="foreign-composition", project_id="project",
            research_design_id="design", parent_source_workflow_run_id="parent",
            member_workflow_run_ids=("parent", "foreign"),
            selected_information_need_ids=("in1",), created_at="now",
        )
        with self.assertRaises(ValueError):
            compositions.create_or_get(cross_project)

        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO research_authority_extensions "
                    "(extension_id,project_id,research_design_id,parent_source_workflow_run_id,"
                    "extension_workflow_run_id,selected_information_need_ids,gap_contract_digest,"
                    "idempotency_key,created_at,status) VALUES "
                    "('bad','project','design','parent','missing',CAST('[]' AS jsonb),'gap','bad','now','completed')"
                ))

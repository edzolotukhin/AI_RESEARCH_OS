from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from domain.research_authority import ComposedResearchAuthority, ResearchAuthorityExtension
from infrastructure.persistence.postgresql.models.authority_extension_model import AuthorityExtensionModel, ComposedAuthorityModel, ComposedAuthorityMemberModel
from infrastructure.persistence.postgresql.models.workflow_run_model import WorkflowRunModel
from infrastructure.persistence.postgresql.models.task_model import WorkflowTaskModel
from infrastructure.persistence.postgresql.models.execution_log_model import ExecutionLogEntryModel


def _extension(model):
    return ResearchAuthorityExtension(
        extension_id=model.extension_id,
        project_id=model.project_id,
        research_design_id=model.research_design_id,
        parent_source_workflow_run_id=model.parent_source_workflow_run_id,
        extension_workflow_run_id=model.extension_workflow_run_id,
        selected_information_need_ids=tuple(model.selected_information_need_ids),
        gap_contract_digest=model.gap_contract_digest,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
        status=model.status,
        terminal_reason=model.terminal_reason,
    )


class PostgreSQLAuthorityExtensionRepository:
    def __init__(self, session_factory): self._session_factory = session_factory
    def create_or_get(self, extension):
        with self._session_factory.session() as session:
            existing = session.scalar(select(AuthorityExtensionModel).where(AuthorityExtensionModel.project_id == extension.project_id, AuthorityExtensionModel.idempotency_key == extension.idempotency_key))
            if existing: return _extension(existing)
            payload = extension.to_dict()
            # Execution mode is durable in the workflow extension state. Keep
            # the pre-existing authority table schema migration-free.
            payload.pop("execution_mode", None)
            session.add(AuthorityExtensionModel(**payload))
            return extension
    def get_by_id(self, extension_id):
        with self._session_factory.session() as session:
            model = session.get(AuthorityExtensionModel, extension_id)
            return _extension(model) if model else None
    def get_by_idempotency_key(self, project_id, idempotency_key):
        with self._session_factory.session() as session:
            model = session.scalar(select(AuthorityExtensionModel).where(AuthorityExtensionModel.project_id == project_id, AuthorityExtensionModel.idempotency_key == idempotency_key))
            return _extension(model) if model else None
    def save(self, extension):
        with self._session_factory.session() as session:
            model = session.get(AuthorityExtensionModel, extension.extension_id)
            if model is None:
                raise ValueError(f"Authority extension not found: {extension.extension_id}")
            immutable = (
                model.project_id, model.research_design_id,
                model.parent_source_workflow_run_id, model.extension_workflow_run_id,
                tuple(model.selected_information_need_ids), model.gap_contract_digest,
                model.idempotency_key, model.created_at,
            )
            candidate = (
                extension.project_id, extension.research_design_id,
                extension.parent_source_workflow_run_id, extension.extension_workflow_run_id,
                tuple(extension.selected_information_need_ids), extension.gap_contract_digest,
                extension.idempotency_key, extension.created_at,
            )
            if immutable != candidate:
                raise ValueError("authority extension immutable identity mismatch")
            model.status = extension.status.value
            model.terminal_reason = extension.terminal_reason

    def reconcile_failed_active(
        self, *, project_id: str, extension_id: str,
        expected_workflow_run_id: str, failure_class: str,
        reason: str, dry_run: bool,
    ) -> dict:
        """Conditionally reconcile one stale extension in one transaction.

        The workflow row is always locked before the extension row.  The same
        checks are repeated under lock for apply, so the operator command never
        relies on a stale preflight read.
        """
        now = datetime.now(timezone.utc)
        with self._session_factory.session() as session:
            workflow = session.scalar(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.id == expected_workflow_run_id,
                ).with_for_update()
            )
            if workflow is None:
                return {"ok": False, "code": "workflow_not_found"}
            extension = session.scalar(
                select(AuthorityExtensionModel).where(
                    AuthorityExtensionModel.extension_id == extension_id,
                ).with_for_update()
            )
            if extension is None:
                return {"ok": False, "code": "extension_not_found"}
            if extension.project_id != project_id:
                return {"ok": False, "code": "project_mismatch"}
            if extension.extension_workflow_run_id != expected_workflow_run_id:
                return {"ok": False, "code": "workflow_linkage_mismatch"}
            if workflow.project_id != project_id:
                return {"ok": False, "code": "workflow_project_mismatch"}
            task_statuses = list(session.scalars(select(WorkflowTaskModel.status).where(
                WorkflowTaskModel.workflow_run_id == expected_workflow_run_id,
            )).all())
            terminal = {"completed", "failed", "skipped", "cancelled", "paused"}
            if workflow.status != "failed":
                return {"ok": False, "code": "workflow_not_failed", "status": workflow.status}
            if any(status not in terminal for status in task_statuses):
                return {"ok": False, "code": "nonterminal_task"}
            if workflow.claimed_by and (
                workflow.lease_expires_at is None or workflow.lease_expires_at > now
            ):
                return {"ok": False, "code": "active_execution_lease"}
            if extension.status == "technical_error":
                return {"ok": True, "code": "already_reconciled", "status": extension.status}
            if extension.status != "active":
                return {"ok": False, "code": "extension_not_active", "status": extension.status}
            result = {
                "ok": True, "code": "dry_run" if dry_run else "reconciled",
                "extension_id": extension_id,
                "workflow_run_id": expected_workflow_run_id,
                "previous_status": extension.status,
                "new_status": "technical_error",
                "failure_class": str(failure_class)[:120],
                "reason": str(reason)[:256],
                "timestamp": now.isoformat(),
            }
            if dry_run:
                return result
            extension.status = "technical_error"
            extension.terminal_reason = (
                f"{str(failure_class)[:80]}: {str(reason)[:170]}"
            )[:256]
            event_id = f"{expected_workflow_run_id}:authority_extension_reconciled"
            existing = session.scalar(select(ExecutionLogEntryModel).where(
                ExecutionLogEntryModel.event_id == event_id,
            ))
            if existing is None:
                session.add(ExecutionLogEntryModel(
                    event_id=event_id, run_id=expected_workflow_run_id,
                    task_id=None, event_type="authority_extension_reconciled",
                    timestamp=now.isoformat(), payload={
                        "extension_id": extension_id,
                        "workflow_id": expected_workflow_run_id,
                        "previous_status": "active",
                        "new_status": "technical_error",
                        "failure_class": str(failure_class)[:120],
                        "reconciliation_reason": str(reason)[:256],
                        "operator_action": "authority_extension_reconciliation",
                    },
                ))
            return result


class PostgreSQLComposedAuthorityRepository:
    def __init__(self, session_factory): self._session_factory = session_factory
    def create_or_get(self, composition):
        with self._session_factory.session() as session:
            existing = session.scalar(select(ComposedAuthorityModel).where(ComposedAuthorityModel.composition_digest == composition.composition_digest))
            if existing: return self.get_by_id(existing.composition_id)
            runs = {
                item.id: item for item in session.scalars(
                    select(WorkflowRunModel).where(
                        WorkflowRunModel.id.in_(composition.member_workflow_run_ids),
                    )
                ).all()
            }
            if set(runs) != set(composition.member_workflow_run_ids):
                raise ValueError("composition contains an unknown workflow")
            if any(item.project_id != composition.project_id for item in runs.values()):
                raise ValueError("composition contains a cross-project workflow")
            extensions = session.scalars(select(AuthorityExtensionModel).where(
                AuthorityExtensionModel.extension_workflow_run_id.in_(
                    tuple(item for item in composition.member_workflow_run_ids
                          if item != composition.parent_source_workflow_run_id)
                )
            )).all()
            extension_by_run = {item.extension_workflow_run_id: item for item in extensions}
            for run_id in composition.member_workflow_run_ids:
                if run_id == composition.parent_source_workflow_run_id:
                    continue
                extension = extension_by_run.get(run_id)
                if extension is None or (
                    extension.project_id, extension.research_design_id,
                    extension.parent_source_workflow_run_id,
                ) != (
                    composition.project_id, composition.research_design_id,
                    composition.parent_source_workflow_run_id,
                ):
                    raise ValueError("composition extension lineage mismatch")
            session.add(ComposedAuthorityModel(composition_id=composition.composition_id, project_id=composition.project_id, research_design_id=composition.research_design_id, parent_source_workflow_run_id=composition.parent_source_workflow_run_id, selected_information_need_ids=list(composition.selected_information_need_ids), composition_version=composition.composition_version, composition_digest=composition.composition_digest, created_at=composition.created_at))
            session.flush()
            for run_id in composition.member_workflow_run_ids:
                session.add(ComposedAuthorityMemberModel(composition_id=composition.composition_id, workflow_run_id=run_id))
            return composition
    def get_by_id(self, composition_id):
        with self._session_factory.session() as session:
            model = session.get(ComposedAuthorityModel, composition_id)
            if not model: return None
            members = session.scalars(select(ComposedAuthorityMemberModel.workflow_run_id).where(ComposedAuthorityMemberModel.composition_id == composition_id)).all()
            return ComposedResearchAuthority(model.composition_id, model.project_id, model.research_design_id, model.parent_source_workflow_run_id, tuple(members), tuple(model.selected_information_need_ids), model.composition_version, model.composition_digest, model.created_at)
    def get_by_digest(self, composition_digest):
        with self._session_factory.session() as session:
            model = session.scalar(select(ComposedAuthorityModel).where(ComposedAuthorityModel.composition_digest == composition_digest))
            return self.get_by_id(model.composition_id) if model else None
    def get_latest_for_parent(self, project_id, parent_source_workflow_run_id):
        with self._session_factory.session() as session:
            model = session.scalar(
                select(ComposedAuthorityModel)
                .where(
                    ComposedAuthorityModel.project_id == project_id,
                    ComposedAuthorityModel.parent_source_workflow_run_id
                    == parent_source_workflow_run_id,
                )
                .order_by(
                    ComposedAuthorityModel.created_at.desc(),
                    ComposedAuthorityModel.composition_id.desc(),
                )
                .limit(1)
            )
            return self.get_by_id(model.composition_id) if model else None

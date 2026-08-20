from __future__ import annotations

import io
import unittest
from dataclasses import replace

from openpyxl import Workbook

from application.quantitative.dataset_import_service import QuantitativeDatasetImportService
from application.quantitative.quality_control import (
    CleaningEngine,
    DataQualityService,
    QuantitativeQualityError,
    assess_dataset_quality,
    build_cleaning_decision,
    build_cleaning_decision_set,
    build_questionnaire_snapshot,
    reconcile_quality_runs,
)
from domain.quantitative.quality import (
    ApprovalState,
    CleaningAction,
    DatasetQualityState,
    InterviewState,
    IssueType,
    ReconciliationState,
    RoutingConsequence,
    RoutingRule,
)
from domain.quantitative.dataset import DatasetFormat, DatasetVersionKind
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider


def workbook_bytes(headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class PropertyQBApprovedCleaningProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage()
        self.digest = Sha256DigestProvider()
        self.importer = QuantitativeDatasetImportService(
            importers=(XlsxOpenpyxlAdapter(),),
            storage=self.storage,
            digest_provider=self.digest,
        )
        self.qc = DataQualityService(storage=self.storage, digest_provider=self.digest)

    def imported(self, rows=None, dataset_id="qb"):
        rows = rows or [
            ["a", "YES", None, InterviewState.COMPLETED.value],
            ["b", "NO", "unexpected", InterviewState.SCREENED_OUT.value],
            ["c", "YES", "ok", InterviewState.PARTIAL.value],
        ]
        return self.importer.import_bytes(
            workbook_bytes(["id", "gate", "followup", "state"], rows),
            filename="synthetic.xlsx",
            dataset_format=DatasetFormat.XLSX,
            dataset_id=dataset_id,
            project_id="project-qb",
            run_id="run-qb",
            data_sheet="Data",
        )

    def snapshot(self, imported, *, complete=True, domain=("YES", "NO")):
        variables = {v.name: v.variable_id for v in imported.codebook.variables}
        rule = RoutingRule(
            "skip-followup", "1", variables["gate"], ("NO",),
            variables["followup"], RoutingConsequence.SKIPPED, "routing-fp-1",
        )
        return build_questionnaire_snapshot(
            snapshot_id="questionnaire-1",
            version="1",
            codebook_version_id=imported.codebook.codebook_version_id,
            question_variable_bindings=tuple((name, variable_id) for name, variable_id in variables.items()),
            answer_domains=((variables["gate"], domain),),
            required_variable_ids=(variables["followup"],),
            routing_rules=(rule if complete else replace(rule, target_variable_id="unknown"),),
            interview_state_variable_id=variables["state"],
            technical_id_variable_id=variables["id"],
            digest_provider=self.digest,
        )

    def qc_run(self, imported, snapshot=None, run_id="qc-1"):
        return self.qc.detect(
            dataset=imported.dataset_version,
            codebook=imported.codebook,
            questionnaire=snapshot or self.snapshot(imported),
            detection_run_id=run_id,
        )

    def decision(self, imported, action, refs, *, variables=(), transformation=(), rationale="approved reason"):
        return build_cleaning_decision(
            parent=imported.dataset_version,
            action=action,
            affected_refs=tuple(refs),
            variable_ids=tuple(variables),
            transformation=tuple(transformation),
            rationale=rationale,
            actor_id="manager-1",
            digest_provider=self.digest,
        )

    def decision_set(self, imported, decisions, state=ApprovalState.APPROVED):
        return build_cleaning_decision_set(
            parent=imported.dataset_version,
            decisions=tuple(decisions),
            approval_state=state,
            approver_id="manager-1" if state is ApprovalState.APPROVED else None,
            approved_at="2026-08-20T12:00:00Z" if state is ApprovalState.APPROVED else None,
            digest_provider=self.digest,
        )

    def test_a_to_h_qc_detection_routing_partial_screenout_and_pseudonyms(self):
        imported = self.imported(rows=[
            ["same", "BAD", None, InterviewState.COMPLETED.value],
            ["same", "NO", "must-skip", InterviewState.SCREENED_OUT.value],
            ["unique", "YES", "ok", InterviewState.PARTIAL.value],
        ])
        run = self.qc_run(imported)
        types = {issue.issue_type for issue in run.issues}
        self.assertIn(IssueType.OUT_OF_DOMAIN_VALUE, types)
        self.assertIn(IssueType.ROUTING_VIOLATION, types)
        self.assertIn(IssueType.REQUIRED_ANSWER_MISSING, types)
        self.assertIn(IssueType.DUPLICATE_RESPONDENT_ID, types)
        self.assertIn(IssueType.PARTIAL_INTERVIEW, types)
        self.assertFalse(any("same" in ref or "unique" in ref for issue in run.issues for ref in issue.affected_respondent_refs))
        screened = imported.analytical_respondent_ids[1]
        missing_issue = next(issue for issue in run.issues if issue.issue_type is IssueType.REQUIRED_ANSWER_MISSING)
        self.assertNotIn(screened, missing_issue.affected_respondent_refs)

    def test_c_incomplete_routing_is_not_evaluated(self):
        imported = self.imported()
        run = self.qc_run(imported, self.snapshot(imported, complete=False))
        self.assertIn("skip-followup", run.not_evaluated_rule_ids)

    def test_i_j_k_lineage_and_non_material_actions(self):
        imported = self.imported()
        engine = CleaningEngine(storage=self.storage, digest_provider=self.digest)
        for action in (CleaningAction.NO_ACTION, CleaningAction.INVESTIGATE):
            decision = self.decision(imported, action, ())
            self.assertIsNone(engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=self.decision_set(imported, (decision,))))

    def test_l_to_p_approval_rationale_exclude_set_missing_recode_and_replay(self):
        imported = self.imported()
        refs = imported.analytical_respondent_ids
        variables = {v.name: v.variable_id for v in imported.codebook.variables}
        with self.assertRaisesRegex(QuantitativeQualityError, "rationale"):
            self.decision(imported, CleaningAction.EXCLUDE_RESPONDENTS, (refs[0],), rationale="")
        exclusion = self.decision(imported, CleaningAction.EXCLUDE_RESPONDENTS, (refs[1],))
        draft = self.decision_set(imported, (exclusion,), ApprovalState.DRAFT)
        engine = CleaningEngine(storage=self.storage, digest_provider=self.digest)
        with self.assertRaisesRegex(QuantitativeQualityError, "not approved"):
            engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=draft)
        approved = self.decision_set(imported, (exclusion,))
        first = engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=approved)
        second = engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=approved)
        self.assertEqual(first, second)
        self.assertEqual(first.version_kind, DatasetVersionKind.CLEANED)
        self.assertEqual(self.storage.get_respondent_lineage(first.version_id), (refs[0], refs[2]))
        self.assertEqual(self.storage.get_parsed_rows(imported.dataset_version.version_id)[1][0], "b")

        set_missing = self.decision(imported, CleaningAction.SET_MISSING, (refs[0],), variables=(variables["gate"],))
        missing_child = engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=self.decision_set(imported, (set_missing,)))
        self.assertIsNone(self.storage.get_parsed_rows(missing_child.version_id)[0][1])
        recode = self.decision(imported, CleaningAction.RECODE, (refs[0],), variables=(variables["gate"],), transformation=(("from", "YES"), ("to", "NO")))
        recoded = engine.execute(parent=imported.dataset_version, codebook=imported.codebook, decision_set=self.decision_set(imported, (recode,)))
        self.assertEqual(self.storage.get_parsed_rows(recoded.version_id)[0][1], "NO")

    def test_q_r_conflicts_fail_closed(self):
        imported = self.imported()
        ref = imported.analytical_respondent_ids[0]
        variable = imported.codebook.variables[1].variable_id
        recode1 = self.decision(imported, CleaningAction.RECODE, (ref,), variables=(variable,), transformation=(("to", "A"),))
        recode2 = self.decision(imported, CleaningAction.RECODE, (ref,), variables=(variable,), transformation=(("to", "B"),))
        missing = self.decision(imported, CleaningAction.SET_MISSING, (ref,), variables=(variable,))
        for pair in ((recode1, recode2), (recode1, missing)):
            with self.assertRaisesRegex(QuantitativeQualityError, "conflicting"):
                self.decision_set(imported, pair)

    def test_material_unknown_respondent_is_rejected_as_no_op(self):
        imported = self.imported()
        decision = self.decision(
            imported,
            CleaningAction.EXCLUDE_RESPONDENTS,
            ("unknown-pseudonym",),
        )
        with self.assertRaisesRegex(QuantitativeQualityError, "unknown respondents"):
            CleaningEngine(storage=self.storage, digest_provider=self.digest).execute(
                parent=imported.dataset_version,
                codebook=imported.codebook,
                decision_set=self.decision_set(imported, (decision,)),
            )

    def test_s_t_w_changed_decision_parent_or_affected_set_changes_authority(self):
        imported = self.imported()
        refs = imported.analytical_respondent_ids
        one = self.decision_set(imported, (self.decision(imported, CleaningAction.EXCLUDE_RESPONDENTS, (refs[0],)),))
        two = self.decision_set(imported, (self.decision(imported, CleaningAction.EXCLUDE_RESPONDENTS, (refs[1],)),))
        self.assertNotEqual(one.fingerprint, two.fingerprint)
        other = self.imported(dataset_id="other")
        with self.assertRaisesRegex(QuantitativeQualityError, "stale"):
            CleaningEngine(storage=self.storage, digest_provider=self.digest).execute(parent=other.dataset_version, codebook=other.codebook, decision_set=one)

    def test_y_reconciliation_resolved_remains_new_and_superseded(self):
        imported = self.imported(rows=[["a", "BAD", None, "COMPLETED"], ["b", "YES", "ok", "COMPLETED"]])
        parent = self.qc_run(imported)
        same = self.qc_run(imported, run_id="qc-2")
        states = {item.state for item in reconcile_quality_runs(parent, same)}
        self.assertIn(ReconciliationState.REMAINS, states)
        clean_import = self.imported(rows=[["a", "YES", "ok", "COMPLETED"], ["b", "YES", "ok", "COMPLETED"]], dataset_id="clean")
        resolved = reconcile_quality_runs(parent, self.qc_run(clean_import, self.snapshot(clean_import), "qc-3"))
        self.assertIn(ReconciliationState.RESOLVED, {item.state for item in resolved})
        changed = self.imported(
            rows=[["a", "BAD", None, "COMPLETED"], ["b", "BAD", "ok", "COMPLETED"]],
            dataset_id="changed",
        )
        changed_states = {
            item.state
            for item in reconcile_quality_runs(
                parent,
                self.qc_run(changed, self.snapshot(changed), "qc-4"),
            )
        }
        self.assertIn(ReconciliationState.SUPERSEDED, changed_states)
        self.assertIn(ReconciliationState.NEW, changed_states)

    def test_z_rare_valid_category_is_not_qc_failure(self):
        rows = [[str(i), "YES" if i < 100 else "NO", "ok", "COMPLETED"] for i in range(101)]
        imported = self.imported(rows=rows, dataset_id="rare")
        run = self.qc_run(imported)
        self.assertNotIn(IssueType.OUT_OF_DOMAIN_VALUE, {issue.issue_type for issue in run.issues})

    def test_aa_to_ac_quality_assessment_authority(self):
        clean = self.imported(rows=[["a", "YES", "ok", "COMPLETED"]], dataset_id="approved")
        run = self.qc_run(clean)
        approved = assess_dataset_quality(dataset=clean.dataset_version, qc_run=run, manager_approved=True, approval_fingerprint="manager-approval", digest_provider=self.digest)
        self.assertEqual(approved.state, DatasetQualityState.QC_APPROVED)
        review = self.imported(rows=[["a", "BAD", "ok", "COMPLETED"]], dataset_id="review")
        self.assertEqual(assess_dataset_quality(dataset=review.dataset_version, qc_run=self.qc_run(review), manager_approved=False, approval_fingerprint=None, digest_provider=self.digest).state, DatasetQualityState.QC_REVIEW_REQUIRED)
        blocked = self.imported(rows=[["same", "YES", "ok", "COMPLETED"], ["same", "YES", "ok", "COMPLETED"]], dataset_id="blocked")
        self.assertEqual(assess_dataset_quality(dataset=blocked.dataset_version, qc_run=self.qc_run(blocked), manager_approved=False, approval_fingerprint=None, digest_provider=self.digest).state, DatasetQualityState.QC_BLOCKED)

    def test_ad_ae_no_desk_or_external_paths(self):
        import inspect
        import application.quantitative.quality_control as module
        source = inspect.getsource(module)
        for forbidden in ("InformationNeed", "EvidenceExpectation", "domain.sources", "openai", "tavily", "llm_client"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

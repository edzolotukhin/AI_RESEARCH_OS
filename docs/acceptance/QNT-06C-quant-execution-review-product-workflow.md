# QNT-06C — Quantitative execution and review product workflow

## Baseline and scope

- Branch: `acceptance/live-desk-research-01`.
- Baseline HEAD: `d7d6dde5d09901aea18147949df854a86b55057d` (QNT-06B remote-accepted).
- Scope is the canonical product path from an approved Analysis Design through execution, governed statistical authority, Findings, Insights, Report, Review, and an Approved Revision.
- No QNT-06D deliverable handoff, PDF/PPTX change, provider call, ARK path, or migration was added.

## Product workflow

- The owner-scoped quantitative product service now exposes execution only for the current exact approved Analysis Design and its immutable dataset binding.
- The analysis UI exposes `Виконати аналіз` only when the canonical study is eligible.
- Execution delegates to the existing design-aware quantitative workflow; it does not duplicate statistical calculation, Findings/Insights validation, Review, or approval rules.
- When the established semantic-authorization boundary is reached, the UI presents the exact persisted authorization token. Stale or mismatched tokens fail closed; successful authorization resumes the same run through the worker path.
- The Results page projects the canonical Review verdict and issues and, only after approval, the immutable Approved Revision identity and source bindings.
- Legacy/non-canonical studies cannot use this canonical execution action.

## Authority and integrity preservation

- QNT-02 remains authoritative for dataset/result identities and statistical values.
- QNT-03 Findings and Insight validators remain authoritative; the product layer does not fabricate or override semantic output.
- QNT-04 remains authoritative for deterministic Review and Approved Revision persistence.
- QNT-06B continues to enforce owner scope, current-design approval, exact source binding, and fail-closed product readiness.
- The resumed worker service now retains the protected canonical Review pin; without it the recovered workflow could complete semantic stages without running the accepted Review boundary.

## Provider-free compatibility remediation

- The deterministic acceptance Report adapter now emits the bounded author fields appropriate to the prompt contract it receives: the historical QK-V1 payload remains compatible, while design-aware QK-3 leaves fingerprints, numeric/result references, and analytical context to canonical derivation.
- QK-3's declared output schema now includes `LIMITATIONS`, matching both its existing parser/domain enum and QNT-04's requirement that accepted limitation Insights appear in a limitation section.
- A regression proves a governed exact-context limitation Insight can form a supported QK-3 `LIMITATIONS` section. The change does not weaken numeric, lineage, context, causality, PII, or support validation.

## Activity and authorization

- Execution, semantic authorization, Review, and Approved Revision continue through the existing persisted workflow and project-activity mechanisms.
- Owner scoping is enforced for read and command paths. Unknown, foreign, legacy, unapproved-design, and stale-authorization requests fail closed.
- No direct database editing, state fabrication, or authorization bypass was used.

## Verification

- Focused QNT-06C/QJ/QK/QNT-04/QNT-06B/worker/structured-output group: `114 passed`; additionally `77 subtests passed`; `0 failed`, `0 errors`.
- Narrow post-remediation compatibility gate: `5 passed`; `0 failed`, `0 errors`.
- PostgreSQL integration (`test_qnt03_post_analysis.py`, `test_qnt02_method_pin.py`) against a dedicated disposable PostgreSQL 16 database: `6 passed`; `0 failed`, `0 errors`.
- Earlier expanded offline adversarial and Desk/shared regression gate: `134 passed`; additionally `95 subtests passed`; `0 failed`, `0 errors`.
- Compilation and `git diff --check`: passed (only the repository's Windows line-ending notices for two HTML templates).
- Canonical full offline suite (`python run_tests.py`), executed once after the final fix: `3155 total`; `2996 passed`; `159 skipped`; `0 failures`; `0 errors`.

The disposable `qnt06c-postgres-final` container was removed after verification. No historical container, database, volume, fixture, or untracked acceptance artifact was modified.

## Remaining boundary

- This phase establishes the product execution/review workflow; QNT-06D deliverable integration remains outside scope.
- No provider-backed quantitative generation was exercised or required. Acceptance is deterministic and provider-free.

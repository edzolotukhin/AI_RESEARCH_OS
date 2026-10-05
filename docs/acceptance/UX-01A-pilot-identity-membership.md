# UX-01A — Local acceptance evidence

## Baseline

- Branch: `acceptance/live-desk-research-01`
- Initial HEAD: `602ad025fbb38e2c5d1a1d8e9f60f1cbd886960a`
- Initial divergence: `0/0`
- Previous exact remote workflow: GitHub Actions run `37299510497`, successful.
- Initial Alembic head: `022_qua04_report_deliverables`.

## Implemented boundary

- Individual active/disabled User with salted scrypt password verifier.
- Opaque, hashed, persisted 12-hour browser session; logout and disable revocation.
- Login, account, logout, pilot-user administration, and OWNER membership UI.
- OWNER/RESEARCHER/VIEWER enforced from current server-side membership.
- Server-side project filtering and project-derived route/service authorization.
- PostgreSQL-atomic Project + first OWNER + creation Activity.
- Explicit legacy-project bootstrap allowlist; no automatic broad grant.
- Request-derived human actor carried into existing governance and Activity fields.
- Existing service bearer authentication preserved and absent from browser output.
- SameSite/HttpOnly cookies, production Secure default, same-origin mutation check, bounded login throttle.

## Focused evidence

- Compile validation: passed.
- Identity/session/auth/project/activity compatibility group: `53 passed`.
- Desk/Quant/Qual/download/browser focused group: `84 passed`.
- PostgreSQL UX-01A E2E: `2 passed`:
  - Alice login → Project → atomic OWNER;
  - Bob added as RESEARCHER and performs Qual activation;
  - `QUAL_RUN_CREATED.actor_id` is Bob's User ID;
  - Bob demoted to VIEWER and mutation denied;
  - membership removed and access denied;
  - Alice's persisted session and membership survive application-container restart;
  - invalid first-owner FK rolls back the Project transaction.
- Migration smoke: `1 passed`: base → 023 → base → 023, final identity tables present.
- Invalid credentials, disabled login/session, expiry, forgery, logout replay, cross-origin mutation, missing/foreign membership, guessed output/download path, stale role, stale membership, non-owner membership administration, and last-owner protection are covered by focused tests.

## Research and authority compatibility

UX-01A changes actor and access resolution only. Desk Evidence, Quant Dataset, Qual Transcript, Findings, Insights, Review, Approved Revision, Report, and immutable deliverable authority are unchanged. AI origin is not replaced by human attribution. Browser-facing Qual nested resources include `project_id` and resolve records within that project; Quant studies resolve to their Project; project outputs and PDF/PPTX paths authorize the Project before source/artifact lookup.

## Migration and data preservation

- New head: `023_ux01a_identity_membership` (single head).
- No legacy Project was assigned automatically.
- No historical research row was rewritten.
- Downgrade with identity data is deliberately refused.
- Disposable databases: `ux01a_test`, `ux01a_migration_test`; they contain synthetic acceptance data only.

## Final gates

The first canonical run executed `3200` tests and exposed two gate-expectation conflicts: the readiness test still named head 022, and the JSON architecture scanner traversed the preserved untracked third-party `node_modules` tree. No runtime/product test failed. The migration expectation was advanced to legitimate head 023 and the scanner now excludes dependency/VCS/virtual-environment trees while continuing to scan repository production Python. Both affected tests then passed `2/2`.

The permitted post-fix canonical run completed:

- total: `3200`;
- passed: `3035`;
- skipped: `165`;
- failures: `0`;
- errors: `0`.

No OpenAI, Tavily, AssemblyAI, ARK, or live research call was required or performed by UX-01A.

## Limitations

See the architecture record for deferred enterprise IAM and pilot operational limits. Password reset/change is operator-managed. The login throttle is per process. Cross-origin browser APIs are not supported. Historical Activity remains honestly unattributed unless an original actor was already persisted.

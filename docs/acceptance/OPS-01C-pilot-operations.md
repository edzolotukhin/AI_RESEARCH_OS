# OPS-01C — Pilot operations acceptance

## Baseline and scope

Baseline `c6edcbafc7a42ab3cd9e22916f8be5822b98ac02` on `acceptance/live-desk-research-01`, initially 0/0 with clean tracked/index state. Alembic had one head, `023_ux01a_identity_membership`; migration 024 was absent. Historical untracked acceptance/runtime artifacts were preserved.

The audit and O1/O2/O3/O4 classification are recorded in the architecture record. The implementation is read-only and uses the accepted pilot administrator identity, readiness query, persisted jobs, OPS-01B backup policy, bounded filesystem capacity checks, and provider policy. It performs no provider call and exposes no research payload.

## Deterministic and authorization evidence

- OPS-01C status and UI tests: 8 passed initially; final focused group included all OPS-01C cases.
- Existing identity/product-shell/health regression: 19 passed.
- Fixtures cover healthy, worker stale/unavailable, stale job, failed job, backup overdue, storage critical, provider disabled, repeated provider failure, and sanitized monitoring failure.
- Unauthenticated access redirects to login; non-admin researcher access is server-denied; only `PILOT_ADMIN_USER_ID` sees the secondary Operations link.

## Graphical evidence

PASS using cached `mcr.microsoft.com/playwright:v1.62.1-noble` (`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`). Disposable Chromium rendered Healthy, Attention, and Critical fixtures and a Critical 820×1000 viewport. Assertions covered overall prominence, failed/stale jobs, overdue backup, 94% critical storage, policy-disabled transcription, bounded failure detail, and no horizontal overflow. Server-side OWNER/operator access and RESEARCHER/VIEWER denial are covered by UI integration tests. No P0/P1 remained; no screenshot was retained.

## Regression and final gate

Focused OPS-01A/OPS-01B and bounded Desk/Quant/Qual/Outputs/Activity regression, including OPS-01C: **70 passed plus 18 subtests**. An earlier equivalent selection before the final VIEWER denial assertion passed 62 plus 18 subtests. The backup creation/encryption/verification contracts and pilot Compose health/private-PostgreSQL/bounded-log contracts remained green.

The single final canonical `python run_tests.py` suite passed: **3,233 total; 3,068 passed; 165 skipped; 0 failures; 0 errors**. No OpenAI, Tavily, AssemblyAI, or other live provider call was made. Alembic remained the single head `023_ux01a_identity_membership`; migration 024 remained absent.

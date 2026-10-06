# UX-01D — Pilot onboarding, contextual help and feedback

## Baseline and audit

Baseline was `613fee93ea05c76a3d5f6e9c885343b4e148bac0` on `acceptance/live-desk-research-01`, matching upstream at 0/0 with a clean tracked tree/index. Alembic had one head, `023_ux01a_identity_membership`; migration 024 was absent; initial `git diff --check` passed. Existing historical untracked acceptance/runtime artifacts were left untouched.

First-use audit found U1/U2 friction: no compact product orientation on Projects, role labels on the list were technical, method prerequisites were implicit, VIEWER relied on missing buttons, Review/Approved Version/Outputs required verbal explanation, and Help/Feedback were not discoverable. High-value U3 additions cover insufficient-evidence refusal, structured Quant input, transcript/audio/privacy choices, and recoverable feedback failure. U4 analytics, tours, admin ticket UI, method tutorials, and mobile redesign remain deferred.

## Implemented behavior

- Dismissible, non-blocking Projects welcome panel; dismissal is browser-local presentation state.
- Direct-page method guidance for Desk, Quant and Qual, plus explicit VIEWER read-only notice.
- Concise Help surface covering start, methods, safe Desk refusal, Review, Approved Version, Outputs, privacy and feedback.
- Project Outputs explain PDF/PPTX as deliverables from the approved research state.
- Feedback is authenticated, bounded to four categories and 20–2000 plain-text characters, secret-pattern checked, whitespace-normalized and safely template-escaped.
- Captured context is limited to authenticated user ID, timestamp, safe UI route, and authorized project ID/role. No research payload, DOM, screenshot, attachment, dataset row, transcript/audio, evidence excerpt, respondent metadata, pseudonym map, token or provider payload is automatically captured.
- The pilot-safe sink is the existing structured operational log, not Activity. Sink failure returns 503, retains the typed message and presents retry guidance. No migration or support-ticket system was introduced.

## Verification

Focused UX/authorization/integration plus bounded identity, membership, OPS, Desk Activity, Quant, Qual, approval and Outputs regressions: 46 passed before the two final authorization additions; the final focused UX-01D module is recorded with the final command evidence below.

Graphical acceptance used cached `mcr.microsoft.com/playwright:v1.62.1-noble` (`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`). Disposable Chromium inspected Login, first-use and returning Projects, Overview with all three method hints, Outputs, Help, feedback form/success/failure, VIEWER, and 820×1000 Help. Eleven screenshots were inspected; no horizontal overflow, clipped primary action, P0 or P1 remained. Screenshots and temporary launcher/server are removed during cleanup; image remains cached.

Architecture-language review found no new researcher-facing leakage of authority, projection, adapter, orchestration, materialization or currentness. Professional research terms remain. Existing legacy surfaces outside the UX-01D guidance scope are not redesigned.

## Final evidence

- Focused UX-01D tests: 8 passed
- Bounded shared regressions: 46 passed
- Canonical suite: 3241 total, 3076 passed, 165 skipped, 0 failures, 0 errors
- Final Alembic: single head `023_ux01a_identity_membership`; migration 024 absent
- Final diff check: passed; commit evidence is reported after creation

No OpenAI, Tavily, AssemblyAI or live research call was made.

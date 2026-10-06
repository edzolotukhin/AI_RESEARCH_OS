# UX-01C — Method workflow simplification acceptance

## Baseline and environment

- Branch: `acceptance/live-desk-research-01`
- Starting/local remote HEAD: `782e70cb4939fe6466dc1bf82eb6e6f243f43edc` (`0/0`)
- Alembic: single head `023_ux01a_identity_membership`; migration 024 absent
- Browser: `mcr.microsoft.com/playwright:v1.62.1-noble`
- Image ID: `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`
- Chromium: `/ms-playwright/chromium-1234/chrome-linux64/chrome`
- Environment: disposable in-memory API on loopback with synthetic identities and research material; no live providers or participant data

## Graphical evidence

Real Chromium rendered and inspected a synthetic initial Qual run, a mature persisted Qual run, OWNER and VIEWER sessions, refresh/direct-open resume, accepted Quant overview, accepted Desk start surface, and an `820 × 1000` Qual viewport.

The mature fixture covered prepared transcripts, transcript provenance, corpus, codebook/coding, themes with supporting and deviant evidence, accepted Finding/Insight, human Review, Approved Version, final report, and canonical Outputs link. The initial fixture covered the empty prerequisite state. Privacy-blocked audio was inspected through the rendered source-choice guidance: it explains the policy restriction as a protective state and points to prepared DOCX/TXT without weakening fail-closed provider policy. Invalid upload remains server-validated; no raw error or fake audio metadata was introduced.

Desk and Quant retained their accepted visual families and showed no UX-01C regression. No horizontal overflow occurred at the narrow viewport. VIEWER saw the derived state and authorized content without the report-creation mutation CTA; server-side authorization remains authoritative.

## Defects and corrections

Two P1 defects were found during graphical inspection:

1. Derived CTA fragments did not all resolve to real section anchors. Stable anchors were added.
2. Source guidance described audio and prepared transcript as equal and did not explain the privacy block. Prepared DOCX/TXT is now the recommended normal path; audio is an explicit policy-dependent alternative.

Both affected surfaces were re-rendered. No P0 or unresolved P1 remains. Long specialist controls and mixed Ukrainian/English research labels are retained as P2 because they reflect existing method workspaces and are outside this focused phase.

## Verification

- Pre-existing derivation evidence: 4 passed
- Pre-existing shell/Qual lifecycle/output evidence: 19 passed
- Post-correction focused UX-01C test: 5 passed
- Combined Qual, shell, identity/security, Outputs, Activity, Quant weighting, and Desk integrity regression: 67 passed
- Graphical gate: PASS
- First canonical run: 3,225 total; 3,059 passed; 165 skipped; 1 failure caused solely by the two task-owned temporary preview launchers being discovered by the FastAPI import boundary test. The launchers and screenshots were removed, and the exact architecture test passed 1/1.
- Final post-cleanup canonical suite: 3,225 total; 3,060 passed; 165 skipped; 0 failures; 0 errors

Interaction burden changed from manual lifecycle inference and source ambiguity to an explicit stage, completed work, one primary action, recommended prepared-transcript path, resume derivation, and direct Review/Outputs handoffs. Desk and Quant required no UX-01C changes.

Temporary screenshots and launchers are acceptance-only and must be removed after this record is finalized. The Playwright image remains cached. No push or deployment is part of UX-01C local acceptance.

# OPS-01B — Local acceptance evidence

## Baseline

- Branch `acceptance/live-desk-research-01`; initial HEAD `ca2ac9041fc4be65b5d93a688f75386d1edc82ad`; divergence `0/0`.
- OPS-01A exact GitHub Actions run `37339633809` completed successfully.
- Alembic single head: `023_ux01a_identity_membership`.

## Implemented controls

- restic encrypted snapshot tooling around consistent custom-format `pg_dump`, protected/project storage, bounded manifest, integrity check, age status, and 14-daily/8-weekly retention.
- Restore requires an empty database/storage and explicit disposable confirmation; it verifies SHA/head/checksums and revokes restored browser sessions.
- Participant-data external transcription is disabled by default and cannot be enabled by credentials alone.
- Qual TXT/DOCX/audio and Quant SAV/XLSX are validated before persistence; unsafe filename paths, malformed/mismatched content, and unsafe DOCX archives fail closed.

## Executed evidence

### Encrypted backup and independent copy

- Source Compose project: `ai_research_os_ops01b_source`; PostgreSQL, API, and worker were healthy with zero restarts.
- Representative synthetic authority: project `ops01b-recovery-project`, OWNER membership, two Project Activity events, approved Desk report `ops01b-approved-report`, one protected artifact, immutable PDF, and worker-generated PPTX.
- The fake off-host repository was a separate host path mounted only at `/offhost`; it was not a source PostgreSQL/protected/project volume.
- Encrypted restic backup ID `pilot-20261005T173502Z`; snapshot `233e483ddb004db013985df28af0cc3e31b9f8709d6e1c6c43deb9b0c8d97ec0`.
- The backup command, including one-time recovery-image build and repository initialization, completed within 17.4 seconds. Subsequent status reported the snapshot within the 24-hour policy.
- Full repository verification passed with `restic check --read-data`. Retention completed with 14 daily and 8 weekly recovery points.

### Clean isolated restore

- Restore Compose project: `ai_research_os_ops01b_restore` with separately named PostgreSQL, protected-data, project-data, staging volumes, and backend network.
- The target PostgreSQL public schema and both target file stores were empty before restore. The first attempt safely stopped while PostgreSQL was still initializing; no restore occurred. After the target became healthy, the same deterministic command completed.
- Restore used only the encrypted off-host repository, separately supplied recovery credential, repository/deployment definition, and runtime configuration. It did not mount any source-authority volume.
- Restore duration: 2.686 seconds. Restored application SHA: `ca2ac9041fc4be65b5d93a688f75386d1edc82ad`; restored Alembic head: `023_ux01a_identity_membership`.
- Restored PostgreSQL, API, and worker were healthy. All restored active browser sessions were revoked (`0` remained active).
- Fresh owner authentication succeeded; OWNER membership and project visibility were retained; the unrelated synthetic user was denied both membership and deliverable access.
- The approved report and two Project Activity events were visible through application read services.

### Exact immutable recovery evidence

| Artifact | Source SHA-256 | Restored SHA-256 | Result |
| --- | --- | --- | --- |
| Protected research file | `20ae3c55cad6312e34cc59c1c795f102d89c21b6290555cce39ae86a18b0f5ce` | `20ae3c55cad6312e34cc59c1c795f102d89c21b6290555cce39ae86a18b0f5ce` | exact |
| PDF | `0bd73203cf3eb23813012b27492a484757a96a8bc56e42be8c84b286fc069090` | `0bd73203cf3eb23813012b27492a484757a96a8bc56e42be8c84b286fc069090` | exact |
| PPTX | `336c35b79de376b9b947f14d00123a4a7cc897880da1a2443412ea540c899dad` | `336c35b79de376b9b947f14d00123a4a7cc897880da1a2443412ea540c899dad` | exact |

### Privacy, upload, and regression evidence

- No live OpenAI, Tavily, or AssemblyAI calls occurred; only fictional identities/content were used.
- Missing recovery credential, missing protected storage, subprocess/`pg_dump` failure, non-empty restore target, unsafe filenames, malformed/path-traversing DOCX, extension/signature mismatch, and malformed audio are covered by fail-closed tests with content-safe errors.
- Participant audio transfer remains disabled unless the explicit policy gate is enabled; prepared TXT/DOCX remains provider-free.
- Focused OPS/identity/Qual/Quant/Desk regression: 68 passed, 0 failed/errors.
- The first canonical run executed 3,217 tests and exposed one architecture-only failure: `tools/pilot_recovery.py` used direct JSON decoding outside the repository's canonical validator. The recovery tool was corrected to use `JsonValidator`; the exact architecture test plus recovery safety tests then passed 10/10.
- Final post-fix canonical offline suite: 3,217 tests run; 3,052 passed; 165 skipped; 0 failures; 0 errors. No provider credentials or calls were used.

## Acceptance conclusion

- The isolated drill proved encrypted independent backup, clean restore, application-level authority and authorization, and byte-exact recovery of protected/PDF/PPTX artifacts.
- Observed restore time was 2.686 seconds; verification after service startup completed in under 14 seconds. The pilot objective is nightly backups (RPO up to one backup interval); practical RTO additionally depends on host provisioning, image availability, repository size, and operator validation.
- DATA-SAFETY pilot gate: `DATA_SAFETY_PILOT_GATE_PASSED`.
- Remaining P0 before real-data pilot: configure and verify the real off-host destination and separately held recovery credential; complete production monitoring/operator visibility and real-server DNS/TLS/firewall validation.
- Remaining P1: simplified navigation/onboarding/help/feedback and routine repeat restore drills.
- Deferred: centralized compliance tooling, malware scanning service, automated legal retention workflow, multi-host HA, and OPS-01C monitoring.

## OPS-01B-R1 remote PostgreSQL integration closure

- The first exact remote workflow for commit `66061e0636b5893f06570e6d1b9ff3c84ce34379`, GitHub Actions run `37353642419`, failed in step 14, `PostgreSQL integration tests`. The failed remote run remains the historical CI result; it has not been rewritten or rerun as part of this local correction.
- CI executes `python -W error::ResourceWarning -m unittest discover -s tests/integration/postgresql -p "test_*.py" -v` against disposable PostgreSQL 16 test and migration databases. Direct remote job-log download was unavailable in this environment (GitHub returned HTTP 403 and no authenticated GitHub CLI was available), so the exact group was reproduced locally with tracked repository files and CI-equivalent PostgreSQL configuration.
- The first broken transition was qualitative audio artifact upload in `tests.integration.postgresql.test_qua01_qualitative_e2e.Qua01PostgresqlE2E.test_audio_is_processed_by_existing_worker_loop`. The stale fixture `RIFFfixture` no longer satisfied the accepted OPS-01B WAV contract (`RIFF` plus the `WAVE` form marker); upload correctly failed closed, and the test subsequently raised `KeyError: 'artifact_id'`.
- Root-cause classification: stale PostgreSQL integration fixture exposed by the intended OPS-01B upload-hardening contract, not a production upload-validation defect. The fixture now contains the minimum structurally valid synthetic WAV header. No security check, provider-isolation rule, application behavior, or migration was weakened.
- Two PDF failures seen during the initial local reproduction were environment-only: the local process lacked CI's configured font. With the CI-equivalent `PDF_FONT_PATH`, both passed and were unrelated to the remote qualitative fixture failure.
- Post-fix exact failing test: 1 passed. PostgreSQL repository contracts: 37 passed. Focused OPS-01B and qualitative authority/API tests: 20 passed. Final exact PostgreSQL integration group: 164 tests run, 163 passed, 1 skipped, 0 failures/errors.
- One canonical post-fix offline suite was run: 3,217 tests; 3,052 passed; 165 skipped; 0 failures; 0 errors. No OpenAI, Tavily, AssemblyAI, or other live provider call occurred.

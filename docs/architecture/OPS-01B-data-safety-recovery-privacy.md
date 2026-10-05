# OPS-01B — Data safety, recovery, and privacy

## Recovery authority inventory

Canonical recovery state is PostgreSQL plus `pilot_protected_data`. PostgreSQL contains users, password hashes, memberships, projects, method configuration/state, Desk authority, Quant metadata, Qual artifacts/transcripts/coding/themes, Findings, Insights, Reviews, Approved Revisions, reports, immutable PDF/PPTX bytes, Activity, and durable jobs. Quant raw files, parsed rows, protected respondent bindings, lineage, and manifests live in `pilot_protected_data`. `pilot_project_data` is retained as a compatibility boundary and is included even when empty.

Operational but non-research authority includes Caddy ACME state and container logs. Caddy certificates are environment-specific and regenerable; they are not included in research recovery snapshots. Images, caches, temporary uploads, build products, and active browser sessions are regenerable/disposable. Deployment recovery uses the accepted Git SHA, this Compose definition, migration head, and a separately supplied non-secret profile. Runtime and provider secrets are never included.

## Backup architecture

The supported tool is restic, using its authenticated encryption, snapshot, repository-check, retention, and remote-backend support. PostgreSQL is captured with `pg_dump --format=custom`; copying a live PGDATA directory is prohibited. Protected and compatibility storage are copied into encrypted snapshot input after the logical dump and verified with SHA-256 inventory before restic commits the snapshot. This is not a distributed transaction: the pilot consistency boundary is database dump followed by immutable protected-file capture. A backup fails if required storage is unavailable or any captured checksum cannot be represented.

`RESTIC_REPOSITORY` is backend-neutral and may reference a restricted S3-compatible bucket, SFTP repository, REST server, or operator-approved remote filesystem. The local acceptance repository is a separate disposable boundary and never source authority. The restic password file is mounted read-only at runtime. Its disaster-recovery copy must be held separately from both pilot host and backup repository, for example in the operator's approved password manager plus an offline recovery escrow. The credential is never committed, backed up, or logged.

Each snapshot contains a bounded JSON manifest: backup id/time, exact application SHA, Alembic head, deployment profile, PostgreSQL client version, authority classes, PostgreSQL dump checksum, and protected/project file checksums. Research content is not printed. Snapshot identity is returned by restic after commit. Repository integrity and actual restore remain separate gates.

## Schedule, retention, RPO/RTO

Run nightly in the pilot server timezone and before migration or destructive maintenance. After a successful snapshot and integrity check, retain 14 daily and 8 weekly points. Pruning is not run after a failed backup. `status` exposes latest snapshot id, timestamp, age, and 24-hour policy state for OPS-01C monitoring.

The intended RPO is one successful nightly interval, plus a pre-release checkpoint. No formal RTO is promised: it depends on database/protected-data size, remote bandwidth, clean-host provisioning, and verification. The acceptance record reports observed synthetic restore time.

## Restore semantics

Restore requires `RESTORE_CONFIRMATION=DISPOSABLE_EMPTY_TARGET`, an empty PostgreSQL public schema, and empty protected/project targets. It verifies application SHA, Alembic head, dump checksum, and every protected-file checksum before restoring. It cannot overwrite an active pilot authority by default. Restored browser sessions are revoked; identities and memberships survive, but users must authenticate again. Completed/failed jobs retain canonical state. Existing lease expiry/fencing governs queued or formerly leased work; operators must keep worker stopped until database/storage and compatibility checks pass.

After catastrophic loss, rotate database, application/session/CSRF, provider, and service credentials before reopening. Preserve the backup decryption credential until recovery and repository verification complete; rotate it only through a deliberate restic repository/key procedure.

## Privacy classes and provider transfer

| Class | Examples | Storage/access | Provider transfer | Retention/deletion |
|---|---|---|---|---|
| 0 Public | public Desk sources | project authority; members | search queries/public context permitted | project policy |
| 1 Internal | designs, plans, internal reports | PostgreSQL; project members | only configured workflow purpose | project policy |
| 2 Confidential Research | datasets, findings, transcripts, coding | PostgreSQL/protected volume; members | bounded configured processing, no raw Quant rows | approved project purpose |
| 3 Participant/Personal | audio, identifiers, pseudonym bindings | protected/PostgreSQL; least privilege | denied by default; explicit operator gate required | shortest approved study period |

Backups inherit Class 3, are encrypted, access-restricted, non-public, and operator-restored. Logs contain safe IDs, counts, states, sizes, hashes, and error categories—not dataset rows, transcripts, participant identity, audio, prompts, credentials, or backup filenames where sensitive.

Desk may transfer bounded queries and public-source context to configured providers. Deterministic Quant numerical authority never transfers respondent-level rows to an AI provider. Prepared Qual DOCX/TXT remains provider-free. Audio transcription is blocked unless `ALLOW_PARTICIPANT_DATA_EXTERNAL_TRANSCRIPTION=1`; credentials alone do not grant participant-data transfer and no silent provider fallback exists.

## Upload and deletion policy

All upload filenames are bounded metadata, never paths. Quant keeps 20 MiB, 10,000-row, 200-variable, and 100,000-cell limits; SAV/XLSX signatures must match extensions and XLSX archive expansion remains bounded. Qual validates UTF-8 TXT, bounded safe DOCX OOXML, supported audio signatures, and size limits before persistence. Client MIME is advisory. Rejected content is not persisted, so no failed-upload cleanup artifact remains.

Project hard deletion is intentionally not added: immutable research provenance and cross-store protected files need a separately designed, auditable destructive workflow. Until then, removal means access revocation/retention expiry under operator procedure, with a verified recent backup before any future destructive maintenance.

No migration is introduced. The accepted schema remains `023_ux01a_identity_membership`.

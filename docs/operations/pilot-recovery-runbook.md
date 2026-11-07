# Pilot backup and disaster recovery runbook

## Normal backup

Install/use the repository recovery image through `docker-compose.pilot.backup.yml`. Keep the restic credential outside Git, outside the backup repository, and retain a recovery copy away from the pilot host.

Set exact `APP_SHA`, the actual pre-migration `ALEMBIC_HEAD=028_research_authority_extension`, remote `RESTIC_REPOSITORY`, and `RESTIC_PASSWORD_FILE_HOST`. The migration head in the backup manifest must describe the database being backed up; do not use the future release head for this checkpoint. Then run:

```text
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery create
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery check --full
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery status
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery retention
```

Schedule `create`, then `check`, then `retention` nightly in the server timezone. Alert on nonzero exit or `within_24h_policy=false`. Run and verify an additional snapshot before migrations or destructive maintenance.

The recovery command reads the live PostgreSQL database and both persistent file stores. It does not restart application services, but it creates an ephemeral recovery container, writes staging data and a restic snapshot, runs a bounded integrity check, and updates `backup-status.json`. The database dump and file copies are not one distributed transaction; quiesce research writes when a cross-store consistency checkpoint is required.

Never rely on the Compose fallback for `ALEMBIC_HEAD`; provide it explicitly in the shell environment. Confirm the source database reports `028_research_authority_extension` before creating the pre-migration checkpoint.

## Isolated restore drill

The production backup Compose file is not a restore-drill configuration: it joins `pilot_backend` and mounts production volumes. Use the repository-side `docker-compose.recovery-drill.yml` with `.env.recovery-drill` copied from `.env.recovery-drill.example` as an operator-only environment file. `RESTIC_REPOSITORY` must be a remote repository URI reachable from inside the recovery container; an arbitrary host filesystem path is not valid because this drill deliberately has no host repository bind mount. The drill defines a separate PostgreSQL 16 service, database volume, protected/project/work/runtime volumes, and a project-scoped private network. It has no host ports and no production volume or network references.

Prepare only disposable targets and set:

```text
APP_SHA=<exact application SHA from the backup manifest>
ALEMBIC_HEAD=028_research_authority_extension
RESTORE_CONFIRMATION=DISPOSABLE_EMPTY_TARGET
```

After a fresh backup and repository integrity check, start the disposable PostgreSQL target and confirm that it is healthy and empty. Then run exactly:

```bash
docker compose --project-name airos-recovery-drill \
  --env-file .env.recovery-drill \
  -f docker-compose.recovery-drill.yml \
  up -d recovery-postgres

docker compose --project-name airos-recovery-drill \
  --env-file .env.recovery-drill \
  -f docker-compose.recovery-drill.yml \
  run --rm recovery restore <verified-snapshot-id>
```

Do not combine this restore command with `docker-compose.pilot.yml` or `docker-compose.pilot.backup.yml`. The recovery tool refuses non-empty database/storage targets, verifies the manifest SHA and Alembic head, validates PostgreSQL/protected/project checksums, then restores the dump and files. Keep API and worker stopped during the drill; validate the restored database and revision before any application startup. Cleanup is limited to the disposable Compose project, containers, network and volumes and requires separate authorization.

Required gates are: fresh backup, repository integrity, isolated empty-target restore, revision-028 verification, representative application read checks, and retained evidence. A successful backup alone does not authorize migration 029.

## Total-host-loss restore

1. Keep the lost host and all old authorities offline.
2. Provision a clean supported Linux host with encrypted storage and the exact accepted Git SHA from the manifest.
3. Obtain the recovery credential from separate custody. Do not copy it into Git or the backup repository.
4. Configure an empty PostgreSQL database and empty protected/project volumes under a distinct Compose project.
5. Keep API, worker, and proxy stopped. Set `RESTORE_CONFIRMATION=DISPOSABLE_EMPTY_TARGET` and run `recovery restore <snapshot-id>`.
6. Confirm the tool reports matching application SHA, migration head, PostgreSQL dump checksum, and protected-file inventory. Active browser sessions are revoked by restore policy.
7. Start API only; verify PostgreSQL and `/ready`, then login with a real user credential and verify project membership, method authority, Activity, Approved Revision, and immutable output hashes.
8. Start worker only after restored job/lease state is reviewed. Verify worker health and that no stale lease causes duplicate execution.
9. Rotate database, CSRF/session, service, and provider credentials. Do not rotate the restic decryption credential until restore and repository integrity are complete.
10. Open access only after authorization denial for an unrelated user and artifact byte checks pass.

Stop if the target is non-empty, manifest SHA/head differs, repository check fails, any required protected file is missing, or application-level authorization/data checks fail. Never repair canonical data manually to make a drill pass.

## Retention and data handling

Policy is 14 daily and 8 weekly snapshots. Backup storage is Class 3. Restrict repository listing and restore credentials to operators. Do not log research filenames/content. Project deletion is deferred until an auditable cross-store deletion capability exists; access revocation and documented retention expiry are the current safe controls.

External audio transcription remains disabled unless participant-data transfer is explicitly approved and `ALLOW_PARTICIPANT_DATA_EXTERNAL_TRANSCRIPTION=1` is set. Prepared DOCX/TXT transcripts remain the preferred provider-free pilot path.

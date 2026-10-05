# Pilot backup and disaster recovery runbook

## Normal backup

Install/use the repository recovery image through `docker-compose.pilot.backup.yml`. Keep the restic credential outside Git, outside the backup repository, and retain a recovery copy away from the pilot host.

Set exact `APP_SHA`, `ALEMBIC_HEAD=023_ux01a_identity_membership`, remote `RESTIC_REPOSITORY`, and `RESTIC_PASSWORD_FILE_HOST`. Then run:

```text
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery create
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery check --full
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery status
docker compose --env-file .env.pilot -f docker-compose.pilot.yml -f docker-compose.pilot.backup.yml --profile operations run --rm recovery retention
```

Schedule `create`, then `check`, then `retention` nightly in the server timezone. Alert on nonzero exit or `within_24h_policy=false`. Run and verify an additional snapshot before migrations or destructive maintenance.

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

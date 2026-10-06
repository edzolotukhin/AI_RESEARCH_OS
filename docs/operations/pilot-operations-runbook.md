# Pilot operations runbook

## Daily check

As the configured pilot operator, open **Account → Operations** once daily (about 2–5 minutes). Confirm the environment label, overall status, API/database/worker, stale or failed jobs, backup freshness, storage, and provider warnings. Refresh once if a timestamp is unexpectedly old.

## Status meanings

- **Healthy:** the known check is within policy.
- **Attention:** investigate soon; the pilot may continue if the affected workflow is not required.
- **Critical:** stop or materially constrain the pilot until understood.
- **Unavailable:** the check could not establish safety; treat a critical unknown conservatively.
- **Disabled:** an optional capability is intentionally unavailable by configuration or privacy policy.

## Pilot stop conditions

Stop new pilot work for database unavailability, stale/unavailable worker, critical stale jobs, backup outside the 24-hour policy, storage at 90%+, authorization/cross-project concern, recovery-integrity concern, or a required provider repeatedly failing. Preserve evidence; do not improvise data repair.

## API failure

Check `/health`, then `/ready`, and the pilot Compose service state/logs. Do not expose environment values in a ticket. If readiness fails, use the database procedure below.

## Database failure

Stop writes. Confirm PostgreSQL container health and the readiness reason. Do not run ad-hoc migrations or restore over the active database.

## Worker failure

Confirm the worker container and its Docker healthcheck. A missing/stale dashboard heartbeat is not permission to fabricate completion or rerun research. Follow the accepted service restart procedure only after preserving logs.

## Stale/failed jobs

Record job ID, type, state, and safe failure code. Do not cancel, delete, edit, or retry from the dashboard. Use an existing supported retry path only after diagnosing the cause.

## Backup overdue

Run the accepted OPS-01B backup status/check procedure. A repository that exists but has no fresh verified snapshot is not healthy. Never place restic credentials in reports or logs.

## Storage critical

Stop artifact-producing work at 90% usage. Preserve protected volumes. Remove only identified disposable operational files under an authorized cleanup procedure; never delete research artifacts to make space.

## Provider problems

Do not enable policy-disabled transcription to make the page green. For an enabled provider, verify configuration and safe failure category without replaying participant/research payloads or making diagnostic paid calls.

## Recovery escalation

For data loss, corruption, host loss, or restore validation, stop here and follow `docs/operations/pilot-recovery-runbook.md`. Do not restore into the active database or bypass the disposable-empty-target guard.

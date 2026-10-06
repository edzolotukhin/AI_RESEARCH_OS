# OPS-01C — Pilot operations architecture

## Operational gap audit

The accepted product already had liveness/readiness endpoints, a PostgreSQL readiness query, Docker worker health, durable presentation and qualitative job state, OPS-01B restic status, protected volumes, bounded Docker logs, and a pilot administrator identity. It did not provide one authorized, safe view joining those signals.

- **O1:** worker visibility, false-green prevention, backup freshness, critical storage, and server-side operator authorization.
- **O2:** bounded persisted job summary, safe failures, provider policy/failure state, environment identity, and a daily runbook.
- **O3:** historical trends, richer type-specific job runtime thresholds, and automated notifications.
- **O4:** enterprise metrics/logging/tracing/SIEM and automatic remediation.

OPS-01C implements O1 and the bounded O2 items only.

## Read model and authorization

`OperationsStatusService` is a deterministic read-only aggregator. `/ui/operations` is available only to the existing `PILOT_ADMIN_USER_ID`; hiding the secondary navigation link is not the authorization boundary. No role, monitoring database, or migration is added.

The status vocabulary is `Healthy`, `Attention`, `Critical`, `Unavailable`, and `Disabled`. Overall status is the highest severity. `Unavailable` is above `Attention`, so an unknown pilot-critical check cannot produce green. `Disabled` is healthy-neutral for an intentionally absent optional capability.

## Sources and bounds

- API: the current process serving the page.
- Database: the existing bounded readiness check, including migration compatibility.
- Worker: an atomic heartbeat file written by the worker and shared read-only with the API. Freshness is 90 seconds. This complements, and does not redefine, Docker health.
- Jobs: at most 50 newest persisted presentation jobs. Pending/processing older than 30 minutes are stale and critical; failed jobs are attention. Only IDs, type, project reference, timestamps, state, and bounded failure codes are exposed.
- Backup: the exact OPS-01B `status` payload and authoritative `within_24h_policy`; no repository existence inference. The recovery command atomically refreshes the shared status artifact when `status` is run.
- Storage: filesystem capacity only for configured project/protected roots. No recursive scan. Under 70% is healthy, 70–89.9% attention, and 90%+ critical.
- Providers: configuration/privacy policy plus injected safe recent failure counts. No provider pings. Policy-disabled transcription is `Disabled`, not broken.

All rendered diagnostics pass a bounded sanitizer. Credentials, URLs, payloads, participant content, dataset rows, transcript text, and provider request/response data are outside the read model.

## Environments and stop policy

Production/pilot-only signals absent in development are shown as `Disabled`; absent in pilot/production they are `Unavailable`. Pilot stop/escalation conditions include unavailable database or worker signal, stale jobs, overdue backup, critical storage, security/recovery-integrity concerns, or provider failure blocking an active workflow. The dashboard never performs remediation.

## Logging and deferred scope

Existing startup/shutdown/job failure logs remain authoritative. Docker rotation stays at five 10 MiB files per service. No high-frequency polling, provider calls, alerting framework, mutation console, infrastructure platform, or research administration is introduced.

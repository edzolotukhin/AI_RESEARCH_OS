# INFRA-02 — worker healthcheck timeout semantics

2026-09-27. Baseline b662526048801c7af3e2b16c02610835189fe08d,
acceptance/live-desk-research-01. Infrastructure only; no product/ARK changes.

INFRA-01 established Engine-generated timeout (-1), not main-worker failure:
5s was shorter than observed import6.03s plus readiness0.25s; manual equivalent
checks succeeded in9.54–11.16s including transport. Restart:no behavior is separate.

## Narrow configuration

New `docker-compose.ark07-health.yml` overrides only worker healthcheck.timeout
to15s. Existing shared Compose and production configuration unchanged. Actual
container inspection confirms timeout15000000000ns, interval15s, retries8,
start_period30s, unchanged command. Only ARK07 worker recreated once, no repeated
restart-until-green. API/PG/history untouched. New worker restart count remains0.

Reproduce from repository root (private existing credentials never printed):

```powershell
docker compose --env-file .env.prf08l -p ai_research_os_ark07 -f docker-compose.prf08l.yml -f .env.ark07-runtime/compose.yml -f docker-compose.ark07-health.yml up -d --no-deps worker
python tools/acceptance_health.py ai_research_os_ark07-worker-1
```

Always include the health override in subsequent ARK07 Compose operations.

## Reporting semantics

Reusable read-only tools/acceptance_health.py classifies Docker State/Health.Log:
0→HEALTHY; Engine timeout diagnostic with-1→HEALTHCHECK TIMEOUT;
other-1/missing probe/inspection failure→EXECUTION FAILURE; other nonzero→
APPLICATION FAILURE; stopped main container→CONTAINER NOT RUNNING.
It preserves raw code/start/end and safe timeout category; arbitrary application
output is deliberately not echoed because it can contain secrets. Raw logs remain
in Docker. Host elapsed time is not used to infer application failure or timeout.
CLI returns nonzero for every nonhealthy category. No health requirement weakened.

## Targeted verification

`python -m unittest tests.test_acceptance_health -q`:7 passed,0 failures/errors.
Covers successful11s probe, actual timeout diagnostic after15s, application exit1,
success, exec failure, stopped container and sensitive-output non-disclosure.
CLI read-only smoke returned HEALTHY/exit0. No full suite run.

Six distinct real automatic Engine probes after recreation, all exit0:

|UTC start|UTC end|Elapsed seconds|
|---|---|---:|
|16:00:35.465|16:00:39.378|3.913|
|16:00:54.380|16:00:58.323|3.944|
|16:01:13.324|16:01:21.080|7.756|
|16:01:36.074|16:01:41.642|5.568|
|16:01:56.643|16:02:00.425|3.782|
|16:02:15.426|16:02:18.341|2.915|

Probe span approximately103s. Bounded observer ran71.81s, including earlier
retained post-recreation records; records deduplicated by Start. No manual probes
counted as automatic. Every snapshot Running, restart0, OOMfalse, no timeout or
application failure. Two probes exceeded5s and passed under15s naturally.
Final Docker29.6.1 responsive, PostgreSQL healthy, API /ready HTTP200.

## Preservation and result

ARK07 projects0/runs0; no designs/provider calls, costUSD0. Live authorization
unused; ARK07 remains paused but infrastructure ready for a separately requested
resume. Long-term host stability is not guaranteed by this bounded observation.
No research/worker business logic, readiness policy, budgets, provider logic or
restart policy changed. Preliminary ARK07 report SHA256 preserved:
4103c2ffc08cc1f49df2313d0be0af52938a317f481ae6cd9f1afbce65299e38.
INFRA01 diagnostic and existing historical artifacts preserved, not staged.
One local commit: INFRA-02 fix worker healthcheck timeout. No push.

INFRA-02_READY_FOR_ARK07

# Canonical production deployment

There is exactly one supported production release entrypoint:

```sh
python -m tools.pilot_deploy --release-sha <40-character-accepted-git-sha>
```

Run it from the clean production checkout after checking out the accepted
commit. The command always uses project `app`, `docker-compose.pilot.yml` and
the ignored `.env.pilot`. Direct production mutations with bare `docker
compose`, the default `docker-compose.yml`, or a different env file are
unsupported.

For a non-mutating command-plan check use `--dry-run`. For read-only validation
of an already deployed release use `--verify-only`. Both still require the
exact current 40-character HEAD and a clean tracked checkout.

The entrypoint fails before mutation when the release SHA, required files,
rendered Compose project, services, network, PostgreSQL volume, or checkout do
not match the pilot contract. It then builds `migrate`, `api`, and `worker`
from that checkout, starts the existing PostgreSQL volume, verifies one
repository Alembic head, runs the normal migration service, and force-recreates
API and worker from the newly built images.

Success requires:

- project `app`;
- services `postgres`, `api`, and `worker` on `app_pilot_backend`;
- PostgreSQL volume `app_pilot_postgres_data`;
- no deployed service attached to `app_default`;
- healthy PostgreSQL, API, and worker;
- no worker PostgreSQL DNS/availability error;
- public HTTPS `/ready` returning 200 with normal TLS verification;
- running API/worker image IDs matching the freshly built images;
- SHA-256 matches for release-critical report/runtime source files inside both
  running containers and the exact checkout.

The script does not delete unrelated containers, networks, or volumes. In
particular, historical `app-api-run-*` containers are not considered deployed
service health and are not cleaned automatically.

## Rollback boundary

Application rollback means checking out a previously accepted full SHA and
running the same canonical command. It does not downgrade the database.
Schema rollback or data repair requires a separately reviewed recovery plan
and a verified backup; never stamp or edit `alembic_version` manually.

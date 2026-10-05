# Pilot operator runbook

This runbook targets one private Linux host. It does not replace OPS-01B backup/restore or privacy governance.

## Host baseline

- Debian 12 or Ubuntu 22.04/24.04 LTS, Docker Engine 26+ and Compose plugin 2.24.4+.
- Minimum 4 vCPU, 16 GiB RAM, 100–200 GiB encrypted SSD; preferred 8 vCPU, 32 GiB RAM, about 200 GiB.
- Block-device/filesystem encryption is mandatory for Docker data and backup staging paths.
- DNS A/AAAA for the pilot hostname, correct NTP, and outbound DNS/HTTPS.
- Firewall inbound: SSH from controlled operator sources and TCP 80/443. Do not expose 5432, 8000, or worker endpoints.
- Key-based SSH, disabled password root login, restricted sudo, and current OS security updates.

## First deployment

1. Checkout the exact accepted commit and verify its SHA.
2. Copy `.env.pilot.example` to ignored `.env.pilot`; replace every `CHANGE_ME` value. Generate URL-safe random secrets, for example `openssl rand -base64 48 | tr -d '=+/\n'`.
3. Set `PILOT_HOST`, `ALLOWED_HOSTS`, and `TLS_CONTACT_EMAIL`. Leave unused provider keys empty.
4. Verify the Docker data root is on encrypted storage and has at least 30 GiB free (50 GiB recommended before large imports).
5. Validate rendering: `docker compose --env-file .env.pilot -f docker-compose.pilot.yml config --quiet`.
6. Start PostgreSQL only, wait for healthy, then apply exactly one migration job:
   `docker compose --env-file .env.pilot -f docker-compose.pilot.yml up -d postgres`
   `docker compose --env-file .env.pilot -f docker-compose.pilot.yml --profile operations run --rm migrate`
7. Bootstrap the owner once:
   `docker compose --env-file .env.pilot -f docker-compose.pilot.yml --profile operations run --rm bootstrap-owner`
   Record the resulting user id as `PILOT_ADMIN_USER_ID`, then remove `PILOT_OWNER_PASSWORD` from the runtime env or secret delivery path.
8. Start `api`, `worker`, and `proxy`. Verify HTTPS `/health`, `/ready`, login, project access, and logout.

## Normal release

1. Record current image/commit and database migration head.
2. Fetch and checkout the exact accepted commit; review release notes and migration reversibility.
3. Build images, run the one-shot migration service once, then recreate API and worker before proxy only when required.
4. Verify PostgreSQL, `/ready`, worker health, HTTPS login, and one authorized project page.

## Restart

Use `docker compose --env-file .env.pilot -f docker-compose.pilot.yml restart api worker proxy`. PostgreSQL should be restarted only when operationally required. Confirm `/ready` and worker health afterward.

## Rollback

Application rollback means selecting the previous accepted commit/image and recreating API/worker. It does **not** reverse database schema. Database downgrade is a separate, explicitly reviewed operation and must not be attempted without a validated backup/restore point and migration-specific procedure. Prefer forward fixes for the pilot.

## Health and data locations

- Proxy: HTTPS request and Caddy logs.
- API: `/health` (liveness), `/ready` (dependency readiness).
- Worker: `python -m worker.healthcheck` inside the worker container.
- PostgreSQL: `pilot_postgres_data` (all relational authority, Qual state/artifacts, PDF/PPTX bytes).
- Protected files: `pilot_protected_data` (Quant raw/parsed/protected respondent data).
- Project compatibility path: `pilot_project_data`; PostgreSQL is authoritative in pilot mode.
- Caddy state: `pilot_caddy_data` and `pilot_caddy_config` (certificate/account state, not research authority).

Docker logs are bounded to 5 × 10 MiB per service. Monitor Docker disk, PostgreSQL volume, protected volume, certificate renewal, container health, and free space. A full monitoring/retention policy belongs to OPS-01C.

## Backup boundary for OPS-01B

Back up PostgreSQL consistently, `pilot_protected_data`, and Caddy state needed for continuity. Include the accepted commit SHA and non-secret configuration manifest. Do not put plaintext secrets in backups or documentation. OPS-01A does not establish backup readiness: an encrypted off-host backup and isolated restore drill remain mandatory.

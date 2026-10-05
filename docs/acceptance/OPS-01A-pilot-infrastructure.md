# OPS-01A — Local acceptance evidence

## Baseline

- Branch: `acceptance/live-desk-research-01`.
- Initial HEAD and remote: `831c416e540e94f68a7496e03b8e12b6b595be7e`.
- Initial divergence: `0/0`; tracked/index clean; historical untracked artifacts preserved.
- UX-01A remote workflow `37313167987`: completed successfully for the exact baseline SHA.
- Alembic: one head, `023_ux01a_identity_membership`.

## Implemented baseline

The pilot definition adds Caddy, API/UI, worker, private PostgreSQL, explicit named storage, one-shot migration/bootstrap services, fail-closed configuration validation, trusted-host enforcement, runtime-only CSRF signing, bounded Docker logs, and operator documentation. No domain migration or research-authority change was introduced.

Production TLS uses the configured hostname and Caddy ACME. Local acceptance used Caddy internal TLS at `https://localhost:18443`; it does not prove public DNS or trusted-certificate issuance.

## Executed evidence

- Compose rendered successfully using Docker Compose `v5.5.1`.
- Disposable project: `ai_research_os_ops01a`.
- PostgreSQL migrated from base through exact head `023_ux01a_identity_membership`.
- Runtime services: PostgreSQL healthy, API healthy, worker healthy, proxy running.
- Published ports: proxy only, loopback `18080/18443`; PostgreSQL/API/worker had no published host ports.
- An untrusted `Host` request reached FastAPI from the proxy network and was rejected HTTP 400.
- `/ready` returned HTTP 200 on three consecutive HTTPS checks.
- HTTPS login returned a session cookie with `Secure`, `HttpOnly`, and `SameSite=Lax`.
- Cross-origin mutation returned HTTP 403; logout returned HTTP 303 and revoked the session.
- Cross-user scenario through HTTPS: researcher received 404 before membership, owner added `RESEARCHER` through the UI, researcher then received HTTP 200.
- Optional provider credentials were empty. The stack started and all acceptance used deterministic adapters; no OpenAI, Tavily, or AssemblyAI call occurred.
- Synthetic SAV upload, QC, design approval, analysis, semantic authorization, Review, and Approved Revision completed through supported HTTPS UI actions.
- Quant PDF generation/download through HTTPS: 26,537 bytes, two downloads byte-identical, SHA-256 `9ce1df19e3a8a7efbba6daa4b10eedab41464ad7167cd9dd6be6d168829f63d8`, correct PDF MIME and attachment disposition.
- Quant PPTX asynchronous generation: scheduled through HTTPS UI, processed by the separate worker, 132,709 bytes, two downloads byte-identical, SHA-256 `1672322d9e5c7fa17b4154372b2cc278106fcf2e71c94875da01406f94a2babd`, correct PPTX MIME.
- Application/worker/proxy containers were stopped, removed, and recreated while PostgreSQL and named volumes remained. User ids, project id, and protected-file SHA-256 remained exact; worker health returned exit 0 after recreation.
- Synthetic protected artifact SHA-256 remained `698297120be812721e23bd65aa726f21e9f42a817a33253ea964dfabe16fd2b6`.
- A bounded deterministic Desk run also executed through the worker and safely completed with insufficient Evidence; this confirmed infrastructure did not manufacture research sufficiency.

The initial outputs-page request exposed a real infrastructure configuration defect: accepted browser sessions had no server-side CSRF signing key unless a legacy service API key was configured. The remediation introduced mandatory pilot `UI_CSRF_SECRET`, separate from browser identity and provider/service credentials. After rebuilding, outputs returned HTTP 200 and canonical PDF/PPTX actions succeeded.

## Focused tests

- Pilot configuration/network/storage/host tests: 8 passed.
- Combined OPS, UX-01A browser identity, Desk/CMF outputs, Quant deliverables, and Qual deliverables: 44 passed.
- Production-like stack E2E: passed as listed above.

## Final verification

- Canonical offline suite: 3,208 tests run; 3,043 passed; 165 skipped; 0 failures; 0 errors.
- No OpenAI, Tavily, or AssemblyAI calls occurred during the suite or infrastructure acceptance.
- Disposable Compose project `ai_research_os_ops01a` was stopped and removed after acceptance. Its four containers, five named volumes, and three project-labelled networks were removed; the runtime-only `.env.ops01a` was deleted. Unrelated Docker projects and historical volumes were not changed.

## Storage, backup, and privacy result

PostgreSQL contains relational authority, qualitative binary state, and immutable document bytes. Quant protected files use `pilot_protected_data`. The host encrypted-volume boundary is mandatory; the application does not claim application-level encryption at rest.

Backup inventory is PostgreSQL, Quant protected storage, compatibility project storage if populated, Caddy certificate/account continuity data, accepted SHA, and non-secret configuration metadata. Plaintext secrets are excluded. `BACKUP/RESTORE P0 OPEN` remains explicit.

Privacy classes: proxy/static health information is public; service/network metadata is internal; project research and deliverables are confidential; respondent/source/audio/transcript material is participant/personal data. Retention/deletion and provider-transfer governance remain open for OPS-01B.

## Deferred/not verified locally

- Real public DNS, ACME issuance, browser trust chain, and actual Linux server firewall: not verified.
- Encrypted off-host backup and isolated restore: not implemented or verified.
- Full upload MIME/content hardening and privacy governance: deferred to OPS-01B.
- Central monitoring and final log-retention policy: deferred to OPS-01C.

# UX-01A — Pilot identity and project membership

## Scope and threat model

UX-01A separates human browser identity from the existing bearer-key service identity. A browser must present an opaque server-side session cookie; a service continues to use the existing API-key boundary. Browser input never supplies a trusted user ID, role, API key, or ownership claim. The pilot threat model covers credential guessing, stolen/forged/replayed session IDs, cross-site form submission, ID guessing, stale roles/memberships, disabled accounts, and accidental loss of the last project owner.

It is not an enterprise IAM system. SSO, OAuth, SCIM, organizations, teams, MFA, invitations, password reset, and complex RBAC are deferred.

## User and password authentication

`User` has a UUID, normalized email, display name, password verifier, active/disabled status, and UTC creation/update timestamps. PostgreSQL is authoritative. Passwords use Python's standard `hashlib.scrypt` primitive with a fresh 128-bit random salt, fixed work parameters, a 32-byte verifier, and timing-safe `hmac.compare_digest`. Plaintext passwords are neither persisted nor logged. Policy is 12–256 characters.

Login returns one generic failure for an unknown user, wrong password, disabled user, or bounded throttle. A per-login-identifier in-process pilot throttle permits five failures in a rolling 15-minute window. This is deliberately small-pilot protection, not a distributed rate limiter.

## Browser sessions and cookie security

The browser receives a 256-bit opaque random token. Only its SHA-256 digest is stored in `browser_sessions`; the row binds one exact User and has a 12-hour expiry and optional revocation timestamp. Logout revokes it. Disabling a User revokes all sessions and every resolution also rechecks current status. PostgreSQL sessions survive application restart.

The cookie is `HttpOnly`, `SameSite=Lax`, path-scoped to `/ui`, and `Secure` when `UI_COOKIE_SECURE=1`; if not explicitly configured, production (`APP_ENV=production|prod`) enforces `Secure`. Invalid/expired sessions redirect to login with a bounded local `/ui/...` return path. There is no fallback to a service identity in a production container.

State-changing UI requests use SameSite cookies and reject a present cross-origin `Origin`. The application serves same-origin HTML forms and has no cross-origin browser API. This is the selected pilot CSRF control; a synchronizer token may be added if cross-origin embedding or browser APIs are introduced.

## Membership and roles

`ProjectMembership(project_id, user_id)` is unique and records role, creation time, and creating User. Ordinary browser project discovery starts from the server-side membership repository, not from an unfiltered project list.

- `OWNER`: read/write research and governance, outputs, and membership administration.
- `RESEARCHER`: read/write normal research and existing governance actions, but no membership administration.
- `VIEWER`: read-only project state and permitted downloads.

Every browser project route is checked against current membership on every request. Project-derived Desk, Quantitative, Qualitative, Activity, report, artifact, and download services resolve their owning project and fail closed. Role demotion and membership removal therefore take effect without changing the cookie. At least one OWNER must remain; only an OWNER can mutate memberships.

For PostgreSQL, browser project creation inserts the Project, initial OWNER membership, and canonical `PROJECT_CREATED` Activity row in one database transaction. Non-production in-memory/file test backends use compensating deletion because they are not production authority.

## Attribution and actors

The server derives a request-scoped human actor from the resolved session. Existing canonical `actor_id`, `created_by`, reviewer/approver, and Activity fields receive that stable User ID. Activity presentation resolves known IDs to display names; it does not expose email, password identity, or internal authentication data. AI proposal origin remains in the existing provenance records while the accepting/reviewing human remains the actor. Worker/system events with no human request remain unattributed/system events; historical events are not rewritten or assigned to invented people.

## Legacy projects and bootstrap

Migration 023 intentionally does not bulk-assign old projects. They remain inaccessible to ordinary Users until an operator explicitly names them. `tools/bootstrap_pilot_owner.py` requires `PILOT_OWNER_EMAIL`, `PILOT_OWNER_DISPLAY_NAME`, and `PILOT_OWNER_PASSWORD`; it never prints the password. Optional `UX01A_LEGACY_PROJECT_IDS` is an explicit comma-separated allowlist. The operation is idempotent for an existing matching owner and refuses conflicting membership; ambiguous projects fail closed.

The small admin surface is enabled only for the User ID configured as `PILOT_ADMIN_USER_ID`. It creates pilot accounts and enables/disables them. Project ownership does not imply infrastructure administration.

## Compatibility and precedence

Service/API bearer authentication is unchanged and remains server-side. Human browser routes use the session principal. The only API-key fallback is attached to explicitly injected test containers through `_test_api_key_plaintext`; production composition never sets it. No HTML, cookie payload, JavaScript, local storage, or OpenAPI response contains a service credential.

Migration `023_ux01a_identity_membership` creates `users`, `browser_sessions`, and `project_memberships` from head 022. It does not mutate accepted research authority data. Downgrade refuses while User or membership data exists, preventing silent identity loss.

## Pilot limitations

There is no self-service password recovery/change, distributed login throttle, MFA, invitation email, organization boundary, real-time collaboration, SSO/OAuth/SCIM, or enterprise audit export. Account creation and recovery are operator-managed for PILOT-01. Membership administration accepts existing users only.

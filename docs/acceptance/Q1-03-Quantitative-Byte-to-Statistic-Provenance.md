# Q1-03 — Quantitative Byte-to-Statistic Provenance

## Verdict

PROPERTY QA passes offline. The first Quantitative slice deterministically
binds each `StatisticalResult` to the imported file bytes, immutable
`DatasetVersion`, codebook and variable semantics, missing-value rules,
analysis specification, and computation version.

## Invariant

The same bytes and semantic inputs produce the same dataset and result
fingerprints. A respondent-value change changes the data and dataset
fingerprints. A codebook semantic change changes the codebook and dataset
fingerprints. Row order remains significant. Presentation eligibility does
not remove authoritative computed categories.

## Hashing boundary

Canonical serialization remains in `application/quantitative/fingerprints.py`.
Application code depends only on `DeterministicDigestProvider`. The accepted
infrastructure adapter, `Sha256DigestProvider`, owns the `hashlib` import and
returns lowercase SHA-256 hexadecimal digests. Moving the primitive behind
this port did not change canonical payloads or fingerprint semantics.

The repository-wide legacy crypto-boundary test still reports eight existing
non-Quantitative application imports. Q1-03 introduces no additional entry in
that violation list.

## Dependency gate

`pyreadstat==1.3.5` is pinned. The repository supports Python
`>=3.11,<3.15`; validation used Python 3.14.5. `pip check` passed. The direct
runtime dependency added by installation was `narwhals==2.24.0`; the existing
NumPy installation satisfied the other requirement without a repository pin
change.

## Offline acceptance

- PROPERTY QA focused tests: 19/19 passed.
- Quantitative import and one-way computation tests: passed.
- Full repository discovery: 1,979 tests, 0 failures, 0 errors, 91 skipped.
- Scanner parking: 92 untracked forensic helpers restored byte-for-byte;
  SHA-256/size mismatches: 0.
- `git diff --check`: passed at closeout.

## External activity

No Research, provider calls, live LLM calls, runtime refresh, database writes,
or live/client dataset access occurred. Package-index access was limited to
the accepted dependency gate. The SAV acceptance fixture is the existing
local synthetic fixture.

## Scope and risks

This is an isolated offline slice. It adds no workflow, API, UI, database,
schema, migration, production storage, or Desk Research integration. The
in-memory storage adapter is not a production persistence design. Advanced
proprietary-file metadata, production PII access controls, keyed
pseudonymization, and retention policy remain future work.

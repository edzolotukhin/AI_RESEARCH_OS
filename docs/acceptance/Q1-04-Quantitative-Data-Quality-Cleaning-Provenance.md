# Q1-04 — Quantitative Data Quality and Cleaning Provenance

## PROPERTY QB

Every CLEANED `DatasetVersion` is a deterministic immutable child of one
exact parent version, one immutable approved `CleaningDecisionSet`, and one
deterministic CleaningEngine version. QC detection alone cannot mutate data
or exclude respondents.

## Accepted methodology rules

- A specified routing violation is a QC issue, not an automatic deletion.
- A questionnaire-defined screen-out is a legitimate terminal outcome.
- A partial interview requires methodological review.
- `EXCLUDE_RESPONDENTS`, `SET_MISSING`, and `RECODE` require a rationale and
  explicit approval.
- Cleaning may reduce achieved quotas; invalid respondents are not retained
  merely to preserve quota counts.
- V1 permits a Research Manager to author, preview, and approve the same
  fingerprint-bound decision set.

## Implemented QC detectors

- out-of-domain values;
- explicit routing violations;
- required-answer missingness;
- duplicate respondent identifiers;
- partial-interview review flags.

Incomplete routing bindings are reported as `NOT_EVALUATED`; routing is never
inferred from observed blanks.

## Respondent lineage and PII

RAW import stores stable pseudonymous respondent references with row lineage.
CLEANED descendants inherit retained references without regeneration from
child row position. Issues contain pseudonyms, variable IDs, and bounded
metrics only; no names, phone numbers, email addresses, or raw open text are
included in ordinary diagnostics.

## Cleaning authority

`CleaningDecision` supports `NO_ACTION`, `INVESTIGATE`,
`EXCLUDE_RESPONDENTS`, `SET_MISSING`, and `RECODE`. An immutable ordered
`CleaningDecisionSet` binds the exact parent and ordered decision
fingerprints, preview fingerprint/count, and approval metadata. Unknown
respondents, stale parents, repeated exclusions, conflicting cell
transformations, and material no-ops fail closed.

## CLEANED DatasetVersion provenance

The child records the parent ID/fingerprint, decision-set ID/fingerprint,
engine version, resulting data/dataset fingerprints, and retained/excluded
respondent-set fingerprints. RAW storage remains immutable. Identical replay
produces identical CLEANED identity.

## QC reconciliation and quality assessment

Fresh QC runs reconcile issues as `NEW`, `REMAINS`, `RESOLVED`,
`SUPERSEDED`, or `NOT_EVALUATED`; mutable parent status is not copied.
`DatasetQualityAssessment` is separate from Desk Sufficiency and supports
`QC_PENDING`, `QC_REVIEW_REQUIRED`, `QC_APPROVED`, and `QC_BLOCKED`, bound to
the exact dataset and QC authority.

## Acceptance

- PROPERTY QB: 11/11 passed.
- PROPERTY QA regression: 19/19 passed.
- Quantitative subsystem: 30/30 passed.
- Full repository suite: 1,990 tests, 0 failures, 0 errors, 91 skipped.
- Scanner helpers: 92 parked/restored; SHA-256/size mismatches: 0.
- Repository crypto check: no Q1-04 violation; eight documented pre-existing
  application violations remain out of scope.

## Deferred scope

Duration thresholds, straight-lining, numeric outlier policy, quota
correction, distribution-anomaly policy, open-end coding, weighting,
cross-tabs, significance testing, production persistence, migrations,
workflow, API, UI, and reporting are not implemented.

No Research, provider calls, live LLM calls, runtime refresh, or client/live
respondent data were used.

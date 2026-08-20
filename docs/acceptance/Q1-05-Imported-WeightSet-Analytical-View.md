# Q1-05 — Imported WeightSet and Analytical View

## PROPERTY QC

Every authoritative weighted `StatisticalResult` derives from one exact
QC-approved `DatasetVersion`, one validated immutable `WeightSet`, an explicit
approval bound to that WeightSet, one immutable `AnalyticalDatasetView`, and a
deterministic weighted computation method. Unweighted respondent N and weighted
base are separate authoritative quantities.

## Imported-weight forms and respondent authority

The offline slice supports an embedded variable with role `WEIGHT` and a
separate keyed weight source. An embedded variable binds through inherited row
lineage. A separate source binds technical respondent keys through a protected,
immutable technical-ID-to-pseudonym map; source row order is never authority.
The protected binding is stored separately from analytical projections and is
carried from RAW to CLEANED lineage. Raw technical identifiers are not emitted
in StatisticalResults or ordinary validation diagnostics.

## WeightSet provenance and validation

`WeightSet` binds the exact DatasetVersion, source checksum or embedded variable
fingerprint, parser identity where applicable, respondent-key specification,
canonical pseudonym-to-weight vector, validation contract, and deterministic
reproducibility fingerprint. Canonical vector order is pseudonym order.

Validation fails closed for incomplete retained coverage, duplicate or unknown
keys, negative, non-numeric, NaN, or infinite weights, and unavailable stable
binding. A known parent respondent excluded from a CLEANED version is classified
explicitly and excluded from the analytical vector. Exact min, max, mean, sum,
coverage, and validation counts remain inspectable. Imported weights are never
normalized, recalculated, raked, or otherwise repaired.

Finite zero weight is `VALID_WITH_WARNINGS`. It remains visible in diagnostics,
counts in unweighted N when otherwise eligible, and contributes exactly zero to
weighted base. A zero weighted valid base fails closed.

## Approval and AnalyticalDatasetView

Immutable approval binds the exact DatasetVersion fingerprint, WeightSet
fingerprint, and validation fingerprint. Only `APPROVED` authority may produce
a weighted view. Changed dataset, weight vector, source provenance, binding, or
validation authority invalidates reuse. A CLEANED DatasetVersion therefore
requires a newly bound, validated, and approved WeightSet.

`AnalyticalDatasetView` binds dataset, current `QC_APPROVED` assessment,
analysis specification, weighting mode, optional WeightSet, eligible respondent
set, filter/base definition, and its own fingerprint. An unweighted view cannot
carry a WeightSet. A weighted view cannot execute against a different dataset,
specification, respondent set, or WeightSet.

## Deterministic statistics and result provenance

Weighted categorical computation retains every category and emits unweighted
category N, unweighted valid N, weighted category base, weighted valid base, and
weighted percentage using exact `Decimal` arithmetic. The existing presentation
rule is applied to weighted percentage: values above 1.0% are default-presented;
values at or below 1.0% remain authoritative but default-hidden.

Weighted numeric computation emits unweighted valid N, weighted valid base, and
the deterministic weighted mean `sum(weight * value) / sum(weight)`. No fallback
to an unweighted mean exists. Presentation rounding is outside the authority and
does not alter fingerprints.

Weighted StatisticalResults carry WeightSet and AnalyticalDatasetView IDs and
fingerprints plus distinct `unweighted_n` and `weighted_base`. Their
reproducibility fingerprints include the exact dataset, codebook/variable,
analysis specification, view, WeightSet, bases, statistic, and computation
method/version. Existing PROPERTY QA unweighted behavior is unchanged.

## PII and architecture boundary

Protected binding may inspect technical IDs internally. Ordinary projections do
not expose technical IDs, names, phone numbers, email addresses, or raw weight
rows. Quantitative weighting has no Source, Evidence, InformationNeed,
Sufficiency, provider, or LLM dependency. No Desk Research, workflow, API, UI,
database, schema, migration, dependency, or production-persistence change is
included.

The repository crypto-boundary check found no Q1-05-introduced violation. Its
single failing assertion remains the documented eight pre-existing direct
application-level crypto imports; those files were not modified by Q1-05.

## Offline acceptance

- PROPERTY QC: 12/12 passed.
- PROPERTY QA: 19/19 passed.
- PROPERTY QB: 11/11 passed.
- Quantitative subsystem: 42/42 passed.
- Full repository suite: 2,002 tests, 0 failures, 0 errors, 91 skipped.
- Scanner helpers: 42 narrowly parked and restored; SHA-256/size mismatches: 0.
- `git diff --check`: passed.
- Provider calls, live LLM calls, Research, and live/client datasets: none.

## Explicitly deferred

- weight construction, normalization, raking, rim weighting, and post-stratification;
- weighted median, cross-tabs, significance testing, and segmentation;
- Findings, reports, and presentation generation;
- workflow, API, UI, database, and production-persistence integration.

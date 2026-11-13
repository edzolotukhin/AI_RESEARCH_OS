# Information Need classification and executable derivations — patch 4

Parent: `148dc5681e40351c9d0cbcb7fe79ef376e2406f5`.
No database migration, acquisition, Evidence wiring, Readiness gate or H3 change.
Readiness and post-analysis coverage alignment remains patch 5.

## Immutable contracts

InformationNeed carries optional kind ACQUIRED/DERIVED/OUTPUT, dependency IDs,
and a versioned DerivationContract. Legacy absent fields deserialize as ACQUIRED,
empty dependencies and no derivation. Default fields are omitted on serialization
so existing snapshots and fingerprints retain their previous representation.
Historical Designs are not classified from their names or modified.

New classified Designs validate dependency membership, uniqueness, self-reference,
cycles and RQ scope before execution. DERIVED requires dependencies and an explicit
derivation; OUTPUT cannot be a computational input. No operation is inferred from
an IN description. The supported contract is `derivation-v1`:

```json
{
  "version": "derivation-v1",
  "operation_type": "YEAR_OVER_YEAR_PERCENT_CHANGE",
  "metric": "Population",
  "input_unit": "persons",
  "geography": "Ukraine",
  "required_periods": ["2019", "2020", "2021"],
  "decimal_places": 6,
  "max_inputs": 100,
  "max_provider_attempts": 1,
  "method": ""
}
```

Numeric operations consume explicit qualified ACQUIRED observation series.
Arithmetic chaining over other DERIVED results is refused by this input-binding
contract; semantic synthesis may depend on validated DERIVED Findings. The
contract never implies unit conversions, geographic harmonization, conflict
resolution, missing-year interpolation or inferred metric aliases.

## Existing AnalysisService integration

The existing Analysis engine first creates ACQUIRED Findings through unchanged
provenance and independent entailment gates. DERIVED/OUTPUT cannot be assigned by
that ordinary provider pass. AnalysisService then executes explicit derivations
in dependency order, persists only validated results and passes all supported
Findings to existing Insight generation. OUTPUT is not executed as an analysis
operation. Provider metadata cannot self-certify a deterministic derivation.

Calculations require validated dependency Findings and qualified Evidence in the
expected project/design/run authority. The validator checks source revision,
canonical citation, v2 semantic binding, workbook cell/period/header, metric,
literal unit/geography and complete required periods. Conflicting observations
and zero percentage denominators cause explicit refusal. Reproduction repeats
the authority checks and calculation before persistence. Literal numeric
entailment is not required for a newly calculated number; ordinary Finding
validators are unchanged.

Supported operations:

* YEAR_OVER_YEAR_ABSOLUTE_CHANGE: end - start, for consecutive years.
* YEAR_OVER_YEAR_PERCENT_CHANGE: (end - start) / start * 100.
* CUMULATIVE_ABSOLUTE_CHANGE: final - initial, with all declared observations.
* CUMULATIVE_PERCENT_CHANGE: (final - initial) / initial * 100.

Decimal execution uses precision 34, ROUND_HALF_EVEN and explicit decimal places.
Raw and rounded strings, formula, input values, period pair, unit/geography,
dependency Finding IDs, Evidence IDs and Source revision lineage are persisted
under Finding.metadata.derivation. Findings retain ordinary Evidence references.
The deterministic method is `deterministic-derivation-v1`.

TREND_CHARACTERIZATION, CROSS_SOURCE_COMPARISON and LIMITATION_SYNTHESIS reuse
the existing Analysis provider with an explicit bounded contract and validated
dependency input. Cross-source comparison requires distinct resources and binary
identities. Provider attempts are at most 1 by default, hard maximum 2; input count
and prompt bounds also respect existing Analysis limits. New numeric claims
outside the supplied authority are rejected. All semantic candidates pass the
existing provenance and independent entailment validators. Technical provider
errors propagate as AnalysisError and are recorded as technical_error; a
methodological refusal is recorded as insufficient. This does not calculate or
replace the authoritative research outcome.

Run-scoped assessment facts are written to `analysis_derivations` in the existing
shared state. Reprocessing replaces this snapshot. Deduplication of DERIVED
Findings includes the contract, exact IN scope and dependency Finding identity;
legacy Finding deduplication is unchanged.

## Control results and qualification

| Operation | Period | Raw result | Rounded (6 places) |
|---|---|---|---|
| YoY absolute | 2020/2019 | -50 | -50.000000 |
| YoY percent | 2020/2019 | -5 | -5.000000 |
| YoY absolute | 2021/2020 | -50 | -50.000000 |
| YoY percent | 2021/2020 | -5.263157894736842105263157894736842 | -5.263158 |
| Cumulative absolute | 2019–2021 | -100 | -100.000000 |
| Cumulative percent | 2019–2021 | -10 | -10.000000 |

Focused tests cover legacy serialization, graph/operation rejection, all four
calculations, raw/rounding preservation, missing observations, zero denominator,
unit/geography mismatch, conflicting values, foreign project/run/design/checksum,
tampered results, all semantic operation contracts, unsupported/fabricated
synthesis, bounded attempts and technical failure.

Disposable PostgreSQL 16 (`patch4_test`, loopback 55439) uses production Evidence
and Analysis factories with deterministic fixtures only at the external LLM
boundary. Local HTTP/XLSX acquisition produces actual structured Evidence. The
test persists the immutable full Design snapshot, one ACQUIRED and six DERIVED
Findings, and an Insight. Three external-boundary fixture calls cover ACQUIRED
generation, independent entailment and Insights; arithmetic makes no LLM calls.
Fresh connections restore Design/Findings and verify Evidence/Source lineage and
citation integrity. Repeated Analysis preserves IDs/counts and leaves original
Source/Evidence unchanged.

```powershell
python -m pytest tests/application/analysis tests/domain/planning tests/application/test_async_design_generation.py tests/application/qualitative tests/application/research_quality/test_authoritative_outcome.py tests/application/test_composition_root.py -q
# Configure disposable PostgreSQL flags and DATABASE_URL_TEST only.
python -m unittest tests.integration.postgresql.test_executable_derivations tests.integration.postgresql.test_prf08c_evidence_integrity tests.application.ports.test_postgresql_repository_contracts -q
```

Final qualification: 123 focused/regression tests passed; 43 disposable
PostgreSQL/repository integration tests passed; no failures or skips in those
groups. Compile validation and git diff --check passed. Production and external
AI providers were not used. Disposable infrastructure is removed after testing.

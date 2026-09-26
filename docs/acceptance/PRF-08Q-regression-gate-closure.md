# PRF-08Q — Regression gate closure

## Baseline and demonstrated cause

Branch `acceptance/live-desk-research-01`, initial HEAD
`f1c662465865be73634317067af0284005520829`, recorded upstream ahead 19 / behind 0.
Tracked tree/index initially clean; existing untracked artifacts preserved.

Directly reproduced
`tests.application.structured_output.test_structured_output_layer.StructuredOutputArchitectureTests.test_p_json_loads_only_in_validator`:
the assertion expected `offenders == []` but found `tools/acceptance_http.py`.

Classification **A: helper violates the existing architecture contract**.
The test scans non-test Python files, including tools, and permits direct JSON
decoding only in the shared validator and the existing deterministic design
response implementation. `JsonValidator.validate` is an existing syntax-only
decoder returning validity/data; no model, repair, persistence or provider call
is involved. The helper's direct decoder was introduced by PRF-08M commit
`e912cac`, after this contract existed. PRF-08M accepted safe diagnostic
visibility, not an architectural exemption. Its record reports targeted tests,
not a passing full architecture suite. There is no evidence authorizing a new
exception or declaring this rule stale. PRF-08P merely exposed this existing
conflict; its content-deduplication changes are not implicated.

## Minimal correction

The HTTP helper delegates JSON syntax validation to the existing `JsonValidator`.
Only validated data enters the unchanged allowlisted/redacting diagnostic filter.
An invalid result, ValueError or recursion error still produces `invalid_json`;
validator error text and raw body are not logged. The JSON serializer remains
unchanged. HTTP status, endpoint path, stage, safe validation fields and
allowlisted request/correlation IDs remain available. Body-size limits, HTML
alert handling, secret redaction, response closing, successful POST semantics
and no-retry behavior are preserved.

The established caller `tools/prf08l_ui.py` supports both package import and
direct script execution. For the latter, the helper resolves the repository
root from its own file before importing the shared validator. A subprocess
test invokes CLI help from an unrelated temporary directory, without a network
request, to protect that existing entry point.

The architecture test, its discovery scope and allowlist are unchanged. No
alternate decoder, test exclusion or acceptance-specific parsing bypass was
introduced. No shared-validator or research/product/persistence code changed.

## Validation

Targeted command:

```text
python -m unittest tests.application.structured_output.test_structured_output_layer tests.api.ui.test_prf08m_design_diagnostics
```

**46 passed, zero failures/errors/skips.** Three new regressions verify use of
the shared validator with redaction/correlation retention, safe recursion-error
handling and direct-script import. Existing tests additionally check malformed,
oversized and unreadable bodies, HTML-only alerts, persisted secret omission,
no retries, valid design requests and representative 422 visibility.

Canonical `python run_tests.py`: executed exactly once, **2891 tests,
2744 passed, 147 skipped, zero failures/errors**, 103.178 seconds. Skipped
integration tests are not counted as executed PostgreSQL passes. The passing
full suite was not repeated. Final status: **PRF-08P_READY_FOR_NEXT_GATE**.

PRF-08P's 16/16 focused and 20/20 PostgreSQL/API-worker evidence is reused:
neither source deduplication nor these runtime/persistence paths changed.
PRF-08P's SELECT-only B/D/F/H/J/O count/checksum/workflow fingerprints are reused;
no historical database was accessed or mutated in PRF-08Q. No migration,
Docker change, OpenAI/Tavily call, live run or push occurred.

## Delivery

Scope: the HTTP helper, its directly affected diagnostic tests, this record and
a closure addendum to PRF-08P. Historical PRF-08P failure evidence remains intact.
No credentials, environment files, live-provider payloads or runtime artifacts
are included. One requested local commit: `PRF-08Q close regression gate conflict`.

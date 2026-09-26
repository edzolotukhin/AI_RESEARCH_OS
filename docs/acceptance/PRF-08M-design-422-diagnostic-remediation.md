# PRF-08M — Design 422 diagnostic remediation

## Baseline and scope

Branch `acceptance/live-desk-research-01`, initial HEAD `c8f3f332752948ce32d69dd11cee9c4be05e03f4`, ahead 15 / behind 0 against recorded upstream. Tracked tree/index initially clean; existing unrelated untracked artifacts preserved. Offline diagnosis only: no OpenAI/Tavily calls, research activation, product-code changes or push. PRF-08K research logic was not re-audited or changed.

## Exact reconstructed request

The committed PRF-08L helper invoked `generate --project f8b634b0-dae6-44a1-86ed-cc1c00726e9f`. It called:

```text
POST http://127.0.0.1:18086/ui/projects/f8b634b0-dae6-44a1-86ed-cc1c00726e9f/design/generate
Content-Type: application/x-www-form-urlencoded
Content-Length: 0

[empty body: urlencode({}).encode() == b""]
```

No design JSON, brief body, design ID or Authorization header was supplied by this helper for that action. The existing loopback UI resolves its configured authenticated owner. The brief was already saved on the project; `selected_methods` is `["DESK"]` and the brief digest is `7262e5080260e56109b7e95431ec481c`.

The route `project_design_generate(request: Request, project_id: str)` has no body/schema/Form parameter. Its normal HTML form likewise has no required input. Existing PF-02 tests use an empty POST. The facade authorizes the project, and the planning service reads its saved methods/brief before calling the planner. Thus an absent JSON request body is **not** a demonstrated defect. Neither brief nor request shape was changed.

## Offline reproduction and root-cause boundary

The exact frozen brief was read with SELECT from the original PRF-08L project, then piped in memory to a disposable `docker run --rm --network none` process using the existing production-compatible dependency image and current source mounted read-only. No historical volume/credential was attached. The normal test container uses memory persistence, deterministic search and a mocked model. The historical project ID was reused only inside that ephemeral memory fixture.

1. Replaying the empty form request with a sentinel at the mock model boundary reached that boundary exactly once. The application's existing global handler translated the deliberately raised sentinel into HTTP 500. This is **not** a reproduction of the historical 422: it proves pre-provider request validation and project prerequisites did not reject the exact brief/request. Brief equality remained true.
2. Replaying with the established deterministic planner mock returned **303**, made **one mock model call**, saved a DRAFT in memory and retained **runs=0**. This validates the current request path, not the missing historical provider output or research quality.

The historical API log/record establishes a 422 response at `2026-09-26T08:11:34.680149902Z`. The route's ValueError handler embeds exception text in an HTML `div.alert`. The old helper raised urllib's status-only HTTPError without reading/persisting that response body; the body and exception details are not recoverable from the retained acceptance artifacts. No paid request was repeated to obtain a new, potentially different error.

**Exact historical 422 root cause: NOT ESTABLISHED.** No malformed acceptance request, API/schema incompatibility, product validation defect or environment defect was proven by offline replay. It would be speculative to assign one of those classifications. The separate **demonstrated diagnostic-loss cause** is an acceptance-helper defect: unhandled HTTPError discarded available response diagnostics. Only that generic defect is fixed here.

## Diagnostic visibility change

New reusable `tools/acceptance_http.py` supplies a single-attempt form POST wrapper. The PRF-08L helper delegates to it without changing endpoints, request values, timeout, redirect behavior, approval or activation semantics. No automatic retry was added.

On non-2xx responses, a bounded JSON diagnostic is emitted to stderr and appended as one JSON line to the selected diagnostic log. Fields include HTTP status, endpoint path (no query/userinfo), action/stage, allowlisted request/correlation identifiers if supplied, and safe validation details. JSON errors retain only `detail/errors/error/message/msg/type/loc/code`; input/ctx/request/provider-payload fields are not retained. HTML errors retain alert text only, not full pages, project content, scripts, hidden inputs or forms. Unsupported/malformed/oversized bodies are explicitly omitted. Read failure still retains status/stage/path.

Known sensitive environment/request values and recognized credential/authorization patterns are redacted before output. Provider preview/prompt/payload tails are omitted. Response headers other than the allowlisted IDs are not logged. Body reads are capped at 64 KiB, message length/list depth/counts are bounded, and the response is closed. This is intentionally not arbitrary response-body archival or a guarantee to detect every unlabelled secret embedded in free text; raw body logging must not be added to bypass these limits.

The helper accepts `--diagnostics`; its default is `artifacts/acceptance/prf08l_http_errors.log`, confirmed ignored by Git's existing `*.log` rule. Tests wrote only synthetic diagnostics to temporary directories. No historical log/artifact was overwritten, and no real failed-body log was fabricated. Future use does not itself authorize a paid retry.

## Targeted validation

Final command:

```text
python -m unittest tests.api.ui.test_prf08m_design_diagnostics tests.api.ui.test_pf_02_method_selection_design_gate tests.api.ui.test_pf_01_project_workspace
```

**35 tests passed, 0 failures/errors, 0 skips** (2.553 seconds). Thirteen new tests cover JSON 422 fields; alert-only extraction/redaction; provider-preview omission; unsupported, oversized, malformed and unreadable bodies; safe persisted diagnostics; CLI wiring; no retries; unchanged successful empty POST behavior; model-boundary reachability; DRAFT without activation; and a representative injected ValueError rendered through the real endpoint/template. The injected RQ5 message is synthetic and is **not claimed as the historical error**.

An initial sentinel test expected the RuntimeError to escape TestClient; it was corrected to assert the existing global handler's HTTP 500 and the single mock boundary call. No product behavior was changed for that test. The exact frozen-brief network-disabled replay described above separately passed both boundary and deterministic-success checks.

No full 2874-test suite, PostgreSQL write/integration suite, worker suite or live run was repeated: changes are restricted to acceptance tooling/tests/documentation. Existing FastAPI TestClient dependency deprecation warning is unrelated; test results were green.

## Historical preservation and retry decision

Before/after SELECT-only checks matched whole-project-row MD5 `5b18b7672577452be426b394398d0f63` and brief MD5 `7262e5080260e56109b7e95431ec481c`. Saved design remains absent; workflow runs, sources and Evidence all remain **0**. The committed PRF-08L stopped acceptance record and its Compose configuration/startup/owner files were not edited. No frozen brief, provider credential, DB record, research outcome or threshold was altered. Historical PRF-08L is still a stopped pre-activation attempt, not a live run.

A future separately authorized attempt now has safer error visibility and a locally validated request path. However, the underlying historical 422 has **not** been causally diagnosed or fixed. This task does not justify claiming a successful remediation of that rejection or automatically retrying PRF-08L. Full diagnosis would require the lost original error/provider evidence, or an owner-authorized future diagnostic attempt. Neither is manufactured here.

One local commit `PRF-08M preserve design validation diagnostics` preserves the demonstrated generic diagnostic fix, its tests and this evidence. No push. Final status: **PRF-08M_DIAGNOSIS_INCOMPLETE**.

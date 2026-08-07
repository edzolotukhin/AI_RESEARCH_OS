# =============================================================================
# P1-07 — Serbia Microgreens Controlled Desk Research E2E
# DIRECT API RUNBOOK — ONE RUN ONLY
# PS C:\AI_AGENTS\AI_RESEARCH_OS>
# =============================================================================
# DO NOT RUN until explicitly approved.
# DO NOT resubmit on failure — capture diagnostics and STOP.
# =============================================================================
#
# OPERATOR PREREQUISITE (before running this script):
#
#   1. Bootstrap API key once (if not already done):
#        docker compose run --rm api alembic upgrade head
#        docker compose run --rm api python -m tools.create_api_key --name serbia-e2e-acceptance
#
#   2. Set the API key in THIS shell (never commit or print the value):
#        $env:AI_RESEARCH_OS_API_KEY = "<plaintext-from-bootstrap>"
#
#   3. Ensure host .env supplies OPENAI_API_KEY and SEARCH_API_KEY for compose.
#
# =============================================================================
#
# COST ENVELOPE NOTE (read-only — do not change budgets):
#
#   LLM_MAX_CALLS_PER_RUN=24 applies to WORKFLOW execution in the worker only.
#   It does NOT include Planner LLM calls (Planner runs synchronously in the
#   API process during POST /projects/{id}/research, before the worker starts).
#
#   Planner theoretical maximum: <= 9 LLM calls
#     (PLANNER_SEMANTIC_MAX_ATTEMPTS=3 x structured_output_max_attempts=3)
#
#   Total controlled-run theoretical envelope: <= 33 LLM calls (9 planner + 24 workflow)
#
#   _run_usage_summary in GET /workflow-runs/{id}/results covers WORKFLOW budget
#   consumption only. It does NOT prove planner usage.
#
#   Planner calls: NOT DIRECTLY INCLUDED IN RUN USAGE SUMMARY.
#   Indirect evidence only: API container logs around submit time (no call counter):
#     docker compose -f docker-compose.yml -f docker-compose.lowcost.yml logs api --no-log-prefix |
#       Select-String -Pattern "<run_id>","research_submitted","structured_output"
#
# =============================================================================

$ErrorActionPreference = "Stop"
Set-Location "C:\AI_AGENTS\AI_RESEARCH_OS"

$ComposeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.lowcost.yml")
$BaseUrl = "http://localhost:8000"
$BriefPath = "examples\n8n\fixtures\serbia_microgreens_brief.json"
$PollIntervalSeconds = 5
$MaxPollAttempts = 180   # 15 minutes max; extend manually if needed

# Verified from docker-compose.yml (postgres service, host port 5432):
$DiagnosticDatabaseUrl = "postgresql+psycopg://ai_research_os:ai_research_os_dev@localhost:5432/ai_research_os"

# -----------------------------------------------------------------------------
# PRECHECK
# -----------------------------------------------------------------------------
Write-Host "=== PRECHECK ===" -ForegroundColor Cyan

if (-not $env:AI_RESEARCH_OS_API_KEY) {
    throw "Missing AI_RESEARCH_OS_API_KEY. Configure it before controlled E2E."
}

$branch = git branch --show-current
Write-Host "branch: $branch"
if ($branch -ne "acceptance/live-desk-research-01") {
    Write-Warning "Expected branch acceptance/live-desk-research-01 — review before continuing."
}

git status --short

$trackedChanges = git status --short | Where-Object {
    $_ -match '^\s*[MADRCU]' -and $_ -notmatch '^\?\?'
}
if ($trackedChanges) {
    Write-Host "STOP: unexpected tracked modifications detected:" -ForegroundColor Red
    $trackedChanges | ForEach-Object { Write-Host "  $_" }
    throw "Resolve or stash tracked changes before E2E acceptance."
}

git log -1 --oneline
docker version

# -----------------------------------------------------------------------------
# STACK START
# -----------------------------------------------------------------------------
Write-Host "`n=== STACK START ===" -ForegroundColor Cyan
docker compose @ComposeArgs up -d --build
docker compose @ComposeArgs ps

Write-Host "Waiting for API health..."
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "$BaseUrl/health" -Method GET
        if ($health.status -eq "ok") {
            $readyResp = Invoke-RestMethod -Uri "$BaseUrl/ready" -Method GET
            if ($readyResp.status -eq "ready") {
                $ready = $true
                break
            }
        }
    } catch {
        # API still starting
    }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    throw "API not ready after 120s. Check: docker compose @ComposeArgs logs api worker"
}
Write-Host "API ready."

# -----------------------------------------------------------------------------
# MIGRATION
# -----------------------------------------------------------------------------
Write-Host "`n=== MIGRATION ===" -ForegroundColor Cyan
docker compose @ComposeArgs run --rm api alembic upgrade head
docker compose @ComposeArgs run --rm api alembic current

# -----------------------------------------------------------------------------
# CONFIG / SECRET PRESENCE CHECK (booleans only)
# -----------------------------------------------------------------------------
Write-Host "`n=== CONFIG / SECRET PRESENCE CHECK ===" -ForegroundColor Cyan

function Test-EnvPresent([string]$Name) {
    $value = docker compose @ComposeArgs exec -T worker printenv $Name 2>$null
    return [bool]($value -and $value.Trim())
}

$secretChecks = [ordered]@{
    OPENAI_API_KEY = Test-EnvPresent "OPENAI_API_KEY"
    SEARCH_API_KEY = Test-EnvPresent "SEARCH_API_KEY"
    PERSISTENCE_BACKEND = Test-EnvPresent "PERSISTENCE_BACKEND"
    DATABASE_URL = Test-EnvPresent "DATABASE_URL"
}
$secretChecks.GetEnumerator() | ForEach-Object {
    Write-Host ("{0}={1}" -f $_.Key, $_.Value)
}
if (-not $secretChecks.OPENAI_API_KEY -or -not $secretChecks.SEARCH_API_KEY) {
    throw "Required provider keys missing in worker container environment."
}

Write-Host "`n=== LOW-COST ENVELOPE (worker container) ===" -ForegroundColor Cyan
Write-Host "NOTE: LLM_MAX_CALLS_PER_RUN=24 is workflow-only; planner calls are separate (see header)."
$budgetVars = @(
    "LLM_MAX_CALLS_PER_RUN",
    "EVIDENCE_MAX_LLM_CALLS",
    "SUFFICIENCY_MAX_LLM_CALLS",
    "ANALYSIS_MAX_LLM_CALLS",
    "REPORT_MAX_LLM_CALLS",
    "REVIEW_MAX_CALLS",
    "SOURCE_MAX_SOURCES_PER_RUN",
    "SOURCE_MAX_CANDIDATES_PER_QUERY",
    "SOURCE_MAX_CANDIDATES_PER_INFORMATION_NEED",
    "SOURCE_MIN_SUCCESSFUL_SOURCES",
    "SOURCE_MIN_INFORMATION_NEED_COVERAGE_RATIO",
    "EVIDENCE_MAX_ITEMS_PER_SOURCE",
    "RESEARCH_MAX_GAP_ROUNDS_PER_RUN",
    "TARGETED_MAX_ATTEMPTS_PER_GAP",
    "TARGETED_MAX_QUERIES_PER_GAP",
    "TARGETED_MAX_SOURCES_PER_GAP",
    "SUFFICIENCY_REASONING_EFFORT",
    "SUFFICIENCY_MAX_OUTPUT_TOKENS",
    "LLM_MODEL",
    "SEARCH_PROVIDER",
    "PLANNER_SEMANTIC_MAX_ATTEMPTS"
)
foreach ($var in $budgetVars) {
    $val = docker compose @ComposeArgs exec -T worker printenv $var 2>$null
    if (-not $val) {
        $val = docker compose @ComposeArgs exec -T api printenv $var 2>$null
    }
    Write-Host ("{0}={1}" -f $var, ($(if ($val) { $val.Trim() } else { "<unset>" })))
}

$llmCap = docker compose @ComposeArgs exec -T worker printenv LLM_MAX_CALLS_PER_RUN 2>$null
if ($llmCap.Trim() -ne "24") {
    Write-Warning "Expected LLM_MAX_CALLS_PER_RUN=24 in worker; verify docker-compose.lowcost.yml overlay."
}

# -----------------------------------------------------------------------------
# BRIEF LOAD
# -----------------------------------------------------------------------------
Write-Host "`n=== BRIEF LOAD ===" -ForegroundColor Cyan
if (-not (Test-Path $BriefPath)) {
    throw "Missing frozen brief: $BriefPath"
}
$briefJsonRaw = Get-Content -Path $BriefPath -Raw -Encoding UTF8
$brief = $briefJsonRaw | ConvertFrom-Json
Write-Host "title: $($brief.title)"
Write-Host "geography: $($brief.geography -join ', ')"
Write-Host "objective_count: $($brief.objectives.Count)"

# -----------------------------------------------------------------------------
# PROJECT CREATE (exactly one fresh project)
# -----------------------------------------------------------------------------
Write-Host "`n=== PROJECT CREATE ===" -ForegroundColor Cyan
$authHeaders = @{
    Authorization = "Bearer $env:AI_RESEARCH_OS_API_KEY"
}
$projectName = "Serbia Microgreens E2E Acceptance $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$projectBody = @{ name = $projectName } | ConvertTo-Json

$project = Invoke-RestMethod `
    -Uri "$BaseUrl/projects" `
    -Method POST `
    -Headers $authHeaders `
    -ContentType "application/json" `
    -Body $projectBody

$projectId = $project.id
Write-Host "project_id: $projectId"
Write-Host "project_name: $($project.name)"

# -----------------------------------------------------------------------------
# IDEMPOTENCY KEY (fresh, single use)
# -----------------------------------------------------------------------------
Write-Host "`n=== IDEMPOTENCY KEY ===" -ForegroundColor Cyan
$idempotencyKey = [guid]::NewGuid().ToString()
$correlationId = [guid]::NewGuid().ToString()
Write-Host "idempotency_key: $idempotencyKey"
Write-Host "correlation_id: $correlationId"

# -----------------------------------------------------------------------------
# ONE RESEARCH SUBMIT
# -----------------------------------------------------------------------------
Write-Host "`n=== ONE RESEARCH SUBMIT ===" -ForegroundColor Cyan
$researchHeaders = @{
    Authorization = "Bearer $env:AI_RESEARCH_OS_API_KEY"
    "Idempotency-Key" = $idempotencyKey
}
$researchBodyObj = [ordered]@{
    brief = $brief
    source = "serbia-e2e-acceptance"
    correlation_id = $correlationId
}
$researchBodyJson = $researchBodyObj | ConvertTo-Json -Depth 20

try {
    $run = Invoke-RestMethod `
        -Uri "$BaseUrl/projects/$projectId/research" `
        -Method POST `
        -Headers $researchHeaders `
        -ContentType "application/json" `
        -Body $researchBodyJson
} catch {
    Write-Host "STOP: research submit failed." -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host $reader.ReadToEnd()
    } else {
        Write-Host $_.Exception.Message
    }
    throw "Do NOT resubmit. Investigate and STOP."
}

$runId = $run.run_id
Write-Host "run_id: $runId"
Write-Host "project_id: $($run.project_id)"
Write-Host "status: $($run.status)"
Write-Host "is_terminal: $($run.is_terminal)"
Write-Host "idempotent_replay: $($run.idempotent_replay)"

if (-not $runId) { throw "STOP: run_id missing after submit." }
if ($run.idempotent_replay) { throw "STOP: idempotent_replay=True on fresh submit — do NOT resubmit." }

# -----------------------------------------------------------------------------
# POLL TO TERMINAL
# -----------------------------------------------------------------------------
Write-Host "`n=== POLL TO TERMINAL ===" -ForegroundColor Cyan
$terminalRun = $null
for ($attempt = 1; $attempt -le $MaxPollAttempts; $attempt++) {
    $poll = Invoke-RestMethod `
        -Uri "$BaseUrl/workflow-runs/$runId" `
        -Method GET `
        -Headers $authHeaders

    if ($attempt -eq 1 -or ($attempt % 6) -eq 0 -or $poll.is_terminal) {
        Write-Host ("[{0}] poll={1} status={2} is_terminal={3}" -f (
            (Get-Date -Format "HH:mm:ss"), $attempt, $poll.status, $poll.is_terminal))
    }

    if ($poll.is_terminal) {
        $terminalRun = $poll
        break
    }
    Start-Sleep -Seconds $PollIntervalSeconds
}

if (-not $terminalRun) {
    Write-Host "STOP: polling timeout reached." -ForegroundColor Red
    Write-Host "Current run_id: $runId"
    Write-Host "Fetch current state manually: GET $BaseUrl/workflow-runs/$runId"
    throw "Do NOT submit another run."
}

# -----------------------------------------------------------------------------
# TERMINAL RUN SUMMARY
# -----------------------------------------------------------------------------
Write-Host "`n=== TERMINAL RUN SUMMARY ===" -ForegroundColor Cyan
$terminalRun | Select-Object `
    id, project_id, status, is_terminal, `
    source_count, evidence_count, finding_count, insight_count, `
    report_count, review_count, `
    final_review_verdict, final_artifact_available, final_artifact_id |
    Format-List

Write-Host "Tasks (execution order by dependency):"
$terminalRun.tasks |
    Sort-Object { @(
        "task-collect-evidence",
        "task-extract-evidence",
        "task-assess-research-readiness",
        "task-analyze",
        "task-write-report",
        "task-review-report"
    ).IndexOf($_.definition_id) } |
    Select-Object definition_id, name, status, executor_id |
    Format-Table -AutoSize

# -----------------------------------------------------------------------------
# RESULTS
# -----------------------------------------------------------------------------
Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
$results = Invoke-RestMethod `
    -Uri "$BaseUrl/workflow-runs/$runId/results" `
    -Method GET `
    -Headers $authHeaders

Write-Host "results_ready: $($results.results_ready)"
Write-Host "status: $($results.status)"
Write-Host "research_loop_count: $($results.research_loop_count)"

if ($results.research_readiness) {
    $results.research_readiness | Select-Object `
        ready_for_analysis, targeted_research_required, termination_reason, `
        research_loop_count, research_loop_termination_reason |
        Format-List
}

# -----------------------------------------------------------------------------
# USAGE / BUDGET SUMMARY (workflow only — planner NOT included)
# -----------------------------------------------------------------------------
Write-Host "`n=== USAGE / BUDGET SUMMARY (workflow only) ===" -ForegroundColor Cyan
Write-Host "Planner calls: NOT DIRECTLY INCLUDED IN RUN USAGE SUMMARY."
Write-Host "Workflow cap: LLM_MAX_CALLS_PER_RUN=24. Total theoretical envelope <=33 incl. planner."

$usageItem = $results.task_results | Where-Object { $_.task_id -eq "_run_usage_summary" } | Select-Object -First 1
if ($usageItem -and $usageItem.snapshot) {
    $usage = $usageItem.snapshot
    $usage | Select-Object `
        total_llm_calls, total_elapsed_ms, budget_exhausted, `
        exhaustion_stage, exhaustion_reason, total_output_tokens, total_reasoning_tokens |
        Format-List

    if ($usage.stages) {
        Write-Host "Per-stage usage:"
        $usage.stages.GetEnumerator() | ForEach-Object {
            [PSCustomObject]@{
                stage = $_.Key
                llm_calls = $_.Value.llm_calls
                retries = $_.Value.retries
                elapsed_ms = $_.Value.elapsed_ms
                output_tokens = $_.Value.output_tokens
                reasoning_tokens = $_.Value.reasoning_tokens
            }
        } | Format-Table -AutoSize
    }

    if ($usage.total_llm_calls -gt 24) {
        Write-Warning "Workflow LLM calls ($($usage.total_llm_calls)) exceeded low-cost workflow cap (24)."
    }
} else {
    Write-Warning "No _run_usage_summary found in results.task_results."
}

# -----------------------------------------------------------------------------
# READINESS / TARGETED LOOP SUMMARY
# -----------------------------------------------------------------------------
Write-Host "`n=== READINESS / TARGETED LOOP ===" -ForegroundColor Cyan
if ($results.research_readiness) {
    $needRows = foreach ($rq in $results.research_readiness.research_question_assessments) {
        foreach ($need in $rq.information_need_assessments) {
            [PSCustomObject]@{
                information_need_id = $need.information_need_id
                research_question_id = $need.research_question_id
                status = $need.status
                gap_types = ($need.gap_types -join ", ")
                missing_aspects = ($need.missing_aspects -join ", ")
                search_directives = ($need.search_directives -join ", ")
                evidence_count = $need.evidence_count
            }
        }
    }
    $needRows | Format-Table -AutoSize
} else {
    Write-Warning "research_readiness not present in /results — check task-assess-research-readiness snapshot or logs."
}

if ($results.research_loop_history) {
    Write-Host "research_loop_history entries: $($results.research_loop_history.Count)"
    $results.research_loop_history | Select-Object -First 5 | Format-List
}

# Optional detailed JSON expansion:
# $results | ConvertTo-Json -Depth 20 | Out-File "artifacts\acceptance\serbia_e2e_results_$runId.json" -Encoding utf8

# -----------------------------------------------------------------------------
# POST-RUN FORENSIC DIAGNOSTIC (read-only PostgreSQL)
# -----------------------------------------------------------------------------
Write-Host "`n=== POST-RUN DIAGNOSTIC ===" -ForegroundColor Cyan
$previousDatabaseUrl = $env:DATABASE_URL
New-Item -ItemType Directory -Force -Path "artifacts\acceptance" | Out-Null
try {
    $env:DIAGNOSE_RUN_ID = $runId
    $env:DATABASE_URL = $DiagnosticDatabaseUrl
    python scripts/diagnose_live_run.py |
        Out-File "artifacts\acceptance\serbia_e2e_diagnose_$runId.txt" -Encoding utf8
    Get-Content "artifacts\acceptance\serbia_e2e_diagnose_$runId.txt" | Select-Object -First 80
} finally {
    Remove-Item Env:DIAGNOSE_RUN_ID -ErrorAction SilentlyContinue

    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
}

# -----------------------------------------------------------------------------
# WORKER LOGS (this run only)
# -----------------------------------------------------------------------------
Write-Host "`n=== WORKER LOGS (filtered) ===" -ForegroundColor Cyan
docker compose @ComposeArgs logs worker --no-log-prefix 2>&1 |
    Select-String -Pattern $runId |
    Select-Object -Last 80

Write-Host "`n=== API LOGS (submit/planner context — no planner call counter) ===" -ForegroundColor Cyan
docker compose @ComposeArgs logs api --no-log-prefix 2>&1 |
    Select-String -Pattern $runId, "research_submitted" |
    Select-Object -Last 40

Write-Host "`nOptional error filters:"
Write-Host ('  docker compose -f docker-compose.yml -f docker-compose.lowcost.yml logs worker | Select-String "' + $runId + '","ERROR","BudgetExhaustedError","structured_output","sufficiency","targeted"')

# -----------------------------------------------------------------------------
# STOP CONDITIONS — DO NOT RESUBMIT
# -----------------------------------------------------------------------------
Write-Host "`n=== STOP CONDITIONS ===" -ForegroundColor Yellow
Write-Host @"
DO NOT RESUBMIT if any of these occurred:
- HTTP submit error after run_id was created
- worker failure / contract exhaustion / BudgetExhaustedError
- terminal status=failed
- terminal insufficient with no final artifact (if acceptance required approve+artifact)
- report/review failure
- polling timeout
- idempotent_replay=True on fresh submit

ONE controlled run = ONE WorkflowRun ($runId)
Capture diagnostics and STOP for review.
"@ -ForegroundColor Yellow

# -----------------------------------------------------------------------------
# ACCEPTANCE CHECKLIST (operator judgment)
# -----------------------------------------------------------------------------
Write-Host "`n=== ACCEPTANCE CHECKLIST ===" -ForegroundColor Cyan
Write-Host @"
Technical PASS:
[ ] one fresh project created ($projectId)
[ ] one fresh run submitted ($runId)
[ ] idempotent_replay=False
[ ] worker claimed run
[ ] terminal state reached ($($terminalRun.status))
[ ] no uncaught exception in worker logs
[ ] workflow LLM calls <= 24 (_run_usage_summary; planner separate)
[ ] total theoretical LLM envelope understood (<=33 incl. planner)
[ ] targeted rounds <= 1
[ ] sources <= 5
[ ] persistence queryable via API + diagnose script

Pipeline PASS (review manually):
[ ] Planner valid (research_design present on run)
[ ] Sources acquired (source_count > 0)
[ ] Evidence non-empty (evidence_count > 0)
[ ] Readiness outcome plausible
[ ] No unexpected BLOCKED on legacy needs
[ ] Analysis completed if ready_for_analysis
[ ] Report completed if analysis ran
[ ] Review completed
[ ] Final artifact available if acceptance target is approve+artifact

Forensic PASS:
[ ] run_id preserved
[ ] workflow usage summary captured (planner NOT in summary)
[ ] readiness captured
[ ] loop history captured
[ ] diagnose_live_run.py output saved
[ ] worker + api logs checked

Overall E2E: PASS or FAIL — STOP FOR REVIEW (operator decision)
"@

Write-Host "`nRunbook section complete. run_id=$runId project_id=$projectId" -ForegroundColor Green

param([int]$Port = 18084)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$rootEnv = Join-Path $repo '.env'
$acceptanceEnv = Join-Path $repo '.env.prf08h'
$compose = Join-Path $repo 'docker-compose.prf08h.yml'
$expectedHead = '49efa7541f2ecefd6387f1bf27abbc936a8a8508'

& git -C $repo merge-base --is-ancestor $expectedHead HEAD
if ($LASTEXITCODE -ne 0) {
    throw 'PRF-08H requires the accepted PRF-08G source revision.'
}
$trackedChanges = @(& git -C $repo diff --name-only) + @(& git -C $repo diff --cached --name-only)
$committedChanges = @(& git -C $repo diff --name-only $expectedHead HEAD)
$allowedChanges = @('docker-compose.prf08h.yml', 'tools/prf08h_register_owner.py', 'scripts/prf08h_start.ps1', 'tools/prf08h_readonly_audit.py', 'docs/acceptance/PRF-08H-live-research-coverage-rerun.md')
if (@($trackedChanges + $committedChanges | Where-Object { $_ -notin $allowedChanges }).Count -ne 0) {
    throw 'Product source or unrelated tracked changes require review.'
}
if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -in @(8000, 18080, 18081, 18082, 18083)) {
    throw 'Select a free acceptance port distinct from active applications.'
}

function Read-RequiredLocalKey([string]$name) {
    if (-not (Test-Path -LiteralPath $rootEnv)) {
        throw 'Local provider configuration is absent.'
    }
    $matching = @(Get-Content -LiteralPath $rootEnv | Where-Object {
        $_ -match ('^\s*' + [regex]::Escape($name) + '\s*=')
    })
    if ($matching.Count -ne 1) {
        throw "Expected exactly one configured $name entry."
    }
    $value = ($matching[0] -split '=', 2)[1].Trim()
    if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and $value[0] -in @('"', "'")) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace($value) -or $value.Contains("`n") -or $value.Contains("`r")) {
        throw "$name is not safely configured."
    }
    return $value
}

if (-not (Test-Path -LiteralPath $acceptanceEnv)) {
    $openaiKey = Read-RequiredLocalKey 'OPENAI_API_KEY'
    $searchKey = Read-RequiredLocalKey 'SEARCH_API_KEY'
    $dbBytes = New-Object byte[] 24
    $uiBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($dbBytes)
        $rng.GetBytes($uiBytes)
    } finally {
        $rng.Dispose()
    }
    $dbPassword = [BitConverter]::ToString($dbBytes).Replace('-', '').ToLowerInvariant()
    $keyId = [Guid]::NewGuid().ToString('N').Substring(0, 12)
    $keySecret = [Convert]::ToBase64String($uiBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $uiKey = "airos_${keyId}_${keySecret}"
    $content = @(
        "PRF08H_DB_PASSWORD=$dbPassword"
        "PRF08H_UI_KEY=$uiKey"
        "PRF08H_PORT=$Port"
        "PRF08H_OPENAI_API_KEY=$openaiKey"
        "PRF08H_SEARCH_API_KEY=$searchKey"
    ) -join "`n"
    [System.IO.File]::WriteAllText($acceptanceEnv, $content + "`n")
    $openaiKey = $null
    $searchKey = $null
    $content = $null
} else {
    $recordedPort = Select-String -LiteralPath $acceptanceEnv -Pattern '^PRF08H_PORT=(\d+)$' | Select-Object -First 1
    if (-not $recordedPort -or [int]$recordedPort.Matches[0].Groups[1].Value -ne $Port) {
        throw 'The existing PRF-08H environment uses a different port; reuse it.'
    }
}

Push-Location $repo
try {
    $args = @('--project-name', 'ai_research_os_prf08h', '--env-file', $acceptanceEnv, '--file', $compose)
    & docker compose @args config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H Compose configuration is invalid.' }
    & docker compose @args build api
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H image build failed.' }
    & docker compose @args up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H PostgreSQL did not become healthy.' }
    & docker compose @args run --rm --no-deps api python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H migration failed.' }
    & docker compose @args run --rm --no-deps owner
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H local owner registration failed.' }
    & docker compose @args up -d --wait --no-build api worker
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08H API or worker did not become healthy.' }
    Write-Output "PRF-08H UI: http://127.0.0.1:$Port/ui/projects"
} finally {
    Pop-Location
}

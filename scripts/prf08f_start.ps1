param([int]$Port = 18083)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$rootEnv = Join-Path $repo '.env'
$acceptanceEnv = Join-Path $repo '.env.prf08f'
$compose = Join-Path $repo 'docker-compose.prf08f.yml'
$expectedHead = 'b9bf66662e37a95f02966bcae663fd5d4eeb4ece'

if ((& git -C $repo rev-parse HEAD) -ne $expectedHead) {
    throw 'PRF-08F requires the accepted PRF-08E source revision.'
}
if (@(& git -C $repo diff --name-only).Count -ne 0 -or
    @(& git -C $repo diff --cached --name-only).Count -ne 0) {
    throw 'Tracked source/index changes require review before building PRF-08F.'
}
if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -in @(8000, 18080, 18081, 18082)) {
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
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($dbBytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($uiBytes)
    $dbPassword = [Convert]::ToHexString($dbBytes).ToLowerInvariant()
    $keyId = [Guid]::NewGuid().ToString('N').Substring(0, 12)
    $keySecret = [Convert]::ToBase64String($uiBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $uiKey = "airos_${keyId}_${keySecret}"
    $content = @(
        "PRF08F_DB_PASSWORD=$dbPassword"
        "PRF08F_UI_KEY=$uiKey"
        "PRF08F_PORT=$Port"
        "PRF08F_OPENAI_API_KEY=$openaiKey"
        "PRF08F_SEARCH_API_KEY=$searchKey"
    ) -join "`n"
    [System.IO.File]::WriteAllText($acceptanceEnv, $content + "`n")
    $openaiKey = $null
    $searchKey = $null
    $content = $null
} else {
    $recordedPort = Select-String -LiteralPath $acceptanceEnv -Pattern '^PRF08F_PORT=(\d+)$' | Select-Object -First 1
    if (-not $recordedPort -or [int]$recordedPort.Matches[0].Groups[1].Value -ne $Port) {
        throw 'The existing PRF-08F environment uses a different port; reuse it.'
    }
}

Push-Location $repo
try {
    $args = @('--project-name', 'ai_research_os_prf08f', '--env-file', $acceptanceEnv, '--file', $compose)
    & docker compose @args config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F Compose configuration is invalid.' }
    & docker compose @args build api
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F image build failed.' }
    & docker compose @args up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F PostgreSQL did not become healthy.' }
    & docker compose @args run --rm --no-deps api python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F migration failed.' }
    & docker compose @args run --rm --no-deps owner
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F local owner registration failed.' }
    & docker compose @args up -d --wait --no-build api worker
    if ($LASTEXITCODE -ne 0) { throw 'PRF-08F API or worker did not become healthy.' }
    Write-Output "PRF-08F UI: http://127.0.0.1:$Port/ui/projects"
} finally {
    Pop-Location
}

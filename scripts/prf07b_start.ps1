param([int]$Port = 18080)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repo '.env.prf07b'
$composePath = Join-Path $repo 'docker-compose.prf07b.yml'

if ($Port -lt 1024 -or $Port -gt 65535 -or $Port -eq 8000) {
    throw 'Choose a free non-system port other than 8000.'
}
if (-not (Test-Path -LiteralPath $envPath)) {
    $dbBytes = New-Object byte[] 24
    $keyBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($dbBytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($keyBytes)
    $dbPassword = [Convert]::ToHexString($dbBytes).ToLowerInvariant()
    $keyId = [Guid]::NewGuid().ToString('N').Substring(0, 12)
    $keySecret = [Convert]::ToBase64String($keyBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $uiKey = "airos_${keyId}_${keySecret}"
    $content = "PRF07B_DB_PASSWORD=$dbPassword`nPRF07B_UI_KEY=$uiKey`nPRF07B_PORT=$Port`n"
    [System.IO.File]::WriteAllText($envPath, $content)
} else {
    $recordedPort = Select-String -LiteralPath $envPath -Pattern '^PRF07B_PORT=(\d+)$' | Select-Object -First 1
    if (-not $recordedPort -or [int]$recordedPort.Matches[0].Groups[1].Value -ne $Port) {
        throw 'The existing acceptance environment uses a different port. Reuse its recorded port.'
    }
}

Push-Location $repo
try {
    $args = @('--project-name', 'ai_research_os_prf07b', '--env-file', $envPath, '--file', $composePath)
    & docker compose @args config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance Compose configuration is invalid.' }
    & docker compose @args build api
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance image build failed.' }
    & docker compose @args up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance PostgreSQL did not become healthy.' }
    & docker compose @args run --rm --no-deps api python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance migration failed.' }
    & docker compose @args run --rm --no-deps seed
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance fixture seed failed.' }
    & docker compose @args up -d --wait --no-build api worker
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance API or worker did not become healthy.' }
    Write-Output "Acceptance UI: http://127.0.0.1:$Port/ui/projects"
} finally {
    Pop-Location
}

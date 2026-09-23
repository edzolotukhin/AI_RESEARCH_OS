$ErrorActionPreference = 'Stop'
try {
    $running = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/ui/projects/prf05b-canonical-desk/outputs' -UseBasicParsing -TimeoutSec 2
    if ($running.StatusCode -eq 200 -and $running.Content.Contains('Активність проєкту')) {
        Write-Output 'PRF-05B visual server already running at http://127.0.0.1:8010'
        exit 0
    }
} catch { }
$databaseName = 'ai_research_os_prf05b_demo_20260923_v2'
$existing = docker exec ai_research_os_postgres psql -U ai_research_os -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$databaseName'"
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect PostgreSQL databases' }
if (-not $existing) {
    docker exec ai_research_os_postgres psql -U ai_research_os -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $databaseName"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create disposable PRF-05B demo database' }
}
$inspection = docker inspect ai_research_os_postgres | ConvertFrom-Json
$passwordEntry = $inspection[0].Config.Env | Where-Object { $_ -match '^POSTGRES_PASSWORD=' } | Select-Object -First 1
if (-not $passwordEntry) { throw 'PostgreSQL password configuration is unavailable' }
$encodedPassword = [uri]::EscapeDataString($passwordEntry.Substring(18))
$env:PRF05B_DEMO_DATABASE_URL = "postgresql+psycopg://ai_research_os:${encodedPassword}@127.0.0.1:5432/$databaseName"
$server = Start-Process -FilePath 'python' -ArgumentList '-m', 'tools.prf05b_visual_server' -WorkingDirectory (Resolve-Path '.').Path -WindowStyle Hidden -PassThru
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/ui/projects/prf05b-canonical-desk/outputs' -UseBasicParsing -TimeoutSec 2
        if ($page.StatusCode -eq 200 -and $page.Content.Contains('Активність проєкту')) {
            Write-Output "PRF-05B visual server ready: http://127.0.0.1:8010 (PID $($server.Id))"
            exit 0
        }
    } catch { }
    if ($server.HasExited) { throw "PRF-05B visual server exited during startup (PID $($server.Id))" }
}
throw 'PRF-05B visual server did not become ready within 60 seconds'

# Full local verification: unit tests, PostgreSQL tests, and git diff --check.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_test_env.ps1")

$repositoryRoot = Get-RepositoryRoot
Set-Location $repositoryRoot

Write-Host "=== Unit tests ==="
& (Join-Path $PSScriptRoot "test_unit.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "=== PostgreSQL tests ==="
& (Join-Path $PSScriptRoot "test_postgres.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "=== git diff --check ==="
git diff --check
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "All local verification checks passed."
exit 0

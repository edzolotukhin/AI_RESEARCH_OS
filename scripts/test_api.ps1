# Run in-memory HTTP API tests and OpenAPI smoke checks.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_test_env.ps1")

$repositoryRoot = Get-RepositoryRoot
Set-Location $repositoryRoot

$warningArgs = @("-W", "error::ResourceWarning")

Write-Host "[1/2] API tests"
Invoke-PythonCommand -Arguments (
    $warningArgs + @(
        "-m", "unittest", "discover",
        "-s", "tests/api",
        "-p", "test_*.py",
        "-v"
    )
)

Write-Host "[2/2] OpenAPI smoke"
Invoke-PythonCommand -Arguments @(
    "-c",
    "from tests.api.helpers import build_test_client; c,_=build_test_client(); assert c.get('/openapi.json').status_code==200"
)

Write-Host "API verification passed."
exit 0

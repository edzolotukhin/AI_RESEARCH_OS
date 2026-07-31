# Run the default unit test suite without PostgreSQL integration dependencies.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_test_env.ps1")

$repositoryRoot = Get-RepositoryRoot
Set-Location $repositoryRoot

$savedEnv = @{}
foreach ($name in @(
        "POSTGRESQL_INTEGRATION_TESTS",
        "DATABASE_URL_TEST",
        "DATABASE_URL",
        "PERSISTENCE_BACKEND"
    )) {
    Save-EnvVar -Name $name -Store $savedEnv
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
}

try {
    Write-Host "Running unit test suite from $repositoryRoot"
    Invoke-PythonCommand -Arguments @("run_tests.py")
    Write-Host "Unit test suite passed."
    exit 0
}
finally {
    Restore-EnvVars -Store $savedEnv
}

# Worker integration tests including process-level crash/recovery.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_test_env.ps1")

$repositoryRoot = Get-RepositoryRoot
Set-Location $repositoryRoot

$savedEnv = @{}
foreach ($name in @(
        "POSTGRESQL_INTEGRATION_TESTS",
        "DATABASE_URL_TEST",
        "DATABASE_URL",
        "PERSISTENCE_BACKEND",
        "WORKER_LEASE_DURATION_SECONDS",
        "WORKER_HEARTBEAT_INTERVAL_SECONDS",
        "WORKER_CRASH_TEST_GATE_DIR",
        "WORKER_ID",
        "WORKER_CRASH_TEST_MODE"
    )) {
    Save-EnvVar -Name $name -Store $savedEnv
}

try {
    Write-Host "[1/4] Docker PostgreSQL"
    Invoke-ExternalCommand -CommandName "docker compose up -d postgres" -CommandBlock {
        docker compose up -d postgres
    } | Out-Null

    $postgresConfig = Get-DockerComposePostgresConfig -RepositoryRoot $repositoryRoot
    Wait-PostgresContainerHealthy -ContainerName $postgresConfig.ContainerName

    Write-Host "[2/4] Alembic"
    Ensure-PostgresTestDatabase `
        -ContainerName $postgresConfig.ContainerName `
        -User $postgresConfig.User `
        -MainDatabase $postgresConfig.MainDatabase `
        -TestDatabase $postgresConfig.TestDatabase
    Set-PostgresTestEnv `
        -User $postgresConfig.User `
        -Password $postgresConfig.Password `
        -TestDatabase $postgresConfig.TestDatabase
    Invoke-PythonCommand -Arguments @("-m", "alembic", "upgrade", "head")

    $warningArgs = @("-W", "error::ResourceWarning")

    Write-Host "[3/4] Worker PostgreSQL integration"
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest", "discover",
            "-s", "tests/integration/postgresql",
            "-p", "test_worker_execution.py",
            "-v"
        )
    )
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest", "discover",
            "-s", "tests/integration/postgresql",
            "-p", "test_claim_matrix.py",
            "-v"
        )
    )
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest",
            "tests.application.execution.test_lease_guards",
            "-v"
        )
    )

    Write-Host "[4/4] Process crash/recovery"
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest",
            "tests.integration.worker.test_process_crash_recovery",
            "-v"
        )
    )

    Write-Host "Worker verification passed."
    exit 0
}
finally {
    Restore-EnvVars -Store $savedEnv
}

# Run PostgreSQL contract and integration tests against Docker Compose PostgreSQL.
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
}

try {
    Write-Host "[1/5] Docker"
    docker version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker is not available."
    }
    docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose is not available."
    }
    docker compose up -d postgres | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up -d postgres failed."
    }

    $postgresConfig = Get-DockerComposePostgresConfig -RepositoryRoot $repositoryRoot
    Write-Host "[2/5] PostgreSQL health"
    Wait-PostgresContainerHealthy -ContainerName $postgresConfig.ContainerName
    Write-Host "PostgreSQL container is healthy."

    Write-Host "[3/5] Alembic"
    Ensure-PostgresTestDatabase `
        -ContainerName $postgresConfig.ContainerName `
        -User $postgresConfig.User `
        -MainDatabase $postgresConfig.MainDatabase `
        -TestDatabase $postgresConfig.TestDatabase
    Set-PostgresTestEnv `
        -User $postgresConfig.User `
        -Password $postgresConfig.Password `
        -TestDatabase $postgresConfig.TestDatabase
    Write-Host "Using test database: $($postgresConfig.TestDatabase)"

    Invoke-PythonCommand -Arguments @("-m", "alembic", "upgrade", "head")
    Invoke-PythonCommand -Arguments @("-m", "alembic", "current")

    $warningArgs = @("-W", "error::ResourceWarning")

    Write-Host "[4/5] Repository contracts"
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest",
            "tests.application.ports.test_postgresql_repository_contracts",
            "-v"
        )
    )

    Write-Host "[5/5] Integration tests"
    Invoke-PythonCommand -Arguments (
        $warningArgs + @(
            "-m", "unittest", "discover",
            "-s", "tests/integration/postgresql",
            "-p", "test_*.py",
            "-v"
        )
    )

    Write-Host "PostgreSQL verification passed."
    exit 0
}
finally {
    Restore-EnvVars -Store $savedEnv
}

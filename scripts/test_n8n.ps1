# External orchestration HTTP verification (n8n contract without n8n UI in CI).
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
    Write-Host "[1/5] Docker PostgreSQL"
    Invoke-ExternalCommand -CommandName "docker compose up -d postgres" -CommandBlock {
        docker compose up -d postgres
    } | Out-Null

    $postgresConfig = Get-DockerComposePostgresConfig -RepositoryRoot $repositoryRoot
    Wait-PostgresContainerHealthy -ContainerName $postgresConfig.ContainerName

    Write-Host "[2/5] Alembic"
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

    Write-Host "[3/5] External orchestration integration"
    Invoke-PythonCommand -Arguments @(
        "-W", "error::ResourceWarning",
        "-m", "unittest",
        "tests.integration.api.test_external_orchestration",
        "-v"
    )

    Write-Host "[4/5] n8n product acceptance"
    Invoke-PythonCommand -Arguments @(
        "-W", "error::ResourceWarning",
        "-m", "unittest",
        "tests.integration.api.test_n8n_product_acceptance",
        "-v"
    )

    Write-Host "[5/5] n8n native workflow validation"
    Invoke-PythonCommand -Arguments @(
        "-W", "error::ResourceWarning",
        "-m", "unittest",
        "tests.integration.n8n.test_n8n_native_workflow",
        "-v"
    )

    Write-Host "External orchestration verification passed."
    exit 0
}
finally {
    Restore-EnvVars -Store $savedEnv
}

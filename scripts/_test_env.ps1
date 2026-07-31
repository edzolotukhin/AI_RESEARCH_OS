# Shared helpers for local verification scripts.
# Dot-sourced by scripts/test_unit.ps1, scripts/test_postgres.ps1, and scripts/test_all.ps1.

function Get-RepositoryRoot {
    $root = Resolve-Path (Join-Path $PSScriptRoot "..")
    return $root.Path
}

function Save-EnvVar {
    param(
        [string]$Name,
        [hashtable]$Store
    )

    if (Test-Path -Path "Env:$Name") {
        $Store[$Name] = (Get-Item -Path "Env:$Name").Value
    }
}

function Restore-EnvVars {
    param([hashtable]$Store)

    foreach ($name in @(
            "POSTGRESQL_INTEGRATION_TESTS",
            "DATABASE_URL_TEST",
            "DATABASE_URL",
            "PERSISTENCE_BACKEND"
        )) {
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }

    foreach ($entry in $Store.GetEnumerator()) {
        Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
    }
}

function Clear-PostgresEnvVars {
    Remove-Item -Path "Env:POSTGRESQL_INTEGRATION_TESTS" -ErrorAction SilentlyContinue
    Remove-Item -Path "Env:DATABASE_URL_TEST" -ErrorAction SilentlyContinue
    Remove-Item -Path "Env:DATABASE_URL" -ErrorAction SilentlyContinue
}

function Get-DockerComposePostgresConfig {
    param(
        [string]$RepositoryRoot,
        [string]$TestDatabaseName = "ai_research_os_test"
    )

    if ($TestDatabaseName -notmatch "test") {
        throw "Refusing to use integration database '$TestDatabaseName' without 'test' in the name."
    }

    $composeFile = Join-Path $RepositoryRoot "docker-compose.yml"
    if (-not (Test-Path $composeFile)) {
        throw "docker-compose.yml not found at $composeFile"
    }

    $content = Get-Content -Path $composeFile -Raw
    $user = ([regex]::Match($content, "POSTGRES_USER:\s*(\S+)")).Groups[1].Value
    $password = ([regex]::Match($content, "POSTGRES_PASSWORD:\s*(\S+)")).Groups[1].Value
    $mainDatabase = ([regex]::Match($content, "POSTGRES_DB:\s*(\S+)")).Groups[1].Value

    if (-not $user -or -not $password -or -not $mainDatabase) {
        throw "Could not read PostgreSQL credentials from docker-compose.yml"
    }

    return [PSCustomObject]@{
        User = $user
        Password = $password
        MainDatabase = $mainDatabase
        TestDatabase = $TestDatabaseName
        ContainerName = "ai_research_os_postgres"
    }
}

function Wait-PostgresContainerHealthy {
    param(
        [string]$ContainerName,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = docker inspect --format "{{.State.Health.Status}}" $ContainerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $health -eq "healthy") {
            return
        }
        Start-Sleep -Seconds 2
    }

    throw "PostgreSQL container '$ContainerName' did not become healthy within ${TimeoutSeconds}s."
}

function Ensure-PostgresTestDatabase {
    param(
        [string]$ContainerName,
        [string]$User,
        [string]$MainDatabase,
        [string]$TestDatabase
    )

    $exists = docker exec $ContainerName psql -U $User -d $MainDatabase -tAc `
        "SELECT 1 FROM pg_database WHERE datname = '$TestDatabase';"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query PostgreSQL for test database existence."
    }

    if ($exists.Trim() -ne "1") {
        docker exec $ContainerName psql -U $User -d $MainDatabase -c `
            "CREATE DATABASE $TestDatabase;" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create test database '$TestDatabase'."
        }
    }
}

function Set-PostgresTestEnv {
    param(
        [string]$User,
        [string]$Password,
        [string]$TestDatabase
    )

    $databaseUrl = "postgresql+psycopg://${User}:$Password@localhost:5432/$TestDatabase"
    $env:POSTGRESQL_INTEGRATION_TESTS = "1"
    $env:DATABASE_URL_TEST = $databaseUrl
    $env:DATABASE_URL = $databaseUrl
}

function Invoke-PythonCommand {
    param(
        [string[]]$Arguments
    )

    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: python $($Arguments -join ' ')"
    }
}

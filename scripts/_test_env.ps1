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
        $result = Invoke-ExternalCommand -AllowNonZeroExit -Quiet -CommandName "docker inspect health" -CommandBlock {
            docker inspect --format "{{.State.Health.Status}}" $ContainerName
        }
        if ($result.ExitCode -eq 0 -and $result.Text.Trim() -eq "healthy") {
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

    $existsResult = Invoke-ExternalCommand -Quiet -CommandName "docker exec psql check database" -CommandBlock {
        docker exec $ContainerName psql -U $User -d $MainDatabase -tAc `
            "SELECT 1 FROM pg_database WHERE datname = '$TestDatabase';"
    }
    $exists = $existsResult.Text.Trim()
    if ($existsResult.ExitCode -ne 0) {
        throw "Failed to query PostgreSQL for test database existence."
    }

    if ($exists -ne "1") {
        Invoke-ExternalCommand -Quiet -CommandName "docker exec psql create database" -CommandBlock {
            docker exec $ContainerName psql -U $User -d $MainDatabase -c `
                "CREATE DATABASE $TestDatabase;"
        } | Out-Null
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

function Invoke-ExternalCommand {
    <#
    .SYNOPSIS
        Runs a native or external command without treating stderr progress output as failure.

    Native tools such as Docker Compose and Python often write normal status lines to stderr.
    With $ErrorActionPreference = "Stop", PowerShell would treat those as terminating errors
    even when the process exit code is zero. This helper evaluates $LASTEXITCODE instead.
    #>
    param(
        [Parameter(Mandatory)]
        [scriptblock]$CommandBlock,
        [string]$CommandName,
        [switch]$AllowNonZeroExit,
        [switch]$Quiet
    )

    if ([string]::IsNullOrWhiteSpace($CommandName)) {
        $CommandName = $CommandBlock.ToString().Trim()
    }

    $previousErrorAction = $ErrorActionPreference
    $exitCode = 0
    $output = @()
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $CommandBlock 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }

    $lines = foreach ($item in $output) {
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            [string]$item.Exception.Message
        } else {
            [string]$item
        }
    }

    if (-not $Quiet) {
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                Write-Host $line
            }
        }
    }

    $result = [PSCustomObject]@{
        ExitCode = $exitCode
        Output = $lines
        Text = ($lines -join [Environment]::NewLine)
    }

    if (-not $AllowNonZeroExit -and $exitCode -ne 0) {
        throw "External command failed: $CommandName (exit code $exitCode)"
    }

    return $result
}

function Invoke-PythonCommand {
    param(
        [string[]]$Arguments
    )

    $commandName = "python $($Arguments -join ' ')"
    Invoke-ExternalCommand -CommandName $commandName -CommandBlock {
        & python @Arguments
    } | Out-Null
}

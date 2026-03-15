param(
    [string]$BackendUrl = 'http://127.0.0.1:8000',
    [string]$MirrorRoot = ''
)

$ErrorActionPreference = 'Stop'

function Invoke-Robocopy {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    $baseArgs = @($Source, $Destination, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP') + $ExtraArgs
    & robocopy @baseArgs | Out-Null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ge 8) {
        throw "robocopy failed with exit code $exitCode for $Source"
    }
}

function Assert-NodeVersion {
    $nodeVersion = (& node -v).TrimStart('v')
    $version = [Version]$nodeVersion
    $minimum = [Version]'18.18.0'
    if ($version -lt $minimum) {
        throw "Node.js $nodeVersion is too old. Required: >= 18.18.0"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$frontendSource = Join-Path $repoRoot 'frontend'
$contractsSource = Join-Path $repoRoot 'contracts'

if (-not $MirrorRoot) {
    $MirrorRoot = Join-Path $env:TEMP 'rumor-checking-live'
}

$mirrorFrontend = Join-Path $MirrorRoot 'frontend'
$mirrorContracts = Join-Path $MirrorRoot 'contracts'

Assert-NodeVersion

New-Item -ItemType Directory -Force -Path $MirrorRoot | Out-Null
Invoke-Robocopy -Source $frontendSource -Destination $mirrorFrontend -ExtraArgs @('/XD', '.next', 'node_modules')
Invoke-Robocopy -Source $contractsSource -Destination $mirrorContracts

$mirrorNext = Join-Path $mirrorFrontend '.next'
if (Test-Path $mirrorNext) {
    Remove-Item $mirrorNext -Recurse -Force
}

Write-Host "Mirrored frontend to: $mirrorFrontend"
Write-Host "Mirrored contracts to: $mirrorContracts"
Write-Host "Backend URL: $BackendUrl"
Write-Host ''
Write-Host 'Running frontend checks from the Windows-local mirror...'

$env:NEXT_PUBLIC_API_BASE_URL = $BackendUrl

Push-Location $mirrorFrontend
try {
    npm ci --no-audit --no-fund
    npm run typecheck
    npm test
    npm run build
}
finally {
    Pop-Location
}

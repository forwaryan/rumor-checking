param(
    [string]$BackendUrl = 'http://127.0.0.1:8000',
    [int]$Port = 3020,
    [string]$MirrorRoot = ''
)

$ErrorActionPreference = 'Stop'

function Invoke-Robocopy {
    param(
        [string]$Source,
        [string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    $baseArgs = @($Source, $Destination, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP') + $ExtraArgs
    & robocopy @baseArgs | Out-Null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ge 8) {
        throw "robocopy failed with exit code $exitCode for $Source"
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

New-Item -ItemType Directory -Force -Path $MirrorRoot | Out-Null
Invoke-Robocopy -Source $frontendSource -Destination $mirrorFrontend -ExtraArgs @('/XD', '.next')
Invoke-Robocopy -Source $contractsSource -Destination $mirrorContracts

$mirrorNext = Join-Path $mirrorFrontend '.next'
if (Test-Path $mirrorNext) {
    Remove-Item $mirrorNext -Recurse -Force
}

Write-Host "Mirrored frontend to: $mirrorFrontend"
Write-Host "Mirrored contracts to: $mirrorContracts"
Write-Host "Backend proxy target: $BackendUrl"
Write-Host "Frontend URL: http://127.0.0.1:$Port"
Write-Host ''
Write-Host 'Starting Next.js from the Windows-local mirror to avoid WSL/UNC watcher issues...'

$cmd = "cd /d `"$mirrorFrontend`" && set BACKEND_PROXY_TARGET=$BackendUrl && set NEXT_PUBLIC_API_BASE_URL= && node node_modules\next\dist\bin\next dev -p $Port"
cmd.exe /c $cmd



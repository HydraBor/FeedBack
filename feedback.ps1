param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status',
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [ValidateRange(1, 300)]
    [int]$Timeout = 30
)
$ErrorActionPreference = 'Stop'
$feedbackDistribution = if ($env:FEEDBACK_WSL_DISTRO) { $env:FEEDBACK_WSL_DISTRO } else { 'Ubuntu' }
if ($PSScriptRoot -match '^\\\\wsl(?:\.localhost|\$)\\([^\\]+)\\(.+)$') {
    if (!$env:FEEDBACK_WSL_DISTRO) { $feedbackDistribution = $Matches[1] }
    $feedbackProjectDirectory = '/' + $Matches[2].Replace('\', '/')
} else {
    $feedbackProjectDirectory = wsl.exe -d $feedbackDistribution -- wslpath -u $PSScriptRoot
    if ($LASTEXITCODE -ne 0 -or !$feedbackProjectDirectory) {
        throw 'Cannot resolve the project directory in WSL. Check the WSL distribution and project path.'
    }
}

function Read-FeedbackStatus {
    $feedbackOutput = wsl.exe -d $feedbackDistribution --cd $feedbackProjectDirectory -- .venv/bin/python scripts/service.py status --json
    if ($LASTEXITCODE -notin @(0, 1)) { throw 'Cannot inspect the service. Install project dependencies first.' }
    return (($feedbackOutput -join "`n") | ConvertFrom-Json)
}

if ($Action -eq 'start') {
    $feedbackStatus = Read-FeedbackStatus
    if ($feedbackStatus.status -ne 'stopped') {
        if (!$feedbackStatus.managed) {
            throw 'An older foreground service is running. Run feedback.ps1 stop, then feedback.ps1 start to switch to background mode.'
        }
        if ($feedbackStatus.status -eq 'running') {
            Write-Host ("Already running: http://localhost:" + $feedbackStatus.port + '/')
            exit 0
        }
    } else {
        # Separate hidden WSL host survives this terminal and retains Windows interop.
        $feedbackArguments = @(
            '-d', $feedbackDistribution,
            '--cd', ('"' + $feedbackProjectDirectory + '"'), '--',
            '.venv/bin/python', 'scripts/service.py', 'start', '--hold', '--port', $Port, '--timeout', $Timeout
        )
        $feedbackHost = Start-Process -FilePath 'wsl.exe' -ArgumentList $feedbackArguments -WindowStyle Hidden -PassThru
    }
    $feedbackDeadline = (Get-Date).AddSeconds($Timeout)
    do {
        Start-Sleep -Milliseconds 500
        $feedbackStatus = Read-FeedbackStatus
        if ($feedbackStatus.status -eq 'running') {
            Write-Host ("Started in background: http://localhost:" + $feedbackStatus.port + '/')
            Write-Host ("Log: " + (Join-Path $PSScriptRoot '.run\service.log'))
            exit 0
        }
        if ($feedbackHost -and $feedbackHost.HasExited) {
            throw 'Startup failed. Check .run/service.log in the project directory.'
        }
    } while ((Get-Date) -lt $feedbackDeadline)
    throw 'Startup is not ready yet. Check feedback.ps1 status and .run/service.log.'
}
if ($Action -eq 'stop') {
    wsl.exe -d $feedbackDistribution --cd $feedbackProjectDirectory -- .venv/bin/python scripts/service.py stop --timeout $Timeout
} else {
    wsl.exe -d $feedbackDistribution --cd $feedbackProjectDirectory -- .venv/bin/python scripts/service.py status
}
exit $LASTEXITCODE

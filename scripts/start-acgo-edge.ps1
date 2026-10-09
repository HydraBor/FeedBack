$ErrorActionPreference = 'Stop'
$edgePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
if (!(Test-Path -LiteralPath $edgePath)) { throw 'Microsoft Edge was not found. Please install Edge first.' }
$acgoProfile = Join-Path $env:LOCALAPPDATA 'Feedback-ACGO\Edge-Profile'
New-Item -ItemType Directory -Force -Path $acgoProfile | Out-Null
# This window is intentionally visible: the lecturer signs in themselves.
Start-Process -FilePath $edgePath -ArgumentList @(
    '--remote-debugging-port=9223', '--remote-debugging-address=127.0.0.1',
    ('--user-data-dir="' + $acgoProfile + '"'), '--no-first-run',
    '--disable-extensions', 'https://www.acgo.cn/'
)
Write-Host 'Sign in to ACGO in the new Edge window and keep it open. Then return to the feedback app.'

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
wsl.exe -d $feedbackDistribution --cd $feedbackProjectDirectory -- bash scripts/start.sh
exit $LASTEXITCODE

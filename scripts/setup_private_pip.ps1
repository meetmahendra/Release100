<#
.SYNOPSIS
    Configures pip.ini with private GitHub Packages registry credentials for 1-click installation.

.DESCRIPTION
    Configures pip with your private GitHub Packages token once.
    After running this script, you can run clean commands without specifying URLs:
      pip install release100-core
      pip install release100-cartridge-temperature-marker

.PARAMETER GitHubUser
    Your GitHub username.

.PARAMETER GitHubToken
    Your GitHub Personal Access Token (PAT) with 'read:packages' scope.

.PARAMETER Org
    The GitHub Organization or owner repository name. Default is 'your-org'.

.EXAMPLE
    .\scripts\setup_private_pip.ps1 -GitHubUser "depali" -GitHubToken "ghp_xxxxxxxxxxxx" -Org "Canectar"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$GitHubUser,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$GitHubToken,

    [Parameter(Mandatory = $false, Position = 2)]
    [string]$Org = "canectar"
)

$pipDir = Join-Path $env:APPDATA "pip"
if (-not (Test-Path $pipDir)) {
    New-Item -ItemType Directory -Path $pipDir -Force | Out-Null
}

$pipIniPath = Join-Path $pipDir "pip.ini"
$indexUrl = "https://${GitHubUser}:${GitHubToken}@nuget.pkg.github.com/${Org}/simple/"

$iniContent = @"
[global]
extra-index-url = $indexUrl
"@

Set-Content -Path $pipIniPath -Value $iniContent -Encoding UTF8 -Force

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  PRIVATE PACKAGE REGISTRY CONFIGURED SUCCESSFULLY" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "Config Path : $pipIniPath" -ForegroundColor Gray
Write-Host "Registry    : GitHub Packages ($Org)" -ForegroundColor Gray
Write-Host ""
Write-Host "You can now install packages directly with standard pip commands:" -ForegroundColor Yellow
Write-Host "  pip install release100-core" -ForegroundColor White
Write-Host "  pip install release100-cartridge-temperature-marker" -ForegroundColor White
Write-Host "  pip install release100-cartridge-mail-organizer" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan

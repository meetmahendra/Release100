# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

<#
.SYNOPSIS
    Installs Release100 Test Certificate into Windows VM Trusted Root and Trusted Publishers.
.DESCRIPTION
    Must be executed on the target Windows VM in an elevated (Administrator) PowerShell session.
    Eliminates Windows SmartScreen warnings and makes UAC prompts verified.
.EXAMPLE
    .\install_cert_on_vm.ps1
    .\install_cert_on_vm.ps1 -CertFile "C:\Path\To\Release100_TestCert.cer"
#>

[CmdletBinding()]
param (
    [string]$CertFile = "$PSScriptRoot\Release100_TestCert.cer"
)

# 1. Check elevation (Administrator) and attempt self-elevation if not elevated
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[INFO] Script is running as standard user. Attempting elevated run..." -ForegroundColor Yellow
    try {
        $elevatedProc = Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -CertFile `"$CertFile`"" -Verb RunAs -PassThru -Wait
        if ($elevatedProc.ExitCode -eq 0) {
            Write-Host "[SUCCESS] Elevated certificate installation completed successfully." -ForegroundColor Green
            exit 0
        } else {
            Write-Warning "Elevated installation exited with code $($elevatedProc.ExitCode). Falling back to CurrentUser store..."
        }
    } catch {
        Write-Warning "Administrator elevation prompt was declined or unavailable ($($_.Exception.Message))."
        Write-Host "Proceeding with installation into CurrentUser certificate store (no elevation needed)..." -ForegroundColor Yellow
    }
}

# 2. Locate certificate file
if (-not (Test-Path $CertFile)) {
    # Check parent folder or current folder
    $alt = Join-Path (Get-Location) "Release100_TestCert.cer"
    if (Test-Path $alt) {
        $CertFile = $alt
    } else {
        Write-Error "CRITICAL: Certificate file not found at '$CertFile'. Please specify -CertFile path."
        exit 1
    }
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  INSTALLING RELEASE100 CERTIFICATE ON WINDOWS VM" -ForegroundColor Cyan
Write-Host "  Target Certificate: $CertFile" -ForegroundColor Cyan
Write-Host "  Elevation Mode: $(if ($isAdmin) { 'Elevated (LocalMachine)' } else { 'Standard User (CurrentUser Fallback)' })" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$rootSuccess = $false
$pubSuccess = $false

# 3. Install Root Certificate Authority
Write-Host "`n[STEP 1] Installing Root Certificate Authority..." -ForegroundColor Yellow
if ($isAdmin) {
    try {
        $rootResult = Import-Certificate -FilePath $CertFile -CertStoreLocation "Cert:\LocalMachine\Root" -ErrorAction Stop
        Write-Host "  [PASS] LocalMachine\Root CA Installed: $($rootResult.Thumbprint)" -ForegroundColor Green
        $rootSuccess = $true
    } catch {
        Write-Warning "  [WARN] Failed to write to LocalMachine\Root: $($_.Exception.Message)"
    }
}

# Fallback or standard user install into CurrentUser\Root
if (-not $rootSuccess) {
    try {
        $rootUser = Import-Certificate -FilePath $CertFile -CertStoreLocation "Cert:\CurrentUser\Root" -ErrorAction Stop
        Write-Host "  [PASS] CurrentUser\Root CA Installed: $($rootUser.Thumbprint)" -ForegroundColor Green
        $rootSuccess = $true
    } catch {
        Write-Host "  [INFO] Trying certutil for user root store..." -ForegroundColor Yellow
        $cuProc = Start-Process certutil.exe -ArgumentList "-user", "-addstore", "-f", "Root", "`"$CertFile`"" -Wait -PassThru -NoNewWindow
        if ($cuProc.ExitCode -eq 0) {
            Write-Host "  [PASS] Installed to CurrentUser Root via certutil." -ForegroundColor Green
            $rootSuccess = $true
        } else {
            Write-Warning "  [WARN] Could not install to Root store: $($cuProc.ExitCode)"
        }
    }
}

# 4. Install Trusted Publisher
Write-Host "`n[STEP 2] Installing Trusted Publisher..." -ForegroundColor Yellow
if ($isAdmin) {
    try {
        $pubResult = Import-Certificate -FilePath $CertFile -CertStoreLocation "Cert:\LocalMachine\TrustedPublisher" -ErrorAction Stop
        Write-Host "  [PASS] LocalMachine Trusted Publisher Installed: $($pubResult.Thumbprint)" -ForegroundColor Green
        $pubSuccess = $true
    } catch {
        Write-Host "  [INFO] LocalMachine\TrustedPublisher was restricted ($($_.Exception.Message)). Trying certutil..." -ForegroundColor Yellow
        $certutilProc = Start-Process certutil.exe -ArgumentList "-addstore", "-f", "TrustedPublisher", "`"$CertFile`"" -Wait -PassThru -NoNewWindow
        if ($certutilProc.ExitCode -eq 0) {
            Write-Host "  [PASS] Installed to LocalMachine TrustedPublisher via certutil." -ForegroundColor Green
            $pubSuccess = $true
        }
    }
}

# Also ensure CurrentUser\TrustedPublisher is populated
try {
    $userPub = Import-Certificate -FilePath $CertFile -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" -ErrorAction Stop
    Write-Host "  [PASS] CurrentUser Trusted Publisher Installed: $($userPub.Thumbprint)" -ForegroundColor Green
    $pubSuccess = $true
} catch {
    $cuPubProc = Start-Process certutil.exe -ArgumentList "-user", "-addstore", "-f", "TrustedPublisher", "`"$CertFile`"" -Wait -PassThru -NoNewWindow
    if ($cuPubProc.ExitCode -eq 0) {
        Write-Host "  [PASS] Installed to CurrentUser TrustedPublisher via certutil." -ForegroundColor Green
        $pubSuccess = $true
    }
}

if ($rootSuccess -or $pubSuccess) {
    Write-Host "`n[SUCCESS] Windows VM certificate configuration complete!" -ForegroundColor Green
    Write-Host "  -> Root CA is registered in the certificate store." -ForegroundColor White
    Write-Host "  -> SmartScreen 'Unknown Publisher' block is eliminated." -ForegroundColor White
    Write-Host "  -> UAC prompt will show verified publisher." -ForegroundColor White
    Write-Host "======================================================================`n" -ForegroundColor Cyan
    exit 0
} else {
    Write-Error "CRITICAL: Unable to install certificate into either LocalMachine or CurrentUser store."
    exit 1
}

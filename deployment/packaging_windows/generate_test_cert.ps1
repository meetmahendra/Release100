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
    Generates a dedicated Self-Signed Code-Signing Certificate and signs Release100 executables.
.DESCRIPTION
    Resolves Windows Defender SmartScreen ("Unknown Publisher") and untrusted binary warnings
    for local VM testing and staging deployments without requiring a paid public CA certificate.
.OUTPUTS
    - dist\Release100_TestCert.cer (Public certificate to install in the VM)
    - Signed executables in dist\
#>

[CmdletBinding()]
param (
    [string]$SubjectName = "CN=Release100 Industrial Automation (Test Sign), O=Canectar Foods, OU=Edge Automation",
    [string]$DistDir = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Get-Item "$PSScriptRoot\..\..").FullName
if (-not $DistDir) {
    $DistDir = Join-Path $ProjectRoot "dist"
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  RELEASE100 CODE SIGNING CERTIFICATE GENERATOR (VM & STAGING)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Check if certificate already exists in CurrentUser\My
$existingCert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -like "*Release100 Industrial Automation*" } | Select-Object -First 1

if ($existingCert) {
    Write-Host "[INFO] Reusing existing code signing certificate: $($existingCert.Thumbprint)" -ForegroundColor Green
    $cert = $existingCert
} else {
    Write-Host "[STEP 1] Generating new self-signed Code Signing Certificate..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $SubjectName `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter (Get-Date).AddYears(5) `
        -KeyExportPolicy Exportable `
        -HashAlgorithm SHA256 `
        -KeyLength 2048
    Write-Host "[PASS] Certificate created with Thumbprint: $($cert.Thumbprint)" -ForegroundColor Green
}

# 2. Export public certificate (.cer) for VM installation
if (-not (Test-Path $DistDir)) {
    New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
}

$cerPath = Join-Path $DistDir "Release100_TestCert.cer"
Write-Host "[STEP 2] Exporting public certificate to: $cerPath" -ForegroundColor Yellow
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
Write-Host "[PASS] Public certificate ready for VM transfer: $cerPath" -ForegroundColor Green

# Copy installer helper to dist
$vmHelper = Join-Path $PSScriptRoot "install_cert_on_vm.ps1"
if (Test-Path $vmHelper) {
    Copy-Item -Path $vmHelper -Destination (Join-Path $DistDir "install_cert_on_vm.ps1") -Force
    Write-Host "[PASS] Copied install_cert_on_vm.ps1 to dist for VM convenience." -ForegroundColor Green
}

# 3. Sign Executables if present
$targets = @(
    (Join-Path $DistDir "Release100\Release100.exe"),
    (Join-Path $DistDir "installer\Release100_Setup_v1.3.0.exe")
)

Write-Host "[STEP 3] Signing available binaries..." -ForegroundColor Yellow
$signedCount = 0

foreach ($target in $targets) {
    if (Test-Path $target) {
        Write-Host "  -> Signing: $target" -ForegroundColor Cyan
        try {
            # Attempt timestamping with public RFC3161 server, fallback to local if offline
            Set-AuthenticodeSignature -FilePath $target -Certificate $cert -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com" -ErrorAction Stop | Out-Null
            Write-Host "     [PASS] Signed with DigiCert timestamp." -ForegroundColor Green
        } catch {
            Set-AuthenticodeSignature -FilePath $target -Certificate $cert -HashAlgorithm SHA256 | Out-Null
            Write-Host "     [PASS] Signed without timestamp (offline mode)." -ForegroundColor Yellow
        }
        $signedCount++
    } else {
        Write-Host "  -> Binary not yet compiled: $target (Skipping)" -ForegroundColor Gray
    }
}

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host "  SUMMARY:" -ForegroundColor Cyan
Write-Host "  1. Certificate Thumbprint: $($cert.Thumbprint)" -ForegroundColor White
Write-Host "  2. Public VM Certificate : $cerPath" -ForegroundColor White
Write-Host "  3. Signed Binaries Count : $signedCount" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "To trust this application on your Windows VM, copy 'Release100_TestCert.cer' and run:" -ForegroundColor Yellow
Write-Host "  Import-Certificate -FilePath .\Release100_TestCert.cer -CertStoreLocation Cert:\LocalMachine\Root" -ForegroundColor White
Write-Host "  Import-Certificate -FilePath .\Release100_TestCert.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher" -ForegroundColor White
Write-Host "======================================================================`n" -ForegroundColor Cyan

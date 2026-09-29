@echo off
title Release100 Kiosk - Install Root Certificate
echo ======================================================================
echo   Installing Release100 Test Certificate into Windows Certificate Store
echo ======================================================================
echo Installing to LocalMachine Root and TrustedPublisher...
certutil -addstore -f "Root" "%~dp0Release100_TestCert.cer" >nul 2>&1
certutil -addstore -f "TrustedPublisher" "%~dp0Release100_TestCert.cer" >nul 2>&1

if %errorlevel% neq 0 (
    echo LocalMachine write access denied. Installing to CurrentUser store...
    certutil -user -addstore -f "Root" "%~dp0Release100_TestCert.cer"
    certutil -user -addstore -f "TrustedPublisher" "%~dp0Release100_TestCert.cer"
) else (
    echo Successfully installed to LocalMachine Trusted Root Store.
)

echo.
echo ======================================================================
echo   Certificate Installation Completed!
echo   You can now launch Release100_Kiosk.exe without SmartScreen warnings.
echo ======================================================================
pause

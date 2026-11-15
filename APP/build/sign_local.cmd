@echo off
REM =====================================================================
REM  Sign Pydew Valley with a local certificate, so Windows 11 Smart App
REM  Control stops blocking the game.
REM
REM  HOW TO USE
REM    1. Right-click this file and choose "Run as administrator"
REM       (or just double-click it and click "Yes" on the prompt).
REM    2. Click "Yes" again when it asks to install the certificate.
REM    3. Press a key to close the window.
REM
REM  WHY
REM    Smart App Control blocks unsigned executables with no override
REM    button. A signature whose certificate is trusted at the MACHINE
REM    level satisfies it. A certificate trusted only in the user's own
REM    store does NOT - that was tested and the game was still blocked.
REM
REM  WHAT IT TOUCHES
REM    - adds "Pydew Valley" to LocalMachine\Root (a trusted root CA)
REM    - signs APP\dist\PydewValley.exe with it
REM
REM  To undo: remove the certificate from "Trusted Root Certification
REM  Authorities" in certmgr.msc.
REM =====================================================================
setlocal

set "CER=%~dp0pydew-valley.cer"
set "EXE=%~dp0..\dist\PydewValley.exe"

REM ---- already elevated? ------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator rights...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "Start-Process -FilePath '%~f0' -ArgumentList @('/c','pause') -Verb RunAs"
    echo.
    echo If nothing happened, right-click this file and choose
    echo    "Run as administrator".
    pause
    exit /b 1
)

if not exist "%CER%" (
    echo ERROR: %CER% is missing.
    echo        Run build\sign_local_setup.cmd first to create it.
    pause
    exit /b 1
)

echo.
echo == Installing the certificate into LocalMachine\Root ==
certutil -f -addstore Root "%CER%"
if errorlevel 1 (
    echo ERROR: could not add the certificate.
    pause
    exit /b 1
)

echo.
echo == Signing the executable ==
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-ChildItem 'Cert:\CurrentUser\My' | Where-Object { $_.Subject -like '*Pydew Valley*' } | Select-Object -First 1;" ^
  "if (-not $c) { Write-Host 'ERROR: certificate not found in CurrentUser\My'; exit 1 };" ^
  "$s = Set-AuthenticodeSignature -FilePath '%EXE%' -Certificate $c -HashAlgorithm SHA256;" ^
  "Write-Host ('    ' + $s.Status + ' - ' + $s.StatusMessage)"

echo.
echo == Verifying ==
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "(Get-AuthenticodeSignature '%EXE%').Status"

echo.
echo == Now try starting the game ==
echo    %EXE%
echo.
echo Press any key to close.
pause >nul
endlocal

@echo off
REM =====================================================================
REM  Step 1 of 2: create the Pydew Valley signing certificate.
REM
REM  Run this ONCE as your normal user (no administrator needed).
REM  It creates a self-signed code-signing certificate in your personal
REM  store and exports it to build\pydew-valley.cer.
REM
REM  Then run sign_local.cmd as administrator - it installs the
REM  certificate at machine level and signs the game.
REM =====================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-ChildItem 'Cert:\CurrentUser\My' | Where-Object { $_.Subject -like '*Pydew Valley*' } | Select-Object -First 1;" ^
  "if (-not $c) {" ^
  "  $c = New-SelfSignedCertificate -Subject 'CN=Pydew Valley' -Type CodeSigningCert -CertStoreLocation 'Cert:\CurrentUser\My' -KeyUsage DigitalSignature -NotAfter (Get-Date).AddYears(3);" ^
  "  Write-Host ('created  ' + $c.Thumbprint)" ^
  "} else { Write-Host ('existing ' + $c.Thumbprint) };" ^
  "Export-Certificate -Cert $c -FilePath '%~dp0pydew-valley.cer' -Type CERT -Force | Out-Null;" ^
  "Write-Host ('exported ' + '%~dp0pydew-valley.cer')"
echo.
echo Now run sign_local.cmd as administrator.
pause
endlocal

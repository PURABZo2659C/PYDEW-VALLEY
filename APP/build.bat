@echo off
REM ---------------------------------------------------------------------
REM Build PYDEW VALLEY for Windows.
REM
REM   dist\Pydew Valley [v*] Windows.zip  THE Windows deliverable
REM   dist\PydewValley.exe                the single-file executable
REM   dist\PydewValley\                   the folder build (Aseprite layout)
REM
REM PyInstaller cannot cross-compile, so the macOS and Linux ZIPs are
REM built by the Build and Release workflow, never here.
REM
REM The build tooling lives in this APP folder; the game source
REM (code\, graphics\, audio\, font\, data\) is one level up.
REM
REM Usage:  build.bat            exe + ZIP
REM         build.bat exe        only the single-file executable
REM         build.bat zip        only the Windows ZIP
REM         build.bat folder     only the folder build (instant start)
REM         build.bat all        exe + ZIP for a release (used by CI)
REM ---------------------------------------------------------------------
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "APPDIR=%CD%"
for %%I in ("%APPDIR%") do set "APPDIR=%%~fI"
set "GAMEROOT=%APPDIR%\.."
for %%I in ("%GAMEROOT%") do set "GAMEROOT=%%~fI"
if not defined RUNNER_TEMP set "RUNNER_TEMP=%TEMP%"
set "WORKPATH=%RUNNER_TEMP%\pydew-valley-pyinstaller"
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=default"

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python is not on PATH.
    exit /b 1
)

REM ---- 1. Line endings + icon + version resource ------------------------
REM cmd.exe cannot reliably match `call :label` targets in files that use
REM bare LF endings, so the batch files are normalised to CRLF first.
python "%APPDIR%\build\fix_line_endings.py"
if errorlevel 1 (
    echo WARNING: could not normalise the batch file line endings.
    echo          If the build fails with "cannot find the batch label",
    echo          close this window and run build.bat again.
)

echo == Generating the icon ==
python "%APPDIR%\build\make_icon.py"
if errorlevel 1 (
    echo ERROR: icon generation failed.
    exit /b 1
)

echo == Generating the version resource ==
python "%APPDIR%\build\make_version_info.py"
if errorlevel 1 (
    echo ERROR: version resource generation failed.
    exit /b 1
)

REM ---- 2. Pick the target ---------------------------------------------
if "%TARGET%"=="default" goto build_exe
if "%TARGET%"=="all" goto build_all
if "%TARGET%"=="exe" goto build_exe
if "%TARGET%"=="zip" goto build_zip
if "%TARGET%"=="folder" goto build_folder
echo ERROR: unknown target "%TARGET%" (use: default, all, exe, zip, folder)
exit /b 1

:build_all
call :make_exe
if errorlevel 1 exit /b 1
call :make_zip
if errorlevel 1 exit /b 1
goto done

:build_exe
call :make_exe
if errorlevel 1 exit /b 1
if "%TARGET%"=="exe" goto done
call :make_zip
if errorlevel 1 exit /b 1
goto done

:build_folder
call :make_folder
if errorlevel 1 exit /b 1
goto done

:build_zip
if not exist "%APPDIR%\dist\PydewValley.exe" (
    call :make_exe
    if errorlevel 1 exit /b 1
)
call :make_zip
if errorlevel 1 exit /b 1
goto done

REM ---- the actual build steps ------------------------------------------
REM Each step only clears its OWN output. Clearing everything up front
REM used to delete the single file executable when only the folder
REM build was requested.
:make_exe
echo.
echo == Building the single-file executable ==
if exist "%APPDIR%\dist\PydewValley.exe" del /q "%APPDIR%\dist\PydewValley.exe" 2>nul
call :clean_work
if errorlevel 1 exit /b 1
set "PYDEW_ONEDIR="
python -m PyInstaller --clean --noconfirm --workpath "%WORKPATH%" "%APPDIR%\PydewValley.spec"
if errorlevel 1 (
    echo ERROR: the single-file build failed.
    exit /b 1
)
exit /b 0

:make_folder
echo.
echo == Building the folder version ==
if exist "%APPDIR%\dist\PydewValley" rmdir /s /q "%APPDIR%\dist\PydewValley" 2>nul
call :clean_work
if errorlevel 1 exit /b 1
set "PYDEW_ONEDIR=1"
python -m PyInstaller --clean --noconfirm --workpath "%WORKPATH%" "%APPDIR%\PydewValley.spec"
if errorlevel 1 (
    echo ERROR: the folder build failed.
    exit /b 1
)
exit /b 0

:make_zip
echo.
echo == Building the ZIP ==
python "%APPDIR%\build\make_zip.py"
if errorlevel 1 (
    echo ERROR: the ZIP build failed.
    exit /b 1
)
exit /b 0

REM ---- clear the external PyInstaller work folder ----------------------
REM Each build leaves a work folder behind and the next one cannot
REM clear it while the file indexer still holds a handle, so it is
REM cleared before every build rather than once at the start.
:clean_work
set "WORK_TRIES=0"
:clean_work_loop
if exist "%WORKPATH%\PydewValley" rmdir /s /q "%WORKPATH%\PydewValley" 2>nul
if exist "%WORKPATH%\PydewValley" goto clean_work_wait
exit /b 0

:clean_work_wait
set /a WORK_TRIES+=1
if !WORK_TRIES! GEQ 15 (
    echo ERROR: the external PyInstaller work folder is locked by another program.
    echo        Close any running game or Explorer window on it and retry.
    exit /b 1
)
echo    waiting for the file lock to clear...
timeout /t 3 /nobreak >nul
goto clean_work_loop

:done
echo.
echo == Done ==
if exist "%APPDIR%\dist\PydewValley.exe" echo    dist\PydewValley.exe
for %%F in ("%APPDIR%\dist\*.zip") do echo    dist\%%~nxF
endlocal

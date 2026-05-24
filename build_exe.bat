@echo off
setlocal

rem Use the current Python interpreter instead of the Windows launcher `py`,
rem because `py` may point to Python 3.14 on this system and break the build.
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo Building DLP-Utility with %PYTHON%...
if exist "%~dp0dist\launcher.exe" del /q "%~dp0dist\launcher.exe"
if exist "%~dp0dist\DLP-Utility.exe" del /q "%~dp0dist\DLP-Utility.exe"
"%PYTHON%" -m PyInstaller --noconfirm --clean launcher.spec
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)
echo Build complete. The EXE will be in the dist\ folder.
endlocal

@echo off
cd /d "D:\project\mhj"

echo.
echo ==========================================
echo   Cleaning previous PyInstaller build
echo ==========================================
echo.

powershell -NoProfile -Command "Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue"

if errorlevel 1 (
    echo ERROR: Failed to clean build/dist folders.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   Building MHJ Downloader
echo ==========================================
echo.

pyinstaller --noconfirm --clean ".\MHJ.spec"

if errorlevel 1 (
    echo.
    echo ==========================================
    echo   BUILD FAILED
    echo ==========================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   BUILD SUCCESSFUL
echo ==========================================
echo.

pause
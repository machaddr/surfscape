@echo off
setlocal enabledelayedexpansion

REM Surfscape Build Script for Windows
REM This script builds a static executable using PyInstaller

echo ========================================
echo   Surfscape Build Script (Windows)
echo ========================================
echo.

REM Function definitions using goto labels for colored output
goto :main

:print_status
echo [INFO] %~1
goto :eof

:print_success
echo [SUCCESS] %~1
goto :eof

:print_warning
echo [WARNING] %~1
goto :eof

:print_error
echo [ERROR] %~1
goto :eof

:main

REM Check if Python is installed
python3 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python3
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=python
    ) else (
        call :print_error "Python is not installed or not in PATH"
        pause
        exit /b 1
    )
)

call :print_status "Python version:"
%PYTHON_CMD% --version

REM Check if pip is installed
pip3 --version >nul 2>&1
if not errorlevel 1 (
    set PIP_CMD=pip3
) else (
    pip --version >nul 2>&1
    if not errorlevel 1 (
        set PIP_CMD=pip
    ) else (
        call :print_error "pip is not installed or not in PATH"
        pause
        exit /b 1
    )
)

REM Install dependencies
call :print_status "Installing dependencies..."
%PIP_CMD% install -r requirements.txt

REM Clean previous builds
call :print_status "Cleaning previous builds..."
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
if exist "__pycache__" rmdir /s /q __pycache__
for /r %%i in (*.pyc) do del "%%i" 2>nul

REM Build the executable
call :print_status "Building executable with PyInstaller..."
pyinstaller --clean surfscape.spec

REM Check if build was successful
if exist "dist\surfscape.exe" (
    call :print_success "Build completed successfully!"
    call :print_status "Executable location: %CD%\dist\surfscape.exe"
    
    REM Get file size
    for %%I in (dist\surfscape.exe) do set SIZE=%%~zI
    set /a SIZE_MB=!SIZE!/1024/1024
    call :print_status "Executable size: !SIZE_MB! MB"
    
    REM Check for dependencies using dumpbin if available
    where dumpbin >nul 2>&1
    if not errorlevel 1 (
        call :print_warning "Executable may have dynamic dependencies. Run 'dumpbin /dependents dist\surfscape.exe' to see them."
    )
    
    echo.
    echo ========================================
    call :print_success "BUILD COMPLETE!"
    echo ========================================
    echo You can find your executable at: .\dist\surfscape.exe
    echo To run: .\dist\surfscape.exe
    echo.
    
) else (
    call :print_error "Build failed! Check the output above for errors."
    pause
    exit /b 1
)

echo Press any key to exit...
pause >nul

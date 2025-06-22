@echo off

REM Clean script for Surfscape project
REM Removes all build artifacts and temporary files

echo Cleaning Surfscape build artifacts...

REM Remove build directories
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
if exist "__pycache__" rmdir /s /q __pycache__
if exist "venv" rmdir /s /q venv

REM Remove Python cache files
for /r %%i in (*.pyc) do del "%%i" 2>nul
for /r %%i in (*.pyo) do del "%%i" 2>nul
for /d /r %%i in (__pycache__) do rmdir /s /q "%%i" 2>nul

REM Remove PyInstaller backup files
del *.spec.bak 2>nul

echo Clean complete!
pause

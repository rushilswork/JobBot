@echo off
setlocal enabledelayedexpansion
title JobBot Setup

echo.
echo  ==========================================
echo   JobBot - Automated Setup
echo  ==========================================
echo.

:: ── Check Python ──────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download it from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

:: ── Check pip ─────────────────────────────────────────────────────────────────
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not available. Try reinstalling Python.
    pause
    exit /b 1
)
echo [OK] pip found

:: ── Upgrade pip ───────────────────────────────────────────────────────────────
echo.
echo [1/4] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip upgraded

:: ── Install requirements ──────────────────────────────────────────────────────
echo.
echo [2/4] Installing Python dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements. Check output above.
    pause
    exit /b 1
)
echo [OK] All Python packages installed

:: ── Install Playwright browsers ───────────────────────────────────────────────
echo.
echo [3/4] Installing Playwright browsers (this may take a few minutes)...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Playwright browser install failed. Check output above.
    pause
    exit /b 1
)
echo [OK] Playwright Chromium installed

:: ── Create required directories ───────────────────────────────────────────────
echo.
echo [4/4] Setting up folders...
if not exist data       mkdir data
if not exist config     mkdir config
if not exist logs       mkdir logs
echo [OK] Folders ready

:: ── Check config.yaml ─────────────────────────────────────────────────────────
if not exist config\config.yaml (
    echo.
    echo [WARN] config\config.yaml not found.
    echo        Create it from config\config.example.yaml before running JobBot.
)

:: ── Launch dashboard ──────────────────────────────────────────────────────────
echo.
echo  ==========================================
echo   Setup Complete! Launching JobBot...
echo  ==========================================
echo.
echo  Dashboard will open at http://localhost:8000
echo  First user to sign up becomes admin.
echo.
python main.py dashboard

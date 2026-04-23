@echo off
setlocal enabledelayedexpansion
title Docs Chat - Setup and Launch

cls
echo.
echo  Docs Chat -- Automated Setup and Launch
echo  Free - Local - Private - No API Key Needed
echo.

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if not exist "%SCRIPT_DIR%\app.py" (
    echo  [ERROR] Cannot find app.py in %SCRIPT_DIR%
    echo  Make sure start-windows.bat is in C:\doc-chat\ together with app.py
    pause
    exit /b 1
)
echo  [OK] Running from: %SCRIPT_DIR%
echo.

where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Docker is not installed.
    echo  Install from: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WAIT] Docker not running. Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  Waiting for Docker...
    for /l %%i in (1,1,30) do (
        timeout /t 2 /nobreak >nul
        docker info >nul 2>&1
        if !errorlevel! equ 0 goto docker_ready
        echo  Still waiting... %%i of 30
    )
    echo  [ERROR] Docker did not start. Open Docker Desktop manually and try again.
    pause
    exit /b 1
)

:docker_ready
echo  [OK] Docker is running.
echo.

if not exist "C:\pdfs" (
    echo  [INFO] Creating folder C:\pdfs ...
    mkdir "C:\pdfs"
    echo  [OK] Created. Put your PDF and DOCX files in C:\pdfs
) else (
    echo  [OK] Documents folder C:\pdfs exists.
)
echo.

echo  [BUILD] Building Docker image (first time: 3-5 min, then instant)...
echo.
docker build -t docs-chat:latest "%SCRIPT_DIR%"
if %errorlevel% neq 0 (
    echo  [ERROR] Docker build failed. See error above.
    pause
    exit /b 1
)
echo.
echo  [OK] Image ready.
echo.

docker rm -f docs-chat >nul 2>&1

echo  [START] Starting container...
echo.
docker run -d ^
  --name docs-chat ^
  --restart unless-stopped ^
  -p 5000:5000 ^
  -v "C:/pdfs:/docs" ^
  -v ollama_models:/root/.ollama ^
  -e DOCS_FOLDER=/docs ^
  -e DOCS_LABEL=C:\pdfs ^
  -e OLLAMA_MODEL=llama3.2:1b ^
  -e PLATFORM=windows ^
  docs-chat:latest

if %errorlevel% neq 0 (
    echo  [ERROR] Could not start container. See error above.
    pause
    exit /b 1
)

echo  [OK] Container is running.
echo.
echo  [INFO] AI model downloading in background (first run only, ~700MB).
echo         Wait for the green dot in the app before asking questions.
echo.
timeout /t 6 /nobreak >nul
start http://localhost:5000

echo.
echo  Commands:
echo    docker stop docs-chat      - Stop
echo    docker start docs-chat     - Start again (instant)
echo    docker logs -f docs-chat   - View logs
echo.
echo  Press any key to close this window.
pause >nul

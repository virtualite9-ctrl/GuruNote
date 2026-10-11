@echo off
:: GuruNote - React/PyWebView UI 실행 (Windows, v1.0+ 권장 진입점).
:: setup.bat 가 생성한 .venv 를 activate 없이 직접 사용.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv 를 찾을 수 없습니다. 먼저 setup.bat 를 실행하세요.
    exit /b 1
)

".venv\Scripts\python.exe" app_webview.py %*

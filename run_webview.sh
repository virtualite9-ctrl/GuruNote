#!/bin/bash
# GuruNote — React/PyWebView UI 실행 (macOS / Linux, v1.0+ 권장 진입점).
#
# setup.sh 가 만든 .venv 를 activate 없이 직접 사용한다 (macOS 의
# `command not found: python` / `streamlit` 문제 회피). stdout/stderr 는
# 콘솔에 그대로 남겨 pywebview + 파이프라인 디버깅을 쉽게 한다.
#
# macOS 에서 Finder 더블 클릭이 필요하면 run_webview.command 를 쓴다.
# Windows 는 run_webview.bat.
set -e
cd "$(dirname "$0")"

# 프로젝트 venv 우선 (setup.sh 레이아웃과 일치), 없으면 시스템 python.
if [ -x "./.venv/bin/python" ]; then
  PY="./.venv/bin/python"
elif [ -x "./venv/bin/python" ]; then
  PY="./venv/bin/python"
else
  PY="$(command -v python3 || command -v python || true)"
fi

if [ -z "$PY" ]; then
  echo "❌ Python 을 찾을 수 없습니다. 먼저 'bash setup.sh' 를 실행하세요." >&2
  exit 1
fi

exec "$PY" app_webview.py "$@"

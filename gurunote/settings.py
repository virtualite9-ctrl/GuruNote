"""앱 내 설정 저장/로드 유틸리티 (.env + os.environ 동기화)."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from dotenv import set_key

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env(override: bool = False) -> Path | None:
    """`ENV_PATH` 의 `.env` 를 환경변수로 읽어들인다.

    창을 띄우는 진입점(`gui.py` / `app.py` / `app_webview.py`)은 각자 모듈 레벨에서
    `load_dotenv()` 를 부른다. CLI 와 MCP 서버는 그러지 않아, 설정 화면이 저장한 `.env`
    를 통째로 무시하고 있었다.

    `load_dotenv()` 를 인자 없이 부르면 현재 작업 디렉터리에서 위로 훑는다. MCP 서버는
    클라이언트가 임의의 디렉터리에서 띄우므로 그 방식은 못 쓴다. 설정이 실제로 저장되는
    경로를 직접 가리킨다.

    기본적으로 이미 설정된 환경변수를 덮어쓰지 않는다 — 실제 환경이 파일보다 우선이다.

    Returns:
        읽어들인 파일 경로. 파일이 없거나 python-dotenv 가 없으면 None.
    """
    if not ENV_PATH.is_file():
        return None
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
    except ModuleNotFoundError:
        return None
    load_dotenv(ENV_PATH, override=override)
    return ENV_PATH


def ensure_env_file() -> Path:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# GuruNote 설정 (자동 생성)\n", encoding="utf-8")
    return ENV_PATH


def backup_env_file() -> Path:
    env_path = ensure_env_file()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = env_path.with_name(f".env.backup_{ts}")
    shutil.copy2(env_path, backup)
    return backup


def save_settings(settings: Mapping[str, str], create_backup: bool = True) -> tuple[int, Path | None]:
    """
    설정을 .env 와 os.environ 에 동시에 반영.

    Returns:
      (changed_count, backup_path_or_none)
    """
    env_path = ensure_env_file()
    backup_path = backup_env_file() if create_backup else None

    changed = 0
    for key, raw_value in settings.items():
        value = (raw_value or "").strip()
        old = os.environ.get(key, "")
        if old == value:
            continue

        if value:
            os.environ[key] = value
            set_key(str(env_path), key, value)
        else:
            os.environ.pop(key, None)
            set_key(str(env_path), key, "")
        changed += 1

    return changed, backup_path

"""
로컬 UI 상태 영속화 (~/.gurunote/ui_state.json).

Phase 2: 현재는 히스토리 우측 트리 내비게이션 패널의 facet expand 상태만
저장/복원한다. 필터 선택, 창 크기 등은 세션마다 초기화한다.

파일 쓰기 실패 / 파싱 실패 / 키 누락은 모두 silent fallback (기본값).
어떤 경우에도 GUI 동작을 차단하지 않는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_STATE_DIR = Path.home() / ".gurunote"
_STATE_PATH = _STATE_DIR / "ui_state.json"


def load_ui_state() -> dict[str, Any]:
    """파일 존재/파싱 실패 시 빈 dict 반환."""
    try:
        if not _STATE_PATH.exists():
            return {}
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_ui_state(state: dict[str, Any]) -> bool:
    """atomic write (임시파일 → replace). 실패 시 False."""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _STATE_PATH)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_nav_expand(state: dict[str, Any]) -> dict[str, bool]:
    """`state` 에서 `nav_expand` 섹션만 안전하게 추출. 타입 검증 포함."""
    raw = state.get("nav_expand")
    if not isinstance(raw, dict):
        return {}
    return {k: bool(v) for k, v in raw.items() if isinstance(k, str)}


def set_nav_expand(state: dict[str, Any], expand: dict[str, bool]) -> dict[str, Any]:
    """in-place 로 `state["nav_expand"]` 갱신 후 state 반환."""
    state["nav_expand"] = dict(expand)
    return state

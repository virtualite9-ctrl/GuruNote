"""GUI 공용 UI 프리미티브 (테마·위젯·토스트·상태 영속화).

기존 `gurunote/ui_theme.py`, `gurunote/ui_components.py`, `gurunote/ui_toast.py`,
`gurunote/ui_state.py` 한 파일씩이던 것을 패키지로 나눴다. 의존 방향:

    toast → theme
    components → theme
    state (독립), theme (독립)

기존 `from gurunote.ui.theme import X` 등을 그대로 쓸 수 있게 공개 이름을
전부 re-export 한다. GUI 본체(`gui.py`)는 `gurunote.ui.theme` 등 하위 모듈을
직접 쓰고, 이 패키지 진입점은 외부 참조용 얇은 표면으로 유지한다.
"""
from __future__ import annotations

from gurunote.ui.components import (  # noqa: F401
    button,
    card,
    divider,
    section_header,
    status_pill,
    tag_chip,
)
from gurunote.ui.state import (  # noqa: F401
    get_nav_expand,
    load_ui_state,
    save_ui_state,
    set_nav_expand,
)
from gurunote.ui.theme import *  # noqa: F401,F403
from gurunote.ui.toast import ToastManager  # noqa: F401

__all__ = [
    # components
    "button",
    "card",
    "divider",
    "section_header",
    "status_pill",
    "tag_chip",
    # state
    "get_nav_expand",
    "load_ui_state",
    "save_ui_state",
    "set_nav_expand",
    # toast
    "ToastManager",
    # theme
    "BTN_DANGER",
    "BTN_GHOST",
    "BTN_PRIMARY",
    "BTN_SECONDARY",
    "C_ACCENT",
    "C_BG",
    "C_BORDER",
    "C_DANGER",
    "C_INFO",
    "C_ON_PRIMARY",
    "C_PRIMARY",
    "C_PRIMARY_BRIGHT",
    "C_PRIMARY_HO",
    "C_SIDEBAR",
    "C_SUCCESS",
    "C_SURFACE",
    "C_SURFACE_HI",
    "C_TEXT",
    "C_TEXT_DIM",
    "C_TEXT_MUTED",
    "C_WARNING",
    "FONT_BODY",
    "FONT_HEADING",
    "FONT_META",
    "FONT_PAGE_TITLE",
    "FONT_SECTION",
    "FONT_SUBSECTION",
    "HEIGHT_LG",
    "HEIGHT_MD",
    "HEIGHT_SM",
    "HEIGHT_XL",
    "RADIUS_LG",
    "RADIUS_MD",
    "RADIUS_SM",
    "SPACE_LG",
    "SPACE_MD",
    "SPACE_SM",
    "SPACE_XL",
    "SPACE_XXL",
    "SPACE_XXS",
    "SPACE_XXXL",
    "STATUS_COLORS",
    "WEIGHT_BOLD",
    "WEIGHT_NORMAL",
]
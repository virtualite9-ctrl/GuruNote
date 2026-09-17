"""
GuruNote UI 컴포넌트 라이브러리
==============================

`gui.py` 에서 반복 생성하던 위젯(버튼/칩/섹션 헤더/카드 프레임) 을
factory 함수로 추출. Phase 1a 에서는 정의만 하고 `gui.py` 는 아직 import 하지
않는다 — 후속 Phase (1b/1c/1d) 에서 점진 이관.

설계 원칙
---------
- **단일 책임**: 각 factory 는 위젯 하나만 반환.
- **토큰 의존**: 직접 색상/픽셀 리터럴 금지 — `gurunote.ui.theme` 의 상수만 사용.
- **customtkinter 위젯 반환**: 추가 세팅(`.grid(...)` 등) 은 호출자가 결정.
- **kwargs pass-through**: customtkinter 의 남은 옵션은 `**kwargs` 로 위임.

사용 예시
---------
    from gurunote.ui import components as uic
from gurunote.ui import theme as ut

    btn = uic.button(parent, text="저장", variant=ut.BTN_PRIMARY,
                     command=on_save)
    btn.grid(row=0, column=0, padx=ut.SPACE_MD, pady=ut.SPACE_SM)

    pill = uic.status_pill(parent, status="완료")
    chip = uic.tag_chip(parent, text="LLM")
    header = uic.section_header(parent, title="AI Provider",
                                subtitle="키는 .env 에 저장됩니다")
    card = uic.card(parent)
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from gurunote.ui import theme as ut


# =============================================================================
# 버튼 factory
# =============================================================================
# 변형별 스타일 맵 — (fg_color, hover_color, text_color, border_width, border_color).
# - primary:   채워진 purple, 화면당 0~1 개 (메인 CTA)
# - secondary: 채워진 surface_hi, 2순위 액션 (저장/테스트/새로고침)
# - ghost:     투명 배경 + hover 시 surface_hi (보기/복사/폴더 열기)
# - danger:    채워진 danger, 삭제/취소
_BUTTON_STYLES = {
    ut.BTN_PRIMARY: {
        "fg_color": ut.C_PRIMARY,
        "hover_color": ut.C_PRIMARY_HO,
        "text_color": ut.C_ON_PRIMARY,
        "border_width": 0,
    },
    ut.BTN_SECONDARY: {
        "fg_color": ut.C_SURFACE_HI,
        "hover_color": ut.C_BORDER,
        "text_color": ut.C_TEXT,
        "border_width": 0,
    },
    ut.BTN_GHOST: {
        "fg_color": "transparent",
        "hover_color": ut.C_SURFACE_HI,
        "text_color": ut.C_TEXT,
        "border_width": 1,
        "border_color": ut.C_BORDER,
    },
    ut.BTN_DANGER: {
        "fg_color": ut.C_DANGER,
        "hover_color": "#D97570",  # danger hover — tone 60
        "text_color": ut.C_BG,
        "border_width": 0,
    },
}


def button(
    parent,
    *,
    text: str,
    variant: str = ut.BTN_SECONDARY,
    command: Optional[Callable[[], None]] = None,
    height: int = ut.HEIGHT_MD,
    width: Optional[int] = None,
    font_size: int = ut.FONT_BODY,
    font_weight: str = ut.WEIGHT_NORMAL,
    **kwargs,
) -> ctk.CTkButton:
    """변형 기반 버튼 factory.

    `variant` 는 `theme.BTN_*` 중 하나. 알 수 없는 값이면 secondary 폴백.

    추가 kwargs 는 `CTkButton` 으로 그대로 전달 (e.g. `state`, `image`).
    """
    style = _BUTTON_STYLES.get(variant, _BUTTON_STYLES[ut.BTN_SECONDARY])
    kw = {
        "text": text,
        "command": command,
        "height": height,
        "corner_radius": ut.RADIUS_SM,
        "font": ctk.CTkFont(size=font_size, weight=font_weight),
        **style,
    }
    if width is not None:
        kw["width"] = width
    kw.update(kwargs)  # 호출자가 override 가능
    return ctk.CTkButton(parent, **kw)


# =============================================================================
# 카드 frame factory
# =============================================================================
def card(parent, *, fg_color: str = ut.C_SURFACE, **kwargs) -> ctk.CTkFrame:
    """카드 모양 frame (2dp elevation, RADIUS_MD).

    `gui.py` 의 기존 `_card()` helper 와 호환 — 같은 시각 결과.
    """
    kw = {
        "fg_color": fg_color,
        "corner_radius": ut.RADIUS_MD,
        "border_width": 1,
        "border_color": ut.C_BORDER,
    }
    kw.update(kwargs)
    return ctk.CTkFrame(parent, **kw)


# =============================================================================
# 섹션 헤더 (title + optional subtitle)
# =============================================================================
def section_header(
    parent,
    *,
    title: str,
    subtitle: Optional[str] = None,
    title_size: int = ut.FONT_SECTION,
) -> ctk.CTkFrame:
    """섹션 제목(+ 부제) frame.

    반환된 frame 은 `grid()`/`pack()` 으로 배치. 내부 라벨 2개를
    grid 로 세로 배치한다 (subtitle 없으면 title 한 줄).
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        frame,
        text=title,
        font=ctk.CTkFont(size=title_size, weight=ut.WEIGHT_BOLD),
        text_color=ut.C_TEXT,
        anchor="w",
    ).grid(row=0, column=0, sticky="w")

    if subtitle:
        ctk.CTkLabel(
            frame,
            text=subtitle,
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(ut.SPACE_XXS, 0))

    return frame


# =============================================================================
# Status pill — 작업 상태 표시 (완료 / 실패 / 처리 중 / 대기)
# =============================================================================
def status_pill(parent, *, status: str) -> ctk.CTkLabel:
    """상태 pill. `status` 는 `theme.STATUS_COLORS` 의 key 중 하나.

    알 수 없는 status 면 "대기" 스타일로 폴백 (silent).
    """
    fg, text_color = ut.STATUS_COLORS.get(status, ut.STATUS_COLORS["대기"])
    return ctk.CTkLabel(
        parent,
        text=status,
        fg_color=fg,
        text_color=text_color,
        corner_radius=ut.RADIUS_SM,
        height=ut.HEIGHT_SM,
        font=ctk.CTkFont(size=ut.FONT_META, weight=ut.WEIGHT_BOLD),
        padx=ut.SPACE_SM,
    )


# =============================================================================
# Tag chip — 태그/분류 라벨 (둥근 chip, 회색 배경)
# =============================================================================
def tag_chip(
    parent,
    *,
    text: str,
    variant: str = "default",  # "default" | "accent"
) -> ctk.CTkLabel:
    """태그/키워드 chip. `default` 는 회색 surface_hi, `accent` 는 보라 틴트."""
    if variant == "accent":
        fg = ut.C_PRIMARY
        tc = ut.C_ON_PRIMARY
    else:
        fg = ut.C_SURFACE_HI
        tc = ut.C_TEXT_DIM
    return ctk.CTkLabel(
        parent,
        text=text,
        fg_color=fg,
        text_color=tc,
        corner_radius=ut.RADIUS_SM,
        height=ut.HEIGHT_SM,
        font=ctk.CTkFont(size=ut.FONT_META),
        padx=ut.SPACE_SM,
    )


# =============================================================================
# 분리선 (섹션 간 구분)
# =============================================================================
def divider(parent, *, orient: str = "horizontal") -> ctk.CTkFrame:
    """얇은 구분선. orient 는 'horizontal' | 'vertical'."""
    if orient == "vertical":
        return ctk.CTkFrame(
            parent, width=1, fg_color=ut.C_BORDER, corner_radius=0,
        )
    return ctk.CTkFrame(
        parent, height=1, fg_color=ut.C_BORDER, corner_radius=0,
    )


__all__ = [
    "button",
    "card",
    "section_header",
    "status_pill",
    "tag_chip",
    "divider",
]

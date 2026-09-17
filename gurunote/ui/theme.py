"""
GuruNote UI 디자인 토큰
=======================

데스크톱 GUI(`gui.py`) 에서 분산돼 있던 색상/간격/반경/폰트/높이 상수를
한 곳으로 모은 모듈. Phase 1a 에서는 "단일 출처" 를 확보하는 것이 목적이며
`gui.py` 는 아직 이 모듈을 import 하지 않는다 (중복 정의 허용, 후속 PR 에서 이관).

사용 규칙
---------
- **색상**은 Material 3 다크 팔레트(purple 톤) 기반. `C_*` 접두사.
- **간격/반경/높이**는 4·8 배수 grid. 직접 픽셀 값을 쓰지 말고 상수를 쓸 것.
- **폰트 크기**는 역할(title/section/body/meta) 기준.
- **버튼 변형(primary/secondary/ghost/danger)** 은 `ui_components.button()` 을
  통해서만 적용 — 여기서는 색상 파라미터만 제공.

한 줄 요약: "픽셀/색상 리터럴을 코드에 직접 쓰지 말고 여기서 가져다 쓸 것."
"""
from __future__ import annotations

# =============================================================================
# 색상 — Material 3 dark theme (purple tonal palette)
# =============================================================================
# 톤 규칙:
#   - Surface 계층은 elevation 별로 점진적으로 밝아짐 (base → +1dp → +2dp → +3dp)
#   - Primary 는 tone 30 (container), 텍스트는 tone 95+
#   - "on-*" 색상은 해당 배경 위에 올라갈 텍스트용 — WCAG AA 4.5:1 이상
# -----------------------------------------------------------------------------

# Surface 계층
C_BG = "#141218"           # base — 메인 배경
C_SIDEBAR = "#1D1B20"      # +1dp elevation — 사이드바
C_SURFACE = "#211F26"      # +2dp — 카드/다이얼로그
C_SURFACE_HI = "#2B2930"   # +3dp — hover/강조 블록
C_BORDER = "#49454F"       # outline variant — 구분선/테두리

# Primary (purple)
C_PRIMARY = "#4F378B"       # tone 30 — primary container 배경 (CTA)
C_PRIMARY_HO = "#5D43A8"    # hover 시 한 단계 밝게
C_PRIMARY_BRIGHT = "#D0BCFF"  # tone 80 — 아이콘/하이라이트 전용 (배경 X)
C_ON_PRIMARY = "#FFFFFF"    # primary container 위 텍스트

# Accent (soft lavender)
C_ACCENT = "#CCC2DC"        # tone 80 (secondary) — 소프트 라벤더

# Text
C_TEXT = "#E6E0E9"          # on-surface — 본문
C_TEXT_DIM = "#938F99"      # on-surface-variant — 보조/비활성
C_TEXT_MUTED = "#7A7680"    # placeholder 수준

# Semantic
C_SUCCESS = "#81C995"       # Material green 200
C_WARNING = "#FDD663"       # Material yellow 300
C_DANGER = "#F2B8B5"        # Material error container on-dark
C_INFO = "#8AB4F8"          # Material blue 200

# =============================================================================
# 간격(spacing) — 4·8 grid
# =============================================================================
# 내부 여백/외부 여백/위젯 간격 모두 이 토큰 사용. 직접 `padx=10` 같은
# 임의 값 금지 — 재사용성과 일관성 확보를 위해.
SPACE_XXS = 2
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32
SPACE_XXXL = 48

# =============================================================================
# 반경(corner radius) — 8/12/16
# =============================================================================
RADIUS_SM = 8     # 작은 요소 (pill/chip/small button)
RADIUS_MD = 12    # 카드/dialog content
RADIUS_LG = 16    # 큰 카드/modal outer

# =============================================================================
# 높이 — 버튼/입력 위젯 표준
# =============================================================================
HEIGHT_SM = 28    # dense (chip/small button)
HEIGHT_MD = 32    # 기본 버튼
HEIGHT_LG = 40    # 입력 Entry / primary 버튼
HEIGHT_XL = 48    # hero CTA

# =============================================================================
# 폰트 크기 — 역할 기준
# =============================================================================
FONT_PAGE_TITLE = 27    # 페이지 제목 (사이드바 브랜드, dialog title)
FONT_HEADING = 21       # 섹션 제목 — 큰
FONT_SECTION = 16       # 섹션 제목 — 중간
FONT_SUBSECTION = 14    # 서브섹션
FONT_BODY = 13          # 본문
FONT_META = 11          # 메타/캡션/힌트

# Font weight
WEIGHT_BOLD = "bold"
WEIGHT_NORMAL = "normal"

# =============================================================================
# 버튼 변형 — 네이밍 상수 (실제 스타일은 ui_components.button 에서)
# =============================================================================
BTN_PRIMARY = "primary"       # 채워진 purple — 화면당 0~1 개
BTN_SECONDARY = "secondary"   # 채워진 surface_hi — 중요도 2순위
BTN_GHOST = "ghost"           # 투명 배경 + hover 시 surface_hi — 부가 액션
BTN_DANGER = "danger"         # 채워진 danger — 삭제/취소

# =============================================================================
# 상태 pill 색상 — 작업 상태 표현 (히스토리 등에서 사용)
# =============================================================================
STATUS_COLORS = {
    "완료": (C_SUCCESS, C_BG),     # (fg, text)
    "실패": (C_DANGER, C_BG),
    "처리 중": (C_WARNING, C_BG),
    "대기": (C_TEXT_DIM, C_BG),
}

__all__ = [
    # Surface
    "C_BG", "C_SIDEBAR", "C_SURFACE", "C_SURFACE_HI", "C_BORDER",
    # Primary
    "C_PRIMARY", "C_PRIMARY_HO", "C_PRIMARY_BRIGHT", "C_ON_PRIMARY",
    # Accent
    "C_ACCENT",
    # Text
    "C_TEXT", "C_TEXT_DIM", "C_TEXT_MUTED",
    # Semantic
    "C_SUCCESS", "C_WARNING", "C_DANGER", "C_INFO",
    # Spacing
    "SPACE_XXS", "SPACE_XS", "SPACE_SM", "SPACE_MD", "SPACE_LG",
    "SPACE_XL", "SPACE_XXL", "SPACE_XXXL",
    # Radius
    "RADIUS_SM", "RADIUS_MD", "RADIUS_LG",
    # Height
    "HEIGHT_SM", "HEIGHT_MD", "HEIGHT_LG", "HEIGHT_XL",
    # Font
    "FONT_PAGE_TITLE", "FONT_HEADING", "FONT_SECTION", "FONT_SUBSECTION",
    "FONT_BODY", "FONT_META",
    "WEIGHT_BOLD", "WEIGHT_NORMAL",
    # Button variants
    "BTN_PRIMARY", "BTN_SECONDARY", "BTN_GHOST", "BTN_DANGER",
    # Status
    "STATUS_COLORS",
]

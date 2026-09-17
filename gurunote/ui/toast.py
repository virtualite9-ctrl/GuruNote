"""
GuruNote Toast 알림 매니저
==========================

`messagebox.showinfo(...)` 같은 blocking modal 대신, 화면 모서리에 잠깐
나타났다 사라지는 non-blocking 알림. 저장 성공/복사 완료/소소한 에러 등
흐름을 끊지 않는 피드백용.

설계 원칙
---------
- **non-blocking**: 메인 스레드의 `after()` 로 자동 dismiss, UI 블록 없음.
- **스택 가능**: 여러 개 동시 호출 시 세로로 쌓임 (최신이 위).
- **레벨별 색상**: info(기본) / success / warning / error — `gurunote.ui.theme` 사용.
- **root 에 바인딩**: 한 앱당 하나의 `ToastManager` 인스턴스 — 재사용.

사용 예시
---------
    from gurunote.ui_toast import ToastManager
    from gurunote.ui import components  # noqa (참고용)

    # 앱 init 에서 한 번만:
    toast = ToastManager(self)

    # 이후 어디서든:
    toast.show("저장했습니다", level="success")
    toast.show("Obsidian 연결 실패", level="error", duration=4000)
"""
from __future__ import annotations

from typing import List, Optional

import customtkinter as ctk

from gurunote.ui import theme as ut

# 레벨별 배경/텍스트 색상 맵
_LEVEL_COLORS = {
    "info": (ut.C_SURFACE_HI, ut.C_TEXT),
    "success": (ut.C_SUCCESS, ut.C_BG),
    "warning": (ut.C_WARNING, ut.C_BG),
    "error": (ut.C_DANGER, ut.C_BG),
}

# 토스트 기본 설정
_DEFAULT_DURATION_MS = 2500    # 2.5 초
_STACK_GAP = 6                  # 토스트 간 세로 간격
_OFFSET_BOTTOM = 24             # root 하단에서부터의 여백
_OFFSET_RIGHT = 24              # root 우측에서부터의 여백


class ToastManager:
    """Root window 에 부착되는 토스트 매니저.

    모든 토스트는 root 의 **우측 하단** 에 스택된다 (신규가 위로). macOS 의
    시스템 알림 센터 UX 와 비슷한 방향성.

    주의: `root` 는 `ctk.CTk` 또는 `ctk.CTkToplevel` 이어야 함. grid 가 아닌
    `place()` 로 띄우므로 root 의 geometry 와 충돌하지 않음.
    """

    def __init__(self, root) -> None:
        self._root = root
        self._active: List[ctk.CTkFrame] = []  # 현재 살아 있는 토스트들

    # ── public API ──
    def show(
        self,
        message: str,
        *,
        level: str = "info",
        duration: int = _DEFAULT_DURATION_MS,
    ) -> None:
        """토스트 표시. level 은 "info" | "success" | "warning" | "error"."""
        fg, tc = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        toast = self._build_toast(message, fg, tc)
        self._active.append(toast)
        self._relayout()
        # duration 후 자동 dismiss
        self._root.after(duration, lambda t=toast: self._dismiss(t))

    def clear(self) -> None:
        """활성 토스트 모두 즉시 제거."""
        for t in list(self._active):
            self._dismiss(t)

    # ── internal ──
    def _build_toast(self, message: str, fg: str, text_color: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(
            self._root,
            fg_color=fg,
            corner_radius=ut.RADIUS_SM,
            border_width=0,
        )
        ctk.CTkLabel(
            frame,
            text=message,
            text_color=text_color,
            font=ctk.CTkFont(size=ut.FONT_BODY, weight=ut.WEIGHT_BOLD),
            anchor="w",
        ).pack(padx=ut.SPACE_MD, pady=ut.SPACE_SM, fill="x")
        # 클릭 시 즉시 닫기 (사용자 편의)
        frame.bind("<Button-1>", lambda _e, t=frame: self._dismiss(t))
        return frame

    def _relayout(self) -> None:
        """활성 토스트를 우측 하단에 세로 스택 재배치.

        `place()` 의 relx/rely = 1.0 (우하 기준), anchor = "se" 로
        root 크기 변화에도 자동 따라감.
        """
        # 아래에서 위로 쌓기 — 최신 항목이 가장 위에 오도록 역순 배치.
        y_offset = _OFFSET_BOTTOM
        for toast in reversed(self._active):
            try:
                toast.update_idletasks()
                h = toast.winfo_reqheight()
            except Exception:  # noqa: BLE001
                h = 40
            try:
                toast.place(
                    relx=1.0, rely=1.0,
                    x=-_OFFSET_RIGHT, y=-y_offset,
                    anchor="se",
                )
                # 위로 올리기 — 다른 위젯에 가려지지 않도록.
                toast.lift()
            except Exception:  # noqa: BLE001
                pass
            y_offset += h + _STACK_GAP

    def _dismiss(self, toast: ctk.CTkFrame) -> None:
        if toast not in self._active:
            return  # 이미 제거됨
        self._active.remove(toast)
        try:
            toast.place_forget()
            toast.destroy()
        except Exception:  # noqa: BLE001
            pass
        self._relayout()


__all__ = ["ToastManager"]

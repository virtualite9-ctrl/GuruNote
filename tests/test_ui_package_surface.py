"""`gurunote/ui` 패키지 표면 — 파일 분할 후에도 바뀌지 않아야 하는 것들.

1. 기존 호출부가 쓰던 이름이 패키지 레벨에서 그대로 보여야 한다 (`gurunote.ui.ToastManager`).
2. toast 와 components 는 테마를 모듈 객체로 받는다(`from gurunote.ui import theme as ut`).
   그래서 `gurunote.ui.theme.X` 를 patch 하면 ut.X 를 호출 시점에 읽는 코드까지 반영된다 —
   그 계약을 실제 patch 로 고정한다.
3. 하위 모듈끼리 이름을 직접 import 하면(`from gurunote.ui.theme import C_PRIMARY`)
   patch 지점이 갈라진다 — 모듈 레벨에서는 금지하고 AST 로 검사한다.

`.venv` 에 customtkinter 가 없으므로 실행 검사는 전부 스텁을 끼운 별도 인터프리터에서
돈다 (tests/test_entry_points_import.py 의 STUB_PREAMBLE).
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "gurunote" / "ui"
SUBMODULES = ("components", "state", "theme", "toast")

# tkinter / customtkinter / Pillow 는 CI 에 없다. 속성 접근 시 타입을 돌려주는 스텁.
STUB_PREAMBLE = '''
import sys, types


class _Any:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()


class _Mod(types.ModuleType):
    def __getattr__(self, name):
        return type(name, (_Any,), {})


for _name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox",
              "customtkinter", "PIL", "PIL.Image", "PIL.ImageTk"):
    sys.modules[_name] = _Mod(_name)
'''


def run(snippet: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, GURUNOTE_NO_REDIRECT="1")
    return subprocess.run([sys.executable, "-c", STUB_PREAMBLE + snippet],
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=180, env=env)


class TestPublicSurfaceSurvived:
    def test_every_declared_public_name_is_importable(self):
        """`gurunote.ui.__all__` 에 선언된 이름이 실제로 패키지에서 보여야 한다."""
        result = run(
            "import gurunote.ui as ui\n"
            "missing = [n for n in ui.__all__ if not hasattr(ui, n)]\n"
            "print('MISSING:' + ','.join(missing))\n"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        out = [line for line in result.stdout.splitlines()
               if line.startswith("MISSING:")][0]
        assert out == "MISSING:", out

    @pytest.mark.parametrize("name", [
        "button", "card", "divider", "section_header", "status_pill",
        "tag_chip",  # components
        "get_nav_expand", "load_ui_state", "save_ui_state",
        "set_nav_expand",  # state
        "ToastManager",  # toast
        "C_PRIMARY", "C_SUCCESS", "BTN_PRIMARY", "FONT_BODY", "SPACE_MD",
        "STATUS_COLORS",  # theme (star import)
    ])
    def test_representative_names_survived(self, name):
        result = run(f"import gurunote.ui as ui; assert hasattr(ui, {name!r})\n")
        assert result.returncode == 0, result.stdout + result.stderr


class TestSubmodulesImportCleanly:
    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_each_submodule_imports_on_its_own(self, mod_name):
        """순환 import 가 생기면 하위 모듈 단독 import 가 깨진다."""
        result = run(f"import gurunote.ui.{mod_name} as m; print(m.__name__)\n")
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"gurunote.ui.{mod_name}" in result.stdout


class TestPatchTargetContract:
    """theme 모듈 객체를 patch 하면 toast/components 에서도 보여야 한다."""

    def test_theme_patch_is_visible_through_toast_and_components(self):
        result = run(
            "import gurunote.ui.theme as theme\n"
            "import gurunote.ui.toast as toast\n"
            "import gurunote.ui.components as components\n"
            "assert toast.ut is theme, 'toast 가 theme 모듈 객체를 공유하지 않는다'\n"
            "assert components.ut is theme, 'components 가 theme 모듈 객체를 공유하지 않는다'\n"
            "theme.C_SUCCESS = '#0f0f0f'\n"
            "assert toast.ut.C_SUCCESS == '#0f0f0f'\n"
            "print('ok')\n"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout

    def test_no_top_level_name_imports_from_a_sibling(self):
        """`from gurunote.ui.<sibling> import name` 은 모듈 레벨에서 금지.

        `from gurunote.ui import theme` (모듈 객체 자체) 는 patch 계약을 지키는
        유일한 허용 형태다.
        """
        offenders = []
        for mod_name in SUBMODULES:
            tree = ast.parse((PKG / f"{mod_name}.py").read_text(encoding="utf-8"))
            for node in tree.body:  # 모듈 레벨만
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.module.startswith("gurunote.ui."):
                    offenders.append(f"{mod_name}: {node.module} -> "
                                     f"{[a.name for a in node.names]}")
        assert offenders == [], offenders


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
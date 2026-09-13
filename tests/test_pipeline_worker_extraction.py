"""PipelineWorker 가 UI 툴킷과 분리된 상태를 유지하는지 검사 (backlog B09).

원래 `PipelineWorker` 는 `gui.py` (CustomTkinter 진입점) 안에 있었고 React/PyWebView
진입점이 `from gui import PipelineWorker` 로 끌어왔다. `gui.py` 는 모듈 레벨에서
customtkinter 를 import 하고 stdout/stderr 을 로그 파일로 돌리는 부수효과를 실행하므로,
React 경로가 UI 툴킷과 그 부수효과를 떠안고 있었다.

sys.modules 오염을 피하려고 각 import 검사를 별도 인터프리터에서 돌린다.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLKITS = ("customtkinter", "tkinter")


def import_probe(module: str) -> set[str]:
    """`module` 을 깨끗한 인터프리터에서 import 하고 적재된 UI 툴킷 이름을 돌려준다."""
    code = (
        "import importlib, json, sys\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps([n for n in {TOOLKITS!r} if n in sys.modules]))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    import json

    return set(json.loads(result.stdout.strip().splitlines()[-1]))


class TestWorkerLivesOutsideTheUiFile:
    def test_worker_module_exists_and_exports_the_class(self):
        from gurunote.pipeline_worker import PipelineWorker

        assert PipelineWorker.__module__ == "gurunote.pipeline_worker"
        assert hasattr(PipelineWorker, "start")

    def test_importing_the_worker_does_not_load_a_ui_toolkit(self):
        assert import_probe("gurunote.pipeline_worker") == set()

    def test_react_session_adapter_does_not_load_a_ui_toolkit(self):
        assert import_probe("gurunote.webui.session") == set()

    def test_react_session_adapter_no_longer_imports_the_ui_file(self):
        source = (ROOT / "gurunote/webui/session.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "gui" not in modules
        assert "gurunote.pipeline_worker" in modules


class TestUiFileKeepsTheNameAvailable:
    def test_gui_still_re_exports_the_worker(self):
        """`gui.PipelineWorker` 를 직접 쓰던 기존 코드가 계속 동작해야 한다.

        `gui.py` 는 customtkinter 를 요구해서 이 환경에서 import 할 수 없으므로
        소스 수준에서 re-export 를 확인한다.
        """
        source = (ROOT / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        reexported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "gurunote.pipeline_worker"
            and any(alias.name == "PipelineWorker" for alias in node.names)
            for node in tree.body
        )
        assert reexported, "gui.py 가 PipelineWorker 를 re-export 하지 않는다"

    def test_gui_no_longer_defines_the_worker_itself(self):
        source = (ROOT / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PipelineWorker"
        ]
        assert defined == [], "PipelineWorker 정의가 gui.py 에 남아 있다"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

"""진입점이 실제로 import 되는지 — UI 툴킷을 스텁으로 대체해서.

`gui.py`(CustomTkinter)와 `app_webview.py`(React/PyWebView)는 지난 네 번의 리팩터가
모두 건드린 파일인데, CI 환경에 tkinter 와 pywebview 가 없어 AST 로만 확인해 왔다.
정적 검사는 "import 한 이름이 실제로 존재하는가" 를 알려주지 못한다.

여기서는 UI 툴킷만 스텁으로 갈아끼우고 모듈을 진짜로 실행한다. 창을 띄우지는 않으므로
위젯 렌더링이나 사용자 상호작용은 여전히 검증 대상이 아니다. 그 부분은 사람이 한 번
띄워 봐야 한다.

각 검사는 별도 인터프리터에서 돈다. `gui.py` 는 import 시 stdout/stderr 을 로그 파일로
돌리므로 `GURUNOTE_NO_REDIRECT=1` 로 막는다.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _importable(module: str) -> bool:
    return subprocess.run([sys.executable, "-c", f"import {module}"],
                          capture_output=True).returncode == 0


# pywebview 는 리눅스에서 GTK/Qt 바인딩을 요구할 수 있어 CI 에 없을 수 있다.
needs_pywebview = pytest.mark.skipif(not _importable("webview"), reason="pywebview 미설치")

# tkinter / customtkinter / Pillow 는 CI 에 없다. 클래스 상속 대상으로도 쓰이므로
# 속성 접근 시 타입을 돌려주는 스텁이 필요하다.
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
                          cwd=ROOT, capture_output=True, text=True, timeout=180, env=env)


class TestLegacyCustomTkinterEntryPoint:
    def test_gui_module_imports(self):
        result = run("import gui; print('ok')")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout

    def test_gui_option_lists_come_from_the_options_module(self):
        result = run(
            "import gui\n"
            "from gurunote.options import STT_ENGINES, LLM_PROVIDERS\n"
            "assert gui.STT_OPTIONS == list(STT_ENGINES), gui.STT_OPTIONS\n"
            "assert gui.LLM_OPTIONS == list(LLM_PROVIDERS), gui.LLM_OPTIONS\n"
            "print('ok')\n")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gui_re_exports_the_same_worker_class(self):
        result = run(
            "import gui\n"
            "from gurunote.pipeline_worker import PipelineWorker\n"
            "assert gui.PipelineWorker is PipelineWorker\n"
            "print('ok')\n")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gui_version_label_matches_the_package(self):
        result = run(
            "import gui, gurunote, pathlib, re\n"
            "source = pathlib.Path('gui.py').read_text(encoding='utf-8')\n"
            "found = re.search(r'text=\"v([0-9.]+)\"', source).group(1)\n"
            "assert found == gurunote.__version__, (found, gurunote.__version__)\n"
            "print('ok')\n")
        assert result.returncode == 0, result.stdout + result.stderr


class TestWebViewEntryPoint:
    @needs_pywebview
    def test_app_webview_module_imports(self):
        result = run("import app_webview; print('ok')")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_session_adapter_uses_the_extracted_worker(self):
        result = run(
            "import gurunote.webui.session as session\n"
            "assert session.PipelineWorker.__module__ == 'gurunote.pipeline_worker'\n"
            "print('ok')\n")
        assert result.returncode == 0, result.stdout + result.stderr

    @needs_pywebview
    def test_pywebview_would_expose_every_service_method(self):
        """pywebview 는 `dir()` + `inspect.ismethod` 로 js_api 를 훑는다 (webview/util.py).

        같은 방식으로 세어, 상속된 서비스 메서드가 JS 에 실제로 노출되는지 확인한다.
        """
        result = run(
            "import inspect\n"
            "from gurunote.webui.bridge import Api\n"
            "from gurunote.service import GuruNoteService\n"
            "api = Api()\n"
            "exposed = {n for n in dir(api)\n"
            "           if inspect.ismethod(getattr(api, n)) and not n.startswith('_')}\n"
            "service = {n for n, _ in inspect.getmembers(GuruNoteService, inspect.isfunction)\n"
            "           if not n.startswith('_')}\n"
            "missing = sorted(service - exposed)\n"
            "assert missing == [], missing\n"
            "print('ok')\n")
        assert result.returncode == 0, result.stdout + result.stderr


class TestReactCallsResolve:
    def test_every_api_call_in_the_front_end_exists_on_the_bridge(self):
        """JSX 가 부르는 `api.<method>` 가 실제로 노출되는지."""
        import re

        called = set()
        for path in (ROOT / "gurunote" / "webui").rglob("*.jsx"):
            called |= set(re.findall(r"\bapi\.([a-z_][a-zA-Z0-9_]*)\s*\(",
                                     path.read_text(encoding="utf-8")))
        assert called, "JSX 에서 api 호출을 하나도 찾지 못했다"
        result = run(
            "import inspect, json, sys\n"
            "from gurunote.webui.bridge import Api\n"
            "api = Api()\n"
            "exposed = [n for n in dir(api)\n"
            "           if inspect.ismethod(getattr(api, n)) and not n.startswith('_')]\n"
            "print(json.dumps(exposed))\n")
        assert result.returncode == 0, result.stdout + result.stderr
        import json

        exposed = set(json.loads(result.stdout.strip().splitlines()[-1]))
        missing = sorted(called - exposed)
        assert missing == [], missing


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

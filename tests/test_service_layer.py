"""창 없는 서비스 계층 — bridge 와 CLI 가 같은 코드를 쓰는지 (backlog B13 3단계).

`Api` 가 담고 있던 동작 중 창이 필요 없는 것을 `gurunote/service.py` 로 옮겼다.
`Api` 는 그것을 상속해 window 배선과 대화상자만 더한다. 검사할 것은 두 가지다.

- JS 쪽에 노출되는 메서드 목록이 줄지 않았는가 (상속이 실제로 먹는가).
- 서비스가 창 없이 동작하는가 (pywebview 없이 import·호출되는가).
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

from gurunote import cli
from gurunote.service import GuruNoteService
from gurunote.webui.bridge import Api

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE_PY = ROOT / "gurunote" / "service.py"
BRIDGE_PY = ROOT / "gurunote" / "webui" / "bridge.py"
WINDOW_ONLY = ("pick_file", "start_pipeline", "select_obsidian_vault_dir",
               "save_result_as", "bind_window", "_require_window")


def public_methods(cls):
    return {n for n, _ in inspect.getmembers(cls, inspect.isfunction)
            if not n.startswith("__")}


class TestServiceWorksWithoutAWindow:
    def test_instantiates_with_no_arguments(self):
        assert GuruNoteService() is not None

    def test_app_info_returns_real_data(self):
        info = GuruNoteService().get_app_info()
        assert info["ok"] is True
        assert info["version"]

    def test_service_module_never_touches_a_window(self):
        tree = ast.parse(SERVICE_PY.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("_window", "create_file_dialog"):
                offenders.append(node.attr)
            if isinstance(node, ast.Name) and node.id == "webview":
                offenders.append("webview")
        assert offenders == [], offenders

    def test_service_imports_without_pywebview_available(self):
        """pywebview 가 없어도 서비스는 import 되어야 한다."""
        code = (
            "import sys\n"
            "sys.modules['webview'] = None\n"
            "from gurunote.service import GuruNoteService\n"
            "print(GuruNoteService().get_app_info()['ok'])\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().endswith("True")


class TestBridgeSurfaceIsPreserved:
    def test_api_exposes_every_service_method(self):
        missing = sorted(public_methods(GuruNoteService) - public_methods(Api))
        assert missing == [], missing

    def test_api_adds_only_the_window_bound_methods(self):
        extra = sorted(public_methods(Api) - public_methods(GuruNoteService))
        assert extra == sorted(WINDOW_ONLY), extra

    @pytest.mark.parametrize("name", [
        "list_history", "get_settings", "semantic_search", "update_note",
        "send_obsidian", "get_canonical_names", "delete_history",
    ])
    def test_api_and_service_share_one_function_object(self, name):
        """위임 메서드를 나열하지 않으므로 같은 함수여야 한다 — 드리프트가 불가능하다."""
        assert getattr(Api, name) is getattr(GuruNoteService, name)
        assert inspect.getmodule(getattr(Api, name)).__name__ == "gurunote.service"

    @pytest.mark.parametrize("name", WINDOW_ONLY)
    def test_window_bound_methods_are_defined_in_the_bridge(self, name):
        tree = ast.parse(BRIDGE_PY.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Api")
        defined = {m.name for m in cls.body if isinstance(m, ast.FunctionDef)}
        assert name in defined, f"{name} 이 bridge 에 없다"

    def test_bridge_no_longer_redefines_service_methods(self):
        tree = ast.parse(BRIDGE_PY.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Api")
        defined = {m.name for m in cls.body if isinstance(m, ast.FunctionDef)}
        overlap = sorted(defined & public_methods(GuruNoteService))
        assert overlap == [], overlap


class TestCliUsesTheService:
    def test_history_renders_rows(self, monkeypatch, capsys):
        monkeypatch.setattr(GuruNoteService, "list_history",
                            lambda self, **kw: {"ok": True, "total": 2, "items": [
                                {"job_id": "j1", "status": "completed", "title": "첫 노트"},
                                {"job_id": "j2", "status": "failed", "title": "둘째"}]})
        assert cli.main(["history", "--limit", "2"]) == 0
        out = capsys.readouterr().out
        assert "j1" in out and "첫 노트" in out and "전체 2건" in out

    def test_history_empty_is_not_an_error(self, monkeypatch, capsys):
        monkeypatch.setattr(GuruNoteService, "list_history",
                            lambda self, **kw: {"ok": True, "items": []})
        assert cli.main(["history"]) == 0
        assert "기록이 없습니다" in capsys.readouterr().out

    def test_history_passes_limit_and_offset_through(self, monkeypatch):
        seen = {}

        def capture(self, **kw):
            seen.update(kw)
            return {"ok": True, "items": []}

        monkeypatch.setattr(GuruNoteService, "list_history", capture)
        cli.main(["history", "--limit", "7", "--offset", "3"])
        assert seen == {"limit": 7, "offset": 3}

    def test_search_failure_exits_one_with_the_code_on_stderr(self, monkeypatch, capsys):
        monkeypatch.setattr(GuruNoteService, "semantic_search",
                            lambda self, **kw: {"ok": False, "code": "INDEX_NOT_BUILT",
                                                "error": "인덱스를 먼저 만드세요"})
        assert cli.main(["search", "확산"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "INDEX_NOT_BUILT" in captured.err

    def test_search_json_carries_the_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(GuruNoteService, "semantic_search",
                            lambda self, **kw: {"ok": False, "code": "X", "error": "e"})
        assert cli.main(["search", "확산", "--json"]) == 1
        assert json.loads(capsys.readouterr().out)["code"] == "X"

    def test_settings_masks_secret_values(self, monkeypatch, capsys):
        monkeypatch.setattr(GuruNoteService, "get_settings",
                            lambda self: {"ok": True, "values": {"LLM_MODEL": "m"},
                                          "secrets_set": {"OPENAI_API_KEY": True,
                                                          "NOTION_TOKEN": False}})
        assert cli.main(["settings"]) == 0
        out = capsys.readouterr().out
        assert "LLM_MODEL=m" in out
        assert "OPENAI_API_KEY=(설정됨)" in out
        assert "NOTION_TOKEN=(미설정)" in out
        assert "sk-" not in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

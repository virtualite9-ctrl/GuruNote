"""CLI 와 MCP 서버가 `.env` 를 읽는지 (설정 화면이 저장하는 그 파일).

창을 띄우는 진입점 셋은 각자 모듈 레벨에서 `load_dotenv()` 를 부르지만, CLI 와 MCP 는
그러지 않아 저장된 설정을 통째로 무시하고 있었다. 실제로 MCP 서버를 클라이언트에
물려보다가 드러났다.

`load_dotenv()` 를 인자 없이 부르면 현재 작업 디렉터리에서 위로 훑는데, MCP 서버는
클라이언트가 임의의 디렉터리에서 띄우므로 그 방식은 못 쓴다. 그래서 `ENV_PATH` 를
직접 가리키는지도 함께 본다.
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRY_POINTS = ("gurunote/cli.py", "gurunote/mcp_server.py")


def calls_load_env(relative: str) -> bool:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "load_env":
                return True
    return False


class TestEnvPathIsTheSavedLocation:
    def test_env_path_is_the_project_root_file(self):
        from gurunote.settings import ENV_PATH

        assert ENV_PATH.name == ".env"
        assert ENV_PATH.parent == ROOT, ENV_PATH

    def test_settings_writes_where_load_env_reads(self):
        """설정 저장과 읽기가 같은 파일을 봐야 한다."""
        source = (ROOT / "gurunote/settings.py").read_text(encoding="utf-8")
        assert "load_dotenv(ENV_PATH" in source, "ENV_PATH 를 직접 읽지 않는다"


class TestEntryPointsLoadIt:
    @pytest.mark.parametrize("relative", ENTRY_POINTS)
    def test_main_calls_load_env(self, relative):
        assert calls_load_env(relative), f"{relative} 의 main 이 load_env 를 부르지 않는다"

    def test_cli_actually_applies_the_file(self, tmp_path):
        """`.env` 에만 있는 값이 CLI 실행 중 환경변수로 보여야 한다."""
        from gurunote.settings import ENV_PATH

        marker = "GURUNOTE_ENV_LOAD_PROBE"
        existed = ENV_PATH.exists()
        original = ENV_PATH.read_text(encoding="utf-8") if existed else None
        ENV_PATH.write_text((original or "") + f"\n{marker}=from-dotenv\n", encoding="utf-8")
        try:
            code = (
                "import os\n"
                "from gurunote.settings import load_env\n"
                "load_env()\n"
                f"print(os.environ.get('{marker}', 'MISSING'))\n"
            )
            env = {k: v for k, v in os.environ.items() if k != marker}
            result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                                    capture_output=True, text=True, timeout=90, env=env)
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip().endswith("from-dotenv"), result.stdout
        finally:
            if original is None:
                ENV_PATH.unlink(missing_ok=True)
            else:
                ENV_PATH.write_text(original, encoding="utf-8")

    def test_real_environment_wins_over_the_file(self, tmp_path):
        """실제 환경변수가 파일보다 우선해야 한다 (override=False)."""
        from gurunote.settings import ENV_PATH

        marker = "GURUNOTE_ENV_PRECEDENCE_PROBE"
        existed = ENV_PATH.exists()
        original = ENV_PATH.read_text(encoding="utf-8") if existed else None
        ENV_PATH.write_text((original or "") + f"\n{marker}=from-dotenv\n", encoding="utf-8")
        try:
            code = (
                "import os\n"
                "from gurunote.settings import load_env\n"
                "load_env()\n"
                f"print(os.environ['{marker}'])\n"
            )
            result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                                    capture_output=True, text=True, timeout=90,
                                    env={**os.environ, marker: "from-real-env"})
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip().endswith("from-real-env"), result.stdout
        finally:
            if original is None:
                ENV_PATH.unlink(missing_ok=True)
            else:
                ENV_PATH.write_text(original, encoding="utf-8")

    def test_missing_file_is_not_an_error(self, monkeypatch, tmp_path):
        import gurunote.settings as settings

        monkeypatch.setattr(settings, "ENV_PATH", tmp_path / "없는파일.env")
        assert settings.load_env() is None

    def test_cwd_does_not_decide_which_file_is_read(self, tmp_path):
        """엉뚱한 디렉터리의 .env 를 집어오면 안 된다 — MCP 는 CWD 가 임의다."""
        decoy = tmp_path / ".env"
        decoy.write_text("GURUNOTE_DECOY_PROBE=picked-up-the-wrong-file\n", encoding="utf-8")
        code = (
            "import os\n"
            "from gurunote.settings import load_env\n"
            "load_env()\n"
            "print(os.environ.get('GURUNOTE_DECOY_PROBE', 'NOT_PICKED_UP'))\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip().endswith("NOT_PICKED_UP"), result.stdout


class TestDependencyIsDeclared:
    def test_python_dotenv_is_a_base_dependency(self):
        """UI 진입점이 모듈 레벨에서 import 하므로 extra 가 아니라 기본이어야 한다."""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        base = text.split("dependencies = [", 1)[1].split("]", 1)[0]
        assert "python-dotenv" in base, base


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

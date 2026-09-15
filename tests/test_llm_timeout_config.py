"""LLM 타임아웃을 환경변수로 조절할 수 있는지.

`LLM_TEMPERATURE` / `LLM_TRANSLATION_MAX_TOKENS` / `LLM_SUMMARY_MAX_TOKENS` 는 이미
환경변수인데 타임아웃 두 개만 하드코딩이었다. 느린 로컬 모델(실측 5.6 tok/s)에서는
90초 안에 약 500 토큰밖에 못 만들어 chunk 번역과 요약이 매번 timeout 으로 떨어진다.

상수는 import 시점에 한 번 읽으므로, 각 검사를 별도 인터프리터에서 돌린다.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
READ = (
    "from gurunote.llm import DEFAULT_LLM_CHUNK_TIMEOUT_SEC as c, LLM_HTTP_TIMEOUT_SEC as h\n"
    "print(f'{c}|{h}')\n"
)


def read_timeouts(**env) -> tuple[float, float]:
    child = {k: v for k, v in os.environ.items()
             if k not in ("LLM_CHUNK_TIMEOUT_SEC", "LLM_HTTP_TIMEOUT_SEC")}
    child.update(env)
    result = subprocess.run([sys.executable, "-c", READ], cwd=ROOT, env=child,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    chunk, http = result.stdout.strip().splitlines()[-1].split("|")
    return float(chunk), float(http)


class TestDefaultsUnchanged:
    def test_without_env_the_previous_values_hold(self):
        assert read_timeouts() == (60.0, 90.0)

    def test_the_documented_default_is_still_asserted_elsewhere(self):
        """`test_phase2_slow_chunk_timeout.py` 가 60.0 을 못박고 있다 — 기본값 변경 금지."""
        source = (ROOT / "tests/test_phase2_slow_chunk_timeout.py").read_text(encoding="utf-8")
        assert "DEFAULT_LLM_CHUNK_TIMEOUT_SEC == 60.0" in source


class TestEnvOverride:
    def test_both_timeouts_are_raised(self):
        assert read_timeouts(LLM_CHUNK_TIMEOUT_SEC="300",
                             LLM_HTTP_TIMEOUT_SEC="420") == (300.0, 420.0)

    def test_each_is_independent(self):
        assert read_timeouts(LLM_CHUNK_TIMEOUT_SEC="240") == (240.0, 90.0)
        assert read_timeouts(LLM_HTTP_TIMEOUT_SEC="240") == (60.0, 240.0)

    def test_fractional_values_are_accepted(self):
        assert read_timeouts(LLM_CHUNK_TIMEOUT_SEC="12.5") == (12.5, 90.0)

    @pytest.mark.parametrize("bad", ["0", "-5", "", "  ", "abc", "60s", "None"])
    def test_unusable_values_fall_back_to_the_default(self, bad):
        """타임아웃 0 이면 모든 호출이 즉시 실패한다 — 조용히 기본값으로 떨어져야 한다."""
        assert read_timeouts(LLM_CHUNK_TIMEOUT_SEC=bad) == (60.0, 90.0)


class TestHelperSemantics:
    def test_positive_guard_does_not_leak_into_temperature(self):
        """`LLM_TEMPERATURE=0` 은 정당한 설정이므로 양수 가드를 공유하면 안 된다."""
        code = (
            "from gurunote.llm.client import LLMConfig\n"
            "print(LLMConfig.from_env(provider='openai_compatible').temperature)\n"
        )
        child = dict(os.environ, LLM_TEMPERATURE="0", OPENAI_API_KEY="x",
                     OPENAI_BASE_URL="http://127.0.0.1:1/v1")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=child,
                                capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert float(result.stdout.strip().splitlines()[-1]) == 0.0

    def test_positive_float_env_is_available_for_reuse(self):
        from gurunote.llm.client import _positive_float_env

        assert _positive_float_env("GURUNOTE_NO_SUCH_KEY_", 7.5) == 7.5


class TestResolvedAtCallTimeNotImportTime:
    """`.env` 는 진입점이 import 뒤에 읽는다 — 그때 설정한 값도 먹어야 한다.

    상수는 import 시점에 한 번만 읽으므로, 여기에만 의존하면 `.env` 로 적은 타임아웃이
    영영 반영되지 않는다. 실제로 그랬다: MCP 서버에 `.env` 로 300 을 줬는데 xgrammar
    점검이 기본값 60 초에서 끊겼다. `gui.py` 도 `gurunote.llm` 을 먼저 import 한 뒤
    `load_dotenv()` 를 부르므로 같은 문제였다.
    """

    def test_env_set_after_import_still_applies(self, monkeypatch):
        from gurunote.llm import client

        monkeypatch.delenv("LLM_CHUNK_TIMEOUT_SEC", raising=False)
        monkeypatch.delenv("LLM_HTTP_TIMEOUT_SEC", raising=False)
        assert client._chunk_timeout_sec() == client.DEFAULT_LLM_CHUNK_TIMEOUT_SEC
        # import 이 끝난 뒤에 설정 — .env 를 나중에 읽는 상황과 같다
        monkeypatch.setenv("LLM_CHUNK_TIMEOUT_SEC", "300")
        monkeypatch.setenv("LLM_HTTP_TIMEOUT_SEC", "360")
        assert client._chunk_timeout_sec() == 300.0
        assert client._http_timeout_sec() == 360.0

    def test_falls_back_to_the_module_constant_when_env_is_unset(self, monkeypatch):
        from gurunote.llm import client

        monkeypatch.delenv("LLM_CHUNK_TIMEOUT_SEC", raising=False)
        monkeypatch.setattr(client, "DEFAULT_LLM_CHUNK_TIMEOUT_SEC", 12.5)
        assert client._chunk_timeout_sec() == 12.5

    def test_unusable_late_value_falls_back(self, monkeypatch):
        from gurunote.llm import client

        monkeypatch.setenv("LLM_CHUNK_TIMEOUT_SEC", "0")
        assert client._chunk_timeout_sec() == client.DEFAULT_LLM_CHUNK_TIMEOUT_SEC

    def test_call_sites_do_not_read_the_constant_directly(self):
        """상수를 직접 쓰면 다시 import 시점에 묶인다."""
        import ast
        import pathlib as _p

        source = (_p.Path(__file__).resolve().parents[1] / "gurunote/llm/client.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in ("_chunk_timeout_sec", "_http_timeout_sec"):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and inner.id in (
                        "DEFAULT_LLM_CHUNK_TIMEOUT_SEC", "LLM_HTTP_TIMEOUT_SEC"):
                    offenders.append(f"{node.name} -> {inner.id}")
        assert offenders == [], offenders


class TestDiscoverability:
    def test_settings_allow_list_exposes_both(self):
        from gurunote.service import _KNOWN_SETTINGS

        assert "LLM_CHUNK_TIMEOUT_SEC" in _KNOWN_SETTINGS
        assert "LLM_HTTP_TIMEOUT_SEC" in _KNOWN_SETTINGS

    def test_env_example_documents_both(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "LLM_CHUNK_TIMEOUT_SEC=" in text
        assert "LLM_HTTP_TIMEOUT_SEC=" in text

    def test_neither_is_treated_as_a_secret(self):
        from gurunote.service import _SECRET_KEYS

        assert "LLM_CHUNK_TIMEOUT_SEC" not in _SECRET_KEYS
        assert "LLM_HTTP_TIMEOUT_SEC" not in _SECRET_KEYS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

"""`gurunote.llm` 이 한 파일에서 패키지로 바뀐 뒤에도 지켜야 하는 것들.

분할하면서 실제로 세 번 밟은 함정을 테스트로 고정한다.

1. `Path(__file__).parent / "data"` — 모듈이 한 단계 깊어져 `gurunote/llm/data/` 를 찾았다.
2. `@dataclass` 누락 — 정의를 옮길 때 데코레이터 줄을 빼먹어 `LLMConfig()` 가 인자를 받지 못했다.
3. 모듈을 넘는 직접 import — 호출부에 별도 바인딩이 생겨 정의 모듈을 patch 해도 먹지 않았고,
   테스트가 실제 엔드포인트를 호출해 멈췄다.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

import gurunote.llm as llm

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "gurunote" / "llm"
SUBMODULES = ("client", "prompts", "chunking", "context",
              "entities", "postprocess", "translate", "summarize")


class TestDataFilesResolve:
    """패키지 안 데이터 파일 경로가 한 단계 깊어져도 맞아야 한다."""

    def test_cjk_lookup_and_loanword_files_exist(self):
        assert llm._CJK_LOOKUP_PATH.is_file(), llm._CJK_LOOKUP_PATH
        assert llm._LOANWORD_FILE.is_file(), llm._LOANWORD_FILE

    def test_data_dir_points_at_the_package_not_the_subpackage(self):
        from gurunote.llm._data import DATA_DIR

        assert DATA_DIR.name == "data"
        assert DATA_DIR.parent.name == "gurunote", DATA_DIR

    def test_lookup_actually_loads(self):
        assert llm._load_cjk_lookup(), "cjk 사전이 비어 있다"


class TestPublicSurfaceSurvived:
    def test_config_still_takes_keyword_arguments(self):
        # @dataclass 가 빠지면 "LLMConfig() takes no arguments" 로 죽는다.
        cfg = llm.LLMConfig(provider="openai_compatible", model="m",
                            api_key="k", base_url="http://local/v1")
        assert cfg.provider == "openai_compatible"
        assert cfg.model == "m"

    @pytest.mark.parametrize("name", [
        "translate_transcript", "summarize_translation", "extract_metadata",
        "chunk_segments", "post_process_cjk", "post_process_cjk_text",
        "load_speaker_names", "load_stt_corrections", "build_video_context_block",
        "refresh_canonical_in_markdown", "test_connection", "LLMConfig",
    ])
    def test_public_names_importable_from_the_package(self, name):
        assert hasattr(llm, name), name

    @pytest.mark.parametrize("name", [
        "_call_llm", "_call_llm_with_continuation", "_call_with_wall_clock_timeout",
        "_check_xgrammar_available", "_get_omlx_signature", "_recover_empty_outputs",
        "_collapse_repeated_lines", "_correct_english_annotations",
        "_correct_korean_in_annotations", "_load_canonical_names",
        "_XGRAMMAR_CHECK_CACHE", "CACHE_DIR",
    ])
    def test_internals_the_tests_rely_on_are_still_re_exported(self, name):
        assert hasattr(llm, name), name

    def test_every_submodule_name_is_re_exported(self):
        missing = []
        for mod_name in SUBMODULES:
            mod = importlib.import_module(f"gurunote.llm.{mod_name}")
            for name in getattr(mod, "__all__", ()):
                if not hasattr(llm, name):
                    missing.append(f"{mod_name}.{name}")
        assert missing == [], missing


class TestSubmodulesImportCleanly:
    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_each_submodule_imports_on_its_own(self, mod_name):
        """순환 import 가 생기면 하위 모듈 단독 import 가 깨진다."""
        code = f"import gurunote.llm.{mod_name} as m; print(m.__name__)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_dependency_direction_has_no_cycle(self):
        edges = {}
        for mod_name in SUBMODULES:
            source = (PKG / f"{mod_name}.py").read_text(encoding="utf-8")
            tree = ast.parse(source)
            deps = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "gurunote.llm"
                for alias in node.names
                if alias.name in SUBMODULES
            }
            edges[mod_name] = deps
        import graphlib

        graphlib.TopologicalSorter(edges).prepare()  # 순환이면 CycleError


class TestPatchTargetContract:
    """모듈을 넘는 참조는 모듈 경유여야 한다 — 그래야 patch 지점이 하나로 정해진다."""

    def test_patching_client_is_observed_by_a_caller_in_another_module(self):
        sentinel = "가짜 번역"
        with patch("gurunote.llm.client._call_llm", return_value=sentinel) as mock:
            from gurunote.llm import summarize

            cfg = llm.LLMConfig(provider="openai_compatible", model="m",
                                api_key="k", base_url="http://local/v1")
            out = summarize.client._call_llm(cfg, "sys", "user")
        assert out == sentinel
        assert mock.called, "다른 모듈에서 client 를 patch 한 효과가 보이지 않는다"

    def test_no_submodule_imports_names_directly_from_a_sibling(self):
        offenders = []
        for mod_name in SUBMODULES:
            source = (PKG / f"{mod_name}.py").read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                # `from gurunote.llm.<sibling> import name` 형태를 금지한다.
                if node.module.startswith("gurunote.llm.") and node.module != "gurunote.llm._data":
                    offenders.append(f"{mod_name}: {node.module} -> "
                                     f"{[a.name for a in node.names]}")
        assert offenders == [], offenders

    def test_entity_cache_writes_land_in_the_isolated_directory(self, tmp_path, monkeypatch):
        """conftest 의 격리가 하위 모듈에도 실제로 먹는지 확인.

        `CACHE_DIR` 은 rebind 로 patch 하므로, 읽는 쪽 모듈을 지정해야 한다. 잘못
        지정하면 조용히 실제 `~/.gurunote/entity_cache/` 에 쓴다.
        """
        target = tmp_path / "cache"
        monkeypatch.setattr("gurunote.llm.entities.CACHE_DIR", target)
        llm._save_entity_cache({"key": "video-1"}, {"Sam Altman": {"korean": "샘 올트먼"}}, {})
        written = list(target.rglob("*.json"))
        assert written, f"{target} 안에 아무것도 쓰이지 않았다"
        assert all(str(p).startswith(str(tmp_path)) for p in written)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

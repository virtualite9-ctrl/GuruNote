"""`gurunote/stt` 가 파일에서 패키지로 바뀐 뒤에도 지켜야 하는 것들.

1. 기존 호출부가 쓰던 이름이 패키지 레벨에서 그대로 보여야 한다 (`gurunote.stt.transcribe`).
2. 하위 모듈이 서로 이름을 직접 import 하면 patch 지점이 흩어진다 — engines 는 mlx 의
   함수를 함수 안에서 lazy import 하므로, 호출 시점에 정의 모듈을 patch 하면 반영된다.
   그 계약을 실제 patch 로 고정한다.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

import gurunote.stt as stt

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "gurunote" / "stt"
SUBMODULES = ("engines", "mlx")


class TestPublicSurfaceSurvived:
    @pytest.mark.parametrize("name", [
        "transcribe", "install_whisperx", "is_whisperx_installed",
        "transcribe_mlx", "is_mlx_whisper_available", "is_apple_silicon",
        "is_mlx_ready",
    ])
    def test_public_names_importable_from_the_package(self, name):
        assert hasattr(stt, name), name

    @pytest.mark.parametrize("name", [
        "_MODELS_DIR", "_WHISPER_REPO_MAP", "_assert_transcript_not_empty",
        "_auto_fallback_hint", "_check_cuda_ready", "_ensure_model_local",
        "_has_nvidia_gpu", "_is_mlx_ready", "_transcribe_assemblyai",
        "_transcribe_whisperx",
        "DEFAULT_DIARIZATION_MODEL", "DEFAULT_MLX_MODEL",
        "SEGMENT_RESPLIT_ENV", "_assign_speaker_by_overlap",
        "_check_mps_ready", "_diarize_with_pyannote", "_merge_drifted_speakers",
        "_normalize_speaker_label", "_resplit_segments_by_semantics",
        "_segment_is_complete", "_segment_last_token",
        "_SEGMENT_END_COMPLETE", "_SEGMENT_END_CONJUNCTIONS",
        "_SEGMENT_END_DANGLING", "_SEGMENT_END_MID_PUNCT",
        "_SEGMENT_END_PREPOSITIONS",
    ])
    def test_internals_the_tests_rely_on_are_still_re_exported(self, name):
        assert hasattr(stt, name), name

    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_every_public_name_is_re_exported(self, mod_name):
        import importlib

        mod = importlib.import_module(f"gurunote.stt.{mod_name}")
        missing = [n for n in getattr(mod, "__all__", ())
                   if not hasattr(stt, n)]
        assert missing == [], f"{mod_name}: {missing}"


class TestSubmodulesImportCleanly:
    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_each_submodule_imports_on_its_own(self, mod_name):
        """순환 import 가 생기면 하위 모듈 단독 import 가 깨진다."""
        code = f"import gurunote.stt.{mod_name} as m; print(m.__name__)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr


class TestPatchTargetContract:
    """mlx 를 patch 하면 engines 의 transcribe(engine="mlx") 가 그걸 써야 한다."""

    def test_patching_mlx_is_observed_by_engines(self, tmp_path):
        from gurunote.types import Segment, Transcript

        sentinel = Transcript(
            segments=[Segment(speaker="A", start=0.0, end=1.0, text="안녕")],
            language="ko", engine="mlx", raw=None,
        )
        audio = tmp_path / "clip.wav"
        audio.write_bytes(b"RIFF")
        with patch("gurunote.stt.mlx.transcribe_mlx",
                   return_value=sentinel) as mock:
            out = stt.engines.transcribe(str(audio), engine="mlx")
        assert out is sentinel
        assert mock.called, "engines 가 mlx 를 patch 한 효과를 보지 못한다"

    def test_no_top_level_name_imports_from_a_sibling(self):
        """`from gurunote.stt.<sibling> import name` 은 모듈 레벨에서 금지.

        함수 안 lazy import 는 호출 시점에 다시 실행되므로 patch 계약을 지킨다 —
        허용한다. 모듈 레벨에서 직접 가져오면 patch 지점이 갈라진다.
        """
        offenders = []
        for mod_name in SUBMODULES:
            tree = ast.parse((PKG / f"{mod_name}.py").read_text(encoding="utf-8"))
            for node in tree.body:  # 모듈 레벨만
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.module.startswith("gurunote.stt."):
                    offenders.append(f"{mod_name}: {node.module} -> "
                                     f"{[a.name for a in node.names]}")
        assert offenders == [], offenders


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
"""Step 2: 음성 인식 + 화자 분리 (Speaker Diarization).

엔진 선택 우선순위 (`auto` 모드):
  1. NVIDIA GPU (CUDA) → **WhisperX** (Distil-Whisper + pyannote).
     청크 분할 처리로 VRAM ~6GB 에서 안정 동작.
  2. Apple Silicon (M1~M5) → **MLX Whisper** (`gurunote.stt.mlx`).
     Metal/MPS 가속, pyannote 화자 분리도 MPS 에서 실행.
  3. 위 둘 다 안 되면 → **AssemblyAI Cloud API** 로 폴백.

세 엔진 모두 결과를 `gurunote.types.Transcript` 형태로 정규화해 반환하므로
LLM/요약 단계는 어느 엔진을 썼는지 신경 쓰지 않아도 된다.

`gurunote/stt.py`, `gurunote/stt_mlx.py` 한 파일이던 것을 패키지로 나눴다.
하위 모듈은 의존 방향이 한쪽으로만 흐른다: engines → mlx.

기존 `from gurunote.stt import X`, `from gurunote.stt_mlx import X` 를 그대로
쓸 수 있게 여기서 전부 re-export 한다. 테스트와 호출부가 private 이름까지
참조하고 있어 공개 이름만 내보내면 깨진다.
"""
from __future__ import annotations

from gurunote.stt.engines import (  # noqa: F401
    ProgressFn,
    _MODELS_DIR,
    _WHISPER_REPO_MAP,
    _assert_transcript_not_empty,
    _auto_fallback_hint,
    _check_cuda_ready,
    _ensure_model_local,
    _has_nvidia_gpu,
    _is_mlx_ready,
    _transcribe_assemblyai,
    _transcribe_whisperx,
    install_whisperx,
    is_whisperx_installed,
    transcribe,
)
from gurunote.stt.mlx import (  # noqa: F401
    DEFAULT_DIARIZATION_MODEL,
    DEFAULT_MLX_MODEL,
    SEGMENT_RESPLIT_ENV,
    _SEGMENT_END_COMPLETE,
    _SEGMENT_END_CONJUNCTIONS,
    _SEGMENT_END_DANGLING,
    _SEGMENT_END_MID_PUNCT,
    _SEGMENT_END_PREPOSITIONS,
    _assign_speaker_by_overlap,
    _check_mps_ready,
    _diarize_with_pyannote,
    _merge_drifted_speakers,
    _normalize_speaker_label,
    _resplit_segments_by_semantics,
    _segment_is_complete,
    _segment_last_token,
    is_apple_silicon,
    is_mlx_ready,
    is_mlx_whisper_available,
    transcribe_mlx,
)
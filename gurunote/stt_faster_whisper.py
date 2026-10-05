"""Direct Faster-Whisper inference; no alignment or speaker diarization."""
from __future__ import annotations

import os
from threading import Event
from typing import Callable, List, Optional

from gurunote.types import Segment, Transcript


def is_cuda_ready() -> bool:
    """Probe CTranslate2 directly; a CPU-only PyTorch install is irrelevant."""
    try:
        import ctranslate2
        from faster_whisper import WhisperModel  # noqa: F401
        return ctranslate2.get_cuda_device_count() > 0
    except (ImportError, OSError, RuntimeError):
        return False


def transcribe_faster_whisper(
    audio_path: str, *, log: Callable[[str], None], hotwords: List[str],
    stop_event: Optional[Event] = None,
) -> Transcript:
    def check_cancelled() -> None:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")

    check_cancelled()
    from faster_whisper import WhisperModel

    model_name = os.environ.get("FASTER_WHISPER_MODEL", "").strip() or "large-v3"
    log(f"Faster-Whisper 모델 로딩 ({model_name}, cuda, float16)...")
    check_cancelled()
    model = WhisperModel(model_name, device="cuda", compute_type="float16")
    try:
        log("전사 중 (Faster-Whisper CUDA, 화자 미분리)...")
        check_cancelled()
        stream, info = model.transcribe(
            audio_path,
            language=None,
            initial_prompt=", ".join(hotwords[:30]) if hotwords else None,
        )
        segments = []
        # Cooperative cancellation: never advance the lazy CUDA iterator after
        # a stop request. An already-running native decode cannot be preempted.
        while True:
            check_cancelled()
            try:
                seg = next(stream)
            except StopIteration:
                break
            check_cancelled()
            segments.append(Segment(
                speaker="UNKNOWN", start=float(seg.start), end=float(seg.end),
                text=seg.text.strip(),
            ))
        check_cancelled()
        log(f"Faster-Whisper 전사 완료 — {len(segments)} 세그먼트 (화자 미분리)")
        check_cancelled()
        return Transcript(
            segments=segments, language=info.language, engine="faster-whisper",
            raw={"language": info.language, "model": model_name, "device": "cuda",
                 "compute_type": "float16", "diarized": False},
        )
    finally:
        model.model.unload_model()

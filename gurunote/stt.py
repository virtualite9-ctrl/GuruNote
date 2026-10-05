"""
Step 2: 음성 인식 + 화자 분리 (Speaker Diarization).

엔진 선택 우선순위 (`auto` 모드):
  1. NVIDIA GPU (CUDA) → **WhisperX** (Distil-Whisper + 선택형 화자 분리).
     청크 분할 처리로 VRAM ~6GB 에서 안정 동작.
  2. Apple Silicon (M1~M5) → **MLX Whisper** (`gurunote.stt_mlx`).
     Metal/MPS 가속, 토큰 없는 화자 분리는 로컬 Resemblyzer CPU 추론.
  3. Resemblyzer 선택 시 로컬 실패를 전파한다. 그 외 기존 모드는
     **AssemblyAI Cloud API** 로 폴백할 수 있다.

세 엔진 모두 결과를 `gurunote.types.Transcript` 형태로 정규화해 반환하므로
LLM/요약 단계는 어느 엔진을 썼는지 신경 쓰지 않아도 된다.
"""

from __future__ import annotations

import gc
import os
import platform
import warnings
from pathlib import Path

# Windows HuggingFace 심볼릭 링크 문제 방지:
# Developer Mode 미활성 시 symlink 생성이 실패(WinError 1314)하므로
# HF Hub 가 symlink 대신 파일 복사를 사용하도록 강제한다.
if platform.system() == "Windows":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    # huggingface_hub >= 0.23 에서 symlink 실패 시 자동 복사 폴백을 활성화
    os.environ.setdefault("HUGGINGFACE_HUB_SYMLINK_WARNING", "0")
from typing import Callable, List, Optional

from gurunote.types import Segment, Transcript
from gurunote.diarization import (
    LocalDiarizationError, check_cancelled, diarize_local_segments, resolve_backend,
    huggingface_token, labels_by_first_appearance,
)

ProgressFn = Callable[[str], None]

# IT/AI 도메인 핫워드 — WhisperX 의 initial_prompt 로 주입해 고유명사 인식률 향상.
IT_AI_HOTWORDS: List[str] = [
    "OpenAI", "Anthropic", "DeepMind", "Google DeepMind", "Meta AI", "xAI",
    "Mistral", "Cohere", "Hugging Face", "NVIDIA",
    "Sam Altman", "Dario Amodei", "Demis Hassabis", "Yann LeCun",
    "Andrej Karpathy", "Ilya Sutskever", "Geoffrey Hinton", "Lex Fridman",
    "GPT-4", "GPT-4o", "GPT-5", "Claude", "Claude Sonnet", "Claude Opus",
    "Gemini", "Llama", "Mistral", "Mixtral", "Qwen", "DeepSeek", "o1", "o3",
    "LLM", "RAG", "Fine-tuning", "Pretraining", "Transformer",
    "Attention", "Embedding", "Tokenizer", "Inference", "Quantization",
    "Diffusion", "Multimodal", "Agent", "Tool use", "MCP",
    "Reinforcement Learning", "RLHF", "Chain of Thought", "Mixture of Experts",
    "Context window", "Hallucination", "Alignment", "AGI", "ASI",
    "CUDA", "TPU", "GPU", "H100", "A100", "PyTorch", "JAX", "TensorRT",
]


# =============================================================================
# Public API
# =============================================================================
def transcribe(
    audio_path: str,
    engine: str = "auto",
    progress: Optional[ProgressFn] = None,
    hotwords: Optional[List[str]] = None,
    stop_event: Optional[object] = None,
    diarization_backend: Optional[str] = None,
) -> Transcript:
    """
    오디오 파일을 화자 분리된 Transcript 로 변환한다.

    Args:
        audio_path: 로컬 오디오 파일 경로
        engine: "whisperx" | "mlx" | "assemblyai" | "auto"
        progress: 진행 메시지 콜백
        hotwords: 도메인 핫워드. None 이면 IT_AI_HOTWORDS 기본값 사용.
        stop_event: 중지 이벤트 (GUI 의 threading.Event)
        diarization_backend: auto | resemblyzer | pyannote | none (로컬 STT용)

    Returns:
        Transcript
    """
    log = progress or (lambda _msg: None)
    engine = (engine or "auto").lower().strip()
    hotwords = hotwords if hotwords is not None else IT_AI_HOTWORDS
    backend = resolve_backend(diarization_backend)
    check_cancelled(stop_event)

    if engine == "whisperx":
        result = _transcribe_whisperx(audio_path, log=log, hotwords=hotwords,
                                     diarization_backend=backend, stop_event=stop_event)
        _assert_transcript_not_empty(result)
        return result

    if engine == "mlx":
        from gurunote.stt_mlx import transcribe_mlx
        result = transcribe_mlx(audio_path, log=log, hotwords=hotwords,
                                diarization_backend=backend, stop_event=stop_event)
        _assert_transcript_not_empty(result)
        return result

    if engine == "assemblyai":
        result = _transcribe_assemblyai(audio_path, log=log)
        _apply_cloud_backend_metadata(result, backend, stop_event)
        _assert_transcript_not_empty(result)
        return result

    # auto 라우팅: CUDA WhisperX → Apple Silicon MLX → AssemblyAI
    if _check_cuda_ready():
        try:
            log("[auto] NVIDIA GPU 감지 — WhisperX 로 전사를 시도합니다.")
            result = _transcribe_whisperx(audio_path, log=log, hotwords=hotwords,
                                         diarization_backend=backend, stop_event=stop_event)
            _assert_transcript_not_empty(result)
            return result
        except LocalDiarizationError:
            raise
        except Exception as exc:  # noqa: BLE001
            if backend == "resemblyzer":
                raise LocalDiarizationError(
                    "Local STT failed with Resemblyzer selected; cloud fallback is disabled"
                ) from exc
            log(f"WhisperX 실패 ({exc}). 다음 엔진으로 폴백합니다.")
    elif _is_mlx_ready():
        try:
            log("[auto] Apple Silicon 감지 — MLX Whisper 로 전사를 시도합니다.")
            from gurunote.stt_mlx import transcribe_mlx
            result = transcribe_mlx(audio_path, log=log, hotwords=hotwords,
                                    diarization_backend=backend, stop_event=stop_event)
            _assert_transcript_not_empty(result)
            return result
        except LocalDiarizationError:
            raise
        except Exception as exc:  # noqa: BLE001
            if backend == "resemblyzer":
                raise LocalDiarizationError(
                    "Local STT failed with Resemblyzer selected; cloud fallback is disabled"
                ) from exc
            log(f"MLX Whisper 실패 ({exc}). AssemblyAI 로 폴백합니다.")
    else:
        if backend == "resemblyzer":
            raise LocalDiarizationError(
                "Resemblyzer selected but no local STT engine is available; "
                "select engine='assemblyai' explicitly to use cloud STT"
            )
        hint = _auto_fallback_hint()
        log(f"[auto] 로컬 GPU STT 미사용{hint} — AssemblyAI Cloud API 로 직행합니다.")

    check_cancelled(stop_event)
    result = _transcribe_assemblyai(audio_path, log=log)
    _apply_cloud_backend_metadata(result, backend, stop_event)
    _assert_transcript_not_empty(result)
    return result


def _apply_cloud_backend_metadata(result: Transcript, backend: str, stop_event=None) -> None:
    check_cancelled(stop_event)
    diarization = {"backend": "assemblyai"}
    if backend == "none":
        result.segments, diarization = diarize_local_segments(
            "", result.segments, backend="none", stop_event=stop_event)
    result.raw = {**(result.raw or {}), "diarization": diarization}


def _is_mlx_ready() -> bool:
    """Apple Silicon + mlx-whisper 패키지 설치 확인."""
    try:
        from gurunote.stt_mlx import is_mlx_ready
        return is_mlx_ready()
    except Exception:  # noqa: BLE001
        return False


def _auto_fallback_hint() -> str:
    """auto 라우팅이 AssemblyAI 로 떨어질 때 사용자 안내 문구."""
    if _has_nvidia_gpu():
        return (
            " (CUDA PyTorch 미설치.\n"
            "  터미널: pip install torch --index-url "
            "https://download.pytorch.org/whl/cu128)"
        )
    import platform
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return (
            " (Apple Silicon 감지됐으나 mlx-whisper 미설치.\n"
            "  터미널: pip install -r requirements-mac.txt)"
        )
    return ""


def _assert_transcript_not_empty(transcript: Transcript) -> None:
    if not transcript.segments:
        raise RuntimeError(
            "전사 결과가 비어 있습니다. 오디오 품질/형식 또는 STT 엔진 설정을 확인해주세요."
        )
    has_text = any((seg.text or "").strip() for seg in transcript.segments)
    if not has_text:
        raise RuntimeError(
            "전사 텍스트가 비어 있습니다. 다른 STT 엔진으로 다시 시도해주세요."
        )


# =============================================================================
# WhisperX 엔진 (Distil-Whisper + 선택형 화자 분리)
# =============================================================================
def is_whisperx_installed() -> bool:
    try:
        import whisperx  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def install_whisperx(progress: Optional[ProgressFn] = None) -> bool:
    import subprocess
    import sys

    log = progress or (lambda _msg: None)
    log("WhisperX 설치 중 (pip install whisperx)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "whisperx"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            log("WhisperX 설치 완료!")
            return True
        log(f"WhisperX 설치 실패:\n{result.stderr[:300]}")
        return False
    except Exception as exc:  # noqa: BLE001
        log(f"WhisperX 설치 실패: {exc}")
        return False


# faster-whisper 모델의 HuggingFace repo 매핑
_WHISPER_REPO_MAP = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
}

_MODELS_DIR = Path.home() / ".gurunote" / "models"


def _has_nvidia_gpu() -> bool:
    """nvidia-smi 가 존재하면 NVIDIA GPU 가 있다고 판단."""
    import shutil
    return shutil.which("nvidia-smi") is not None


def _check_cuda_ready() -> bool:
    """torch.cuda 가 사용 가능한지 확인."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


def _ensure_model_local(model_name: str, log: ProgressFn) -> str:
    """
    WhisperX 모델을 symlink 없이 로컬 디렉토리에 다운로드.

    Windows 의 HuggingFace 캐시 symlink 문제(WinError 1314)를 근본적으로 회피:
    `snapshot_download(local_dir_use_symlinks=False)` 로 파일을 직접 복사.
    이미 다운로드 완료된 경우 즉시 로컬 경로를 반환.

    Returns:
        모델이 저장된 로컬 디렉토리 경로 (WhisperX 에 model_path 로 전달)
    """
    repo_id = _WHISPER_REPO_MAP.get(model_name)
    if not repo_id:
        # 매핑에 없는 이름은 직접 경로 또는 커스텀 repo 로 간주
        return model_name

    local_dir = _MODELS_DIR / model_name
    marker = local_dir / "config.json"

    if marker.exists():
        return str(local_dir)

    # 최초 다운로드
    log(f"모델 다운로드 중 ({repo_id} → {local_dir})...")
    from huggingface_hub import snapshot_download  # type: ignore

    snapshot_download(
        repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,  # 핵심: symlink 대신 파일 복사
    )
    log("모델 다운로드 완료")
    return str(local_dir)


def _transcribe_whisperx(
    audio_path: str, log: ProgressFn, hotwords: List[str],
    diarization_backend: Optional[str] = None,
    stop_event: Optional[object] = None,
) -> Transcript:
    """WhisperX 로 전사 + 화자 분리."""
    backend = resolve_backend(diarization_backend)
    check_cancelled(stop_event)
    import torch

    # pyannote / torchcodec / huggingface 의 무해한 경고 억제
    warnings.filterwarnings("ignore", message=".*torchcodec.*")
    warnings.filterwarnings("ignore", message=".*symlink.*")
    warnings.filterwarnings("ignore", message=".*hf_xet.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
    warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")

    import whisperx  # type: ignore

    # GPU 필수 — CPU 모드는 비실용적이므로 거부
    if not torch.cuda.is_available():
        hint = ""
        if _has_nvidia_gpu():
            hint = (
                "\nNVIDIA GPU 가 있지만 PyTorch 가 CPU 버전입니다.\n"
                "터미널에서 다음 명령 후 앱을 재시작하세요:\n"
                "  pip install torch --index-url https://download.pytorch.org/whl/cu128"
            )
        raise RuntimeError(
            f"WhisperX 는 GPU(CUDA) 가 필요합니다.{hint}\n"
            "GPU 가 없으면 STT 엔진을 'auto' 또는 'assemblyai' 로 변경하세요."
        )

    device = "cuda"
    compute_type = "float16"

    model_name = os.environ.get("WHISPERX_MODEL", "distil-large-v3")
    batch_size = int(os.environ.get("WHISPERX_BATCH_SIZE", "16"))
    initial_prompt = ", ".join(hotwords[:30]) if hotwords else None

    # Windows symlink 문제 완전 우회:
    # HuggingFace 기본 캐시(~/.cache/huggingface/)는 symlink 사용 → WinError 1314.
    # 대신 ~/.gurunote/models/ 에 local_dir_use_symlinks=False 로 직접 다운로드하고
    # 로컬 경로를 WhisperX 에 전달하면 symlink 을 아예 거치지 않는다.
    model_path = _ensure_model_local(model_name, log)

    # WhisperX 의 initial_prompt 는 load_model 의 asr_options 로 전달해야 함
    # (transcribe() 에 직접 넣으면 FasterWhisperPipeline 이 거부)
    asr_options = {}
    if initial_prompt:
        asr_options["initial_prompt"] = initial_prompt

    # 1. 전사
    log(f"WhisperX 모델 로딩 ({model_name}, {device}, {compute_type})...")
    model = whisperx.load_model(
        model_path, device, compute_type=compute_type,
        language="en",
        asr_options=asr_options,
    )

    log("전사 중 (청크 분할 처리)...")
    audio = whisperx.load_audio(audio_path)
    check_cancelled(stop_event)
    result = model.transcribe(audio, batch_size=batch_size)
    check_cancelled(stop_event)
    log(f"전사 완료 — {len(result.get('segments', []))} 세그먼트")

    # 2. 워드 레벨 타임스탬프 정렬
    log("타임스탬프 정렬 중...")
    lang = result.get("language", "en")
    model_a, metadata = whisperx.load_align_model(language_code=lang, device=device)
    result = whisperx.align(
        result["segments"], model_a, metadata, audio, device,
        return_char_alignments=False,
    )
    check_cancelled(stop_event)

    # 모델 메모리 해제 (다음 단계 전에)
    del model, model_a
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if backend in {"resemblyzer", "none"}:
        log("화자 분리: " + ("none (비활성)" if backend == "none" else
                            "로컬 Resemblyzer, ASR 구간별 근사 분리; 겹침 미지원"))
        segments, diarization = diarize_local_segments(
            audio_path,
            [Segment("", float(seg.get("start", 0.0)), float(seg.get("end", 0.0)),
                     seg.get("text") or "") for seg in result.get("segments", [])],
            backend=backend, stop_event=stop_event,
        )
        return Transcript(
            segments=segments, engine="whisperx", language=lang,
            raw={"language": lang, "model": model_name, "diarization": diarization},
        )

    # 3. 화자 분리 (HuggingFace 토큰 + 모델 사용 동의 필요)
    diarization = {"backend": "pyannote", "status": "unavailable"}
    hf_token = huggingface_token()
    if hf_token:
        log("화자 분리 중 (pyannote)...")
        try:
            _DiarPipeline = whisperx.DiarizationPipeline
        except AttributeError:
            from whisperx.diarize import DiarizationPipeline as _DiarPipeline

        try:
            try:
                diarize_model = _DiarPipeline(token=hf_token, device=device)
            except TypeError:
                diarize_model = _DiarPipeline(use_auth_token=hf_token, device=device)
            diarized_turns = diarize_model(audio)
            result = whisperx.assign_word_speakers(diarized_turns, result)
            diarization["status"] = "completed"
            del diarize_model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log("화자 분리 완료")
        except Exception as diar_exc:
            diarization["status"] = "failed"
            err_msg = str(diar_exc)
            if "401" in err_msg or "gated" in err_msg.lower() or "restricted" in err_msg.lower():
                log(
                    "화자 분리 실패: pyannote 모델 접근 권한이 없습니다.\n"
                    "  아래 페이지에서 'Agree and access repository' 를 클릭하세요:\n"
                    "  https://huggingface.co/pyannote/speaker-diarization-community-1\n"
                    "  화자 분리 없이 계속 진행합니다."
                )
            else:
                log(f"화자 분리 실패: {diar_exc}\n  화자 분리 없이 계속 진행합니다.")
    else:
        log(
            "HUGGINGFACE_TOKEN 미설정 — 화자 분리를 건너뜁니다.\n"
            "  화자 분리를 원하면 Settings 에서 HUGGINGFACE_TOKEN 을 설정하고,\n"
            "  https://huggingface.co/pyannote/speaker-diarization-community-1\n"
            "  에서 모델 사용에 동의하세요."
        )

    check_cancelled(stop_event)
    # 4. 공통 Segment 형태로 변환
    segments: List[Segment] = []
    for seg in result.get("segments", []):
        speaker = seg.get("speaker", "SPEAKER_00")
        # SPEAKER_00 → A, SPEAKER_01 → B 변환
        if speaker.startswith("SPEAKER_"):
            try:
                idx = int(speaker.split("_")[-1])
                speaker = chr(ord("A") + idx)
            except (ValueError, IndexError):
                pass

        segments.append(Segment(
            speaker=speaker,
            start=float(seg.get("start", 0.0)),
            end=float(seg.get("end", 0.0)),
            text=(seg.get("text") or "").strip(),
        ))

    segments = labels_by_first_appearance(segments)
    log(f"WhisperX 전사 완료 — {len(segments)} 세그먼트, "
        f"{len(set(s.speaker for s in segments))} 화자")

    return Transcript(
        segments=segments,
        engine="whisperx",
        raw={"language": lang, "model": model_name, "diarization": diarization},
    )


# =============================================================================
# AssemblyAI 폴백 엔진
# =============================================================================
def _transcribe_assemblyai(audio_path: str, log: ProgressFn) -> Transcript:
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "AssemblyAI 폴백을 쓰려면 .env 에 ASSEMBLYAI_API_KEY 를 설정해야 합니다."
        )

    import assemblyai as aai  # type: ignore

    aai.settings.api_key = api_key
    # AssemblyAI API: speech_models 파라미터 (복수형, 문자열 리스트)
    try:
        config = aai.TranscriptionConfig(
            speaker_labels=True,
            speech_models=["universal-3-pro"],
        )
    except TypeError:
        # 구 버전 폴백
        try:
            config = aai.TranscriptionConfig(
                speaker_labels=True,
                speech_model=aai.SpeechModel.best,
            )
        except (TypeError, AttributeError):
            config = aai.TranscriptionConfig(speaker_labels=True)

    log("AssemblyAI 에 업로드 후 화자 분리 전사 중...")
    transcriber = aai.Transcriber()
    result = transcriber.transcribe(audio_path, config=config)

    if result.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI 에러: {result.error}")

    segments: List[Segment] = []
    for utt in result.utterances or []:
        segments.append(
            Segment(
                speaker=str(utt.speaker),
                start=float(utt.start) / 1000.0,
                end=float(utt.end) / 1000.0,
                text=(utt.text or "").strip(),
            )
        )

    log(f"AssemblyAI 전사 완료 — {len(segments)} 세그먼트")
    return Transcript(
        segments=segments,
        engine="assemblyai",
        raw={"id": result.id, "status": str(result.status)},
    )

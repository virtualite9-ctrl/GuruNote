"""Direct CUDA STT contracts; no model downloads, GPU or cloud in unit tests."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from gurunote import stt


@pytest.fixture
def backend(monkeypatch):
    state = SimpleNamespace(
        loads=[], calls=[], unloaded=0, cuda_devices=1, error=None,
        segments=[
            SimpleNamespace(start=0.5, end=1.25, text=" Hello there. "),
            SimpleNamespace(start=1.3, end=2.0, text=" General Kenobi. "),
        ],
    )

    class Model:
        def __init__(self, model, **kwargs):
            state.loads.append((model, kwargs))
            self.model = SimpleNamespace(unload_model=self.unload)

        def unload(self):
            state.unloaded += 1

        def transcribe(self, path, **kwargs):
            state.calls.append((path, kwargs))
            if state.error:
                raise state.error
            return iter(state.segments), SimpleNamespace(language="en", duration=2.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(
        get_cuda_device_count=lambda: state.cuda_devices,
    ))
    # The direct path must work without PyTorch, WhisperX or pyannote.
    for name in ("torch", "whisperx", "pyannote"):
        monkeypatch.setitem(sys.modules, name, None)
    for name in ("FASTER_WHISPER_MODEL", "FASTER_WHISPER_COMPUTE_TYPE", "FASTER_WHISPER_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stt, "_transcribe_assemblyai", lambda *a, **k: pytest.fail("unexpected cloud STT"))
    monkeypatch.setattr(stt, "_is_mlx_ready", lambda: False)
    return state


def test_direct_cuda_transcript_preserves_text_timestamps_and_language(backend):
    transcript = stt.transcribe("speech.wav", engine="faster-whisper", hotwords=["CUDA"])

    assert transcript.engine == "faster-whisper"
    assert transcript.language == "en"
    assert [s.to_dict() for s in transcript.segments] == [
        {"speaker": "UNKNOWN", "start": 0.5, "end": 1.25, "text": "Hello there."},
        {"speaker": "UNKNOWN", "start": 1.3, "end": 2.0, "text": "General Kenobi."},
    ]
    assert backend.loads[0][0] == "large-v3"
    assert backend.loads[0][1]["device"] == "cuda"
    assert backend.loads[0][1]["compute_type"] == "float16"
    assert backend.calls[0][1]["language"] is None
    assert backend.calls[0][1]["initial_prompt"] == "CUDA"
    assert transcript.raw["diarized"] is False
    assert backend.unloaded == 1


def test_configurable_model_preserves_gpu_only_defaults(backend, monkeypatch):
    monkeypatch.setenv("FASTER_WHISPER_MODEL", "base")
    result = stt.transcribe("speech.wav", engine="faster-whisper", hotwords=[])
    assert backend.loads == [("base", {"device": "cuda", "compute_type": "float16"})]
    assert result.raw["model"] == "base"
    assert backend.calls[0][1]["initial_prompt"] is None


@pytest.mark.parametrize("engine", ["whispr", "faster_whisper"])
def test_unknown_engine_is_rejected_without_inference(backend, engine):
    with pytest.raises(ValueError, match="STT"):
        stt.transcribe("speech.wav", engine=engine)
    assert backend.loads == []


def test_auto_uses_direct_cuda_without_torch(backend):
    assert stt.transcribe("speech.wav").engine == "faster-whisper"
    assert backend.unloaded == 1


def test_auto_without_local_gpu_fails_without_cloud(backend):
    backend.cuda_devices = 0
    with pytest.raises(RuntimeError, match="로컬 GPU"):
        stt.transcribe("speech.wav")
    assert backend.loads == []


def test_auto_local_failure_propagates_without_cloud(backend):
    backend.error = RuntimeError("CUDA test failure")
    with pytest.raises(RuntimeError, match="CUDA test failure"):
        stt.transcribe("speech.wav")
    assert backend.unloaded == 1


def test_auto_empty_transcript_fails_without_cloud(backend):
    backend.segments = []
    with pytest.raises(RuntimeError, match="비어"):
        stt.transcribe("speech.wav")
    assert backend.unloaded == 1


@pytest.mark.parametrize("engine", ["auto", "faster-whisper", "whisperx", "mlx", "assemblyai"])
def test_cancelled_before_dispatch_never_loads_or_uploads(backend, engine):
    from threading import Event
    stop = Event()
    stop.set()
    with pytest.raises(RuntimeError, match="중지"):
        stt.transcribe("speech.wav", engine=engine, stop_event=stop)
    assert backend.loads == []
    assert backend.calls == []


@pytest.mark.parametrize("engine", ["auto", "faster-whisper"])
def test_cancel_during_lazy_inference_unloads_without_cloud(backend, engine):
    from threading import Event
    stop = Event()

    def stream():
        stop.set()
        yield SimpleNamespace(start=0, end=1, text="partial")
        pytest.fail("inference continued after cancellation")

    backend.segments = stream()
    with pytest.raises(RuntimeError, match="중지"):
        stt.transcribe("speech.wav", engine=engine, stop_event=stop)
    assert backend.unloaded == 1


@pytest.mark.parametrize("nvidia_smi", [None, "/usr/bin/nvidia-smi"])
def test_explicit_whisperx_without_cuda_reports_runtime_error(monkeypatch, nvidia_smi):
    import shutil

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
    ))
    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace())
    monkeypatch.setattr(shutil, "which", lambda name: nvidia_smi)
    with pytest.raises(RuntimeError, match=r"GPU\(CUDA\)") as exc:
        stt.transcribe("speech.wav", engine="whisperx")
    assert ("PyTorch" in str(exc.value)) == bool(nvidia_smi)


def test_cancel_after_model_load_does_not_start_transcription(backend):
    from threading import Event
    stop = Event()

    def progress(msg):
        if "전사 중" in msg:
            stop.set()

    with pytest.raises(RuntimeError, match="중지"):
        stt.transcribe("speech.wav", engine="faster-whisper", stop_event=stop, progress=progress)
    assert backend.calls == []
    assert backend.unloaded == 1

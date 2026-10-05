"""Local diarization contracts; numerical tests do not claim model accuracy."""
import builtins
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from threading import Event
from copy import deepcopy

from gurunote.types import Segment, Transcript

import pytest


def test_backend_selection_without_hf_token(monkeypatch):
    from gurunote.diarization import resolve_backend

    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    assert resolve_backend() == "resemblyzer"
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "test-token-not-a-credential")
    assert resolve_backend() == "pyannote"
    assert resolve_backend("resemblyzer") == "resemblyzer"
    monkeypatch.setenv("GURUNOTE_DIARIZATION_BACKEND", "none")
    assert resolve_backend() == "none"
    assert resolve_backend(" AUTO ") == "pyannote"
    with pytest.raises(ValueError, match="backend"):
        resolve_backend("invalid")


def test_numerical_clustering_preserves_segments_and_labels_by_first_time():
    from gurunote.diarization import diarize_segments

    # Deliberately out of order: output order and all ASR fields must survive.
    segments = [Segment("old", 4.0, 6.0, " third "),
                Segment("old", 0.0, 2.0, "  First,\n"),
                Segment("old", 2.0, 4.0, "둘째"),
                Segment("old", 6.0, 8.0, "Fourth.")]
    original = deepcopy(segments)
    vectors = {0.0: [3.0, 0.0], 2.0: [0.0, 4.0],
               4.0: [0.99, 0.01], 6.0: [0.01, 0.99]}
    output, metadata = diarize_segments(
        "unused.wav", segments, embed_interval=lambda start, end: vectors[start])
    assert [s.speaker for s in output] == ["A", "A", "B", "B"]
    assert [(s.start, s.end, s.text) for s in output] == [
        (s.start, s.end, s.text) for s in original]
    assert segments == original
    assert metadata["backend"] == "resemblyzer"
    assert metadata["approximate"] is True
    assert metadata["overlap_supported"] is False
    assert metadata["speaker_count"] == 2
    # Real cosine/centroid arithmetic, including scale invariance; no cluster mock.
    again, _ = diarize_segments(
        "unused.wav", segments, embed_interval=lambda start, end: vectors[start])
    assert again == output


def test_dependency_failure_is_actionable_local_error(monkeypatch):
    from gurunote.diarization import LocalDiarizationError, diarize_segments

    original_import = builtins.__import__

    def without_resemblyzer(name, *args, **kwargs):
        if name == "resemblyzer":
            raise ModuleNotFoundError("test: optional resemblyzer not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_resemblyzer)
    with pytest.raises(LocalDiarizationError, match="requirements-diarization.txt") as caught:
        diarize_segments("unused.wav", [Segment("", 0, 2, "a"), Segment("", 2, 4, "b")])
    assert isinstance(caught.value.__cause__, ImportError)


@pytest.mark.parametrize("kind", ["silence", "short_audio", "one_usable", "short_intervals"])
def test_unusable_audio_is_not_fabricated_as_all_a(kind):
    from gurunote.diarization import LocalDiarizationError, _segment_embedding, diarize_segments

    sr = 1000
    tone = [0.1 * math.sin(i * 0.2) for i in range(2000)]
    waveform = {"silence": [0.0] * 4000, "short_audio": tone[:500],
                "one_usable": tone + [0.0] * 2000,
                "short_intervals": tone * 2}[kind]
    segments = [Segment("", 0, 2, "First"), Segment("", 2, 4, "Second")]
    if kind == "short_intervals":
        segments = [Segment("", 0, 0.1, "First"), Segment("", 2, 2.1, "Second")]
    encoded = []

    def encode(clip):
        encoded.append(len(clip))
        return [sum(x * x for x in clip), 0.0]

    def embed(start, end):
        return _segment_embedding(waveform, start, end, sample_rate=sr,
                                  preprocess=lambda clip: clip, encode=encode)

    with pytest.raises(LocalDiarizationError, match="two usable"):
        diarize_segments("unused.wav", segments, embed_interval=embed)
    assert len(encoded) == (1 if kind == "one_usable" else 0)


@pytest.mark.parametrize("when", ["before", "during"])
def test_cancellation_stops_embedding_work(when):
    from gurunote.diarization import DiarizationCancelled, diarize_segments

    stop = Event()
    calls = []
    if when == "before":
        stop.set()

    def embed(start, end):
        calls.append(start)
        stop.set()
        return [1.0, 0.0]

    with pytest.raises(DiarizationCancelled):
        diarize_segments("unused.wav", [Segment("", 0, 2, "a"), Segment("", 2, 4, "b")],
                         stop_event=stop, embed_interval=embed)
    assert len(calls) == (0 if when == "before" else 1)


def test_embedding_inference_failure_keeps_cause_and_local_error_type():
    from gurunote.diarization import LocalDiarizationError, diarize_segments

    failure = OSError("decoder or model failed")

    def fail(start, end):
        raise failure

    with pytest.raises(LocalDiarizationError, match="embedding") as caught:
        diarize_segments("unused.wav", [Segment("", 0, 2, "a"), Segment("", 2, 4, "b")],
                         embed_interval=fail)
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("backend, token", [(None, ""), ("resemblyzer", "present-test-only")])
def test_mlx_tokenfree_path_preserves_asr_without_hf_or_pyannote(monkeypatch, backend, token):
    import gurunote.diarization as diarization
    import gurunote.stt_mlx as mlx

    raw = [{"start": 0.0, "end": 2.0, "text": "  first and "},
           {"start": 2.0, "end": 4.0, "text": " second "},
           {"start": 4.0, "end": 6.0, "text": " third. "}]
    original = deepcopy(raw)
    monkeypatch.setenv("HUGGINGFACE_TOKEN", token)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setenv("GURUNOTE_SEGMENT_RESPLIT", "1")
    monkeypatch.setattr(mlx, "is_apple_silicon", lambda: True)
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(
        transcribe=lambda *a, **kw: {"segments": raw, "language": "ko"}))
    monkeypatch.setattr(diarization, "_load_embedder", lambda *a: (
        lambda start, end: [1, 0] if start != 2 else [0, 1]))
    original_import = builtins.__import__
    forbidden = []

    def no_gated_imports(name, *args, **kwargs):
        if name.startswith(("pyannote", "huggingface_hub")):
            forbidden.append(name)
            raise AssertionError("Token-free diarization touched a gated/HF dependency")
        return original_import(name, *args, **kwargs)

    def no_pyannote(*args, **kwargs):
        pytest.fail("pyannote must not run")

    monkeypatch.setattr(builtins, "__import__", no_gated_imports)
    monkeypatch.setattr(mlx, "_diarize_with_pyannote", no_pyannote)
    output = mlx.transcribe_mlx("synthetic-unused.wav", log=lambda _: None, hotwords=[],
                                diarization_backend=backend)
    assert [s.speaker for s in output.segments] == ["A", "B", "A"]
    assert [(s.start, s.end, s.text) for s in output.segments] == [
        (s["start"], s["end"], s["text"]) for s in original]
    assert raw == original
    assert output.raw["diarization"]["backend"] == "resemblyzer"
    assert output.raw["segment_resplit"] is False
    assert forbidden == []


@pytest.mark.parametrize("local_engine", ["mlx", "whisperx"])
@pytest.mark.parametrize("explicit_backend", [False, True])
def test_auto_engine_never_uploads_after_local_diarization_failure(
        monkeypatch, local_engine, explicit_backend):
    import gurunote.diarization as diarization
    import gurunote.stt as stt
    import gurunote.stt_mlx as mlx

    raw = [{"start": 0, "end": 2, "text": "one"},
           {"start": 2, "end": 4, "text": "two"}]
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setattr(stt, "_check_cuda_ready", lambda: local_engine == "whisperx")
    monkeypatch.setattr(stt, "_is_mlx_ready", lambda: local_engine == "mlx")
    if local_engine == "whisperx":
        _stub_whisperx(monkeypatch, raw)
    else:
        monkeypatch.setattr(mlx, "is_apple_silicon", lambda: True)
        monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(
            transcribe=lambda *a, **kw: {"segments": raw}))

    def broken_embed(start, end):
        raise OSError("local model inference failed")

    monkeypatch.setattr(diarization, "_load_embedder", lambda *a: broken_embed)
    uploads = []

    def cloud(*a, **kw):
        uploads.append(True)
        pytest.fail("Audio must not be uploaded on local diarization failure")

    monkeypatch.setattr(stt, "_transcribe_assemblyai", cloud)
    kwargs = {"diarization_backend": "resemblyzer"} if explicit_backend else {}
    with pytest.raises(diarization.LocalDiarizationError, match="embedding"):
        stt.transcribe("unused.wav", engine="auto", **kwargs)
    assert uploads == []


def _stub_whisperx(monkeypatch, raw):
    import gurunote.stt as stt

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, empty_cache=lambda: None)))
    monkeypatch.setattr(stt, "_ensure_model_local", lambda *a: "test-model")

    def forbidden(*a, **kw):
        pytest.fail("WhisperX pyannote must not run in token-free mode")

    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(
        load_model=lambda *a, **kw: SimpleNamespace(
            transcribe=lambda *a, **kw: {"segments": raw, "language": "en"}),
        load_audio=lambda path: [], load_align_model=lambda **kw: (None, {}),
        align=lambda segments, *a, **kw: {"segments": segments},
        DiarizationPipeline=forbidden, assign_word_speakers=forbidden,
    ))


@pytest.mark.parametrize("backend", [None, "resemblyzer"])
def test_whisperx_tokenfree_path_uses_actual_clustering(monkeypatch, backend):
    import gurunote.diarization as diarization
    import gurunote.stt as stt

    raw = [{"start": 0.0, "end": 2.0, "text": "  first "},
           {"start": 2.0, "end": 4.0, "text": "second\n"}]
    _stub_whisperx(monkeypatch, raw)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setattr(diarization, "_load_embedder", lambda *a: (
        lambda start, end: [1, 0] if start == 0 else [0, 1]))
    output = stt._transcribe_whisperx("unused.wav", log=lambda _: None, hotwords=[],
                                      diarization_backend=backend)
    assert [s.to_dict() for s in output.segments] == [
        dict(raw[0], speaker="A"), dict(raw[1], speaker="B")]
    assert output.raw["diarization"]["backend"] == "resemblyzer"


@pytest.mark.parametrize("engine", ["mlx", "whisperx"])
def test_explicit_none_is_labelled_and_preserves_asr(monkeypatch, engine):
    import gurunote.stt as stt
    import gurunote.stt_mlx as mlx

    raw = [{"start": 0.0, "end": 0.1, "text": " First and "},
           {"start": 0.1, "end": 0.2, "text": " second "}]
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "test-token-not-a-credential")
    if engine == "whisperx":
        _stub_whisperx(monkeypatch, raw)
    else:
        monkeypatch.setattr(mlx, "is_apple_silicon", lambda: True)
        monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(
            transcribe=lambda *a, **kw: {"segments": raw}))
        monkeypatch.setattr(mlx, "_diarize_with_pyannote", lambda *a: pytest.fail("none used pyannote"))
    output = stt.transcribe("unused.wav", engine=engine, diarization_backend="none")
    assert [s.to_dict() for s in output.segments] == [dict(s, speaker="A") for s in raw]
    assert output.raw["diarization"]["backend"] == "none"
    assert output.raw["diarization"]["status"] == "disabled"


@pytest.mark.parametrize("engine", ["mlx", "whisperx"])
def test_authorized_pyannote_remains_available_with_first_appearance_labels(monkeypatch, engine):
    import gurunote.diarization as diarization
    import gurunote.stt as stt
    import gurunote.stt_mlx as mlx

    raw = [{"start": 0.0, "end": 2.0, "text": "First.", "speaker": "SPEAKER_09"},
           {"start": 2.0, "end": 4.0, "text": "Second.", "speaker": "SPEAKER_03"}]
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "test-token-not-a-credential")
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setattr(diarization, "_load_embedder", lambda *a: pytest.fail("pyannote used resemblyzer"))
    calls = []
    if engine == "whisperx":
        _stub_whisperx(monkeypatch, raw)

        def pipeline(**kwargs):
            calls.append(kwargs["token"])
            return lambda audio: "test-turns"

        sys.modules["whisperx"].DiarizationPipeline = pipeline
        sys.modules["whisperx"].assign_word_speakers = lambda turns, result: result
        output = stt._transcribe_whisperx("unused.wav", lambda _: None, [])
    else:
        monkeypatch.setattr(mlx, "is_apple_silicon", lambda: True)
        monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(
            transcribe=lambda *a, **kw: {"segments": raw}))

        def pyannote(path, token, log):
            calls.append(token)
            return [(s["start"], s["end"], s["speaker"]) for s in raw]

        monkeypatch.setattr(mlx, "_diarize_with_pyannote", pyannote)
        output = mlx.transcribe_mlx("unused.wav", lambda _: None, [])
    assert calls == ["test-token-not-a-credential"]
    assert [s.speaker for s in output.segments] == ["A", "B"]
    assert output.raw["diarization"]["backend"] == "pyannote"
    assert output.raw["diarization"]["status"] == "completed"


@pytest.mark.parametrize("failure", ["no_local_engine", "local_asr_dependency"])
def test_selected_tokenfree_mode_cannot_fall_through_to_cloud(monkeypatch, failure):
    import gurunote.stt as stt
    from gurunote.diarization import LocalDiarizationError

    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setattr(stt, "_check_cuda_ready", lambda: failure == "local_asr_dependency")
    monkeypatch.setattr(stt, "_is_mlx_ready", lambda: False)

    def missing_asr(*a, **kw):
        raise ImportError("ASR library missing")

    monkeypatch.setattr(stt, "_transcribe_whisperx", missing_asr)
    monkeypatch.setattr(stt, "_transcribe_assemblyai", lambda *a, **kw: pytest.fail("cloud upload"))
    with pytest.raises(LocalDiarizationError):
        stt.transcribe("unused.wav")


def test_explicit_pyannote_without_token_fails_before_inference(monkeypatch):
    from gurunote.diarization import LocalDiarizationError, resolve_backend

    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    with pytest.raises(LocalDiarizationError, match="HUGGINGFACE_TOKEN"):
        resolve_backend("pyannote")


def test_stt_and_mcp_import_lazily_in_a_fresh_interpreter():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/verify_tokenfree_diarization.py"), "--lazy"],
        cwd=root, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "without optional model packages" in result.stdout


def test_real_adapter_slices_before_preprocessing_and_marks_silence_unknown(monkeypatch):
    """Exercise loader, slicing, energy and clustering with an injected encoder API."""
    from gurunote.diarization import diarize_segments

    waveform = [0.1] * 32000 + [0.0] * 32000 + [-0.1] * 32000
    preprocessed = []
    model_args = []

    class Encoder:
        def __init__(self, **kwargs):
            model_args.append(kwargs)

        def embed_utterance(self, clip):
            return [sum(x for x in clip if x > 0), sum(-x for x in clip if x < 0)]

    def preprocess(clip, source_sr):
        assert source_sr == 16000
        preprocessed.append((len(clip), clip[0]))
        return clip

    def load(path, sr, mono):
        assert path == "synthetic.wav" and sr == 16000 and mono is True
        return waveform, sr

    monkeypatch.setitem(sys.modules, "resemblyzer", SimpleNamespace(
        VoiceEncoder=Encoder, preprocess_wav=preprocess))
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace(load=load))
    original_import = builtins.__import__

    def forbid_hf(name, *args, **kwargs):
        if name.startswith(("pyannote", "huggingface_hub")):
            pytest.fail("Local adapter accessed HF/pyannote")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_hf)
    output, metadata = diarize_segments("synthetic.wav", [
        Segment("", 0, 2, "a"), Segment("", 2, 4, "unusable"), Segment("", 4, 6, "b")])
    assert [s.speaker for s in output] == ["A", "UNKNOWN", "B"]
    assert preprocessed == [(32000, 0.1), (32000, -0.1)]
    assert model_args == [{"device": "cpu", "verbose": False}]
    assert metadata["status"] == "partial"
    assert metadata["unassigned_intervals"] == [1]


@pytest.mark.parametrize("segments", [[], [Segment("", 0, 3, "one")]])
def test_too_few_intervals_do_not_load_model(segments, monkeypatch):
    import gurunote.diarization as diarization

    monkeypatch.setattr(diarization, "_load_embedder", lambda *a: pytest.fail("unnecessary model load"))
    with pytest.raises(diarization.LocalDiarizationError, match="two usable"):
        diarization.diarize_segments("unused.wav", segments)


@pytest.mark.parametrize("vector", [[], [0.0, 0.0], [float("nan"), 1], [float("inf"), 1], ["bad"]])
def test_invalid_embedding_never_becomes_a_speaker(vector):
    from gurunote.diarization import LocalDiarizationError, diarize_segments

    with pytest.raises(LocalDiarizationError):
        diarize_segments("unused.wav", [Segment("", 0, 2, "a"), Segment("", 2, 4, "b")],
                         embed_interval=lambda *a: vector)


@pytest.mark.parametrize("engine", ["auto", "mlx", "whisperx", "assemblyai"])
def test_public_entry_honors_preexisting_cancellation_without_any_engine(monkeypatch, engine):
    import gurunote.stt as stt
    from gurunote.diarization import DiarizationCancelled

    event = Event()
    event.set()
    monkeypatch.setattr(stt, "_transcribe_assemblyai", lambda *a, **kw: pytest.fail("cloud called"))
    with pytest.raises(DiarizationCancelled):
        stt.transcribe("unused.wav", engine=engine, stop_event=event, diarization_backend="resemblyzer")


@pytest.mark.parametrize("engine", ["assemblyai", "auto"])
def test_none_remains_single_speaker_if_cloud_engine_is_used(monkeypatch, engine):
    import gurunote.stt as stt

    source = [Segment("speaker1", 0, 2, "First."), Segment("speaker2", 2, 4, "Second.")]
    monkeypatch.setattr(stt, "_check_cuda_ready", lambda: False)
    monkeypatch.setattr(stt, "_is_mlx_ready", lambda: False)
    monkeypatch.setattr(stt, "_auto_fallback_hint", lambda: "")
    monkeypatch.setattr(stt, "_transcribe_assemblyai", lambda *a, **kw: Transcript(
        segments=source, engine="assemblyai", raw={"id": "test-only"}))
    result = stt.transcribe("unused.wav", engine=engine, diarization_backend="none")
    assert [s.speaker for s in result.segments] == ["A", "A"]
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (s.start, s.end, s.text) for s in source]
    assert result.raw["diarization"]["backend"] == "none"


def test_canonical_hf_token_preserves_authorized_pyannote_mode(monkeypatch):
    from gurunote.diarization import resolve_backend
    import gurunote.stt_mlx as mlx

    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("GURUNOTE_DIARIZATION_BACKEND", raising=False)
    monkeypatch.setenv("HF_TOKEN", "test-canonical-token")
    assert resolve_backend() == "pyannote"
    monkeypatch.setattr(mlx, "is_apple_silicon", lambda: True)
    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=lambda *a, **kw: {
        "segments": [{"start": 0, "end": 2, "text": "First."},
                     {"start": 2, "end": 4, "text": "Second."}]}))
    tokens = []

    def pyannote(path, token, log):
        tokens.append(token)
        return [(0, 2, "SPEAKER_02"), (2, 4, "SPEAKER_03")]

    monkeypatch.setattr(mlx, "_diarize_with_pyannote", pyannote)
    result = mlx.transcribe_mlx("unused.wav", lambda _: None, [])
    assert tokens == ["test-canonical-token"]
    assert [s.speaker for s in result.segments] == ["A", "B"]

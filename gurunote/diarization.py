"""Optional local ASR-segment speaker clustering, not an overlap-aware diarizer.

Resemblyzer's official Apache-2.0 package bundles its pretrained.pt checkpoint:
https://github.com/resemble-ai/Resemblyzer
Heavy dependencies are imported only on use. No HF download or token is needed
by this backend; the separate ASR engines retain their existing model sources.
"""
from __future__ import annotations

import math
import os
from dataclasses import replace
from typing import Callable, Sequence

from gurunote.types import Segment

# Uncalibrated clustering heuristic, not an accuracy/DER measurement.
DEFAULT_SIMILARITY_THRESHOLD = 0.75
# Upstream encoder partials are 1.6 seconds; shorter clips are not padded into
# apparent evidence. This conservative floor can leave short turns unassigned.
MIN_INTERVAL_SECONDS = 1.6

# 토큰 없는 Resemblyzer 군집은 과분할되기 쉬워, 두 조정 노브를 환경변수로 노출한다.
# (production 진입점 diarize_local_segments 에서만 읽어 전달 — diarize_segments 를
#  직접 호출하는 테스트/코드의 기본 동작은 그대로 유지한다.)
ENV_SIMILARITY = "GURUNOTE_DIARIZATION_SIMILARITY"      # float (0,1]; 낮출수록 병합↑(화자↓)
ENV_MAX_SPEAKERS = "GURUNOTE_DIARIZATION_MAX_SPEAKERS"  # int>=1; 군집 상한(초과 시 병합)


def _env_similarity() -> float:
    """`GURUNOTE_DIARIZATION_SIMILARITY` → (0,1] 범위 float. 미설정/무효 시 기본값."""
    raw = os.environ.get(ENV_SIMILARITY, "").strip()
    if not raw:
        return DEFAULT_SIMILARITY_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SIMILARITY_THRESHOLD
    return value if 0 < value <= 1 else DEFAULT_SIMILARITY_THRESHOLD


def _env_max_speakers() -> int | None:
    """`GURUNOTE_DIARIZATION_MAX_SPEAKERS` → int>=1. 미설정/무효 시 None(상한 없음)."""
    raw = os.environ.get(ENV_MAX_SPEAKERS, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 1 else None


class LocalDiarizationError(RuntimeError):
    """Local diarization failed; callers must not fall back to cloud STT."""


class DiarizationCancelled(LocalDiarizationError):
    """Cooperative cancellation (also prohibits cloud fallback)."""


def check_cancelled(stop_event=None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise DiarizationCancelled("Local transcription/diarization cancelled")


def huggingface_token() -> str:
    """Read only environment aliases; never inspect a login cache or auth file."""
    return (os.environ.get("HF_TOKEN", "").strip()
            or os.environ.get("HUGGINGFACE_TOKEN", "").strip())


def resolve_backend(backend: str | None = None) -> str:
    selected = (backend if backend is not None else
                os.environ.get("GURUNOTE_DIARIZATION_BACKEND", "auto")).strip().lower()
    if selected not in {"auto", "resemblyzer", "pyannote", "none"}:
        raise ValueError(f"Invalid diarization backend: {selected!r}")
    if selected == "auto":
        return "pyannote" if huggingface_token() else "resemblyzer"
    if selected == "pyannote" and not huggingface_token():
        raise LocalDiarizationError(
            "pyannote requires HF_TOKEN / HUGGINGFACE_TOKEN and authorized model access")
    return selected


def _speaker_label(index: int) -> str:
    label = ""
    while index >= 0:
        label = chr(ord("A") + index % 26) + label
        index = index // 26 - 1
    return label


def diarize_local_segments(audio_path, segments, *, backend, stop_event=None):
    check_cancelled(stop_event)
    if backend == "none":
        return ([replace(segment, speaker="A") for segment in segments],
                {"backend": "none", "status": "disabled", "approximate": False,
                 "overlap_supported": False, "speaker_count": int(bool(segments))})
    if backend != "resemblyzer":
        raise ValueError(f"Not a local segment diarization backend: {backend!r}")
    return diarize_segments(
        audio_path, segments, stop_event=stop_event,
        similarity_threshold=_env_similarity(),
        max_speakers=_env_max_speakers(),
    )


def _merge_clusters_to_max(centroids, sums, seg_cluster, max_speakers):
    """centroid 쌍 중 가장 유사한 것부터 병합(agglomerative)해 군집 수를 max_speakers
    이하로 줄인다. seg_cluster(세그먼트→centroid 인덱스)를 병합 결과로 재매핑해 반환.

    과분할(같은 화자가 여러 군집으로 쪼개짐)을 사후 보정하기 위한 것으로, 토큰 없는
    근사 분리의 한계를 완화할 뿐 정확도를 보장하지는 않는다.
    """
    root = list(range(len(centroids)))
    cur_sum = {i: list(sums[i]) for i in range(len(centroids))}
    cur_cen = {i: list(centroids[i]) for i in range(len(centroids))}
    active = set(range(len(centroids)))
    while len(active) > max_speakers:
        act = sorted(active)
        best_pair = None
        best_sim = -2.0
        for a in range(len(act)):
            for b in range(a + 1, len(act)):
                i, j = act[a], act[b]
                sim = sum(x * y for x, y in zip(cur_cen[i], cur_cen[j]))
                if sim > best_sim:
                    best_sim = sim
                    best_pair = (i, j)
        i, j = best_pair
        cur_sum[i] = [x + y for x, y in zip(cur_sum[i], cur_sum[j])]
        cur_cen[i] = _unit_vector(cur_sum[i])
        active.discard(j)
        for k in range(len(root)):
            if root[k] == j:
                root[k] = i
    return {index: root[cid] for index, cid in seg_cluster.items()}


def labels_by_first_appearance(segments: Sequence[Segment]) -> list[Segment]:
    names: dict[str, str] = {}
    for segment in sorted(segments, key=lambda item: item.start):
        if segment.speaker not in names:
            names[segment.speaker] = _speaker_label(len(names))
    return [replace(segment, speaker=names[segment.speaker]) for segment in segments]


def _unit_vector(values) -> list[float]:
    vector = [float(value) for value in values]
    norm = math.sqrt(sum(value * value for value in vector))
    if not vector or not math.isfinite(norm) or norm <= 0:
        raise LocalDiarizationError("Invalid or empty speaker embedding")
    return [value / norm for value in vector]


def _segment_embedding(waveform, start, end, *, preprocess, encode, sample_rate=16000,
                       stop_event=None):
    """Slice before VAD so trimming silence cannot shift the ASR time base."""
    check_cancelled(stop_event)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
        raise LocalDiarizationError("Invalid ASR interval timestamps")
    clip = waveform[int(start * sample_rate):int(end * sample_rate)]

    def usable(samples):
        if len(samples) < int(MIN_INTERVAL_SECONDS * sample_rate):
            return False
        energy = sum(float(value) ** 2 for value in samples) / len(samples)
        if not math.isfinite(energy):
            raise LocalDiarizationError("Non-finite audio samples")
        return energy > 1e-10  # Silence/zero guard, not a speech classifier.

    if not usable(clip):
        return None
    voiced = preprocess(clip)
    check_cancelled(stop_event)
    embedding = encode(voiced) if usable(voiced) else None
    check_cancelled(stop_event)
    return embedding


def _load_embedder(audio_path: str, stop_event=None):
    check_cancelled(stop_event)
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
        import librosa
    except Exception as exc:
        raise LocalDiarizationError(
            "Local diarization requires the optional requirements-diarization.txt dependencies"
        ) from exc
    try:
        # The official package includes pretrained.pt. No custom checkpoint,
        # HF client, credential lookup, or torch safety override is used here.
        encoder = VoiceEncoder(device="cpu", verbose=False)
        check_cancelled(stop_event)
        waveform, _ = librosa.load(audio_path, sr=16000, mono=True)
        check_cancelled(stop_event)
    except LocalDiarizationError:
        raise
    except Exception as exc:
        raise LocalDiarizationError("Could not initialize local Resemblyzer inference") from exc

    def embed_interval(start, end):
        return _segment_embedding(
            waveform, start, end,
            preprocess=lambda clip: preprocess_wav(clip, source_sr=16000),
            encode=encoder.embed_utterance,
            stop_event=stop_event,
        )

    return embed_interval


def diarize_segments(
    audio_path: str,
    segments: Sequence[Segment],
    stop_event=None,
    *,
    embed_interval: Callable[[float, float], Sequence[float] | None] | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_speakers: int | None = None,
) -> tuple[list[Segment], dict]:
    """Greedy cosine-centroid clustering of ASR intervals, in timestamp order.

    One embedding per ASR segment cannot resolve within-segment speaker changes
    or overlapping speech. Thresholds are heuristics requiring corpus validation.
    The embedding seam permits numerical tests without the optional model stack.
    """
    check_cancelled(stop_event)
    if not math.isfinite(similarity_threshold) or not 0 < similarity_threshold <= 1:
        raise LocalDiarizationError("Similarity threshold must be in (0, 1]")
    if len(segments) < 2:
        raise LocalDiarizationError("Local diarization requires at least two usable ASR intervals")
    if embed_interval is None:
        embed_interval = _load_embedder(audio_path, stop_event)
    centroids: list[list[float]] = []
    sums: list[list[float]] = []
    seg_cluster: dict[int, int] = {}
    for index in sorted(range(len(segments)), key=lambda i: (segments[i].start, i)):
        check_cancelled(stop_event)
        segment = segments[index]
        try:
            embedding = embed_interval(segment.start, segment.end)
            vector = _unit_vector(embedding) if embedding is not None else None
        except LocalDiarizationError:
            raise
        except Exception as exc:
            raise LocalDiarizationError(f"Local speaker embedding failed for interval {index}") from exc
        check_cancelled(stop_event)
        if vector is None:
            continue
        if centroids and len(vector) != len(centroids[0]):
            raise LocalDiarizationError("Inconsistent speaker embedding dimensions")
        similarities = [sum(a * b for a, b in zip(vector, centroid))
                        for centroid in centroids]
        best = max(range(len(similarities)), key=similarities.__getitem__) if similarities else None
        if best is None or similarities[best] < similarity_threshold:
            best = len(centroids)
            sums.append(vector[:])
            centroids.append(vector)
        else:
            sums[best] = [a + b for a, b in zip(sums[best], vector)]
            centroids[best] = _unit_vector(sums[best])
        seg_cluster[index] = best
    if len(seg_cluster) < 2:
        raise LocalDiarizationError(
            "Local diarization requires at least two usable voiced ASR intervals; "
            "audio may be silent or intervals too short"
        )
    check_cancelled(stop_event)
    # 선택: 화자 수 상한 — 가장 가까운 centroid 쌍부터 병합해 과분할을 사후 보정.
    clusters_before_merge = len(centroids)
    if max_speakers is not None and len(set(seg_cluster.values())) > max_speakers:
        seg_cluster = _merge_clusters_to_max(centroids, sums, seg_cluster, max_speakers)
    # 라벨: 첫 등장(시간) 순서로 A, B, C ... 를 부여.
    order: dict[int, str] = {}
    for index in sorted(seg_cluster, key=lambda i: (segments[i].start, i)):
        cid = seg_cluster[index]
        if cid not in order:
            order[cid] = _speaker_label(len(order))
    labels = {index: order[cid] for index, cid in seg_cluster.items()}
    unassigned = [index for index in range(len(segments)) if index not in labels]
    return ([replace(segment, speaker=labels.get(index, "UNKNOWN"))
             for index, segment in enumerate(segments)],
            {"backend": "resemblyzer", "approximate": True,
             "scope": "one speaker embedding per ASR segment",
             "overlap_supported": False, "speaker_count": len(order),
             "clustering": "greedy_cosine_centroid", "similarity_threshold": similarity_threshold,
             "max_speakers": max_speakers, "clusters_before_merge": clusters_before_merge,
             "usable_intervals": len(labels), "unassigned_intervals": unassigned,
             "minimum_voiced_seconds": MIN_INTERVAL_SECONDS,
             "status": "partial" if unassigned else "clustered"})

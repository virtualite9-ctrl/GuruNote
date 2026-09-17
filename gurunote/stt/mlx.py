"""
Apple Silicon (M1/M2/M3/M4/M5) GPU 로컬 STT 엔진.

`mlx-whisper` (Apple MLX 프레임워크) 로 Whisper 추론을 수행하고,
`pyannote.audio` 화자 분리 파이프라인을 MPS(Metal Performance Shaders)
디바이스에서 실행해 화자 라벨을 부여한다.

WhisperX(CUDA) 와 동일한 `gurunote.types.Transcript` 형태로 결과를 반환하므로
LLM/요약 단계는 어떤 엔진이 사용됐는지 신경 쓰지 않아도 된다.

기본 모델:
    - Whisper:    `mlx-community/whisper-large-v3-mlx`
                  (`MLX_WHISPER_MODEL` 환경변수로 오버라이드)
    - Diarization: `pyannote/speaker-diarization-3.1`
                  (HUGGINGFACE_TOKEN 필요, 모델 사용 동의 필요)
"""

from __future__ import annotations

import os
import platform
import warnings
from typing import Callable, Dict, List, Optional, Tuple

from gurunote.types import Segment, Transcript

ProgressFn = Callable[[str], None]

DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-mlx"
# 5/23 — community-1 default (speaker confusion marked reduction over 3.1, pyannote 4.0+).
# Rollback path: PYANNOTE_DIARIZATION_MODEL=pyannote/speaker-diarization-3.1 (line 315 catch).
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

# 5/24 — STT 의미 단위 재분할 (word-level 방법 4) 토글.
# Whisper segment 경계는 음성 신호 기반이라 의미 단위 부재 (예: "secure and" 같은
# 미완 끝). 재분할 on 시 word-level 구두점 + 끝 검사로 의미 완결 단위로 병합.
# 6개 영상 검증: D leak 해소, 2-pass SHIFT/합침 50%↓, 정합 30→57~69%, 화자 보존.
# 기본 off — daily 1-pass 동작 보존. on 시 llm.py 가 chunk size 자동 축소 (cs=12,
# char_limit=2000) 로 1-pass timeout 회피.
SEGMENT_RESPLIT_ENV = "GURUNOTE_SEGMENT_RESPLIT"

# 끝 검사 사전 — 미완 끝 catch (재분할 시 다음 segment 와 병합).
_SEGMENT_END_COMPLETE = {".", "?", "!"}
_SEGMENT_END_MID_PUNCT = {",", ":", ";", "-", "—"}
_SEGMENT_END_CONJUNCTIONS = {
    "and", "or", "but", "nor", "so", "yet", "for",
    "because", "while", "when", "if", "though", "although",
    "as", "than", "that",
}
_SEGMENT_END_PREPOSITIONS = {
    "to", "of", "in", "on", "at", "by", "from", "with", "for",
    "about", "into", "during", "over", "under", "between",
    "through", "across", "against", "before", "after", "around",
    "as", "without", "within", "upon",
}
_SEGMENT_END_DANGLING = {
    "the", "a", "an",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "do", "does", "did", "done",
    "my", "your", "his", "her", "its", "our", "their",
    "this", "that", "these", "those",
    "more", "less", "most", "least", "very", "really", "quite",
}


# =============================================================================
# 환경 검사 헬퍼
# =============================================================================
def is_apple_silicon() -> bool:
    """macOS arm64 (M1/M2/M3/M4/M5) 여부."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def is_mlx_whisper_available() -> bool:
    try:
        import mlx_whisper  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def is_mlx_ready() -> bool:
    """현재 환경에서 MLX 엔진이 실제로 동작 가능한지 (플랫폼 + 패키지)."""
    return is_apple_silicon() and is_mlx_whisper_available()


def _check_mps_ready() -> bool:
    """torch.backends.mps 사용 가능 여부 (pyannote diarization 가속용)."""
    try:
        import torch
        return bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception:  # noqa: BLE001
        return False


# =============================================================================
# 화자 라벨 정규화 + 할당
# =============================================================================
def _normalize_speaker_label(raw: str) -> str:
    """SPEAKER_00 → A, SPEAKER_01 → B …"""
    if raw and raw.startswith("SPEAKER_"):
        try:
            idx = int(raw.split("_")[-1])
            return chr(ord("A") + idx)
        except (ValueError, IndexError):
            return raw
    return raw or "A"


def _segment_last_token(text: str) -> str:
    """text 마지막 token (트레일링 구두점 strip)."""
    t = text.strip().lower()
    while t and t[-1] in ".,?!;:\"')]":
        t = t[:-1]
    if not t:
        return ""
    parts = t.split()
    return parts[-1] if parts else ""


def _segment_is_complete(text: str) -> bool:
    """segment text 가 의미 완결인지 catch (재분할 끝 검사)."""
    t = text.strip()
    if not t:
        return True
    last_char = t[-1]
    if last_char in _SEGMENT_END_COMPLETE:
        return True
    if last_char in _SEGMENT_END_MID_PUNCT:
        return False
    last_word = _segment_last_token(t)
    if last_word in _SEGMENT_END_CONJUNCTIONS:
        return False
    if last_word in _SEGMENT_END_PREPOSITIONS:
        return False
    if last_word in _SEGMENT_END_DANGLING:
        return False
    # 구두점 부재 = 미완 보수적 (mlx-whisper 는 자연 종결 시 . 부착).
    if last_char not in ".,?!;:":
        return False
    return True


def _resplit_segments_by_semantics(
    raw_segments: List[Dict],
    turns: List[Tuple[float, float, str]],
) -> List[Dict]:
    """Whisper raw segments 를 의미 단위로 재분할 (word-level 방법 4).

    Whisper segment 경계는 음성 신호 기반이라 의미 단위 부재 (예: "secure and"
    같은 미완 끝). 본 함수는 끝 검사 (구두점 + conjunction/preposition/dangling)
    로 미완 segment 검출 후 다음 segment 와 병합. 화자 다르면 병합 부재 (화자
    우선), 시간 갭 5초 초과 부재, 합친 길이 30초 초과 부재.

    Args:
        raw_segments: Whisper raw segments (dict, words 키 포함 가능).
        turns: diarization (start, end, speaker) — 화자 다른 segment 병합 부재용.

    Returns:
        병합된 raw segments (dict, 같은 형태). 후속 noise/dedup loop 그대로 적용 가능.
    """
    if not raw_segments:
        return raw_segments

    # 1차 화자 부착 (segment 단위) — 화자 우선 병합 catch 위함.
    enriched = []
    for s in raw_segments:
        start = float(s.get("start", 0.0))
        end = float(s.get("end", 0.0))
        speaker = _assign_speaker_by_overlap(start, end, turns) if turns else "A"
        enriched.append({**s, "_resplit_speaker": speaker})

    # 2차 greedy 정방향 병합.
    out: List[Dict] = []
    i = 0
    while i < len(enriched):
        cur = dict(enriched[i])
        j = i + 1
        while j < len(enriched):
            cur_text = (cur.get("text") or "").strip()
            if _segment_is_complete(cur_text):
                break
            nxt = enriched[j]
            # 화자 우선 — 다르면 병합 부재.
            if nxt["_resplit_speaker"] != cur["_resplit_speaker"]:
                break
            # 시간 갭 5초 초과 — 의도적 멈춤 catch.
            gap = float(nxt.get("start", 0.0)) - float(cur.get("end", 0.0))
            if gap > 5.0:
                break
            # 합친 길이 30초 초과 부재 — 안전 상한.
            if (float(nxt.get("end", 0.0)) - float(cur.get("start", 0.0))) > 30.0:
                break
            # 병합.
            cur_text_new = ((cur.get("text") or "").rstrip()
                              + " " + (nxt.get("text") or "").lstrip()).strip()
            cur["text"] = cur_text_new
            cur["end"] = nxt.get("end", cur.get("end"))
            cur_words = cur.get("words") or []
            nxt_words = nxt.get("words") or []
            if cur_words or nxt_words:
                cur["words"] = list(cur_words) + list(nxt_words)
            j += 1
        cur.pop("_resplit_speaker", None)
        out.append(cur)
        i = j if j > i else i + 1

    return out


def _assign_speaker_by_overlap(
    seg_start: float,
    seg_end: float,
    turns: List[Tuple[float, float, str]],
) -> str:
    """
    Whisper 세그먼트(seg_start, seg_end) 와 가장 많이 겹치는 diarization 화자를 반환.

    Args:
        turns: [(turn_start, turn_end, speaker_label)] — pyannote 결과
    """
    if not turns:
        return "A"

    overlap_by_speaker: Dict[str, float] = {}
    for t_start, t_end, t_speaker in turns:
        overlap = min(seg_end, t_end) - max(seg_start, t_start)
        if overlap > 0:
            overlap_by_speaker[t_speaker] = overlap_by_speaker.get(t_speaker, 0.0) + overlap

    if not overlap_by_speaker:
        return "A"

    best = max(overlap_by_speaker.items(), key=lambda kv: kv[1])[0]
    return _normalize_speaker_label(best)


# =============================================================================
# 메인 엔트리
# =============================================================================
def transcribe_mlx(
    audio_path: str,
    log: ProgressFn,
    hotwords: List[str],
) -> Transcript:
    """
    Apple Silicon GPU 로컬 STT 실행.

    Returns:
        Transcript (engine="mlx")
    """
    if not is_apple_silicon():
        raise RuntimeError(
            "MLX 엔진은 macOS Apple Silicon (M1/M2/M3/M4/M5) 에서만 동작합니다."
        )
    if not is_mlx_whisper_available():
        raise RuntimeError(
            "mlx-whisper 가 설치되지 않았습니다.\n"
            "  pip install -r requirements-mac.txt\n"
            "  (또는: pip install mlx-whisper pyannote.audio onnxruntime)"
        )

    # pyannote / huggingface 의 무해한 경고 억제 (WhisperX 와 동일 패턴)
    warnings.filterwarnings("ignore", message=".*symlink.*")
    warnings.filterwarnings("ignore", message=".*hf_xet.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
    warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")

    import mlx_whisper  # type: ignore

    model_repo = os.environ.get("MLX_WHISPER_MODEL", DEFAULT_MLX_MODEL)
    initial_prompt = ", ".join(hotwords[:30]) if hotwords else None

    # 1. Whisper 전사 (MLX = Apple GPU/Neural Engine native)
    log(f"MLX Whisper 모델 로딩 ({model_repo})...")
    log("전사 중 (Apple GPU 가속, 단어 레벨 타임스탬프)...")
    transcribe_kwargs: dict = {
        "path_or_hf_repo": model_repo,
        "word_timestamps": True,
        "verbose": False,
    }
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt

    result = mlx_whisper.transcribe(audio_path, **transcribe_kwargs)
    raw_segments = result.get("segments", []) or []
    language = result.get("language", "en")
    log(f"전사 완료 — {len(raw_segments)} 세그먼트, 언어={language}")

    # 2. 화자 분리 (선택: HF 토큰 + 모델 동의 필요)
    diarization_turns: List[Tuple[float, float, str]] = []
    hf_token = os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if hf_token:
        try:
            diarization_turns = _diarize_with_pyannote(audio_path, hf_token, log)
        except Exception as exc:  # noqa: BLE001
            err_msg = str(exc)
            if "401" in err_msg or "gated" in err_msg.lower() or "restricted" in err_msg.lower():
                log(
                    "화자 분리 실패: pyannote 모델 접근 권한이 없습니다.\n"
                    "  아래 페이지에서 'Agree and access repository' 를 클릭하세요:\n"
                    "  https://huggingface.co/pyannote/speaker-diarization-3.1\n"
                    "  화자 분리 없이 단일 화자(A) 로 진행합니다."
                )
            elif "AudioMetaData" in err_msg:
                # torchaudio 2.8+ 에서 `AudioMetaData` 가 제거되어 pyannote.audio 3.x
                # 와 호환 불가. 4.0+ 는 torchcodec 로 마이그레이션해 해결.
                log(
                    "화자 분리 실패: pyannote.audio 3.x 와 최신 torchaudio 가\n"
                    "  호환되지 않습니다 ('AudioMetaData' 제거됨).\n"
                    "  pyannote.audio 4.0+ 로 업그레이드하세요:\n"
                    "    .venv/bin/pip install --upgrade 'pyannote.audio>=4.0'\n"
                    "  단일 화자(A) 로 진행합니다."
                )
            else:
                log(f"화자 분리 실패: {exc}\n  단일 화자(A) 로 진행합니다.")
    else:
        log(
            "HUGGINGFACE_TOKEN 미설정 — 화자 분리를 건너뜁니다.\n"
            "  화자 분리를 원하면 Settings 에서 HUGGINGFACE_TOKEN 을 설정하고,\n"
            "  https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "  에서 모델 사용에 동의하세요."
        )

    # 5/24 — 의미 단위 재분할 (GURUNOTE_SEGMENT_RESPLIT 토글, 기본 on).
    # Whisper segment 경계는 음성 신호 기반이라 의미 단위 부재. 재분할 on 시
    # word-level 끝 검사로 미완 segment 를 다음과 병합 → D leak 해소, 2-pass
    # SHIFT/합침 감소, 정합 향상. off 강제: GURUNOTE_SEGMENT_RESPLIT=0.
    resplit_on = os.environ.get(SEGMENT_RESPLIT_ENV, "1").strip() == "1"
    raw_segments_for_norm = raw_segments
    if resplit_on:
        before_count = len(raw_segments)
        raw_segments_for_norm = _resplit_segments_by_semantics(raw_segments, diarization_turns)
        log(
            f"세그먼트 재분할 (GURUNOTE_SEGMENT_RESPLIT=1) — "
            f"{before_count} → {len(raw_segments_for_norm)} segments (의미 단위 병합)"
        )

    # 3. Segment 정규화 (화자 할당)
    # Layer 6 fix: Whisper hallucination 영역 (빈 text + noise placeholder + 중복) 필터링.
    # 본인 daily 사용 catch (5/9): NVIDIA GTC 영상의 같은 timestamp + 같은 화자의 빈
    # segment 904회 반복 → markdown 본문 904 줄 leak. STT 단계에서 사전 차단해야
    # downstream (LLM translate / exporter markdown / 화자 분리) 모두 자동 graceful.
    _NOISE_PLACEHOLDERS = {"", ".", "-", "—", "...", "…"}
    segments: List[Segment] = []
    _seen_keys: set = set()
    _filtered_empty = 0
    _filtered_duplicate = 0
    for seg in raw_segments_for_norm:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        text = (seg.get("text") or "").strip()

        if text in _NOISE_PLACEHOLDERS:
            _filtered_empty += 1
            continue

        if diarization_turns:
            speaker = _assign_speaker_by_overlap(start, end, diarization_turns)
        else:
            speaker = "A"

        # 동일 (start, speaker, text) 중복 차단 — Whisper hallucination loop 방어.
        dedup_key = (round(start, 2), speaker, text)
        if dedup_key in _seen_keys:
            _filtered_duplicate += 1
            continue
        _seen_keys.add(dedup_key)

        segments.append(Segment(speaker=speaker, start=start, end=end, text=text))

    if _filtered_empty or _filtered_duplicate:
        log(
            f"세그먼트 필터링 — empty/noise {_filtered_empty}, duplicate {_filtered_duplicate} "
            f"제거 ({len(raw_segments)} → {len(segments)})"
        )

    speaker_count = len({s.speaker for s in segments})
    log(f"MLX 전사 완료 — {len(segments)} 세그먼트, {speaker_count} 화자")

    return Transcript(
        segments=segments,
        engine="mlx",
        language=language,
        raw={"language": language, "model": model_repo,
              "segment_resplit": resplit_on},
    )


# =============================================================================
# pyannote diarization (MPS 가속)
# =============================================================================
def _merge_drifted_speakers(result: object, similarity_threshold: float, log: ProgressFn) -> object:
    """Long-form embedding drift 의 cluster 자동 합산 (Layer 1 fix).

    pyannote.audio 4.0+ 의 DiarizeOutput.speaker_embeddings (shape (N, D), labels()
    순서 정합) 를 활용 — 같은 화자가 chunk 마다 다른 cluster 인 경우 (긴 영상의
    embedding drift) cosine similarity ≥ threshold 시 라벨 합산.

    embeddings 부재 (3.x Annotation 직접 반환 / None) 또는 shape mismatch 시
    graceful skip (원본 result 그대로 반환).

    Greedy 합산: 정렬된 라벨 i < j 에 대해 sim[i][j] ≥ threshold 이면 j → i 매핑.
    이미 다른 라벨로 매핑된 라벨은 새 매핑 차단 (chain merge 회피).
    """
    embeddings = getattr(result, "speaker_embeddings", None)
    annotation = getattr(result, "speaker_diarization", None)
    if embeddings is None or annotation is None:
        return result
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return result
    labels = list(annotation.labels())
    n = len(labels)
    if n != len(embeddings) or n < 2:
        return result

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normed = embeddings / norms
    sim = normed @ normed.T

    merge_map: Dict[str, str] = {}
    for i in range(n):
        if labels[i] in merge_map:
            continue
        for j in range(i + 1, n):
            if labels[j] in merge_map:
                continue
            if float(sim[i][j]) >= similarity_threshold:
                merge_map[labels[j]] = labels[i]

    if not merge_map:
        return result

    log(
        f"화자 합산 — {len(merge_map)} cluster 합산 "
        f"({n} → {n - len(merge_map)} speakers, threshold {similarity_threshold:.2f})"
    )
    if hasattr(result, "speaker_diarization"):
        result.speaker_diarization = result.speaker_diarization.rename_labels(merge_map)
    if hasattr(result, "exclusive_speaker_diarization"):
        result.exclusive_speaker_diarization = (
            result.exclusive_speaker_diarization.rename_labels(merge_map)
        )
    return result


def _diarize_with_pyannote(
    audio_path: str,
    hf_token: str,
    log: ProgressFn,
) -> List[Tuple[float, float, str]]:
    """
    pyannote.audio 화자 분리 → [(start, end, speaker_label)] 리스트.
    MPS 디바이스에서 실행 (가능한 경우), 일부 op 는 자동 CPU 폴백.
    """
    log("화자 분리 중 (pyannote, MPS 가속)...")

    from pyannote.audio import Pipeline  # type: ignore
    import torch

    diar_model = os.environ.get("PYANNOTE_DIARIZATION_MODEL", DEFAULT_DIARIZATION_MODEL)

    # pyannote.audio 3.x 는 token=, 그 이전(또는 4.x) 은 use_auth_token= 를 받을 수 있어
    # WhisperX 분기(stt.py)와 동일한 try/except TypeError 폴백을 사용한다.
    try:
        pipeline = Pipeline.from_pretrained(diar_model, token=hf_token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(diar_model, use_auth_token=hf_token)

    if pipeline is None:
        raise RuntimeError(
            f"pyannote 파이프라인 로드 실패 ({diar_model}). "
            "HuggingFace 토큰과 모델 사용 동의를 확인하세요."
        )

    if _check_mps_ready():
        try:
            pipeline.to(torch.device("mps"))
        except Exception as exc:  # noqa: BLE001
            log(f"  MPS 디바이스 이동 실패 ({exc}) — CPU 로 진행")

    # Layer 1 fix: pyannote 의 max_speakers cap (long-form 의 over-segmentation 방어).
    # 단일 화자 컨텐츠 영향 부재 (cap 은 상한, num_speakers=1 정합).
    # default 10 — daily 사용 max 안전 영역. envvar 으로 컨텐츠 별 조절 가능.
    max_speakers_env = int(os.getenv("PYANNOTE_MAX_SPEAKERS", "10"))
    result = pipeline(audio_path, max_speakers=max_speakers_env)

    # Layer 1 fix: long-form embedding drift 의 cluster 자동 합산.
    # 100분 영상에서 같은 화자가 chunk 마다 다른 cluster 가 되는 영역 → cosine
    # similarity ≥ threshold (default 0.75) 시 합산. embeddings 부재 시 graceful skip.
    merge_threshold = float(os.getenv("PYANNOTE_MERGE_THRESHOLD", "0.75"))
    result = _merge_drifted_speakers(result, merge_threshold, log)

    # pyannote.audio 4.0+ 는 pipeline() 결과가 DiarizeOutput dataclass
    # (speaker_diarization / exclusive_speaker_diarization / speaker_embeddings).
    # 3.x 는 Annotation 직접 반환. defensive getattr 으로 두 API 모두 graceful.
    #
    # exclusive_speaker_diarization 이 pyannote 의 명시적 권장:
    # overlapping speech turns 제거 → Whisper STT segment 1:1 매칭 본질 정합.
    # 부재 시 speaker_diarization (overlapping 포함) → 마지막에 result 자체 (3.x).
    annotation = (
        getattr(result, "exclusive_speaker_diarization", None)
        or getattr(result, "speaker_diarization", None)
        or result
    )

    turns: List[Tuple[float, float, str]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append((float(turn.start), float(turn.end), str(speaker)))

    log(f"화자 분리 완료 — {len(turns)} 발화 구간")
    return turns

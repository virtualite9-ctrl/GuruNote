"""고유명사 표기의 일관성 — entity/speaker 캐시, 통용 표기 dict, 검색 그라운딩.

같은 인물·회사가 영상마다 다르게 음차되는 것을 막는 층이다. 디스크 캐시
(`CACHE_DIR`) 와 통용 표기 파일을 읽고 쓴다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from gurunote.llm._data import DATA_DIR
from typing import Callable
from typing import List
from typing import Optional
import hashlib
import json
import os
import re

from gurunote.llm import client

__all__ = [
    '_detect_unexpected_changes',
    '_canonicalize_entity_names',
    '_SPEAKER_LINE_RE',
    '_ENGLISH_NAME_RE',
    '_extract_entities',
    '_build_entity_cache_block',
    '_bootstrap_entity_cache_from_metadata',
    'CACHE_DIR',
    'LOANWORD_SPEC_VERSION',
    'CACHE_SCHEMA_VERSION',
    '_LOANWORD_FILE',
    '_CANONICALIZE_MAX_BODY_CHARS',
    '_compute_cache_key_from_title',
    '_load_loanword_short_version',
    '_load_loanword_full_body',
    '_LOANWORD_SHORT',
    '_get_cache_file_path',
    '_save_entity_cache',
    '_load_entity_cache',
    '_load_entity_cache_full',
    'load_speaker_names',
    '_verify_entities_with_search',
    'load_stt_corrections',
    '_CANONICAL_NAMES_PATH',
    '_CANONICAL_NAMES_DEFAULT',
    '_load_canonical_names',
    '_save_canonical_names',
    '_canonical_effective',
    '_record_auto_spellings',
    '_persist_auto_spellings',
    '_apply_canonical_to_entity_cache',
    '_apply_canonical_to_speaker_cache',
    'refresh_canonical_in_markdown',
]


def _detect_unexpected_changes(
    original: str,
    canonical: str,
    entity_cache: dict,
) -> List[str]:
    """canonicalize 전후 비교 — entity 표기 외 변경 감지.

    줄 단위 비교로, entity_cache 의 한국어 표기 등장이 부재한 줄 변경을 의심으로 기록.
    완벽한 검증 부재 — daily 사용 빈도 데이터 수집 목적 (P-다 path).

    Args:
        original: canonicalize 전 본문.
        canonical: LLM canonicalize 결과 본문.
        entity_cache: B06 신 형식 `{english: {korean, type, source}}` dict.

    Returns:
        의심 변경 줄의 요약 list (로그 용). 변경 부재 시 빈 list.
        줄 수 불일치 시 첫 entry 가 줄 수 불일치 알림.
    """
    orig_lines = original.split("\n")
    canon_lines = canonical.split("\n")

    if len(orig_lines) != len(canon_lines):
        return [f"줄 수 불일치: {len(orig_lines)} → {len(canon_lines)}"]

    cache_koreans = {
        meta.get("korean", "")
        for meta in entity_cache.values()
        if isinstance(meta, dict) and meta.get("korean")
    }

    suspect: List[str] = []
    for i, (o, c) in enumerate(zip(orig_lines, canon_lines)):
        if o == c:
            continue
        # entity_cache 의 표기 중 하나가 canonical 줄에 새로 등장하면 정상 변경 추정.
        is_entity_change = any(k in c and k not in o for k in cache_koreans)
        if not is_entity_change:
            o_short = o[:40] + ("…" if len(o) > 40 else "")
            c_short = c[:40] + ("…" if len(c) > 40 else "")
            suspect.append(f"  L{i}: {o_short!r} → {c_short!r}")

    return suspect


def _canonicalize_entity_names(
    result: str,
    entity_cache: dict,
    config: "LLMConfig",
    log: Optional[client.ProgressFn] = None,
) -> str:
    """B06 §4.3 — 영상 전체 결과의 entity 표기 통일.

    entity_cache 의 canonical 표기 + 외래어 표기법 short version 을 LLM 참조로 주입.
    chunk drift (예: chunk 1 의 '판카즈' vs chunk 2+ 의 '판카지') 통일.

    우선순위 (§3.4):
        1. TRANSLATION_SYSTEM_PROMPT Rule 10 통용 표기 dict
        2. entity_cache 의 canonical 표기 (영상 단위 정답)
        3. 외래어 표기법 short version
        4. LLM 자유 출력

    Args:
        result: post_process_cjk 결과 본문.
        entity_cache: B06 신 형식 `{english: {korean, type, source}}` dict.
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        canonicalize 결과. cache 부재, body 크기 한계 초과, LLM 실패, 본문 길이 변동 큼
        catch 시 원본 그대로 (safe fallback).
    """
    log_fn = log or (lambda _msg: None)
    if not entity_cache:
        return result
    if len(result) > _CANONICALIZE_MAX_BODY_CHARS:
        log_fn(
            f"   ⚠ canonicalize skip — body {len(result)} chars 초과 한계 "
            f"{_CANONICALIZE_MAX_BODY_CHARS}"
        )
        return result

    cache_block = _build_entity_cache_block(entity_cache)
    if not cache_block:
        return result

    loanword_block = _LOANWORD_SHORT
    loanword_section = (
        f"\n\n[외래어 표기법 참조 — 표 1 영어 자모 + 제4장 인명·지명]\n{loanword_block}\n"
        if loanword_block
        else ""
    )

    system = (
        "다음 한국어 번역 본문에서 인명·회사명·지명 등 고유 명사의 표기를 통일하라.\n\n"
        "통일 규칙 (우선순위 위에서 아래로):\n"
        "1. 한국에서 이미 통용되는 표기 (예: Schneider Electric → 슈나이더 일렉트릭)\n"
        "2. 아래 entity 표기 일관 dict 의 한국어 표기 (영상 단위 정답)\n"
        "3. 통용 표기·entity dict 부재 시 외래어 표기법 표준 적용\n\n"
        "[형식 보존 — 변경 금지]\n"
        "- 줄 수 보존, timestamp `[MM:SS]` 보존, 화자 라벨 보존, 본문 의미 보존.\n"
        "- 변경 대상은 고유 명사 표기만 — 본문 단어, 어미, 조사 변경 부재.\n"
        "- **인명·회사명·지명 표기 외의 모든 글자는 원본 그대로 글자 단위 복사하라.**\n"
        "- 일반 단어 (예: '소프트웨어', '데이터', '인프라', '클라우드') 의 철자를 절대 바꾸지 말라.\n"
        "- 아래 entity dict 에 부재한 표기는 원본 그대로 유지하라.\n"
        "- 출력 형식 = 변경된 본문 그대로 (설명·헤더 부재).\n\n"
        f"{cache_block}{loanword_section}"
    )

    try:
        canonical = client._call_llm(config, system, result, max_tokens=config.translation_max_tokens or client.TRANSLATION_MAX_TOKENS)
    except Exception as exc:
        log_fn(f"   ⚠ canonicalize LLM 실패 (원본 유지): {exc}")
        return result

    if not canonical or not canonical.strip():
        log_fn("   ⚠ canonicalize 빈 응답 (원본 유지)")
        return result

    # 본문 길이 변동 큼 catch — LLM 이 본문 truncate 또는 expand 한 경우 차단.
    # ±10% 영역 정합 (translation 결과 ±수십 글자 변동은 표기 변경에 정합).
    orig_lines = result.count("\n")
    new_lines = canonical.count("\n")
    if orig_lines > 0 and abs(new_lines - orig_lines) / max(orig_lines, 1) > 0.10:
        log_fn(
            f"   ⚠ canonicalize 줄 수 변동 큼 (원본 {orig_lines} → {new_lines}, 원본 유지)"
        )
        return result

    # P-다 — entity 외 본문 변경 감지 로그 (canonical 그대로 반환, daily 빈도 수집).
    suspects = _detect_unexpected_changes(result, canonical, entity_cache)
    if suspects:
        log_fn(
            f"   ⚠ canonicalize entity 외 변경 의심 {len(suspects)}건 (canonical 채택, 로그만):"
        )
        for s in suspects[:5]:
            log_fn(s)
        if len(suspects) > 5:
            log_fn(f"   ⚠ … 외 {len(suspects) - 5}건")

    log_fn(
        f"   🔧 entity canonicalize 적용 ({len(entity_cache)}건 cache, "
        f"줄 수 {orig_lines} → {new_lines})"
    )
    return canonical.strip()


_SPEAKER_LINE_RE = re.compile(
    r"^\[(\d{1,2}:\d{2})\]\s+([^:(]+?)\s*(?:\(([^)]+)\))?\s*:",
    re.MULTILINE,
)


_ENGLISH_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\s\.\-']*$")


def _extract_entities(translated_chunk: str) -> dict:
    """chunk 출력의 speaker line prefix 에서 entity 추출.

    Phase 1 redesign 출력 형식 정합:
        첫 등장: "[MM:SS] 한국어 화자명(English Name): 본문"
        이후:    "[MM:SS] 한국어 화자명: 본문"

    Line prefix 한정 매칭으로 본문 중간의 기술 용어 (예: "AI 네이티브(AI Native)") 부재.

    B06 신 형식 (Phase 2B-3 migration, 5/20):
        반환 dict 의 값은 `{korean, type, source}` 신 자료구조.
        chunk 추출은 speaker line prefix 에서 catch 한 entity 이므로 type 기본 "speaker",
        source 자동 "chunk_extract".

    Returns:
        `{English Name: {"korean": str, "type": "speaker", "source": "chunk_extract"}}` dict.
        영문 병기 부재 line 은 skip.
    """
    entities: dict = {}
    for m in _SPEAKER_LINE_RE.finditer(translated_chunk):
        korean = m.group(2).strip()
        english_raw = m.group(3)
        if not english_raw:
            continue
        english = english_raw.strip()
        if _ENGLISH_NAME_RE.match(english):
            entities[english] = {
                "korean": korean,
                "type": "speaker",
                "source": "chunk_extract",
            }
    return entities


def _build_entity_cache_block(entity_cache: dict) -> str:
    """entity_cache 를 LLM context 영역의 markdown block 으로 변환.

    Args:
        entity_cache: B06 신 형식 `{English Name: {korean, type, source}}` dict.

    Returns:
        빈 dict 시 "".
        그 외: "### 영상 entity 표기 일관\n- English Name → 한국어 표기\n..."
    """
    if not entity_cache:
        return ""
    lines = ["### 영상 entity 표기 일관"]
    for english, meta in entity_cache.items():
        korean = meta.get("korean", "") if isinstance(meta, dict) else ""
        if not korean:
            continue
        lines.append(f"- {english} → {korean}")
    return "\n".join(lines)


def _bootstrap_entity_cache_from_metadata(
    video_context: Optional[dict],
    subtitles_text: Optional[str],
    config: "LLMConfig",
) -> dict:
    """영상 메타 + 자막에서 사전 entity 추출 ((b) Two-Stage 부분 적용).

    B06 통합 (5/20):
        - cache 조회 (`_load_entity_cache`) 우선 — cache hit 시 LLM 호출 부재.
        - cache miss 시 LLM 호출 prompt 에 외래어 표기법 short version + 4단계 우선순위 명시.
        - LLM 출력 형식: `English Name → 한국어 표기 [type]` (type ∈ {person, company, place, product}).

    Args:
        video_context: AudioDownloadResult.to_context_dict() 형태. None 가능. video_id 키
            부재 path — fallback 으로 video_title hash 사용 (`_compute_cache_key_from_title`).
        subtitles_text: 영문 자막 본문 (부재 시 None). 길이 큰 자막은 첫 3000자만 사용.
        config: LLM 호출용.

    Returns:
        B06 신 형식 `{English Name: {korean, type, source}}` dict. 추출 실패 시 빈 dict.
    """
    video_title = (video_context or {}).get("title", "") if video_context else ""
    cache_key = (
        (video_context or {}).get("id")
        or (video_context or {}).get("video_id")
        or _compute_cache_key_from_title(video_title)
    )

    if cache_key:
        # 5/23 — cache hit 시 speakers 도 함께 로드 (schema v2). 옛 cache (v1) 자동 invalidate.
        cached_full = _load_entity_cache_full(cache_key)
        if cached_full is not None:
            entities_cached = cached_full["entities"]
            speakers_cached = cached_full["speakers"]
            if speakers_cached:
                entities_cached["__speakers__"] = speakers_cached
            return entities_cached

    parts: List[str] = []
    if video_context:
        description = video_context.get("description", "")
        uploader = video_context.get("uploader", "")
        if video_title:
            parts.append(f"Title: {video_title}")
        if uploader:
            parts.append(f"Uploader: {uploader}")
        if description:
            parts.append(f"Description: {description}")
    if subtitles_text:
        parts.append(f"Subtitles (excerpt):\n{subtitles_text[:3000]}")

    if not parts:
        return {}

    text = "\n\n".join(parts)
    # B06 §3.3 R4 — 외래어 표기법 short version inline + §3.4 4단계 우선순위 명시.
    loanword_block = _LOANWORD_SHORT
    loanword_section = (
        f"\n\n[외래어 표기법 참조 자료 — 표 1 영어 자모 + 제4장 인명·지명 표기 원칙]\n{loanword_block}\n"
        if loanword_block
        else ""
    )
    # 5/23 — speakers 식별 추가 (영상당 1회 LLM). entity 와 같은 호출에서 catch.
    system = (
        "다음 영문 영상 메타 + 자막에서 다음 두 가지를 추출하라:\n\n"
        "**Part 1: 고유 명사 (인명, 회사명, 제품명, 지명) entity 추출**\n"
        "각 항목을 'English Name → 한국어 표기 [type]' 형식으로 한 줄에 하나씩 출력하라. "
        "type ∈ {person, company, place, product}.\n\n"
        "**Part 2: 화자 식별 (영상 등장 화자)**\n"
        "STT 가 화자를 'A', 'B', 'C' 등 단일 영문 라벨로 catch. 영상 메타·자막에서 "
        "각 라벨의 실명을 추론하여 다음 형식으로 출력:\n"
        "'SPEAKER A => English Name | 한국어 표기'\n"
        "예: SPEAKER A => Pankaj Sharma | 판카즈 샤르마\n"
        "추론 불가 라벨 부재 시 해당 라벨 생략 (fallback 은 코드가 catch).\n\n"
        "**한국어 표기 우선순위 (Part 1, 2 공통, 위에서 아래로)**:\n"
        "1. 한국에서 이미 통용되는 표기를 최우선. **철자가 아니라 발음**을 기준으로 음차하라\n"
        "   (예: Schneider Electric → 슈나이더 일렉트릭 [company], "
        "Palmer Luckey → 팔머 럭키 [person] (러커이 ✗), Rick Rieder → 릭 리더 [person] (리크 ✗)).\n"
        "2. 통용 표기 부재 시 아래 외래어 표기법 표준 적용 (예: Pankaj Sharma → 판카즈 샤르마 [person])\n"
        "3. 그 외는 영어 자모 한글 대조표 정합 자유 출력"
        f"{loanword_section}\n"
        "**출력 형식**: 설명·헤더·메타 텍스트 부재. 매핑만 출력.\n"
        "Part 1 (entity) 와 Part 2 (speaker) 줄 형식이 다르니 구분되어 catch 가능.\n"
        "추출할 entity 또는 speaker 부재 시 해당 부분 생략."
    )

    try:
        result = client._call_llm(config, system, text, max_tokens=2048)
    except Exception:
        return {}

    if not result:
        return {}

    entities: dict = {}
    speakers: dict = {}
    speaker_re = re.compile(r"^\s*SPEAKER\s+([A-Z])\s*=>\s*(.+?)\s*\|\s*(.+?)\s*$")
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        # speaker 패턴 우선 catch (SPEAKER X => English | 한국어)
        sp_match = speaker_re.match(line)
        if sp_match:
            label = sp_match.group(1)
            sp_english = sp_match.group(2).strip()
            sp_korean = sp_match.group(3).strip()
            if label and sp_korean:
                speakers[label] = {"english": sp_english, "korean": sp_korean}
            continue
        # entity 패턴 (English → 한국어 [type])
        if "→" not in line:
            continue
        left, right = line.split("→", 1)
        english = left.strip().lstrip("-").strip()
        right_str = right.strip()
        type_match = re.search(r"\[(person|company|place|product)\]\s*$", right_str)
        entity_type = type_match.group(1) if type_match else "unknown"
        korean = re.sub(r"\s*\[[^\]]+\]\s*$", "", right_str).strip()
        if english and korean and _ENGLISH_NAME_RE.match(english):
            entities[english] = {
                "korean": korean,
                "type": entity_type,
                "source": "bootstrap",
            }

    # 5/23 — 화자 식별 결과를 in-memory cache attribute 로 부착 (호출자가 catch 가능).
    # 기존 entities 반환 형식 유지 (1-pass 호환) + speakers 는 module-level 임시 저장.
    if speakers:
        entities["__speakers__"] = speakers   # 마커 키 — translate_transcript 에서 추출
    return entities


CACHE_DIR = Path.home() / ".gurunote" / "entity_cache"


LOANWORD_SPEC_VERSION = "2017-14"


CACHE_SCHEMA_VERSION = "2"


_LOANWORD_FILE = DATA_DIR / "loanword_orthography.md"


_CANONICALIZE_MAX_BODY_CHARS = 60000


def _compute_cache_key_from_title(video_title: str) -> str:
    """video_id 부재 시 video_title hash 로 cache key 생성 — spec §3.1 fallback.

    AudioDownloadResult.to_context_dict() 가 video_id 를 dict 에 포함 부재 — 본 fallback 으로
    같은 영상 재처리 시에도 cache hit 가능.
    """
    if not video_title:
        return ""
    return "title_" + hashlib.sha256(video_title.encode("utf-8")).hexdigest()[:16]


def _load_loanword_short_version() -> str:
    """Bootstrap LLM prompt 용 외래어 표기법 short version — spec §3.3 R4 정합.

    추출 영역:
        - 표 1 (국제 음성 기호 + 한글 대조표) — 영어 음운 매핑 catch
        - 제4장 (인명·지명 표기의 원칙) — 본 phase 본질 자료

    Returns:
        markdown body. 자료 file 부재 시 "" (호출자가 prompt 에서 자동 skip).
    """
    if not _LOANWORD_FILE.exists():
        return ""
    text = _LOANWORD_FILE.read_text(encoding="utf-8")

    table1_match = re.search(
        r"###\s*표\s*1.*?(?=###\s*표\s*2|\Z)",
        text,
        flags=re.DOTALL,
    )
    table1 = table1_match.group(0).strip() if table1_match else ""

    chapter4_match = re.search(
        r"##\s*제4장.*?(?=##\s*제\d+장|##\s*부\s*칙|\Z)",
        text,
        flags=re.DOTALL,
    )
    chapter4 = chapter4_match.group(0).strip() if chapter4_match else ""

    parts = [p for p in (table1, chapter4) if p]
    return "\n\n".join(parts)


def _load_loanword_full_body() -> str:
    """Phase 3 후처리 용 외래어 표기법 전체 본문 — spec §3.3 R4 정합.

    Returns:
        markdown body. 자료 file 부재 시 "" (Sub-B 가 자동 skip).
    """
    if not _LOANWORD_FILE.exists():
        return ""
    return _LOANWORD_FILE.read_text(encoding="utf-8")


_LOANWORD_SHORT = _load_loanword_short_version()


def _get_cache_file_path(video_id: str) -> Path:
    """영상 ID 기반 cache file 경로 — `~/.gurunote/entity_cache/<video_id>.json`."""
    return CACHE_DIR / f"{video_id}.json"


def _save_entity_cache(
    video_id: str,
    video_title: str,
    entities: dict,
    speakers: Optional[dict] = None,
    spec_version: str = LOANWORD_SPEC_VERSION,
) -> None:
    """entity_cache 디스크 저장 (5/23 — speakers 필드 추가, schema v2).

    Args:
        video_id: YouTube 영상 ID (cache key).
        video_title: 영상 제목 (debug 용).
        entities: in-memory dict — `{english: {korean, type, source}}`.
        speakers: speaker mapping `{label: {english, korean}}` (예: {"A": {"english":
            "Pankaj Sharma", "korean": "판카즈 샤르마"}}). None 또는 빈 dict 가능.
        spec_version: 외래어 표기법 본문 버전 (LOANWORD_SPEC_VERSION 기본).

    Side effects:
        CACHE_DIR 부재 시 자동 생성. file 덮어쓰기.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _entity_item(english: str, meta: dict) -> dict:
        item = {
            "english": english,
            "korean": meta.get("korean", ""),
            "type": meta.get("type", "unknown"),
            "source": meta.get("source", "unknown"),
        }
        # 검색 그라운딩 교정 entity 만 원래 철자를 기록 (load_stt_corrections 가 역추적).
        # 비교정 entity 는 필드 자체를 생략 — additive·optional (옛 cache·기존 동작 호환).
        orig = (meta.get("original_english") or "").strip()
        if orig:
            item["original_english"] = orig
        return item

    entities_list = [_entity_item(english, meta) for english, meta in entities.items()]

    speakers_list = [
        {
            "label": label,
            "english": meta.get("english", ""),
            "korean": meta.get("korean", ""),
        }
        for label, meta in (speakers or {}).items()
    ]

    data = {
        "video_id": video_id,
        "video_title": video_title,
        "created_at": datetime.now().astimezone().isoformat(),
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "loanword_spec_version": spec_version,
        "entities": entities_list,
        "speakers": speakers_list,
    }

    cache_path = _get_cache_file_path(video_id)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_entity_cache(
    video_id: str,
    expected_spec_version: str = LOANWORD_SPEC_VERSION,
) -> Optional[dict]:
    """entity_cache 디스크 로드 — entities 만 반환 (기존 호출자 호환).

    Args:
        video_id: YouTube 영상 ID.
        expected_spec_version: 현재 외래어 표기법 본문 버전.

    Returns:
        `{english: {korean, type, source}}` dict 또는 None.
        None 시 호출자는 bootstrap 재실행.
    """
    full = _load_entity_cache_full(video_id, expected_spec_version)
    return full["entities"] if full is not None else None


def _load_entity_cache_full(
    video_id: str,
    expected_spec_version: str = LOANWORD_SPEC_VERSION,
) -> Optional[dict]:
    """5/23 — cache 전체 로드 (entities + speakers). schema v2 검증.

    schema_version 불일치 시 None (옛 cache 자동 invalidate — speakers 부재).

    Returns:
        `{"entities": {english: meta}, "speakers": {label: {english, korean}}}` 또는 None.
    """
    cache_path = _get_cache_file_path(video_id)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # schema v2 검증 — speakers 필드 추가로 옛 cache (v1, schema field 부재) 자동 invalidate.
    if data.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if data.get("loanword_spec_version") != expected_spec_version:
        return None

    entities: dict = {}
    for item in data.get("entities", []):
        english = item.get("english")
        korean = item.get("korean")
        if not english or not korean:
            continue
        entities[english] = {
            "korean": korean,
            "type": item.get("type", "unknown"),
            "source": item.get("source", "unknown"),
        }
        orig = (item.get("original_english") or "").strip()
        if orig:
            entities[english]["original_english"] = orig

    speakers: dict = {}
    for item in data.get("speakers", []):
        label = item.get("label")
        english = item.get("english", "")
        korean = item.get("korean", "")
        if not label or not korean:
            continue
        speakers[label] = {"english": english, "korean": korean}

    return {"entities": entities, "speakers": speakers}


def load_speaker_names(video_context: Optional[dict]) -> dict:
    """영상의 화자 라벨 → English 실명 매핑을 디스크 cache 에서 읽어 반환.

    exporter 의 영어 원문 섹션이 화자 라벨(`A`/`B`) 대신 실명을 찍도록 쓰는 공개 헬퍼.
    `translate_transcript` 가 번역 끝에 저장한 entity cache(`speakers` 필드)를 재사용한다.
    cache_key 산출은 `translate_transcript` 의 저장 경로와 **같은 우선순위**(id → video_id
    → title hash)를 따라 단일 출처를 유지.

    Args:
        video_context: `AudioDownloadResult.to_context_dict()` 형태 (id/video_id/title).

    Returns:
        `{라벨: English 실명}` dict. 다음 경우 모두 **빈 dict**(호출자는 라벨 fallback):
        cache 파일 부재 / schema·spec 버전 불일치 (`_load_entity_cache_full` → None) /
        speakers 부재 / phase2 off 로 저장된 적 없음 / 손상. 예외는 삼켜 깨지지 않는다.
    """
    if not video_context:
        return {}
    try:
        cache_key = (
            video_context.get("id")
            or video_context.get("video_id")
            or _compute_cache_key_from_title(video_context.get("title", ""))
        )
        if not cache_key:
            return {}
        full = _load_entity_cache_full(cache_key)
        if not full:
            return {}
        speakers = full.get("speakers") or {}
        names: dict = {}
        for label, meta in speakers.items():
            if not isinstance(meta, dict):
                continue
            english = (meta.get("english") or "").strip()
            if label and english:
                names[label] = english
        return names
    except Exception:  # noqa: BLE001 — 표시용 부가 정보라 실패는 빈 dict 로 degrade
        return {}


def _verify_entities_with_search(entity_cache: dict, search_fn: Callable, log=None) -> dict:
    """검색 그라운딩 — person/company entity 의 영문 철자를 주입받은 search_fn 으로 검증·교정.

    인명·회사명 STT 오인식(예: Kevin Wurst → Kevin Warsh)을 외부 근거로 통일. search_fn 은
    의존성 주입 (`search_fn(name, hint) -> 교정 english | None`). 테스트는 가짜 함수를 주입.

    동작:
        - 대상: `type ∈ {person, company}` 이고 아직 검색 안 한 (source != "search") entity.
        - 교정 시 entity_cache 의 key 를 정답으로 교체 — 원래 key 는 `original_english` 로
          보존(frontmatter/원문 전파용), `source="search"` 마킹(재검색 방지).
        - 같은 이름 불일치 통일: 한 영상에 Wurst·Warsh 둘 다 있으면 정답(Warsh)으로 병합.
        - search_fn 실패(예외)는 마킹 안 함(다음 기회 재시도). 성공·교정불필요(None/동일)는
          source 만 마킹.

    Returns:
        `{원래 english: 교정 english}` — 본문 병기 치환 + 소스 풀 주입에 쓴다. 교정 없으면 {}.
    """
    corrections: dict = {}
    if not entity_cache:
        return corrections
    targets = [
        eng for eng, meta in list(entity_cache.items())
        if eng != "__speakers__" and isinstance(meta, dict)
        and meta.get("type") in ("person", "company")
        and meta.get("source") != "search"
    ]
    for eng in targets:
        meta = entity_cache.get(eng)
        if not isinstance(meta, dict) or meta.get("source") == "search":
            continue  # 같은 run 에서 통일로 이미 처리된 경우 skip
        searched_ok = True
        try:
            corrected = search_fn(eng, meta.get("type"))
        except Exception:  # noqa: BLE001 — 검색 실패는 graceful skip (교정 없이 진행)
            corrected = None
            searched_ok = False  # 실패는 마킹 안 함 — 다음 기회 재시도 (transient 보호)
        if not corrected or not isinstance(corrected, str) or corrected.strip() == eng:
            if searched_ok:
                meta["source"] = "search"  # 검색했으나 교정 불필요 — 마킹 (재검색 방지)
            continue
        corrected = corrected.strip()
        existing = entity_cache.get(corrected)
        new_meta = dict(existing) if isinstance(existing, dict) else dict(meta)
        new_meta["source"] = "search"
        new_meta["original_english"] = eng
        new_meta.setdefault("type", meta.get("type", "unknown"))
        if not new_meta.get("korean"):
            new_meta["korean"] = meta.get("korean", "")
        entity_cache[corrected] = new_meta
        if eng != corrected:
            entity_cache.pop(eng, None)
        corrections[eng] = corrected
    if log and corrections:
        log("   🔎 검색 그라운딩 교정 "
            f"{len(corrections)}건: " + ", ".join(f"{o}→{c}" for o, c in corrections.items()))
    return corrections


def load_stt_corrections(video_context: Optional[dict]) -> dict:
    """검색 그라운딩 교정 쌍을 디스크 cache 에서 읽어 `{원래 english: 교정 english}` 반환.

    exporter 가 영어 원문 섹션 표시 치환(Wurst→Warsh) + frontmatter 기록에 쓰는 공개 헬퍼.
    `_verify_entities_with_search` 가 entity meta 에 남긴 `original_english` 를 역으로 모은다.
    cache 부재·schema 불일치·교정 부재·손상은 모두 **빈 dict** (호출자는 교정 없이 진행).
    load_speaker_names 와 같은 cache_key 우선순위(단일 출처).
    """
    if not video_context:
        return {}
    try:
        cache_key = (
            video_context.get("id")
            or video_context.get("video_id")
            or _compute_cache_key_from_title(video_context.get("title", ""))
        )
        if not cache_key:
            return {}
        full = _load_entity_cache_full(cache_key)
        if not full:
            return {}
        out: dict = {}
        for english, meta in (full.get("entities") or {}).items():
            if not isinstance(meta, dict):
                continue
            orig = (meta.get("original_english") or "").strip()
            if orig and english and orig != english:
                out[orig] = english
        return out
    except Exception:  # noqa: BLE001 — 표시용 부가 정보라 실패는 빈 dict 로 degrade
        return {}


_CANONICAL_NAMES_PATH = Path.home() / ".gurunote" / "canonical_names.json"


_CANONICAL_NAMES_DEFAULT = {
    "Palmer Luckey": "팔머 럭키",
    "Rick Rieder": "릭 리더",
}


def _load_canonical_names() -> dict:
    """통용 표기 dict 로드 — 신 구조 `{English: {"auto": str, "user": str}}`.

    - auto = GuruNote 가 작업 중 자동 기록한 표기. user = 사용자가 수정한 표기.
    - 옛 flat 구조 `{English: "한국어"}` 는 값을 **user 로 마이그레이션** (사용자가 넣은
      초기값으로 간주). 파일 없음/손상 시 기본값(user)으로 생성.
    """
    raw = None
    try:
        if _CANONICAL_NAMES_PATH.exists():
            data = json.loads(_CANONICAL_NAMES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data
    except Exception:  # noqa: BLE001 — 손상은 기본값으로 degrade
        raw = None

    if raw is None:
        out = {k: {"auto": "", "user": v} for k, v in _CANONICAL_NAMES_DEFAULT.items()}
        _save_canonical_names(out)  # 최초 생성
        return out

    out: dict = {}
    for k, v in raw.items():
        if not k:
            continue
        if isinstance(v, dict):  # 신 구조
            out[str(k)] = {
                "auto": str(v.get("auto") or ""),
                "user": str(v.get("user") or ""),
            }
        elif v:  # 옛 flat → 값을 user 로 마이그레이션
            out[str(k)] = {"auto": "", "user": str(v)}
    return out


def _save_canonical_names(canonical: dict) -> None:
    """`{English: {auto, user}}` atomic 저장 (tmp → os.replace). auto/user 둘 다 빈
    항목은 제외. 실패는 best-effort (다음 기회에 재저장)."""
    clean: dict = {}
    for k, v in canonical.items():
        if not k:
            continue
        if isinstance(v, dict):
            a, u = str(v.get("auto") or "").strip(), str(v.get("user") or "").strip()
        else:  # 방어 — flat 잔존
            a, u = "", str(v).strip()
        if a or u:
            clean[str(k)] = {"auto": a, "user": u}
    try:
        _CANONICAL_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CANONICAL_NAMES_PATH.with_name(_CANONICAL_NAMES_PATH.name + ".tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _CANONICAL_NAMES_PATH)
    except Exception:  # noqa: BLE001
        pass


def _canonical_effective(canonical: dict) -> dict:
    """English.lower() → 적용할 한국어 (**user 우선**, 없으면 auto). 둘 다 없으면 제외.
    신 구조·옛 flat 모두 수용 (호출부 호환)."""
    out: dict = {}
    for k, v in canonical.items():
        if not k:
            continue
        if isinstance(v, dict):
            kor = (v.get("user") or v.get("auto") or "").strip()
        else:
            kor = str(v).strip()
        if kor:
            out[str(k).lower()] = kor
    return out


def _record_auto_spellings(auto_acc: dict, cache: dict, kind: str) -> None:
    """캐시의 **교정 전 raw** 한국어 표기를 auto 누적 dict 에 모은다 (English → korean).
    kind="entity": `{Eng: {korean}}`, kind="speaker": `{label: {english, korean}}`."""
    if not cache:
        return
    if kind == "entity":
        for eng, meta in cache.items():
            if eng == "__speakers__" or not isinstance(meta, dict):
                continue
            kor = (meta.get("korean") or "").strip()
            if eng.strip() and kor:
                auto_acc[eng.strip()] = kor
    else:  # speaker
        for _label, meta in cache.items():
            if not isinstance(meta, dict):
                continue
            eng = (meta.get("english") or "").strip()
            kor = (meta.get("korean") or "").strip()
            if eng and kor:
                auto_acc[eng] = kor


def _persist_auto_spellings(auto_acc: dict) -> None:
    """누적된 auto 표기를 dict 파일에 병합 저장 — **auto 만 갱신, user 불변**."""
    if not auto_acc:
        return
    try:
        canonical = _load_canonical_names()
        changed = False
        for eng, kor in auto_acc.items():
            entry = canonical.get(eng)
            if entry is None:
                canonical[eng] = {"auto": kor, "user": ""}
                changed = True
            elif entry.get("auto") != kor:
                entry["auto"] = kor  # user 는 건드리지 않음
                changed = True
        if changed:
            _save_canonical_names(canonical)
    except Exception:  # noqa: BLE001 — best-effort
        pass


def _apply_canonical_to_entity_cache(entity_cache: dict, canonical: dict, log=None) -> int:
    """entity_cache `{English: {korean,...}}` 의 English key 가 통용 dict 에 있으면
    korean 을 강제 교정 (user 우선, 대소문자 무시). dict 미수록 key 는 불변."""
    if not entity_cache or not canonical:
        return 0
    lower = _canonical_effective(canonical)
    n = 0
    for eng, meta in entity_cache.items():
        if eng == "__speakers__" or not isinstance(meta, dict):
            continue
        canon = lower.get(eng.lower())
        if canon and meta.get("korean") != canon:
            meta["korean"] = canon
            n += 1
    if log and n:
        log(f"   🔧 통용 표기 교정 (entity {n}건)")
    return n


def _apply_canonical_to_speaker_cache(speaker_cache: dict, canonical: dict, log=None) -> int:
    """speaker_cache `{label: {english, korean}}` 의 english 가 통용 dict 에 있으면
    korean 을 강제 교정 (user 우선). 화자 라벨이 본문 prefix 를 지배하므로 함께 교정."""
    if not speaker_cache or not canonical:
        return 0
    lower = _canonical_effective(canonical)
    n = 0
    for _label, meta in speaker_cache.items():
        if not isinstance(meta, dict):
            continue
        eng = (meta.get("english") or "").strip()
        canon = lower.get(eng.lower())
        if canon and meta.get("korean") != canon:
            meta["korean"] = canon
            n += 1
    if log and n:
        log(f"   🔧 통용 표기 교정 (speaker {n}건)")
    return n


def refresh_canonical_in_markdown(md: str, canonical: dict) -> tuple:
    """완성된 노트(md)에서 auto 표기를 user 표기로 텍스트 치환 (A-2 ③ 리프레시).

    - **auto·user 둘 다 있고 서로 다른 항목만** 대상 (옛 auto 표기를 user 로 교체).
      user 만/auto 만인 항목은 바꿀 옛 표기가 없어 skip.
    - 일반형(`팰머 러커이`) + 태그 언더스코어형(`팰머_러커이`) 둘 다 치환.
    - **단일 패스 정규식**(긴 패턴 우선)으로 치환 — 삽입된 user 텍스트를 재검색하지 않아
      연쇄 치환이 일어나지 않는다. auto 가 한국어라 영어 원문 섹션은 자동 무영향.

    Returns: (new_md, 바뀐 항목 수).
    """
    if not md or not canonical:
        return md, 0
    repl_map: dict = {}
    matched_autos: set = set()
    for v in canonical.values():
        if not isinstance(v, dict):
            continue
        auto = (v.get("auto") or "").strip()
        user = (v.get("user") or "").strip()
        if not (auto and user and auto != user):
            continue
        # 일반형
        if auto in md:
            repl_map[auto] = user
            matched_autos.add(auto)
        # 태그 언더스코어형
        auto_tag, user_tag = auto.replace(" ", "_"), user.replace(" ", "_")
        if auto_tag != auto and auto_tag in md:
            repl_map[auto_tag] = user_tag
            matched_autos.add(auto)
    if not repl_map:
        return md, 0
    # 긴 검색어 우선 (substring 항목이 더 긴 항목 안에서 잘못 잡히는 것 방지).
    keys = sorted(repl_map, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    new_md = pattern.sub(lambda m: repl_map[m.group(0)], md)
    return new_md, len(matched_autos)

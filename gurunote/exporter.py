"""
Step 4 & 5: 최종 GuruNote 마크다운 조립 + 파일명 sanitize + autosave.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from gurunote import __version__ as _GURUNOTE_VERSION
from gurunote.types import Transcript, _format_ts

# autosave 기본 경로
AUTOSAVE_DIR = Path.cwd() / "autosave"

# Phase 2B-3-backend Step 3b-1: detected_language → flag emoji + 표시 라벨.
# 한국어 (ko) 컨텐츠는 번역 단계 skip + 원문 섹션 생략 (별도 섹션 불필요).
# 기타 detected language 는 원문 섹션 헤더에 동적으로 사용.
LANGUAGE_FLAG = {
    "en": "🇺🇸",
    "ja": "🇯🇵",
    "zh": "🇨🇳",
    "ko": "🇰🇷",
}
LANGUAGE_LABEL = {
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "한국어",
}


def _language_flag(lang: Optional[str]) -> str:
    """language code → flag emoji (없으면 🌐 globe)."""
    return LANGUAGE_FLAG.get((lang or "").lower(), "🌐")


def _language_label(lang: Optional[str]) -> str:
    """language code → 표시 라벨 (없으면 code 그대로 또는 'unknown')."""
    code = (lang or "").lower()
    return LANGUAGE_LABEL.get(code, code or "unknown")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """
    영상 제목을 파일명으로 안전하게 변환.
    `GuruNote_<영상제목>.md` 의 가운데 부분에 그대로 들어간다.
    """
    if not name:
        return "untitled"
    cleaned = re.sub(r"[\\/:*?\"<>|]", "", name)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("._")
    return cleaned or "untitled"


def build_full_script_section(translated_text: str, *, language: Optional[str] = None) -> str:
    """전체 스크립트 섹션 — 한국어 detected 시 '한국어 원본', 그 외 '번역본' 헤더.

    Phase 2B-3-backend Step 3b-1: 한국어 컨텐츠 시 STT 결과가 곧 한국어 원본이라
    'translated_text' 가 실제로는 transcript.to_plaintext() 로 전달됨 (gui.py 분기).
    """
    if (language or "").lower() == "ko":
        header = "# 📝 전체 스크립트 (한국어 원본)"
    else:
        header = "# 📝 전체 스크립트 번역본"
    return f"{header}\n\n{translated_text.strip()}\n"


def build_original_script_section(
    transcript: Transcript,
    *,
    language: Optional[str] = None,
    speaker_names: Optional[dict] = None,
    stt_corrections: Optional[dict] = None,
) -> str:
    """원문 스크립트 섹션 — 헤더가 detected language 따라 동적.

    Phase 2B-3-backend Step 3b-1: language === 'ko' 시 호출자가 skip 권장
    (한국어는 단일 섹션). 'en' / 'ja' / 'zh' 등은 flag + label 표시.

    speaker_names: `{라벨: English 실명}` (``llm.load_speaker_names`` 산출). 주어지면
    화자 라벨(``seg.speaker``)을 실명으로 치환해 ``**[MM:SS] {실명}:**`` 로 찍는다.
    한국어 번역본은 번역 중 실명이 본문에 들어가는데 영어 원문은 라벨뿐이라, 같은
    화자 매핑을 원문에도 적용해 비대칭을 없앤다. 매핑 없는 라벨은 기존
    ``**[MM:SS] Speaker {라벨}:**`` 로 fallback (화자분리 미식별·cache miss·라벨이
    글자 아님 등에서 보존 — 비거나 깨지지 않는다).

    stt_corrections: `{원래 english: 교정 english}` (``llm.load_stt_corrections``).
    검색 그라운딩이 STT 오인식(Kevin Wurst → Kevin Warsh)을 교정했으면, 영어 원문
    **표시 텍스트**에서만 원래 철자를 교정 철자로 치환(``seg.text`` 원본 불변). 교정명이
    화자 실명이기도 하면 prefix(화자명)도 함께 치환. 검색 off·교정 부재면 표시 무변.
    """
    flag = _language_flag(language)
    label = _language_label(language)
    names = speaker_names or {}
    corrections = stt_corrections or {}
    lines = [f"# {flag} 원문 스크립트 ({label})", ""]
    for seg in transcript.segments:
        ts = _format_ts(seg.start)
        english = names.get(seg.speaker)
        prefix = english if english else f"Speaker {seg.speaker}"
        text = seg.text
        # 교정명이 화자 실명이기도 하면 prefix 도 같은 교정 적용 (본문만 고치고 화자명이
        # stale 하게 남는 불일치 방지). speaker_names 원본은 불변 — 표시 문자열만 치환.
        for _orig, _corr in corrections.items():
            prefix = prefix.replace(_orig, _corr)
            text = text.replace(_orig, _corr)
        lines.append(f"**[{ts}] {prefix}:** {text}")
        lines.append("")
    return "\n".join(lines)


def build_chapters_section(chapters: Iterable) -> str:
    """
    영상 챕터 섹션. `chapters` 는 `Chapter` 객체 또는 dict 리스트.
    빈 경우 빈 문자열을 반환해 호출자가 skip 가능.
    """
    items = list(chapters or [])
    if not items:
        return ""
    lines = ["# ⏱️ 원본 영상 챕터", ""]
    for ch in items:
        if hasattr(ch, "start"):
            start, title = ch.start, ch.title  # type: ignore[union-attr]
        else:
            start, title = ch.get("start", 0), ch.get("title", "")  # type: ignore[union-attr]
        lines.append(f"- `[{_format_ts(float(start))}]` {title}")
    lines.append("")
    return "\n".join(lines)


def build_gurunote_markdown(
    title: str,
    webpage_url: str,
    summary_md: str,
    translated_text: str,
    transcript: Transcript,
    uploader: str | None = None,
    stt_engine: str = "",
    upload_date: Optional[str] = None,
    chapters: Optional[Iterable] = None,
    subtitles_source: str = "",
    # Phase A — 지식 증류기 메타데이터
    organized_title: str = "",
    field: str = "",
    tags: Optional[List[str]] = None,
    # Phase 2B-3-backend Step 3b-1
    detected_language: Optional[str] = None,
    # 영어 원문 섹션 화자 라벨 → English 실명 매핑 (llm.load_speaker_names). None 시 라벨 유지.
    speaker_names: Optional[dict] = None,
    # 검색 그라운딩 교정 쌍 {원래 english: 교정 english} (llm.load_stt_corrections).
    # 영어 원문 표시 치환 + frontmatter 기록. None 시 교정 없음.
    stt_corrections: Optional[dict] = None,
) -> str:
    """
    최종 다운로드용 마크다운 조립.

    구조:
        - YAML frontmatter (Obsidian/Notion 호환 — Phase A)
        - 헤더 (영상 메타: 제목/채널/게시일/URL/STT/화자수/재생시간/분야/태그)
        - 원본 영상 챕터 (있을 경우)
        - GuruNote 요약 (LLM 결과)
        - 전체 번역 스크립트
        - 영어 원문 스크립트
        - 푸터
    """
    display_title = (organized_title or title).strip()

    # YAML frontmatter — Obsidian/Notion 가 자동 인식하는 메타. 비어있으면 생략.
    frontmatter = _build_frontmatter(
        organized_title=organized_title or title,
        original_title=title,
        uploader=uploader or "",
        upload_date=upload_date or "",
        webpage_url=webpage_url,
        field=field,
        tags=tags or [],
        stt_engine=stt_engine,
        duration_sec=transcript.duration,
        num_speakers=len(transcript.speakers),
        detected_language=detected_language,
        stt_corrections=stt_corrections,
    )

    meta_lines = [f"# 🎙️ GuruNote — {display_title}", ""]
    if organized_title and organized_title != title:
        meta_lines.append(f"- **원본 제목:** {title}")
    if uploader:
        meta_lines.append(f"- **채널:** {uploader}")
    if upload_date:
        meta_lines.append(f"- **게시일:** {upload_date}")
    meta_lines.append(f"- **원본 영상:** <{webpage_url}>")
    if field:
        meta_lines.append(f"- **분야:** {field}")
    if tags:
        tag_str = " ".join(f"`#{t}`" for t in tags)
        meta_lines.append(f"- **태그:** {tag_str}")
    if stt_engine:
        meta_lines.append(f"- **STT 엔진:** `{stt_engine}`")
    if subtitles_source:
        meta_lines.append(f"- **참고한 기존 자막:** `{subtitles_source}`")
    meta_lines.append(f"- **화자 수:** {len(transcript.speakers)}")
    if transcript.duration:
        meta_lines.append(f"- **재생 시간:** {_format_ts(transcript.duration)}")
    # 추적성 — 이 노트를 생성한 GuruNote 빌드 버전 (동적, gurunote.__version__).
    meta_lines.append(f"- **생성:** GuruNote v{_GURUNOTE_VERSION}")
    meta_lines.append("")

    chapters_section = build_chapters_section(chapters or [])

    parts: list[str] = []
    if frontmatter:
        parts.extend([frontmatter, ""])
    parts.append("\n".join(meta_lines))
    if chapters_section:
        parts.extend([chapters_section, ""])
    # Phase 2B-3-backend Step 3b-1: 한국어 detected 시 원문 섹션 생략 (단일 섹션).
    is_korean = (detected_language or "").lower() == "ko"
    parts.extend([
        summary_md.strip(),
        "",
        build_full_script_section(translated_text, language=detected_language),
        "",
    ])
    if not is_korean:
        parts.extend([
            build_original_script_section(
                transcript, language=detected_language, speaker_names=speaker_names,
                stt_corrections=stt_corrections,
            ),
            "",
        ])
    parts.extend([
        "---",
        "_Generated by **GuruNote** — Powered by WhisperX · OpenAI / Anthropic · yt-dlp_",
        "",
    ])
    return "\n".join(parts)


def _build_frontmatter(
    *,
    organized_title: str,
    original_title: str,
    uploader: str,
    upload_date: str,
    webpage_url: str,
    field: str,
    tags: List[str],
    stt_engine: str,
    duration_sec: float,
    num_speakers: int,
    detected_language: Optional[str] = None,
    stt_corrections: Optional[dict] = None,
) -> str:
    """
    Obsidian / Notion / Hugo / Jekyll 호환 YAML frontmatter.

    필요한 값이 하나도 없으면 빈 문자열 반환.

    stt_corrections: `{원래 english: 교정 english}` — 검색 그라운딩이 교정한 인명·회사명을
    ``stt_corrections: ["Wurst→Warsh", ...]`` 로 기록 (추적성). 비면 필드 생략.
    """
    if not (organized_title or field or tags):
        return ""

    lines: list[str] = ["---"]
    if organized_title:
        # YAML safe quoting: 콜론/대시/특수문자 안전
        lines.append(f'title: "{_yaml_escape(organized_title)}"')
    if original_title and original_title != organized_title:
        lines.append(f'original_title: "{_yaml_escape(original_title)}"')
    if uploader:
        lines.append(f'uploader: "{_yaml_escape(uploader)}"')
    if upload_date:
        lines.append(f"upload_date: {upload_date}")
    if webpage_url:
        lines.append(f"source_url: {webpage_url}")
    if field:
        lines.append(f'field: "{_yaml_escape(field)}"')
    if tags:
        # Obsidian 스타일: 공백/특수문자 없는 단순 태그
        sanitized = [_yaml_tag(t) for t in tags]
        sanitized = [t for t in sanitized if t]
        if sanitized:
            tag_array = ", ".join(f'"{t}"' for t in sanitized)
            lines.append(f"tags: [{tag_array}]")
    if stt_engine:
        lines.append(f'stt_engine: "{stt_engine}"')
    if duration_sec:
        lines.append(f"duration_sec: {int(duration_sec)}")
    if num_speakers:
        lines.append(f"num_speakers: {num_speakers}")
    if detected_language:
        # 2 자리 ISO 639-1 code (예: "ko", "en") — frontmatter 에 raw 그대로 저장.
        # frontend / 다른 도구가 LANGUAGE_FLAG / LANGUAGE_LABEL 매핑으로 표시.
        lines.append(f'detected_language: "{_yaml_escape(detected_language)}"')
    lines.append(f'created: {datetime.now().isoformat(timespec="seconds")}')
    # 추적성 — 이 노트를 생성한 GuruNote 빌드 버전 (동적, Obsidian 메타/검색·필터용).
    lines.append(f'gurunote_version: "{_GURUNOTE_VERSION}"')
    # 검색 그라운딩 교정 기록 — 인명·회사명 STT 오인식을 무엇으로 교정했는지 (추적성).
    if stt_corrections:
        items = [
            f'"{_yaml_escape(orig)}→{_yaml_escape(corr)}"'
            for orig, corr in stt_corrections.items()
        ]
        if items:
            lines.append(f"stt_corrections: [{', '.join(items)}]")
    lines.append("---")
    return "\n".join(lines)


def _yaml_escape(value: str) -> str:
    """YAML 큰따옴표 문자열 이스케이프 — 백슬래시/큰따옴표만."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _yaml_tag(value: str) -> str:
    """Obsidian 호환 태그 정규화 — 공백을 `_`로, `#` 앞쪽 prefix 제거."""
    v = value.strip().lstrip("#").strip()
    return re.sub(r"\s+", "_", v)


def autosave_result(full_md: str, title: str, save_dir: Path | None = None) -> Path:
    """
    파이프라인 완료 후 full_md 를 autosave/ 폴더에 자동 저장.
    파일명: GuruNote_<title>_<YYYYMMDD_HHMMSS>.md
    Returns: 저장된 파일 경로.
    """
    out_dir = save_dir or AUTOSAVE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"GuruNote_{sanitize_filename(title)}_{ts}.md"
    path = out_dir / fname
    path.write_text(full_md, encoding="utf-8")
    return path

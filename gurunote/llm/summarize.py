"""요약과 메타데이터 추출.
"""
from __future__ import annotations

from typing import Callable
from typing import List
from typing import Optional
import json
import re

from gurunote.llm import chunking
from gurunote.llm import client
from gurunote.llm import context
from gurunote.llm import entities
from gurunote.llm import postprocess
from gurunote.llm import prompts

__all__ = [
    'summarize_translation',
    'extract_metadata',
    '_excerpt_for_metadata',
    '_parse_metadata_json',
]


def summarize_translation(
    translated_text: str,
    title: str,
    config: Optional[client.LLMConfig] = None,
    progress: Optional[client.ProgressFn] = None,
    video_context: Optional[dict] = None,
    stop_event=None,  # threading.Event — partial 사이 polling
) -> str:
    """
    번역본 → 마크다운 요약 (영상 제목/인사이트/타임라인 섹션).
    전체 스크립트는 포함하지 않으며 호출자가 별도로 붙인다.

    video_context 가 제공되면 공식 챕터 목록을 타임라인 섹션의 뼈대로
    사용하도록 LLM 에 주입한다.

    stop_event: threading.Event — set 되면 partial 요약 사이 / 최종 통합 직전에
    RuntimeError raise. translate_transcript 와 같은 패턴.
    """
    log = progress or (lambda _msg: None)
    config = config or client.LLMConfig.from_env()

    def _check_stop() -> None:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")

    system = prompts.SUMMARY_SYSTEM_PROMPT.format(title=title)
    context_block = context.build_video_context_block(video_context)
    if context_block:
        translated_text = (
            f"{context_block}\n### 번역본\n{translated_text}"
        )

    # 요약 단계도 본문이 매우 길면 1차 요약 → 합치기 → 최종 요약 두 단계.
    if len(translated_text) > chunking.DEFAULT_CHUNK_CHAR_LIMIT:
        log("🧪 번역본이 길어 청크별 요약 후 최종 통합합니다…")
        partials: List[str] = []
        # 청크 분할은 빈 줄 기준 단순 분할로 충분
        paragraphs = translated_text.split("\n\n")
        buf: List[str] = []
        size = 0
        for p in paragraphs:
            if size + len(p) > chunking.DEFAULT_CHUNK_CHAR_LIMIT and buf:
                _check_stop()
                partial = client._call_llm(
                    config,
                    system=system,
                    user="다음 부분 번역본의 핵심 인사이트와 타임라인만 요약해:\n\n"
                    + "\n\n".join(buf),
                    max_tokens=config.summary_max_tokens or client.SUMMARY_MAX_TOKENS,
                )
                partials.append(partial)
                buf = []
                size = 0
            buf.append(p)
            size += len(p)
        if buf:
            _check_stop()
            partials.append(
                client._call_llm(
                    config,
                    system=system,
                    user="다음 부분 번역본의 핵심 인사이트와 타임라인만 요약해:\n\n"
                    + "\n\n".join(buf),
                    max_tokens=config.summary_max_tokens or client.SUMMARY_MAX_TOKENS,
                )
            )
        merged_user = (
            "아래는 같은 영상의 부분 요약본들이야. 이를 통합해 GuruNote 스타일의 "
            "최종 요약본을 한 번 더 정리해 줘.\n\n" + "\n\n---\n\n".join(partials)
        )
        log("📝 부분 요약 통합 중…")
        _check_stop()
        merged = client._call_llm(
            config,
            system=system,
            user=merged_user,
            max_tokens=config.summary_max_tokens or client.SUMMARY_MAX_TOKENS,
        ).strip()
        # Phase 3 보완 — 요약 섹션 한자/일본어 후처리 (segment-less A+B).
        merged = postprocess.post_process_cjk_text(merged, config, log)
        # 요약 충실도 (5/28) — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정.
        #   요약 LLM 이 본문 표기('스탠')를 자율 변형('스턴')해도 결정론적으로 통일.
        return postprocess._correct_korean_in_annotations(merged, entities._load_canonical_names())

    log("📝 GuruNote 요약본 생성 중…")
    _check_stop()
    summary = client._call_llm(
        config,
        system=system,
        user=translated_text,
        max_tokens=config.summary_max_tokens or client.SUMMARY_MAX_TOKENS,
    ).strip()
    # Phase 3 보완 — 요약 섹션 한자/일본어 후처리 (segment-less A+B).
    summary = postprocess.post_process_cjk_text(summary, config, log)
    # 요약 충실도 (5/28) — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정.
    #   요약 LLM 이 본문 표기('스탠')를 자율 변형('스턴')해도 결정론적으로 통일.
    return postprocess._correct_korean_in_annotations(summary, entities._load_canonical_names())


def extract_metadata(
    translated_text: str,
    video_meta: Optional[dict] = None,
    config: Optional[client.LLMConfig] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    번역된 스크립트 + 영상 메타데이터에서 분류용 메타데이터를 추출.

    Args:
        translated_text: `translate_transcript` 의 결과 (전체 또는 앞부분 발췌)
        video_meta: yt-dlp 의 영상 메타 (title, uploader, tags, description 등)
        config: client.LLMConfig
        log: 진행 로그 콜백

    Returns:
        {
            "organized_title": str,
            "field": str,
            "tags": list[str] (5개),
        }
        실패 시 빈 dict 반환 (파이프라인 진행 방해 안 함).
    """
    log = log or (lambda _msg: None)
    config = config or client.LLMConfig.from_env()
    video_meta = video_meta or {}

    # LLM 입력 분량 제한 — 앞부분 + 뒷부분 발췌로 토큰 절감
    excerpt = _excerpt_for_metadata(translated_text)

    youtube_title = video_meta.get("title", "") or ""
    uploader = video_meta.get("uploader", "") or ""
    youtube_tags = video_meta.get("tags") or []
    youtube_tag_block = (
        f"\n원본 YouTube 태그: {', '.join(youtube_tags[:15])}" if youtube_tags else ""
    )

    # 제목 지시 분기 — 원본 제목 유무에 따라 직역/요약 신호 명시.
    if youtube_title.strip():
        title_directive = (
            f"- 제목: {youtube_title}\n"
            f"  → organized_title: **위 원본 제목을 구조 그대로 직역**하라 (접두사·게임/문답 형식·"
            f"말장난 보존, 형식 뭉개기·내용 요약 금지). "
            f"인명은 첫 등장 영문 병기 `한국어(English)` 필수.\n"
        )
    else:
        title_directive = (
            "- 제목: (원본 제목 부재)\n"
            "  → organized_title: 인물·주제 중심으로 새로 작성하라.\n"
        )
    user = (
        f"### 영상 메타\n"
        f"{title_directive}"
        f"- 업로더: {uploader}{youtube_tag_block}\n\n"
        f"### 한국어 번역 발췌\n{excerpt}\n"
    )

    log("🏷️  메타데이터(제목/분야/태그) 추출 중…")
    # JSON 은 짧지만 한국어 제목/태그가 길 수 있으므로 config.summary_max_tokens 를
    # 기준으로 여유를 두되, 하한 1024 로 최소 응답 공간 보장.
    metadata_max_tokens = max(1024, (config.summary_max_tokens or 4096) // 4)
    try:
        raw = client._call_llm(
            config,
            system=prompts.METADATA_SYSTEM_PROMPT,
            user=user,
            max_tokens=metadata_max_tokens,
        )
        meta = _parse_metadata_json(raw)
        # B (5/26) — organized_title 영문 병기도 소스(원본 제목 + 번역 본문)로 검증.
        #   summarize/extract 는 entity_cache 미참조 → 제목 오타(Danduril)는 별도 차단.
        if meta.get("organized_title"):
            title_corpus = f"{youtube_title} {translated_text}"
            meta["organized_title"] = postprocess._correct_english_annotations(
                meta["organized_title"], title_corpus
            )
            # 제목 품질 — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정
            #   (LLM 오음차 "스타니슬라프 드루킨밀러(Stan Druckenmiller)" → "스탠 드러켄밀러").
            meta["organized_title"] = postprocess._correct_korean_in_annotations(
                meta["organized_title"], entities._load_canonical_names()
            )
        # Phase 3 보완 — 제목/분야/태그 한자·일본어 후처리 (segment-less A+B).
        if meta.get("organized_title"):
            meta["organized_title"] = postprocess.post_process_cjk_text(meta["organized_title"], config, log)
        if meta.get("field"):
            meta["field"] = postprocess.post_process_cjk_text(meta["field"], config, log)
        if meta.get("tags"):
            meta["tags"] = [postprocess.post_process_cjk_text(t, config, log) for t in meta["tags"]]
        return meta
    except Exception as exc:  # noqa: BLE001
        log(f"  메타데이터 추출 실패 (무시하고 계속): {exc}")
        return {}


def _excerpt_for_metadata(text: str, max_chars: int = 6000) -> str:
    """메타 추출용 발췌 — 앞 70% / 뒤 30% 비율로 자른다."""
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return text[:head] + "\n\n[…중간 생략…]\n\n" + text[-tail:]


def _parse_metadata_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출 (마크다운 코드블록 래핑 허용)."""
    import json
    import re

    if not raw or not raw.strip():
        return {}

    # ```json ... ``` 또는 ``` ... ``` 코드블록 제거
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    payload = fence.group(1) if fence else raw

    # JSON 객체 첫 등장 부분만 추출 (LLM 이 앞뒤로 텍스트 붙이는 경우)
    obj_match = re.search(r"\{.*\}", payload, re.DOTALL)
    if not obj_match:
        return {}

    try:
        data = json.loads(obj_match.group(0))
    except json.JSONDecodeError:
        return {}

    # 스키마 검증 + 정규화
    title_raw = data.get("organized_title")
    field_raw = data.get("field")
    title = title_raw.strip() if isinstance(title_raw, str) else ""
    field = field_raw.strip() if isinstance(field_raw, str) else ""

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        tags_raw = []
    # 문자열만 허용 — `None` / `{}` / 숫자 등이 `str(None)` 거쳐 "None" 같은
    # 쓰레기 태그로 저장되는 것을 방지.
    tags = [t.strip() for t in tags_raw if isinstance(t, str) and t.strip()][:5]

    if not (title or field or tags):
        return {}

    return {
        "organized_title": title,
        "field": field,
        "tags": tags,
    }

"""영상 메타데이터를 프롬프트용 컨텍스트 블록으로 만든다.
"""
from __future__ import annotations

from gurunote.types import _format_ts
from typing import List
from typing import Optional

__all__ = [
    '_MAX_CONTEXT_DESCRIPTION',
    '_MAX_CONTEXT_SUBTITLE',
    'build_video_context_block',
]


_MAX_CONTEXT_DESCRIPTION = 1500   # chars


_MAX_CONTEXT_SUBTITLE = 2000      # chars


def build_video_context_block(video_context: Optional[dict]) -> str:
    """
    AudioDownloadResult 에서 파생된 dict 를 LLM 에 주입할 컨텍스트 블록으로 변환.

    Args:
        video_context: 다음 키를 가진 dict (모두 선택):
            - title, uploader, upload_date, webpage_url
            - description (str)
            - chapters (list[dict] with start/end/title 또는 Chapter 객체 리스트)
            - subtitles_text (str), subtitles_source (str)
            - tags (list[str])

    Returns:
        `"### 영상 컨텍스트\\n..."` 로 시작하는 멀티라인 문자열. 컨텍스트가 없으면 "".
    """
    if not video_context:
        return ""

    lines: List[str] = ["### 영상 컨텍스트"]

    title = (video_context.get("title") or "").strip()
    if title:
        lines.append(f"- 제목: {title}")

    uploader = (video_context.get("uploader") or "").strip()
    if uploader:
        lines.append(f"- 채널: {uploader}")

    upload_date = (video_context.get("upload_date") or "").strip()
    if upload_date:
        lines.append(f"- 게시일: {upload_date}")

    webpage_url = (video_context.get("webpage_url") or "").strip()
    if webpage_url:
        lines.append(f"- 원본 URL: {webpage_url}")

    tags = video_context.get("tags") or []
    if tags:
        lines.append(f"- 태그: {', '.join(tags[:10])}")

    description = (video_context.get("description") or "").strip()
    if description:
        if len(description) > _MAX_CONTEXT_DESCRIPTION:
            description = description[:_MAX_CONTEXT_DESCRIPTION] + "… (truncated)"
        lines.append("")
        lines.append("#### 영상 설명")
        lines.append(description)

    chapters = video_context.get("chapters") or []
    if chapters:
        lines.append("")
        lines.append("#### 공식 챕터")
        for ch in chapters:
            # Chapter 객체 또는 dict 둘 다 지원
            if hasattr(ch, "start"):
                start, title_ch = ch.start, ch.title  # type: ignore[union-attr]
            else:
                start, title_ch = ch.get("start", 0), ch.get("title", "")  # type: ignore[union-attr]
            lines.append(f"- [{_format_ts(float(start))}] {title_ch}")

    subtitle = (video_context.get("subtitles_text") or "").strip()
    if subtitle:
        source = video_context.get("subtitles_source") or "unknown"
        sub_snippet = subtitle
        if len(sub_snippet) > _MAX_CONTEXT_SUBTITLE:
            sub_snippet = sub_snippet[:_MAX_CONTEXT_SUBTITLE] + "… (truncated)"
        lines.append("")
        lines.append(f"#### 영상 기본 자막 발췌 ({source})")
        lines.append(sub_snippet)

    lines.append("")
    lines.append(
        "※ 위 정보를 화자 이름 추론과 챕터 경계 유지의 참고 자료로 사용해. "
        "아래부터 이어지는 스크립트가 실제 번역/요약 대상이야."
    )
    lines.append("")
    return "\n".join(lines)

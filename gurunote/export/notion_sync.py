"""
Notion API 연동 — GuruNote 결과 마크다운을 Notion 페이지로 직접 전송.

Phase E — "지식 증류기" 로드맵.

Phase D 는 Obsidian vault (로컬 파일) 연동이었고, 이 모듈은 Notion workspace
(클라우드) 연동이다. 사용자는 Notion Integration Token 과 parent 페이지/DB ID
를 지정하고 버튼 하나로 결과를 전송한다.

설계:
  - 공식 `notion-client` SDK 사용 (`pip install notion-client`)
  - 의존성 분리: `requirements-notion.txt` (PDF 과 동일 패턴으로 optional)
  - markdown → Notion blocks: 제한된 subset 만 지원 (heading_1/2/3,
    paragraph, bulleted_list_item, numbered_list_item, quote, code, divider).
    Table 은 현재 로그만 남기고 skip.
  - frontmatter → page properties (parent 가 database 인 경우):
    * title (필수 — 모든 DB 의 default title property 로 매핑)
    * field → "Field" (select)
    * tags → "Tags" (multi_select)
    * uploader → "Uploader" (rich_text)
    * upload_date → "Upload Date" (date)
    * source_url → "Source" (url)
    매핑 실패 (property 없거나 타입 불일치) 는 silent skip — title 만 필수.
  - parent 가 page 인 경우 properties 는 무시되고 title 만 페이지 제목으로.

사용자가 Integration Token 을 발급받고 target DB/page 에 명시적으로 공유해야
API 가 작동 (Notion 보안 모델).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# =============================================================================
# 가용성 체크
# =============================================================================
def is_notion_sync_available() -> bool:
    """`notion-client` 가 import 가능한지."""
    try:
        import notion_client  # type: ignore  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def missing_packages_hint() -> str:
    return (
        "Notion 연동에 필요한 패키지가 설치되어 있지 않습니다.\n"
        "다음 명령으로 설치 후 재실행하세요:\n"
        "  pip install -r requirements-notion.txt\n"
        "\n"
        "추가로 Notion Integration Token 을 발급받고 target page/DB 에\n"
        "공유해야 합니다: https://www.notion.so/my-integrations"
    )


# =============================================================================
# 메인 엔트리
# =============================================================================
def save_to_notion(
    full_md: str,
    title: str,
    token: str,
    parent_id: str,
    is_database: bool = True,
) -> str:
    """
    결과 마크다운을 Notion 페이지로 전송.

    Args:
        full_md: 최종 GuruNote 마크다운 (YAML frontmatter + 본문)
        title: 페이지 제목 (fallback: frontmatter `title` 또는 첫 `# ` heading)
        token: Notion Integration Token (`secret_...`)
        parent_id: database ID 또는 page ID (UUID)
        is_database: True 면 parent 를 database 로 해석 (properties 매핑),
            False 면 page 로 해석 (properties 없이 단순 자식 페이지 생성).

    Returns:
        생성된 Notion 페이지 URL.

    Raises:
        RuntimeError — 패키지 미설치 / API 호출 실패 / 인증 실패.
    """
    if not is_notion_sync_available():
        raise RuntimeError(missing_packages_hint())

    from notion_client import Client  # type: ignore

    if not token:
        raise RuntimeError("Notion Integration Token 이 비어 있습니다.")
    if not parent_id:
        raise RuntimeError("Notion parent ID (database/page) 가 비어 있습니다.")

    # frontmatter 분리 + 최종 제목 결정
    frontmatter, body = _split_frontmatter(full_md)
    meta = _parse_simple_yaml(frontmatter) if frontmatter else {}
    final_title = (title or "").strip() or (
        meta.get("title", "").strip() if isinstance(meta.get("title"), str) else ""
    ) or _extract_first_heading(body) or "GuruNote Export"

    # 본문 → Notion blocks
    blocks = _markdown_to_blocks(body)

    # Notion 은 한 번에 최대 100개 블록까지 children 으로 받음
    first_batch = blocks[:100]
    rest_batches = [blocks[i : i + 100] for i in range(100, len(blocks), 100)]

    client = Client(auth=token)

    parent_spec = (
        {"database_id": parent_id} if is_database else {"page_id": parent_id}
    )
    properties = (
        _properties_for_database(final_title, meta) if is_database
        else _properties_for_page(final_title)
    )

    try:
        page = client.pages.create(
            parent=parent_spec,
            properties=properties,
            children=first_batch,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Notion 페이지 생성 실패: {exc}") from exc

    # 초과 블록은 append
    for batch in rest_batches:
        try:
            client.blocks.children.append(block_id=page["id"], children=batch)
        except Exception as exc:  # noqa: BLE001
            # 페이지는 생성됐지만 일부 본문이 누락된 상태 — 사용자에게 알림
            raise RuntimeError(
                f"페이지 생성은 성공했지만 본문 일부 append 실패: {exc}\n"
                f"부분 결과: {page.get('url', '(url unavailable)')}"
            ) from exc

    return page.get("url", "")


# =============================================================================
# Properties 매핑
# =============================================================================
def _properties_for_page(title: str) -> dict:
    """Parent 가 page 인 경우 — title property 만."""
    return {
        "title": [{"type": "text", "text": {"content": title[:2000]}}],
    }


def _properties_for_database(title: str, meta: dict) -> dict:
    """Parent 가 database 인 경우 — title + optional field/tags/uploader/date/source.

    ⚠️ **주의**: DB 스키마에 해당 컬럼명 ("Field", "Tags", "Uploader",
    "Upload Date", "Source") 이 존재하지 않으면 Notion API 가 400 으로
    페이지 생성 전체를 거부한다 (개별 property 단위 silent skip 아님).

    사용자는 target DB 에 다음 컬럼을 미리 생성해야 frontmatter 가 매핑된다:
      - Field: Select
      - Tags: Multi-select
      - Uploader: Text
      - Upload Date: Date
      - Source: URL

    컬럼이 없으면 `_properties_for_page` (title 만) 를 쓰도록 `is_database=False`
    로 호출하는 것이 안전.
    """
    props: dict = {
        # DB 의 default title column 이름은 각 DB 마다 다를 수 있음 — "Name" 과
        # "title" 둘 다 흔함. 여기서는 API 기본인 "title" 키로 보낸다.
        "title": {
            "title": [{"type": "text", "text": {"content": title[:2000]}}]
        },
    }
    field = _str_or_empty(meta.get("field"))
    if field:
        props["Field"] = {"select": {"name": field[:100]}}
    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        props["Tags"] = {
            "multi_select": [{"name": str(t)[:100]} for t in tags if str(t).strip()]
        }
    uploader = _str_or_empty(meta.get("uploader"))
    if uploader:
        props["Uploader"] = {
            "rich_text": [{"type": "text", "text": {"content": uploader[:2000]}}]
        }
    upload_date = _str_or_empty(meta.get("upload_date"))
    if upload_date and re.match(r"^\d{4}-\d{2}-\d{2}$", upload_date):
        props["Upload Date"] = {"date": {"start": upload_date}}
    source = _str_or_empty(meta.get("source_url"))
    if source and source.startswith(("http://", "https://")):
        props["Source"] = {"url": source}
    return props


# =============================================================================
# Markdown → Notion blocks 변환기 (제한된 subset)
# =============================================================================
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _split_frontmatter(md_text: str) -> tuple[str, str]:
    m = _FRONTMATTER_RE.match(md_text)
    if not m:
        return "", md_text
    return m.group(1), md_text[m.end():]


def _parse_simple_yaml(fm_block: str) -> dict:
    """pdf_export 와 동일한 최소 파서 — PyYAML 의존성 회피."""
    out: dict = {}
    for raw in fm_block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items_raw = val[1:-1].strip()
            items = []
            for chunk in re.split(r",\s*", items_raw):
                chunk = chunk.strip().strip('"').strip("'")
                if chunk:
                    items.append(chunk)
            out[key] = items
            continue
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        out[key] = val
    return out


def _extract_first_heading(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _str_or_empty(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _rich_text(text: str) -> list:
    """Notion rich_text 기본 객체. 텍스트 길이 2000 자 제한 (Notion API limit)."""
    return [{"type": "text", "text": {"content": text[:2000]}}]


# 간단한 inline 포매팅 파서 — `**bold**`, `*italic*`, `` `code` ``
_INLINE_SEG_RE = re.compile(
    r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)"
)


def _rich_text_with_inline(text: str) -> list:
    """Inline 볼드/이탤릭/코드 를 감지해 Notion rich_text 배열로 분해."""
    if not text:
        return []
    pieces = _INLINE_SEG_RE.split(text)
    out: list = []
    for piece in pieces:
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            content = piece[2:-2]
            out.append({
                "type": "text",
                "text": {"content": content[:2000]},
                "annotations": {"bold": True},
            })
        elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
            content = piece[1:-1]
            out.append({
                "type": "text",
                "text": {"content": content[:2000]},
                "annotations": {"code": True},
            })
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            content = piece[1:-1]
            out.append({
                "type": "text",
                "text": {"content": content[:2000]},
                "annotations": {"italic": True},
            })
        else:
            out.append({"type": "text", "text": {"content": piece[:2000]}})
    return out


def _markdown_to_blocks(body: str) -> list[dict]:
    """
    markdown 을 Notion blocks 리스트로 변환.

    지원:
      # / ## / ### → heading_1/2/3
      > ...        → quote
      - / * ...    → bulleted_list_item
      1. ...       → numbered_list_item
      ``` 코드블록 → code (language=plain)
      ---          → divider
      나머지       → paragraph
      빈 줄        → skip
      | 테이블     → paragraph 로 변환 + 로그 warning (Notion table 블록은 구조가
                    복잡해 v0.6.0.10 에서는 스킵)
    """
    lines = body.splitlines()
    blocks: list[dict] = []
    i = 0
    in_code = False
    code_buffer: list[str] = []
    code_lang = "plain text"

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 코드 블록 ```
        if stripped.startswith("```"):
            if in_code:
                # 닫는 ```
                blocks.append({
                    "type": "code",
                    "code": {
                        "rich_text": _rich_text("\n".join(code_buffer)),
                        "language": code_lang if code_lang in _NOTION_CODE_LANGS else "plain text",
                    },
                })
                in_code = False
                code_buffer = []
                code_lang = "plain text"
            else:
                in_code = True
                code_lang = stripped[3:].strip() or "plain text"
            i += 1
            continue
        if in_code:
            code_buffer.append(line)
            i += 1
            continue

        # 빈 줄 skip
        if not stripped:
            i += 1
            continue

        # 수평선
        if stripped in ("---", "***", "___"):
            blocks.append({"type": "divider", "divider": {}})
            i += 1
            continue

        # 헤딩
        h_match = re.match(r"^(#{1,3})\s+(.+)", stripped)
        if h_match:
            level = len(h_match.group(1))
            text = h_match.group(2).strip()
            btype = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
            blocks.append({
                "type": btype,
                btype: {"rich_text": _rich_text_with_inline(text)},
            })
            i += 1
            continue

        # 인용
        if stripped.startswith("> "):
            # 연속된 > 줄을 하나의 quote 로 묶음
            quote_lines = [stripped[2:]]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            blocks.append({
                "type": "quote",
                "quote": {"rich_text": _rich_text_with_inline(" ".join(quote_lines))},
            })
            continue

        # 번호 리스트
        num_match = re.match(r"^\d+\.\s+(.+)", stripped)
        if num_match:
            blocks.append({
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": _rich_text_with_inline(num_match.group(1)),
                },
            })
            i += 1
            continue

        # 불릿 리스트
        bul_match = re.match(r"^[-*]\s+(.+)", stripped)
        if bul_match:
            blocks.append({
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": _rich_text_with_inline(bul_match.group(1)),
                },
            })
            i += 1
            continue

        # 테이블 (현재는 스킵 — 단순히 줄을 paragraph 로 보존)
        if stripped.startswith("|"):
            blocks.append({
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text_with_inline(stripped)},
            })
            i += 1
            continue

        # 기본 — 단락 (연속된 non-empty 줄 묶음).
        # H4+ (`####+ `) 는 Notion heading 타입이 없어 paragraph 로 떨어지는데,
        # 앞쪽 `#+ ` prefix 가 본문에 그대로 남으면 보기 흉하므로 제거.
        first = re.sub(r"^#{4,}\s+", "", stripped)
        para_lines = [first]
        i += 1
        while i < len(lines):
            s = lines[i].strip()
            if not s:
                break
            # 다음 줄이 다른 block-level 시작이면 중단
            if (
                s.startswith(("```", "#", "> ", "---", "***", "___", "|"))
                or re.match(r"^\d+\.\s+", s)
                or re.match(r"^[-*]\s+", s)
            ):
                break
            para_lines.append(s)
            i += 1
        blocks.append({
            "type": "paragraph",
            "paragraph": {
                "rich_text": _rich_text_with_inline(" ".join(para_lines)),
            },
        })

    # 미닫힌 코드블록 방어적 처리
    if in_code and code_buffer:
        blocks.append({
            "type": "code",
            "code": {
                "rich_text": _rich_text("\n".join(code_buffer)),
                "language": "plain text",
            },
        })

    return blocks


# Notion 이 허용하는 code language 값 (일부). 그 외엔 "plain text" 로 폴백.
_NOTION_CODE_LANGS = {
    "plain text", "python", "javascript", "typescript", "bash", "shell",
    "markdown", "json", "yaml", "html", "css", "sql", "java", "c",
    "c++", "c#", "go", "rust", "ruby", "php", "swift", "kotlin",
    "diff", "docker", "makefile",
}

"""
깔끔한 PDF 출력 — 마크다운을 렌더링된 PDF 로 변환.

Phase C — "지식 증류기" 로드맵.

설계:
  - 저장된 결과 마크다운(YAML frontmatter + 본문) 을 받아 frontmatter 를
    헤더 블록으로 분리 렌더링하고 본문은 일반 마크다운으로 렌더링.
  - `markdown` 패키지로 MD → HTML, `weasyprint` 로 HTML → PDF.
  - Korean 렌더링: 시스템 설치된 Noto Sans KR / Apple SD Gothic Neo /
    맑은 고딕 순으로 CSS `font-family` fallback 체인 구성.
  - weasyprint 는 시스템 의존성(cairo/pango) 이 있어 `requirements-pdf.txt`
    로 분리하고, 미설치 시 `is_pdf_export_available()` False 를 반환해
    UI 가 친절하게 설치 안내 다이얼로그를 띄울 수 있게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


_AVAILABILITY_CACHE: Optional[bool] = None


def is_pdf_export_available(force_recheck: bool = False) -> bool:
    """`markdown` + `weasyprint` 가 **실제 PDF 렌더 가능**한지 smoke-test.

    `import weasyprint` 는 cairo/pango 시스템 라이브러리가 없어도 성공하고
    stderr 로 "WeasyPrint could not import some external libraries" 경고만
    찍고 넘어간다. 하지만 이후 `HTML().write_pdf()` 시점에 `OSError` 로
    크래시해 PDF 생성이 불가능하다. 이 함수는 **실제로 minimal HTML 객체를
    생성**해 cffi 레벨의 네이티브 바인딩까지 통과하는지 확인한다.

    결과는 프로세스 수명 동안 캐시 — 사용자가 자동 설치 다이얼로그에서
    추가 의존성을 깔면 `force_recheck=True` 로 재확인.
    """
    global _AVAILABILITY_CACHE
    if _AVAILABILITY_CACHE is not None and not force_recheck:
        return _AVAILABILITY_CACHE

    try:
        import markdown  # type: ignore  # noqa: F401
        from weasyprint import HTML  # type: ignore
        # cffi 로 감싸진 pango/cairo 가 실제로 로드되는지 확인 —
        # 경량 HTML 파싱만 수행 (PDF 렌더까진 안 가도 native libs 를 트리거).
        HTML(string="<p>_</p>")
        _AVAILABILITY_CACHE = True
    except Exception:  # noqa: BLE001
        _AVAILABILITY_CACHE = False
    return _AVAILABILITY_CACHE


def missing_packages_hint() -> str:
    """사용자에게 보여줄 설치 안내 문구."""
    import platform
    system = platform.system()
    cmd = "pip install -r requirements-pdf.txt"
    if system == "Darwin":
        sys_hint = (
            "\n  macOS: weasyprint 는 cairo/pango 시스템 라이브러리가 필요합니다.\n"
            "    brew install cairo pango gdk-pixbuf libffi\n"
            f"    {cmd}\n"
            "  (한국어 폰트가 없다면: brew install --cask font-noto-sans-cjk-kr)"
        )
    elif system == "Linux":
        sys_hint = (
            "\n  Linux (Debian/Ubuntu):\n"
            "    sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk\n"
            f"    {cmd}"
        )
    else:
        sys_hint = f"\n  {cmd}"
    return (
        "PDF 출력에 필요한 패키지가 설치되어 있지 않습니다.\n"
        "다음 명령으로 설치 후 재실행하세요:" + sys_hint
    )


def markdown_to_pdf(
    md_text: str,
    out_path: Path,
    title: Optional[str] = None,
) -> Path:
    """
    마크다운 텍스트를 렌더링된 PDF 로 저장.

    Args:
        md_text: YAML frontmatter 가 포함된 결과 마크다운 (없어도 OK)
        out_path: 저장할 .pdf 파일 경로
        title: 문서 제목 (PDF 메타 + 첫 페이지 헤더). None 이면 frontmatter
            의 `title` 또는 본문 첫 `# ...` 헤더를 사용.

    Returns:
        저장 성공한 out_path (절대 경로).

    Raises:
        RuntimeError — weasyprint / markdown 미설치 또는 렌더링 실패.
    """
    if not is_pdf_export_available():
        raise RuntimeError(missing_packages_hint())

    import markdown  # type: ignore
    from weasyprint import HTML, CSS  # type: ignore

    frontmatter, body = _split_frontmatter(md_text)
    meta_dict = _parse_simple_yaml(frontmatter) if frontmatter else {}

    # 제목 결정 우선순위: 인자 > frontmatter title > 본문 첫 H1
    display_title = (
        (title or "").strip()
        or meta_dict.get("title", "").strip()
        or _extract_first_heading(body)
        or "GuruNote Export"
    )

    html_body = markdown.markdown(
        body,
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "sane_lists",
            "nl2br",
        ],
        output_format="html5",
    )

    full_html = _html_template(
        body_html=html_body, title=display_title, meta=meta_dict,
    )

    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    HTML(string=full_html).write_pdf(
        str(out_path),
        stylesheets=[CSS(string=_PDF_CSS)],
    )
    return out_path


# =============================================================================
# Helpers
# =============================================================================
def _split_frontmatter(md_text: str) -> tuple[str, str]:
    """(frontmatter_block_or_empty, body) 튜플."""
    m = _FRONTMATTER_RE.match(md_text)
    if not m:
        return "", md_text
    return m.group(1), md_text[m.end():]


def _parse_simple_yaml(fm_block: str) -> dict:
    """
    단순 YAML 파서 (key: value / key: [list]).

    전용 YAML 파서를 의존성으로 끌어들이지 않기 위한 최소 구현. 우리 exporter
    가 생성하는 frontmatter 만 안전하게 파싱하면 됨.
    """
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
        # 배열 형태: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            items_raw = val[1:-1].strip()
            items = []
            for chunk in re.split(r",\s*", items_raw):
                chunk = chunk.strip().strip('"').strip("'")
                if chunk:
                    items.append(chunk)
            out[key] = items
            continue
        # 큰따옴표 벗기기
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        out[key] = val
    return out


def _extract_first_heading(body: str) -> str:
    """본문의 첫 `# ...` H1 텍스트 (있으면)."""
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _html_template(*, body_html: str, title: str, meta: dict) -> str:
    """minimal HTML 문서 생성."""
    import html as html_lib

    def esc(v) -> str:
        return html_lib.escape(str(v), quote=True)

    # 상단 메타 테이블 (있을 때만)
    meta_rows = []
    for label, key in [
        ("업로더", "uploader"),
        ("게시일", "upload_date"),
        ("원본 URL", "source_url"),
        ("분야", "field"),
        ("STT 엔진", "stt_engine"),
    ]:
        v = meta.get(key)
        if v:
            meta_rows.append(f"<tr><th>{esc(label)}</th><td>{esc(v)}</td></tr>")
    tags = meta.get("tags")
    if isinstance(tags, list) and tags:
        tag_html = " ".join(f'<span class="tag">{esc(t)}</span>' for t in tags)
        meta_rows.append(f"<tr><th>태그</th><td>{tag_html}</td></tr>")
    meta_table = ""
    if meta_rows:
        meta_table = (
            '<table class="meta-table">\n'
            + "\n".join(meta_rows)
            + "\n</table>"
        )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>{esc(title)}</title>
</head>
<body>
<header class="doc-header">
<h1 class="doc-title">{esc(title)}</h1>
{meta_table}
</header>
<main>
{body_html}
</main>
</body>
</html>
"""


# =============================================================================
# CSS — 깔끔한 한국어 친화 타이포그래피
# =============================================================================
_PDF_CSS = r"""
@page {
  size: A4;
  margin: 18mm 16mm 22mm 16mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-size: 9pt;
    color: #888;
  }
}

/* Korean-first font stack — 시스템 설치된 폰트를 순차 시도 */
body {
  font-family:
    "Noto Sans KR",
    "Apple SD Gothic Neo",
    "Malgun Gothic",
    "Pretendard",
    "-apple-system",
    "Helvetica Neue",
    sans-serif;
  font-size: 10.5pt;
  line-height: 1.6;
  color: #1a1a1a;
}

.doc-header {
  border-bottom: 2px solid #333;
  padding-bottom: 8mm;
  margin-bottom: 8mm;
}
.doc-title {
  font-size: 20pt;
  font-weight: 700;
  margin: 0 0 4mm 0;
  color: #111;
}
.meta-table {
  border-collapse: collapse;
  margin: 0;
  font-size: 9.5pt;
}
.meta-table th {
  text-align: left;
  color: #666;
  padding: 1mm 6mm 1mm 0;
  font-weight: 600;
  white-space: nowrap;
  vertical-align: top;
}
.meta-table td {
  padding: 1mm 0;
  vertical-align: top;
}
.tag {
  display: inline-block;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 999px;
  padding: 0.3mm 2.5mm;
  margin-right: 1.5mm;
  font-size: 9pt;
}

h1, h2, h3, h4 {
  font-weight: 700;
  color: #111;
  page-break-after: avoid;
  break-after: avoid;
}
h1 { font-size: 16pt; margin: 8mm 0 3mm; border-bottom: 1px solid #ccc; padding-bottom: 1mm; }
h2 { font-size: 13.5pt; margin: 6mm 0 2mm; }
h3 { font-size: 12pt; margin: 5mm 0 2mm; color: #333; }
h4 { font-size: 10.5pt; margin: 4mm 0 1mm; color: #444; }

p { margin: 0 0 2.5mm; orphans: 2; widows: 2; }

ul, ol { margin: 0 0 3mm 5mm; padding-left: 3mm; }
li { margin-bottom: 0.8mm; }

blockquote {
  border-left: 3px solid #8b5cf6;
  padding: 1mm 4mm;
  margin: 3mm 0;
  color: #333;
  background: #faf7ff;
}

code {
  font-family: "SF Mono", "Menlo", "Consolas", "D2Coding", monospace;
  font-size: 9.5pt;
  background: #f4f4f5;
  padding: 0.3mm 1mm;
  border-radius: 2px;
}
pre {
  font-family: "SF Mono", "Menlo", "Consolas", "D2Coding", monospace;
  background: #f4f4f5;
  padding: 2.5mm;
  border-radius: 3px;
  font-size: 9pt;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  page-break-inside: avoid;
}
pre code { background: none; padding: 0; }

table {
  border-collapse: collapse;
  margin: 3mm 0;
  font-size: 9.5pt;
  width: 100%;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #d4d4d8;
  padding: 1.2mm 2mm;
  text-align: left;
  vertical-align: top;
}
th { background: #f4f4f5; font-weight: 600; }

hr {
  border: none;
  border-top: 1px solid #d4d4d8;
  margin: 6mm 0;
}

a { color: #4338ca; text-decoration: none; }

/* 화자 다이얼로그 강조 — "Speaker A (이름):" 같은 패턴은 그냥 p 로 렌더링되지만
   굵은 부분은 markdown bold 로 처리되면 자동으로 강조됨. */
strong { font-weight: 700; color: #111; }
"""

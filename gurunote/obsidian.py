"""
Obsidian vault 로 결과 마크다운을 직접 저장.

Phase D — "지식 증류기" 로드맵.

Phase A 의 YAML frontmatter 가 이미 Obsidian 호환 형식 (title / tags / field
등) 으로 emit 되므로, 사용자는 파일을 vault 폴더에 복사하기만 하면 Obsidian 이
즉시 인식해 태그 검색 / Dataview 쿼리가 가능하다.

설계:
  - `OBSIDIAN_VAULT_PATH` 환경변수에 vault 루트 경로를 저장
  - `OBSIDIAN_SUBFOLDER` (기본 "GuruNote") 에 해당 vault 내부 하위 폴더 지정
  - vault 는 `.obsidian/` 하위 디렉토리 존재로 판별 (Obsidian 앱이 자동 생성)
  - 파일명 충돌 시 timestamp suffix 로 덮어쓰기 회피
  - Path traversal 차단 — filename / subfolder 에 `..` 나 절대경로 금지
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


DEFAULT_SUBFOLDER = "GuruNote"


def is_obsidian_vault(path: Path) -> bool:
    """Vault 는 `.obsidian/` 하위 디렉토리를 갖는 특징으로 판별.

    Obsidian 이 vault 를 처음 열 때 자동 생성하므로, 이 폴더의 존재가
    "유효한 vault" 의 가장 신뢰할 수 있는 지표다.
    """
    try:
        return path.is_dir() and (path / ".obsidian").is_dir()
    except Exception:  # noqa: BLE001
        return False


def find_vault_candidates(max_depth: int = 2, max_results: int = 20) -> list[Path]:
    """흔히 쓰이는 경로들을 스캔해 Obsidian vault 후보를 반환.

    사용자가 경로를 직접 입력하지 않아도 UI 가 "자동 감지된 vault" 목록을
    곧바로 보여줄 수 있게 한다.

    탐색 루트 (OS 별):
      - macOS: ~/Documents, ~/iCloud Drive (Archive),
        ~/Library/Mobile Documents/iCloud~md~obsidian/Documents
        (Obsidian Sync 기본 경로)
      - Linux: ~/Documents, ~, ~/Notes
      - Windows: ~/Documents, ~/OneDrive/Documents

    Args:
        max_depth: 각 루트 아래 몇 단계까지 하위 폴더를 조사할지 (기본 2).
        max_results: 반환할 최대 후보 수 (기본 20, 과도한 스캔 방지).

    Returns:
        `.obsidian/` 폴더가 확인된 절대 경로 리스트. 수정일 내림차순 정렬
        (최근 사용한 vault 가 먼저).
    """
    import platform

    home = Path.home()
    roots: list[Path] = []
    system = platform.system()

    if system == "Darwin":
        roots += [
            home / "Documents",
            home / "iCloud Drive (Archive)",
            home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
            home,
        ]
    elif system == "Windows":
        roots += [
            home / "Documents",
            home / "OneDrive" / "Documents",
            home,
        ]
    else:  # Linux / other
        roots += [
            home / "Documents",
            home / "Notes",
            home,
        ]

    found: list[Path] = []
    seen: set[Path] = set()

    def _walk(node: Path, depth: int) -> None:
        if len(found) >= max_results or depth > max_depth:
            return
        try:
            if not node.is_dir():
                return
        except Exception:  # noqa: BLE001
            return
        if is_obsidian_vault(node):
            resolved = node.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(resolved)
            return  # vault 내부는 더 들어가지 않음
        if depth == max_depth:
            return
        try:
            for child in node.iterdir():
                # 숨김/시스템 폴더 제외 (macOS Library, .Trash 등)
                if child.name.startswith("."):
                    continue
                _walk(child, depth + 1)
                if len(found) >= max_results:
                    return
        except (PermissionError, OSError):
            return

    for root in roots:
        try:
            if root.exists():
                _walk(root, depth=0)
        except Exception:  # noqa: BLE001
            continue

    # 최근 수정된 vault 가 먼저 오도록 정렬
    def _mtime(p: Path) -> float:
        try:
            return (p / ".obsidian").stat().st_mtime
        except Exception:  # noqa: BLE001
            return 0.0

    found.sort(key=_mtime, reverse=True)
    return found


def resolve_vault_path() -> Optional[Path]:
    """`OBSIDIAN_VAULT_PATH` 환경변수 → 절대 Path. 미설정/무효 시 None.

    `~` 확장 + 심볼릭 링크 해결. 디렉토리 존재만 검증 (vault 마커는 별도
    `is_obsidian_vault` 로 확인).
    """
    raw = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    # 사용자가 shell 에서 복사할 때 `"~/MyVault"` 같이 따옴표가 포함되는 경우가
    # 많아서 앞뒤 쌍/단 따옴표를 벗긴다 (`expanduser` 가 따옴표로 시작하는
    # 문자열에서는 `~` 를 확장하지 않음).
    raw = raw.strip('"').strip("'").strip()
    if not raw:
        return None
    try:
        path = Path(os.path.expanduser(raw)).resolve()
    except Exception:  # noqa: BLE001
        return None
    if not path.is_dir():
        return None
    return path


def resolve_subfolder() -> str:
    """`OBSIDIAN_SUBFOLDER` 환경변수 → 정규화된 하위 폴더명. 기본 'GuruNote'."""
    raw = (os.environ.get("OBSIDIAN_SUBFOLDER") or DEFAULT_SUBFOLDER).strip()
    # 경로 구분자 / traversal 방지 — 단일 폴더 이름만 허용
    raw = raw.strip("/").strip("\\")
    if ".." in raw or "/" in raw or "\\" in raw:
        return DEFAULT_SUBFOLDER
    return raw or DEFAULT_SUBFOLDER


def save_to_vault(
    full_md: str,
    filename: str,
    vault_path: Optional[Path] = None,
    subfolder: Optional[str] = None,
) -> Path:
    """
    결과 마크다운을 Obsidian vault 하위 폴더에 저장.

    Args:
        full_md: 최종 GuruNote 마크다운 (YAML frontmatter 포함)
        filename: 저장할 파일명 (`.md` 확장자 자동 추가)
        vault_path: 명시 경로. None 이면 `OBSIDIAN_VAULT_PATH` 환경변수 사용.
        subfolder: 명시 하위 폴더. None 이면 `OBSIDIAN_SUBFOLDER` 또는
            `DEFAULT_SUBFOLDER` ("GuruNote") 사용.

    Returns:
        저장된 파일의 절대 경로. 동일 파일명이 이미 있으면 `_YYYYMMDD_HHMMSS`
        접미사가 붙은 경로.

    Raises:
        RuntimeError — vault 경로 미설정 또는 유효하지 않음.
        ValueError — filename 또는 subfolder 가 경로 이스케이프 시도.
    """
    if vault_path is None:
        vault_path = resolve_vault_path()
    if vault_path is None:
        raise RuntimeError(
            "Obsidian vault 경로가 설정되지 않았습니다.\n"
            "Settings 다이얼로그에서 `OBSIDIAN_VAULT_PATH` 를 지정하거나\n"
            ".env 에 직접 기록하세요."
        )
    if not vault_path.is_dir():
        raise RuntimeError(
            f"Vault 경로가 존재하지 않거나 디렉토리가 아닙니다: {vault_path}"
        )

    # filename 검증 (Path traversal 방지)
    safe_name = (filename or "").strip()
    if not safe_name:
        raise ValueError("파일명이 비어 있습니다.")
    # Windows 드라이브 레터 (`C:foo`) 는 drive-relative 경로로 vault 밖을 가리킬
    # 수 있어서 콜론도 차단. null byte / 경로 구분자도 함께.
    forbidden = {"/", "\\", "..", ":", "\x00"}
    if any(token in safe_name for token in forbidden):
        raise ValueError(
            f"유효하지 않은 파일명 (경로 구분자, 콜론, '..' 금지): {filename}"
        )
    if not safe_name.lower().endswith(".md"):
        safe_name += ".md"

    # subfolder 해석 + 검증
    if subfolder is None:
        sf = resolve_subfolder()
    else:
        sf = subfolder.strip().strip("/").strip("\\")
        if ".." in sf or "/" in sf or "\\" in sf:
            raise ValueError(f"유효하지 않은 subfolder: {subfolder}")
    target_dir = vault_path / sf if sf else vault_path
    target_dir.mkdir(parents=True, exist_ok=True)

    out_path = target_dir / safe_name
    if out_path.exists():
        # timestamp 에 microsecond 포함 → 같은 초에 2회 저장돼도 충돌 없음.
        # 그래도 실패하면 `_2`, `_3` 카운터로 fallback (극단적 race 방지).
        base_stem = out_path.stem
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        candidate = target_dir / f"{base_stem}_{ts}.md"
        counter = 2
        while candidate.exists():
            candidate = target_dir / f"{base_stem}_{ts}_{counter}.md"
            counter += 1
        out_path = candidate

    out_path.write_text(full_md, encoding="utf-8")
    return out_path


# =============================================================================
# Vault 사본 찾기 / 삭제 — 라이브러리 삭제 시 동기화 (표식 기반)
# =============================================================================
# send_obsidian 이 내보낼 때 frontmatter 에 `gurunote_job_id` 표식을 남긴다.
# 라이브러리에서 노트를 지우면 그 표식이 일치하는 vault 사본만 삭제한다.
# 표식이 없는 (예전에 내보낸) 파일은 매칭되지 않아 건드리지 않는다.
_JOB_ID_FM_RE = re.compile(r'^gurunote_job_id:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)


def _read_frontmatter_job_id(md_head: str) -> Optional[str]:
    """마크다운 머리에서 frontmatter `gurunote_job_id` 값 추출. 없으면 None.

    frontmatter 블록(`--- … ---`) 안만 본다 — 본문에 같은 토큰이 있어도 오탐 회피.
    """
    block_match = re.match(r"^---\n(.*?)\n---\n", md_head, re.DOTALL)
    block = block_match.group(1) if block_match else ""
    if not block:
        return None
    m = _JOB_ID_FM_RE.search(block)
    return m.group(1).strip() if m else None


def find_vault_copies(
    job_id: str,
    vault_path: Optional[Path] = None,
    subfolder: Optional[str] = None,
) -> list[Path]:
    """vault 하위 폴더의 `.md` 중 frontmatter `gurunote_job_id` 가 일치하는 파일 목록.

    파일을 삭제하지 않는다 (확인 / dry-run 용). vault 미설정·표식 파일 없음 → 빈 목록.
    """
    if not job_id:
        return []
    if vault_path is None:
        vault_path = resolve_vault_path()
    if vault_path is None or not vault_path.is_dir():
        return []
    sf = resolve_subfolder() if subfolder is None else subfolder
    target_dir = vault_path / sf if sf else vault_path
    if not target_dir.is_dir():
        return []

    matches: list[Path] = []
    for p in sorted(target_dir.glob("*.md")):
        try:
            head = p.read_text(encoding="utf-8")[:4096]  # frontmatter 만 보면 충분
        except OSError:
            continue
        if _read_frontmatter_job_id(head) == job_id:
            matches.append(p)
    return matches


def delete_from_vault(
    job_id: str,
    vault_path: Optional[Path] = None,
    subfolder: Optional[str] = None,
) -> list[Path]:
    """`find_vault_copies` 가 찾은 표식 일치 파일을 삭제. 삭제한 경로 목록 반환.

    표식 없는 파일은 매칭되지 않으므로 절대 삭제되지 않는다.
    """
    deleted: list[Path] = []
    for p in find_vault_copies(job_id, vault_path, subfolder):
        try:
            p.unlink()
            deleted.append(p)
        except OSError:
            pass
    return deleted

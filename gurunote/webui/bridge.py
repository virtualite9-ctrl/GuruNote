"""GuruNote WebView UI — JavaScript Bridge (pywebview js_api).

Exposes a single ``Api`` class to the front-end via pywebview's ``js_api``
parameter. The browser calls ``window.pywebview.api.<method_name>(...)``;
pywebview marshals arguments and return values as JSON.

**Phase 1 MVP status: skeleton.**

- Most methods raise ``NotImplementedError`` and are wired up incrementally
  in Phase 1-B → Phase 5.
- Only ``get_app_info`` and ``pick_file`` return real data — they are the
  minimum needed to demonstrate that the bridge round-trips correctly.

See ``docs/webview-ui/ARCHITECTURE.md`` § 3 for the full method catalog and
response envelope policy.

Open question (deferred — see ``HANDOFF_MORNING.md``): response envelope
shape (raw dict vs. ``{ok, data, error}`` wrapper vs. raise-and-reject).
The skeleton uses raw dicts on success and ``{ok: False, error: str}`` on
failure as a placeholder. Final shape will be settled before broad wiring.
"""
from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any, Optional

# pywebview is imported lazily inside methods that need it so that this module
# can be imported (e.g., for type checking, docs generation) without the GUI
# dependency. The bound ``window`` reference is what we actually use at runtime.

# ----------------------------------------------------------------------------
# Settings allow-list — Mask-2 policy (Phase 1-C #3)
# ----------------------------------------------------------------------------
# Only keys in _KNOWN_SETTINGS are exposed by get_settings / accepted by
# save_settings. This protects the JS bridge from being used to mutate
# arbitrary process environment variables.
#
# _SECRET_KEYS classifies which fields are sensitive — their values are
# returned as a presence-bool only, never as plaintext, and the UI shows
# "●●●●● [저장됨]" placeholders instead of the raw value.
#
# When adding a new env-driven config, list it here AND in the form section
# layout (gurunote/webui/index.html, Settings card — Phase 1-C #3 commits).
_KNOWN_SETTINGS: tuple[str, ...] = (
    # LLM provider routing + tunables
    "LLM_PROVIDER",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "GOOGLE_API_KEY", "GEMINI_MODEL",
    "LLM_TEMPERATURE",
    "LLM_TRANSLATION_MAX_TOKENS", "LLM_SUMMARY_MAX_TOKENS",
    # STT engines + diarization
    "GURUNOTE_STT_ENGINE",
    "WHISPERX_MODEL", "WHISPERX_BATCH_SIZE",
    "MLX_WHISPER_MODEL",
    "HF_TOKEN", "HUGGINGFACE_TOKEN",  # canonical + legacy alias
    "ASSEMBLYAI_API_KEY",
    # Integrations (Obsidian, Notion)
    "OBSIDIAN_VAULT_PATH", "OBSIDIAN_SUBFOLDER",
    # 작업 완료 후 Obsidian 자동 내보내기 — "1"=on / 그 외=off (기본 꺼짐).
    # React onResult 가 이 값을 읽어 send_obsidian 자동 호출 (백엔드 파이프라인 무변).
    "GURUNOTE_OBSIDIAN_AUTOEXPORT",
    "NOTION_TOKEN", "NOTION_PARENT_ID", "NOTION_PARENT_TYPE",
    # Processing options (불리언 토글 — "1"=on / "0"=off, 미설정 시 백엔드 default on).
    # llm.py:2811(GURUNOTE_TWO_PASS) / stt_mlx.py(GURUNOTE_SEGMENT_RESPLIT) 가
    # os.environ 을 읽으므로 키 추가만으로 저장/로드/반영 (백엔드 로직 무변).
    "GURUNOTE_TWO_PASS", "GURUNOTE_SEGMENT_RESPLIT",
)

_SECRET_KEYS: frozenset[str] = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "ASSEMBLYAI_API_KEY",
    "HF_TOKEN",
    "HUGGINGFACE_TOKEN",
    "NOTION_TOKEN",
})


# === thumbnail enrichment helpers (Phase 2B-3) ===

_YT_VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([a-zA-Z0-9_-]{11})")


def _extract_youtube_video_id(url: Optional[str]) -> Optional[str]:
    """YouTube URL 에서 11-char video ID 추출. 비-YouTube URL → None."""
    if not url:
        return None
    m = _YT_VIDEO_ID.search(url)
    return m.group(1) if m else None


def _resolve_thumbnail_url(video_id: Optional[str]) -> Optional[str]:
    """video_id 기반 thumbnail URL.

    1순위: ``~/.gurunote/thumbnails/{video_id}.jpg`` cached → ``file://`` URI
    2순위: ``https://img.youtube.com/vi/{video_id}/hqdefault.jpg``
    None 입력 → None
    """
    if not video_id:
        return None
    cached = Path.home() / ".gurunote" / "thumbnails" / f"{video_id}.jpg"
    if cached.exists():
        return cached.as_uri()
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


# === Phase 2B-3-backend Layer 7: result.md 의 한국어/영어 섹션 parse ===
# MainScreen.jsx ResultPanel 의 'korean' / 'english' tab 이 두 키 기대 (L167-177).
# 이전: payload 부재 → 항상 fallback "처리 완료 후 표시됩니다." 표시.
# 헤더 영역:
#   - 한국어:  "# 📝 전체 스크립트 번역본"  또는  "# 📝 전체 스크립트 (한국어 원본)"
#              (Step 3b-1 의 ko 분기 시 후자, exporter.py:59-69)
#   - 원문:    "# 🇺🇸 원문 스크립트 (English)"  / 🇯🇵 / 🇨🇳 / 🌐 / etc.
#              (legacy: "# 🇺🇸 영어 원문 스크립트")
#   - 한국어 원본 노트 (Step 3b-1) → 원문 섹션 통째 생략 → english_transcript = ""
_KOREAN_SECTION_RE = re.compile(
    r"^# 📝 전체 스크립트[^\n]*\n(.*?)(?=^# |^---|\Z)",
    re.MULTILINE | re.DOTALL,
)
_ORIGINAL_SECTION_RE = re.compile(
    r"^# .+ 원문 스크립트[^\n]*\n(.*?)(?=^# |^---|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_transcripts(markdown: str) -> tuple[str, str]:
    """result.md → (korean_transcript, english_transcript).

    - 다국어 노트: 두 섹션 모두 정합
    - 한국어 원본 노트 (Step 3b-1): english_transcript = ""
    - Legacy 노트 (섹션 부재): 둘 다 ""
    """
    korean_match = _KOREAN_SECTION_RE.search(markdown)
    english_match = _ORIGINAL_SECTION_RE.search(markdown)
    korean = korean_match.group(1).strip() if korean_match else ""
    english = english_match.group(1).strip() if english_match else ""
    return korean, english


# Phase 2B-3-backend Layer 7: 요약 영역 (📌 + 💡 + ⏱️ 3 섹션) parse.
# build_gurunote_markdown (exporter.py) 의 출력 영역 정합 — 헤더 3개 연속 + script
# 섹션 직전 (# 📝 전체 스크립트). ResultPanel 의 'summary' tab 데이터 source.
_SUMMARY_SECTION_RE = re.compile(
    r"^# 📌 영상 제목.*?(?=^# 📝 전체 스크립트|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _parse_summary(markdown: str) -> str:
    """result.md → 요약 영역 (📌 핵심 주제 + 💡 Insights + ⏱️ 타임라인) markdown text.

    헤더 영역 부재 시 "" 반환 (legacy 노트 또는 비정상 노트).
    """
    match = _SUMMARY_SECTION_RE.search(markdown)
    return match.group(0).strip() if match else ""


# Phase 2B-3-backend Step 3b-3: result.md 의 YAML frontmatter parse (regex 기반).
# PyYAML 의존성 회피 — exporter.py 가 build 하는 알려진 구조만 지원.
# 지원 type: str (quoted/unquoted), int, list ([a, b] 또는 ["a", "b"]).
_FRONTMATTER_BLOCK_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_FM_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def _strip_yaml_value(raw: str) -> object:
    """YAML 값 영역 unquote + type infer (str/int/list)."""
    s = raw.strip()
    if not s:
        return ""
    # List: [a, b] or ["a", "b"]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        items = [_strip_yaml_value(p) for p in inner.split(",")]
        return [it for it in items if it != ""]
    # Quoted string
    if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
        return s[1:-1]
    # Int
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except ValueError:
            pass
    return s


def _parse_frontmatter(markdown: str) -> dict:
    """result.md → frontmatter dict (YAML 영역 parse).

    frontmatter 부재 (--- 영역 없음) → {} 반환. 알려진 구조 (exporter.py 가 build)
    만 지원 — list / quoted str / int / 평문 str 영역.
    """
    match = _FRONTMATTER_BLOCK_RE.match(markdown)
    if not match:
        return {}
    block = match.group(1)
    out: dict = {}
    for line in block.splitlines():
        m = _FM_LINE_RE.match(line)
        if not m:
            continue
        key, raw_val = m.group(1), m.group(2)
        out[key] = _strip_yaml_value(raw_val)
    return out


def _obsidian_note_stem(title: str) -> str:
    """Obsidian 노트 파일명 stem (확장자 제외) — 작업물 제목만으로 구성.

    send_obsidian 의 저장 파일명과 wikilink 대상이 모두 이 helper 를 거치므로,
    파일명과 링크 stem 이 항상 일치한다 (그래프 연결 보장). 출처 구분은 파일명
    접두사 대신 frontmatter ``gurunote_job_id`` 표식 + 하위 폴더(``Gurunote/``)가
    담당하므로 접두사를 붙이지 않는다."""
    from gurunote.exporter import sanitize_filename  # noqa: PLC0415
    return sanitize_filename(title)


def _inject_frontmatter_field(md: str, key: str, value: str) -> str:
    """frontmatter 닫는 ``---`` 직전에 ``key: "value"`` 한 줄을 삽입.

    이미 같은 key 가 있으면 중복 삽입하지 않는다 (재내보내기 대비). frontmatter 가
    없으면 원본 그대로 반환. ``_inject_related_notes`` 와 같은 정규식 패턴 — 기존
    필드는 보존하고 vault 사본에만 적용된다.
    """
    fm_match = re.match(r"^(---\n.*?\n)(---\n)", md, re.DOTALL)
    if not fm_match:
        return md
    head, close = fm_match.group(1), fm_match.group(2)
    if re.search(rf"^{re.escape(key)}:", head, re.MULTILINE):
        return md
    line = f'{key}: "{value}"\n'
    return head + line + close + md[fm_match.end():]


def _inject_related_notes(md: str, related: list) -> str:
    """vault 로 내보낼 마크다운에 RAG 유사 노트를 wikilink 로 삽입.

    - 본문 끝 ``## 연관 노트`` 섹션: ``- [[stem|제목]] (78%)`` (Obsidian 읽기뷰에서
      "제목 (78%)" 로 보이고, 상대 노트가 vault 에 있으면 그래프로 연결).
    - frontmatter ``related: ["[[stem]]", …]`` (Dataview / 그래프용).

    ``related`` 가 비면 원본 그대로 반환 (RAG 미설치/인덱스 없음/유사 노트 없음 시
    내보내기가 깨지지 않게). 저장된 result.md 는 손대지 않고 vault 사본만 수정한다.
    """
    if not related:
        return md

    body_lines = ["", "## 연관 노트", ""]
    fm_links = []
    for r in related:
        t = (r.get("title") or r.get("job_id") or "").strip()
        if not t:
            continue
        stem = _obsidian_note_stem(t)
        pct = round((r.get("score") or 0) * 100)
        body_lines.append(f"- [[{stem}|{t}]] ({pct}%)")
        fm_links.append(f'"[[{stem}]]"')
    if len(body_lines) <= 3:  # 유효 항목 없음
        return md
    body_section = "\n".join(body_lines) + "\n"

    # frontmatter 닫는 --- 직전에 related: 한 줄 삽입 (기존 필드 보존).
    fm_match = re.match(r"^(---\n.*?\n)(---\n)", md, re.DOTALL)
    if fm_match and fm_links:
        head, close = fm_match.group(1), fm_match.group(2)
        related_line = f"related: [{', '.join(fm_links)}]\n"
        md = head + related_line + close + md[fm_match.end():]

    return md.rstrip() + "\n" + body_section


class Api:
    """JavaScript-facing bridge.

    Lifecycle:
        1. ``Api()`` is instantiated before ``webview.create_window``.
        2. The instance is passed as ``js_api=`` to ``create_window``.
        3. After ``create_window`` returns the ``Window``, call
           ``api.bind_window(window)`` so subsequent methods can use
           ``window.create_file_dialog`` and ``window.evaluate_js``.
    """

    # ------------------------------------------------------------------ setup

    def __init__(self) -> None:
        self._window = None  # set via bind_window()

    def bind_window(self, window: Any) -> None:
        """Attach the pywebview Window so the bridge can call its methods."""
        self._window = window

    # ------------------------------------------------------------------ helpers

    def _err(self, code: str, message: str) -> dict:
        return {"ok": False, "error": message, "code": code}

    def _require_window(self) -> Any:
        if self._window is None:
            raise RuntimeError(
                "Api.bind_window() not called — bridge is not ready yet"
            )
        return self._window

    # ============================================================ app info

    def get_app_info(self) -> dict:
        """Return version, platform, hardware info, and project metadata.

        Used by the front-end on initial load to populate the sidebar
        version label and conditionally show Apple Silicon-only options.
        Phase 2B-4c-3: also exposes ``license`` and ``github_url`` for the
        Settings → "GuruNote 정보" panel.
        """
        try:
            from gurunote import __version__
        except ImportError:
            __version__ = "unknown"

        return {
            "ok": True,
            "version": __version__,
            "platform": platform.system(),
            "machine": platform.machine(),
            "is_apple_silicon": (
                platform.system() == "Darwin" and platform.machine() == "arm64"
            ),
            "license": "Elastic License 2.0",
            "github_url": "https://github.com/avlp12/GuruNote",
        }

    # ============================================================ file picker

    def pick_file(self) -> dict:
        """Open native file-open dialog. Returns ``{path, size}`` or ``{cancelled}``.

        The file_types filter mirrors ``gurunote.audio.SUPPORTED_EXTS``
        (8 audio + 9 video = 17 extensions) so users cannot pick a file
        via the dialog's audio/video filter that would subsequently fail
        ``is_supported_local_file`` in ``start_pipeline``.

        ``size`` is the file's byte count (``Path.stat().st_size``), or
        ``None`` if the stat call fails. The front-end uses this for the
        selected-file badge and can still function without it.
        """
        import webview  # local import — only needed at runtime
        from pathlib import Path

        window = self._require_window()
        result = window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                # pywebview 4.x label regex `[\w ]+` rejects '/' — keep label
                # ASCII word chars + spaces only. See webview/util.py
                # parse_file_type → "is not a valid file filter" otherwise.
                "Audio Video Files (*.mp3;*.wav;*.flac;*.m4a;*.aac;*.ogg;*.wma;*.opus;"
                "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.wmv;*.flv;*.ts;*.m4v)",
                "All files (*.*)",
            ),
        )
        if not result:
            return {"cancelled": True}
        path = result[0]
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = None
        return {"path": path, "size": size}

    # ============================================================ pipeline

    def start_pipeline(self, source: dict) -> dict:
        """Validate, then spawn a ``PipelineSession`` on a background thread.

        ``source`` shape::

            {
              "kind": "youtube" | "local",
              "value": str,                 # URL or absolute file path
              "engine": "auto" | "whisperx" | "mlx" | "assemblyai",
              "provider": "openai" | "anthropic" | "gemini" | "openai_compatible",
            }

        Returns ``{"job_id": str}`` on success. Raises on any validation or
        preflight failure; pywebview forwards the exception to JS as a
        Promise reject so callers ``await`` with ``try/catch``.

        Raised ``RuntimeError`` ``args[0]`` uses a ``<CODE>:<detail>`` convention so
        the front-end can switch on structured codes:
            INVALID_URL:<detail>
            INVALID_LOCAL_FILE:<path>
            API_KEY_MISSING:<env_var_name>

        Progress / log / result are delivered via the JS event bus.
        """
        window = self._require_window()

        # ---- shape validation
        if not isinstance(source, dict):
            raise ValueError(f"source must be a dict, got {type(source).__name__}")
        for key in ("kind", "value", "engine", "provider"):
            if key not in source:
                raise ValueError(f"source missing required key: {key!r}")

        kind = source["kind"]
        value = (source.get("value") or "").strip()
        provider = source["provider"]

        # ---- source validation (import from gurunote.audio lazily to avoid
        # pulling in yt-dlp / ffmpeg checks at bridge import time)
        if kind == "youtube":
            from gurunote.audio import is_probably_youtube_url  # noqa: PLC0415
            if not is_probably_youtube_url(value):
                raise RuntimeError("INVALID_URL:유튜브 URL 형식이 아닙니다.")
        elif kind == "local":
            from pathlib import Path  # noqa: PLC0415
            from gurunote.audio import is_supported_local_file  # noqa: PLC0415
            if not value or not Path(value).is_file() or not is_supported_local_file(value):
                raise RuntimeError(f"INVALID_LOCAL_FILE:{value}")
        else:
            raise ValueError(f"source.kind must be 'youtube' or 'local', got {kind!r}")

        # ---- API key preflight (mirrors gui.py _check_api_keys; does NOT launch
        # the settings dialog — JS caller shows a toast with the missing key code)
        import os  # noqa: PLC0415
        key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "openai_compatible": "OPENAI_BASE_URL",
        }
        required_env = key_map.get(provider)
        if required_env and not os.environ.get(required_env):
            raise RuntimeError(f"API_KEY_MISSING:{required_env}")

        # ---- launch
        from gurunote.webui.session import PipelineSession  # noqa: PLC0415
        session = PipelineSession(window, {
            "kind": kind,
            "value": value,
            "engine": source["engine"],
            "provider": provider,
        })
        session.start()
        return {"job_id": session.job_id}

    def stop_pipeline(self, job_id: str) -> dict:
        """Signal the worker for ``job_id`` to stop. Returns ``{"stopped": True}``.

        Raises ``RuntimeError("NO_ACTIVE_SESSION:<job_id>")`` if the job is
        unknown or already completed.
        """
        from gurunote.webui.session import get_session  # noqa: PLC0415
        session = get_session(job_id)
        if session is None:
            raise RuntimeError(f"NO_ACTIVE_SESSION:{job_id}")
        session.request_stop()
        return {"stopped": True}

    def get_pipeline_status(self, job_id: str) -> dict:
        """Poll fallback: returns whether a session is still active for ``job_id``.

        Not normally needed — events push progress. Useful if the front-end
        reloads and loses event-bus state.
        """
        from gurunote.webui.session import get_session  # noqa: PLC0415
        return {"active": get_session(job_id) is not None}

    # ============================================================ settings

    def get_settings(self) -> dict:
        """Return current settings.

        Response shape::

            {
              "ok": True,
              "values": { non_secret_KEY: current str value (possibly "") },
              "secrets_set": { secret_KEY: bool },
            }

        Plaintext secret values are NEVER returned — only a boolean
        presence flag. The UI renders "●●●●● [저장됨]" placeholders for
        keys whose ``secrets_set[key]`` is ``True`` and prompts for new
        input on the rest.
        """
        import os  # noqa: PLC0415

        try:
            values: dict[str, str] = {}
            secrets_set: dict[str, bool] = {}
            for key in _KNOWN_SETTINGS:
                current = os.environ.get(key, "")
                if key in _SECRET_KEYS:
                    secrets_set[key] = bool(current)
                else:
                    values[key] = current
            return {"ok": True, "values": values, "secrets_set": secrets_set}
        except Exception as exc:  # noqa: BLE001
            return self._err(
                "SETTINGS_LOAD_FAILED", f"{type(exc).__name__}: {exc}"
            )

    # ----- 통용 표기 dict (canonical_names.json — .env 와 무관) -----------------
    # 인명·회사명 한국어 표기 교정 dict. 구조 {English: {auto, user}}.
    # 파일 I/O 는 llm.py 의 _load/_save 재사용 (단일 출처). get_settings/.env 와 별개.

    def get_canonical_names(self) -> dict:
        """통용 표기 dict 반환 — ``{English: {"auto": str, "user": str}}``."""
        try:
            from gurunote.llm import _load_canonical_names  # noqa: PLC0415
            return {"ok": True, "names": _load_canonical_names()}
        except Exception as exc:  # noqa: BLE001
            return self._err("CANONICAL_LOAD_FAILED", f"{type(exc).__name__}: {exc}")

    def save_canonical_names(self, payload: Any = None) -> dict:
        """통용 표기 dict 저장. payload = ``{English: {auto, user}}`` (또는 값이 str 이면
        user 로 간주). 빈 항목 제외 + atomic write 는 ``_save_canonical_names`` 가 처리.
        저장 후 정규화된 dict 를 다시 반환 (UI 재로드용)."""
        if not isinstance(payload, dict):
            return self._err("INVALID_NAMES", f"payload must be dict, got {type(payload).__name__}")
        clean: dict = {}
        for k, v in payload.items():
            eng = str(k).strip()
            if not eng:
                continue
            if isinstance(v, dict):
                clean[eng] = {
                    "auto": str(v.get("auto") or "").strip(),
                    "user": str(v.get("user") or "").strip(),
                }
            else:
                clean[eng] = {"auto": "", "user": str(v or "").strip()}
        try:
            from gurunote.llm import _load_canonical_names, _save_canonical_names  # noqa: PLC0415
            _save_canonical_names(clean)
            return {"ok": True, "names": _load_canonical_names()}
        except Exception as exc:  # noqa: BLE001
            return self._err("CANONICAL_SAVE_FAILED", f"{type(exc).__name__}: {exc}")

    def refresh_job_canonical(self, job_id: Any = None) -> dict:
        """기존 노트의 통용 표기 새로고침 (A-2 ③) — auto 표기를 user 표기로 텍스트 치환.

        번역 재실행 없이 완성된 result.md 의 문자열만 교체 (auto·user 둘 다 있는 항목).
        ``get_job_markdown`` → ``refresh_canonical_in_markdown`` → ``update_job_markdown``.
        변경 0 이면 저장 생략. 갱신된 markdown 을 함께 반환 (UI 재렌더용)."""
        if isinstance(job_id, dict):
            job_id = job_id.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")
        try:
            from gurunote.history import get_job_markdown, update_job_markdown  # noqa: PLC0415
            from gurunote.llm import (  # noqa: PLC0415
                _load_canonical_names,
                refresh_canonical_in_markdown,
            )
            md = get_job_markdown(job_id)
            if md is None:
                return self._err("HISTORY_NOT_FOUND", f"no result.md for job {job_id}")
            new_md, changed = refresh_canonical_in_markdown(md, _load_canonical_names())
            if changed and new_md != md:
                update_job_markdown(job_id, new_md)
            return {"ok": True, "changed": changed, "markdown": new_md}
        except Exception as exc:  # noqa: BLE001
            return self._err("CANONICAL_REFRESH_FAILED", f"{type(exc).__name__}: {exc}")

    def save_settings(self, patch: dict) -> dict:
        """Persist a partial settings patch via gurunote.settings.save_settings.

        Behaviors:

        - Only keys in ``_KNOWN_SETTINGS`` are accepted; unknown keys
          short-circuit with ``UNKNOWN_KEYS`` so the JS surface cannot
          mutate arbitrary env vars.
        - Empty-string values trigger the explicit-delete path in
          ``gurunote.settings.save_settings`` (``os.environ.pop`` plus a
          ``KEY=""`` line in ``.env``). JSON ``null`` is coerced to the
          same empty string so a UI sending ``{KEY: null}`` deletes too.
          Unspecified keys are untouched.
        - All values are coerced to ``str`` so JS numbers (e.g.
          ``LLM_TEMPERATURE``) round-trip correctly.

        Response::

            { "ok": True, "changed": int, "backup": str | null }
        """
        from gurunote.settings import save_settings as _save_settings  # noqa: PLC0415

        if not isinstance(patch, dict):
            return self._err(
                "INVALID_PATCH",
                f"patch must be dict, got {type(patch).__name__}",
            )
        unknown = sorted(k for k in patch if k not in _KNOWN_SETTINGS)
        if unknown:
            return self._err(
                "UNKNOWN_KEYS", f"unknown setting keys: {', '.join(unknown)}"
            )
        coerced: dict[str, str] = {
            k: ("" if v is None else str(v)) for k, v in patch.items()
        }
        try:
            changed, backup_path = _save_settings(coerced, create_backup=True)
            return {
                "ok": True,
                "changed": changed,
                "backup": str(backup_path) if backup_path else None,
            }
        except Exception as exc:  # noqa: BLE001
            return self._err(
                "SETTINGS_SAVE_FAILED", f"{type(exc).__name__}: {exc}"
            )

    def detect_hardware(self, payload: Any = None) -> dict:
        """Detect platform / GPU and recommend an STT engine.

        Phase 2B-4c-1: Settings screen "STT 엔진" section uses this to render
        the auto-detect banner ("MLX Whisper 자동 선택됨 — Apple Silicon …").

        Returns a flat dict with platform/cpu_arch/is_apple_silicon, memory_gb,
        gpu={available,type,name}, recommended_stt ∈ {mlx, whisperx, cpu},
        and a human-readable ``banner`` for direct UI rendering. Failures
        degrade gracefully to memory_gb=0.0 / gpu={available:False} rather
        than raising — the UI is informational, not load-bearing.
        """
        import os  # noqa: PLC0415
        import platform as _platform  # noqa: PLC0415

        system = _platform.system().lower()
        machine = _platform.machine()
        is_apple_silicon = system == "darwin" and machine in ("arm64", "aarch64")

        memory_gb = 0.0
        try:
            import psutil  # noqa: PLC0415
            memory_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except ImportError:
            if system == "darwin":
                try:
                    import subprocess  # noqa: PLC0415
                    result = subprocess.run(
                        ["sysctl", "-n", "hw.memsize"],
                        capture_output=True, text=True, check=True, timeout=2,
                    )
                    memory_gb = round(int(result.stdout.strip()) / (1024 ** 3), 1)
                except Exception:  # noqa: BLE001
                    pass

        # Phase 2B-6a: chip brand string for sidebar footer (e.g. "Apple M4 Max").
        # macOS 만 정확한 brand 제공; 다른 OS / 실패 시 machine 값으로 폴백.
        cpu_brand_string = machine
        if system == "darwin":
            try:
                import subprocess  # noqa: PLC0415
                br = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, check=True, timeout=2,
                )
                if br.stdout.strip():
                    cpu_brand_string = br.stdout.strip()
            except Exception:  # noqa: BLE001
                pass

        gpu_info: dict = {"available": False, "type": "none", "name": "-"}
        if is_apple_silicon:
            gpu_info = {
                "available": True,
                "type": "metal_mps",
                "name": "Apple Silicon GPU (Metal/MPS)",
            }
        else:
            try:
                import subprocess  # noqa: PLC0415
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    gpu_info = {
                        "available": True,
                        "type": "cuda",
                        "name": result.stdout.strip().split("\n")[0],
                    }
            except Exception:  # noqa: BLE001
                pass

        if is_apple_silicon:
            recommended = "mlx"
            banner = (
                f"MLX Whisper 자동 선택됨 — Apple Silicon ({machine}) 감지 · "
                f"Metal/MPS GPU 가속 · {memory_gb}GB Unified Memory"
            )
        elif gpu_info["type"] == "cuda":
            recommended = "whisperx"
            banner = (
                f"WhisperX 자동 선택됨 — {gpu_info['name']} 감지 · "
                f"CUDA 가속 · {memory_gb}GB RAM"
            )
        else:
            recommended = "cpu"
            banner = (
                f"CPU STT 사용 — GPU 미감지 · {memory_gb}GB RAM "
                "(성능 제한적)"
            )

        return {
            "ok": True,
            "platform": system,
            "cpu_arch": machine,
            "cpu_brand_string": cpu_brand_string,
            "is_apple_silicon": is_apple_silicon,
            "memory_gb": memory_gb,
            "gpu": gpu_info,
            "recommended_stt": recommended,
            "banner": banner,
        }

    def detect_obsidian_vault(self, payload: Any = None) -> dict:
        """Auto-detect an Obsidian Vault from common macOS locations.

        Phase 2B-4c-2: Settings screen "Obsidian Vault" section uses this for
        the auto-detect banner ("Vault 감지됨 — /path/to/Vault").

        Detection priority:
          1. ``OBSIDIAN_VAULT_PATH`` env var (if it points to a valid Vault)
          2. ``~/Library/Mobile Documents/iCloud~md~obsidian/Documents/*``
             (iCloud-synced Obsidian)
          3. ``~/Documents/Obsidian/*``
          4. ``~/Obsidian/*``

        A folder counts as a valid Vault iff it contains a ``.obsidian/``
        subdirectory. Returns the first valid hit as ``path`` plus a
        ``candidates`` list of all auto-discovered Vaults.
        """
        import os  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        home = Path.home()
        candidates_dirs = [
            home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
            home / "Documents" / "Obsidian",
            home / "Obsidian",
        ]

        found_vaults: list[str] = []
        for parent in candidates_dirs:
            if not parent.exists():
                continue
            try:
                for child in parent.iterdir():
                    if child.is_dir() and (child / ".obsidian").exists():
                        found_vaults.append(str(child))
            except (OSError, PermissionError):
                continue

        env_path = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        if env_path:
            env_path_obj = Path(env_path).expanduser()
            if env_path_obj.exists() and (env_path_obj / ".obsidian").exists():
                return {
                    "ok": True,
                    "detected": True,
                    "path": str(env_path_obj),
                    "source": "env",
                    "candidates": found_vaults,
                }

        if found_vaults:
            return {
                "ok": True,
                "detected": True,
                "path": found_vaults[0],
                "source": "auto_detected",
                "candidates": found_vaults,
            }

        return {
            "ok": True,
            "detected": False,
            "path": None,
            "source": None,
            "candidates": [],
        }

    def select_obsidian_vault_dir(self, payload: Any = None) -> dict:
        """Open a native folder dialog and return the selected Vault path.

        Phase 2B-4c-2: Settings screen "Obsidian Vault → 찾아보기" button.
        Validates that the selected folder contains ``.obsidian/`` and
        surfaces the result via ``valid_vault``; persisting the path to
        env / ``.env`` is the front-end's job (via ``save_settings``).

        Returns:
            ``{ok: True, path: str, valid_vault: bool}`` on selection,
            ``{ok: False, cancelled: True}`` if the user dismisses the dialog,
            ``{ok: False, error, code}`` on dialog failure.
        """
        import webview  # noqa: PLC0415

        window = self._require_window()
        try:
            result = window.create_file_dialog(
                webview.FOLDER_DIALOG,
                allow_multiple=False,
            )
        except Exception as exc:  # noqa: BLE001 — native dialog errors are opaque
            return self._err("DIALOG_FAILED", f"{type(exc).__name__}: {exc}")

        if not result:
            return {"ok": False, "cancelled": True}

        selected = result[0] if isinstance(result, (list, tuple)) else result
        if not selected:
            return {"ok": False, "cancelled": True}

        path_obj = Path(selected)
        valid_vault = (path_obj / ".obsidian").exists()
        return {
            "ok": True,
            "path": str(path_obj),
            "valid_vault": valid_vault,
        }

    def test_connection(
        self,
        payload: Any = None,
        *,
        provider: Optional[str] = None,
    ) -> dict:
        """Probe the given LLM provider with a minimal API call.

        Phase 2B-4c-1: Settings screen "연결 테스트" button. Issues a 1-token
        ping against the configured endpoint and surfaces ``latency_ms`` +
        the model name on success, or the underlying exception name + message
        on failure. Errors are returned as ``{ok: False, …}`` rather than
        raised so the front-end can switch on shape.

        Provider routing — env var sources:
          - openai / openai_compatible: OPENAI_API_KEY (+ OPENAI_BASE_URL),
            OPENAI_MODEL or LLM_MODEL (default ``gpt-4o-mini``)
          - anthropic: ANTHROPIC_API_KEY, ANTHROPIC_MODEL
          - gemini: GOOGLE_API_KEY or GEMINI_API_KEY, GEMINI_MODEL

        Accepts JS object payload (``{provider}``), positional string
        (``test_connection('openai')``), and Python kwarg form.
        """
        import os  # noqa: PLC0415
        import time  # noqa: PLC0415

        if isinstance(payload, dict):
            provider = payload.get("provider", provider)
        elif isinstance(payload, str):
            provider = payload

        if not provider:
            provider = os.environ.get("LLM_PROVIDER", "openai_compatible")

        start = time.time()

        try:
            if provider in ("openai", "openai_compatible"):
                api_key = os.environ.get("OPENAI_API_KEY")
                base_url = (
                    os.environ.get("OPENAI_BASE_URL")
                    or os.environ.get("LLM_BASE_URL")
                )
                model = (
                    os.environ.get("OPENAI_MODEL")
                    or os.environ.get("LLM_MODEL")
                    or "gpt-4o-mini"
                )
                if not api_key:
                    return self._err(
                        "NO_API_KEY",
                        "OPENAI_API_KEY 가 설정되지 않았습니다.",
                    )
                from openai import OpenAI  # noqa: PLC0415
                client = (
                    OpenAI(api_key=api_key, base_url=base_url)
                    if base_url
                    else OpenAI(api_key=api_key)
                )
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    timeout=10.0,
                )
                latency_ms = int((time.time() - start) * 1000)
                return {
                    "ok": True,
                    "provider": provider,
                    "model": model,
                    "latency_ms": latency_ms,
                    "message": f"연결 성공 · {model} · {latency_ms}ms",
                }

            if provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                model = os.environ.get(
                    "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
                )
                if not api_key:
                    return self._err(
                        "NO_API_KEY",
                        "ANTHROPIC_API_KEY 가 설정되지 않았습니다.",
                    )
                from anthropic import Anthropic  # noqa: PLC0415
                client = Anthropic(api_key=api_key)
                client.messages.create(
                    model=model,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}],
                    timeout=10.0,
                )
                latency_ms = int((time.time() - start) * 1000)
                return {
                    "ok": True,
                    "provider": provider,
                    "model": model,
                    "latency_ms": latency_ms,
                    "message": f"연결 성공 · {model} · {latency_ms}ms",
                }

            if provider == "gemini":
                api_key = (
                    os.environ.get("GOOGLE_API_KEY")
                    or os.environ.get("GEMINI_API_KEY")
                )
                model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
                if not api_key:
                    return self._err(
                        "NO_API_KEY",
                        "GOOGLE_API_KEY 또는 GEMINI_API_KEY 가 설정되지 않았습니다.",
                    )
                import google.generativeai as genai  # noqa: PLC0415
                genai.configure(api_key=api_key)
                m = genai.GenerativeModel(model)
                m.generate_content(
                    "ping",
                    generation_config={"max_output_tokens": 1},
                )
                latency_ms = int((time.time() - start) * 1000)
                return {
                    "ok": True,
                    "provider": provider,
                    "model": model,
                    "latency_ms": latency_ms,
                    "message": f"연결 성공 · {model} · {latency_ms}ms",
                }

            return self._err(
                "UNKNOWN_PROVIDER", f"알 수 없는 provider: {provider}"
            )

        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start) * 1000)
            error_type = type(exc).__name__
            return {
                "ok": False,
                "provider": provider,
                "error": str(exc),
                "code": error_type,
                "latency_ms": latency_ms,
                "message": f"{error_type}: {str(exc)[:120]}",
            }

    # ============================================================ history (TODO)

    def list_history(self, payload: Any = None, *, limit: Optional[int] = None, offset: int = 0) -> dict:
        """Return a slice of the history index.

        Backed by ``gurunote.history.load_index`` — the same store that the
        legacy CTk/Streamlit UIs read. WebView pipeline runs land here too
        because ``gui.PipelineWorker`` already calls ``save_job`` on
        completion (success and failure paths).

        Phase 2B-3: each item is enriched with ``video_id`` + ``thumbnail_url``
        so the React JobCard can render thumbnails without round-tripping
        again. Resolution priority: cached ``~/.gurunote/thumbnails/`` →
        YouTube hqdefault → ``None`` (front-end gradient fallback).

        Calling conventions (pywebview 4.x JS bridge marshals JS args
        positionally, so a JS object becomes a single positional dict):

          - JS:     ``api.list_history({limit: 100, offset: 0})``
          - JS:     ``api.list_history()``
          - Python: ``api.list_history(limit=100)``  (kwarg form preserved)
        """
        from gurunote.history import load_index  # noqa: PLC0415

        # Normalize JS-style ``{limit, offset}`` payload, while preserving the
        # original keyword-only form that Python callers may use.
        if isinstance(payload, dict):
            limit = payload.get("limit", limit)
            offset = payload.get("offset", offset)
        elif isinstance(payload, int):
            # Legacy positional ``api.list_history(100)``.
            limit = payload
        # Type guards — protect against malformed JS values reaching slice().
        if not isinstance(offset, int):
            offset = 0
        if limit is not None and not isinstance(limit, int):
            limit = None

        try:
            items = load_index()
            total = len(items)
            if offset:
                items = items[offset:]
            if limit is not None:
                items = items[:limit]
            for item in items:
                video_id = _extract_youtube_video_id(item.get("source_url"))
                item["video_id"] = video_id
                item["thumbnail_url"] = _resolve_thumbnail_url(video_id)
            return {"ok": True, "total": total, "items": items}
        except Exception as exc:  # noqa: BLE001
            return self._err("HISTORY_LIST_FAILED", f"{type(exc).__name__}: {exc}")

    def get_history_detail(self, payload: Any = None, *, job_id: Optional[str] = None) -> dict:
        """Return ``{markdown, full_html, meta, filename}`` for one job.

        ``full_html`` is server-side rendered with the same markdown
        extensions used by the live pipeline so the front-end's existing
        ``renderResult()`` can consume it without branching.

        pywebview JS bridge marshals JS objects as a single positional dict —
        accepts ``api.get_history_detail({job_id})`` and ``api.get_history_detail(job_id)``.
        """
        import markdown as _markdown  # noqa: PLC0415
        from gurunote.history import get_job_markdown, load_index  # noqa: PLC0415

        # Normalize payload (dict / str positional / kwarg).
        if isinstance(payload, dict):
            job_id = payload.get("job_id", job_id)
        elif isinstance(payload, str):
            job_id = payload

        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")

        try:
            md = get_job_markdown(job_id)
            if md is None:
                return self._err("HISTORY_NOT_FOUND", f"no result.md for job {job_id}")
            meta = next(
                (e for e in load_index() if e.get("job_id") == job_id),
                {},
            )
            # Phase 2B-6b: meta 에 thumbnail enrichment (list_history 와 동일 패턴).
            # EditorScreen 의 Preview 영역 위 썸네일 표시에 필요.
            if meta:
                video_id = _extract_youtube_video_id(meta.get("source_url"))
                meta["video_id"] = video_id
                meta["thumbnail_url"] = _resolve_thumbnail_url(video_id)
            full_html = _markdown.markdown(
                md, extensions=["fenced_code", "tables", "toc"]
            )
            # Phase 2B-3-backend Layer 7: 한국어/원문/요약 섹션 parse → ResultPanel tab.
            korean_transcript, english_transcript = _parse_transcripts(md)
            summary_text = _parse_summary(md)
            summary_html = _markdown.markdown(
                summary_text, extensions=["fenced_code", "tables"]
            ) if summary_text else ""
            return {
                "ok": True,
                "job_id": job_id,
                "markdown": md,
                "full_html": full_html,
                "meta": meta,
                "filename": "result.md",
                "korean_transcript": korean_transcript,
                "english_transcript": english_transcript,
                "summary_html": summary_html,
            }
        except Exception as exc:  # noqa: BLE001
            return self._err("READ_FAILED", f"{type(exc).__name__}: {exc}")

    def get_history_log(self, payload: Any = None, *, job_id: Optional[str] = None) -> dict:
        """Return ``pipeline.log`` content for a saved job — Phase 2B-3-backend Layer 7.

        Backend ``gurunote.history.get_job_log`` wrap. ResultPanel 의 'log' tab
        에서 사용 (DetailPanel + EditorScreen 영역). 노트가 cleanup 됐거나 log 가
        없는 경우 (legacy / 실패 노트) ``{ok: True, log: ""}`` graceful 반환.
        """
        # Normalize payload (dict / str positional / kwarg).
        if isinstance(payload, dict):
            job_id = payload.get("job_id", job_id)
        elif isinstance(payload, str):
            job_id = payload

        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")
        try:
            from gurunote.history import get_job_log  # noqa: PLC0415
            log_content = get_job_log(job_id) or ""
            return {"ok": True, "job_id": job_id, "log": log_content}
        except Exception as exc:  # noqa: BLE001
            return self._err("LOG_READ_FAILED", f"{type(exc).__name__}: {exc}")

    def delete_history(self, job_id: str) -> dict:
        """Delete a single note — Phase 2B-3-backend Step 3b-2 wiring.

        ``gurunote.history.delete_job`` 호출 — ``~/.gurunote/jobs/<job_id>/`` 디렉토리
        통째 삭제 + ``history.json`` 의 entry 제거 (원자적 write). Autosave
        (``~/GuruNote/autosave/``) 의 markdown 은 의도적 보존 (backup 영역).
        """
        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")
        try:
            from gurunote.history import delete_job  # noqa: PLC0415
            delete_job(job_id)
        except Exception as exc:  # noqa: BLE001
            return self._err("DELETE_FAILED", f"{type(exc).__name__}: {exc}")

        # best-effort: Obsidian vault 사본 삭제 (gurunote_job_id 표식 매칭).
        # 라이브러리 삭제는 이미 성공 — vault 삭제 실패는 막지 않고 결과에만 기록.
        result = {"ok": True, "job_id": job_id, "vault_deleted": 0}
        try:
            from gurunote.obsidian import delete_from_vault  # noqa: PLC0415
            result["vault_deleted"] = len(delete_from_vault(job_id))
        except Exception as exc:  # noqa: BLE001
            result["vault_error"] = f"{type(exc).__name__}: {exc}"
        return result

    def has_vault_copy(self, job_id: Any = None) -> dict:
        """삭제 확인 다이얼로그용 — vault 에 이 job 의 표식 사본이 있는지.

        ``{ok, has_copy: bool, count: int}``. 확인 실패 시 has_copy=False (안내만 생략).
        """
        if isinstance(job_id, dict):
            job_id = job_id.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return {"ok": True, "has_copy": False, "count": 0}
        try:
            from gurunote.obsidian import find_vault_copies  # noqa: PLC0415
            n = len(find_vault_copies(job_id))
        except Exception:  # noqa: BLE001
            n = 0
        return {"ok": True, "has_copy": n > 0, "count": n}

    # ----- semantic search (의미 검색 / RAG) — gurunote.semantic 재사용 ------
    # semantic.py 는 sentence-transformers 임베딩 + 코사인 유사도로 이미 완성돼
    # 있다 (옛 gui.py/app.py 에서 동작). 여기서는 호출만 — 로직 변경 없음.
    # 선택 의존성 (requirements-search.txt) 미설치 시 is_available() False.

    def semantic_available(self) -> dict:
        """의미 검색 의존성 설치 여부 + 인덱스 빌드 여부. Dashboard 카드용."""
        from gurunote import semantic  # noqa: PLC0415
        return {
            "ok": True,
            "available": semantic.is_available(),
            "built": semantic.is_index_built(),
            "hint": semantic.missing_packages_hint(),
        }

    def semantic_index_stats(self) -> dict:
        """현재 인덱스 요약 (모델 / chunk 수 / 작업 수 / 빌드 시각)."""
        from gurunote import semantic  # noqa: PLC0415
        stats = semantic.index_stats()  # {"built": False} 또는 {"built": True, ...}
        return {"ok": True, "available": semantic.is_available(), **stats}

    def rebuild_index(self) -> dict:
        """저장된 전체 작업으로 의미 검색 인덱스를 (재)빌드한다.

        블로킹 호출 — pywebview 가 JS→Python 호출을 워커 스레드에 dispatch 하므로
        모델이 임베딩하는 동안 UI 는 멈추지 않는다 (save_result_as 와 동일 패턴).
        첫 실행 시 임베딩 모델 (~117MB) 을 다운로드한다. 빌드 요약 + 갱신된
        통계를 반환.
        """
        from gurunote import semantic  # noqa: PLC0415
        from gurunote.history import load_index  # noqa: PLC0415
        if not semantic.is_available():
            return self._err("SEMANTIC_UNAVAILABLE", semantic.missing_packages_hint())
        try:
            jobs = load_index()
            result = semantic.build_index(jobs)
        except RuntimeError as exc:
            return self._err("REBUILD_FAILED", str(exc))
        except Exception as exc:  # noqa: BLE001 — encode/IO 오류 정규화
            return self._err("REBUILD_FAILED", f"{type(exc).__name__}: {exc}")
        return {"ok": True, **result, "stats": semantic.index_stats()}

    def semantic_search(self, payload: Any = None, *, query: Optional[str] = None,
                        job_id: Optional[str] = None, top_k: int = 10) -> dict:
        """의미 유사도 검색. 두 진입점:

          - "의미 검색" 칩: ``api.semantic_search({query})`` — 자유 텍스트 쿼리.
          - "연관 노트" 버튼: ``api.semantic_search({job_id})`` — 해당 노트 본문을
            쿼리로 쓰고 자기 자신은 결과에서 제외.
        """
        from gurunote import semantic  # noqa: PLC0415
        if isinstance(payload, dict):
            query = payload.get("query", query)
            job_id = payload.get("job_id", job_id)
            top_k = payload.get("top_k", top_k)
        elif isinstance(payload, str):
            query = payload

        if not semantic.is_available():
            return self._err("SEMANTIC_UNAVAILABLE", semantic.missing_packages_hint())
        if not semantic.is_index_built():
            return self._err(
                "INDEX_NOT_BUILT",
                "의미 검색 인덱스가 없습니다. 대시보드에서 'Semantic Rebuild' 를 먼저 실행하세요.",
            )

        # 연관 노트: 노트 본문을 쿼리로 사용.
        if job_id and not query:
            from gurunote.history import get_job_markdown  # noqa: PLC0415
            md = get_job_markdown(job_id)
            if not md:
                return self._err("HISTORY_NOT_FOUND", f"no result.md for job {job_id}")
            query = md
        if not isinstance(query, str) or not query.strip():
            return self._err("INVALID_QUERY", "query must be a non-empty string")

        try:
            k = int(top_k) + (1 if job_id else 0)  # 자기 제외 보정
            results = semantic.search(query, top_k=k)
        except RuntimeError as exc:
            return self._err("SEARCH_FAILED", str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._err("SEARCH_FAILED", f"{type(exc).__name__}: {exc}")
        if job_id:
            results = [r for r in results if r.get("job_id") != job_id][: int(top_k)]
        return {"ok": True, "results": results}

    # ============================================================ note edit (TODO)

    def update_note(self, payload: Any = None, *, job_id: Optional[str] = None, markdown: Optional[str] = None) -> dict:
        """Persist edited markdown back to ``~/.gurunote/jobs/<job_id>/result.md``.

        pywebview JS bridge marshals JS objects as a single positional dict.
        Accepts ``api.update_note({job_id, markdown})`` (JS) and
        ``api.update_note(job_id, markdown)`` (Python positional).

        Returns ``{ok: True, path: str}`` or ``{ok: False, error, code}``.
        """
        # Normalize payload shapes.
        if isinstance(payload, dict):
            job_id = payload.get("job_id", job_id)
            markdown = payload.get("markdown", markdown)
        elif isinstance(payload, str) and not isinstance(markdown, str):
            # Python positional: update_note(job_id, markdown)
            # If only one str passed, treat as job_id (markdown must be set via kwarg).
            job_id = payload

        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")
        if not isinstance(markdown, str):
            return self._err("INVALID_MARKDOWN", "markdown must be a string")

        try:
            from gurunote.history import JOBS_DIR, update_meta  # noqa: PLC0415
            job_dir = JOBS_DIR / job_id
            if not job_dir.exists():
                return self._err("HISTORY_NOT_FOUND", f"no job dir for {job_id}")
            result_path = job_dir / "result.md"
            result_path.write_text(markdown, encoding="utf-8")
            # Phase 2B-3-backend Step 3b-3: frontmatter SSOT — result.md 저장 후
            # YAML frontmatter 영역 parse → history.json 의 entry 영역 sync.
            # 사용자가 frontmatter title: 수정 + ⌘S 시 라이브러리 카드 + EditorScreen
            # 헤더 영역 자동 갱신 (옛 title 잔재 부재).
            #
            # Mapping (frontmatter 의 키 ↔ history.json 의 키):
            #   - frontmatter "title"          → history "organized_title" (display)
            #   - frontmatter "original_title" → history "title" (yt-dlp raw)
            #   - frontmatter "field"          → history "field" (직접)
            #   - frontmatter "tags"           → history "tags" (직접)
            #   - frontmatter "uploader"       → history "uploader" (직접)
            #   - 기타 (source_url, upload_date, duration_sec 등) — 사용자 변경 영역 부재 → skip
            fm = _parse_frontmatter(markdown)
            patch: dict = {}
            if "title" in fm:
                patch["organized_title"] = fm["title"]
            if "original_title" in fm:
                patch["title"] = fm["original_title"]
            for key in ("field", "tags", "uploader"):
                if key in fm:
                    patch[key] = fm[key]
            if patch:
                update_meta(job_id, patch)
            return {"ok": True, "path": str(result_path)}
        except OSError as exc:
            return self._err("WRITE_FAILED", f"{type(exc).__name__}: {exc}")

    # ============================================================ exporters

    def save_result_as(self, payload: Any = None, default_filename: Any = None, *,
                       markdown: Optional[str] = None) -> dict:
        """Open native Save dialog and write ``markdown`` to the chosen path.

        Used by the result card's "저장" button and ⌘S shortcut. The caller
        passes the markdown currently rendered in the UI (``result.full_md``)
        plus a suggested filename (autosave basename, or ``GuruNote_<title>.md``
        as fallback).

        pywebview JS bridge marshals JS objects as a single positional dict.
        Accepts:
          - JS object: ``api.save_result_as({markdown, default_filename})``
          - JS positional: ``api.save_result_as(markdown_str, default_filename_str)``
          - Python kwargs: ``api.save_result_as(markdown=..., default_filename=...)``

        Returns:
            ``{"path": str, "cancelled": False}`` on success,
            ``{"cancelled": True}`` if the user dismissed the dialog,
            ``{"ok": False, "error": str, "code": "SAVE_FAILED"}`` on I/O error.

        The default directory is ``~/Documents`` (intentionally distinct from
        the autosave folder so user-initiated saves land somewhere the user
        actively chose, not alongside the auto-captured copies).
        """
        import webview  # noqa: PLC0415

        # Normalize payload shapes.
        if isinstance(payload, dict):
            markdown = payload.get("markdown", markdown)
            default_filename = payload.get("default_filename", default_filename)
        elif isinstance(payload, str):
            # Legacy positional: save_result_as(markdown, default_filename)
            markdown = payload

        if not isinstance(markdown, str):
            return self._err("SAVE_FAILED", f"markdown must be str, got {type(markdown).__name__}")
        if not isinstance(default_filename, str) or not default_filename.strip():
            default_filename = "GuruNote.md"

        window = self._require_window()
        default_dir = str(Path.home() / "Documents")
        try:
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=default_dir,
                save_filename=default_filename,
                file_types=("Markdown (*.md)", "All files (*.*)"),
            )
        except Exception as exc:  # noqa: BLE001 — native dialog errors are opaque; normalize
            return self._err("SAVE_FAILED", f"dialog: {type(exc).__name__}: {exc}")
        # pywebview SAVE_DIALOG: returns a string path, a tuple/list with one
        # path, or a falsy value on cancel. Normalize.
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not path:
            return {"cancelled": True}

        try:
            Path(path).write_text(markdown, encoding="utf-8")
        except OSError as exc:
            return self._err("SAVE_FAILED", f"{type(exc).__name__}: {exc}")
        return {"path": str(path), "cancelled": False}

    # ============================================================ exporters (TODO)

    def save_markdown(self, job_id: str, target_path: Optional[str] = None) -> dict:
        raise NotImplementedError("save_markdown: wired in Phase 2-B")

    def save_pdf(self, job_id: str, target_path: Optional[str] = None) -> dict:
        raise NotImplementedError("save_pdf: wired in Phase 2-B")

    def send_obsidian(self, job_id: Any = None, skip_if_exists: Any = False) -> dict:
        """저장된 노트를 Obsidian vault 로 내보낸다 (RAG 유사 노트 wikilink 포함).

        흐름: result.md 로드 → 의미 검색(설치+인덱스 시)으로 유사 노트 top5(≥0.5)
        → ``## 연관 노트`` 섹션 + frontmatter ``related`` wikilink 삽입
        → ``obsidian.save_to_vault`` (OBSIDIAN_VAULT_PATH). obsidian.py / semantic.py
        로직은 호출만 — 변경 없음. vault 사본만 수정, 저장된 result.md 는 불변.

        Vault 미설정 시 ``code=NO_VAULT`` 로 안내 (Settings → Obsidian 으로 유도).
        RAG 미설치/인덱스 없음/유사 노트 없음이면 연관 노트 없이 그대로 내보낸다.
        """
        from gurunote import obsidian, semantic  # noqa: PLC0415
        from gurunote.history import get_job_markdown, load_index  # noqa: PLC0415

        if isinstance(job_id, dict):
            skip_if_exists = job_id.get("skip_if_exists", skip_if_exists)
            job_id = job_id.get("job_id")
        skip_if_exists = bool(skip_if_exists)
        if not isinstance(job_id, str) or not job_id:
            return self._err("INVALID_ID", "job_id must be a non-empty string")
        if "/" in job_id or "\\" in job_id or ".." in job_id:
            return self._err("INVALID_ID", "job_id contains path separators")

        md = get_job_markdown(job_id)
        if md is None:
            return self._err("HISTORY_NOT_FOUND", f"no result.md for job {job_id}")

        # 자동 내보내기(skip_if_exists)에서만: 같은 job_id 표식 노트가 vault 에 이미
        #   있으면 건너뛴다. 같은 영상 재처리 시 vault 사본 누적을 막는다. 수동 버튼은
        #   플래그를 보내지 않아 항상 새로 저장. find_vault_copies 는 읽기 전용이며
        #   vault 미설정 시 빈 목록 → 건너뛰지 않고 아래 NO_VAULT 흐름으로 이어진다.
        if skip_if_exists:
            existing = obsidian.find_vault_copies(job_id)
            if existing:
                return {
                    "ok": True,
                    "skipped": True,
                    "path": str(existing[0]),
                    "related_count": 0,
                }

        meta = next((e for e in load_index() if e.get("job_id") == job_id), {})
        title = meta.get("organized_title") or meta.get("title") or job_id

        # RAG 유사 노트 (best-effort — 실패해도 내보내기는 진행).
        related: list = []
        if semantic.is_available() and semantic.is_index_built():
            try:
                hits = semantic.search(md, top_k=6, min_score=0.5)
                related = [h for h in hits if h.get("job_id") != job_id][:5]
            except Exception:  # noqa: BLE001 — 검색 실패는 내보내기를 막지 않음
                related = []

        md_out = _inject_related_notes(md, related)
        # 라이브러리 삭제 시 vault 사본 동기화용 표식 (vault 사본에만, result.md 불변).
        md_out = _inject_frontmatter_field(md_out, "gurunote_job_id", job_id)

        # Vault 경로 확인 (미설정 → 안내).
        vault = obsidian.resolve_vault_path()
        if vault is None:
            return self._err(
                "NO_VAULT",
                "Obsidian Vault 경로가 설정되지 않았습니다. 설정 → Obsidian 에서 지정하세요.",
            )

        try:
            out = obsidian.save_to_vault(
                md_out, filename=f"{_obsidian_note_stem(title)}.md",
            )
        except (RuntimeError, ValueError) as exc:
            return self._err("OBSIDIAN_FAILED", str(exc))
        except OSError as exc:
            return self._err("OBSIDIAN_FAILED", f"{type(exc).__name__}: {exc}")
        return {
            "ok": True,
            "path": str(out),
            "vault": str(vault),
            "related_count": len(related),
        }

    def send_notion(self, job_id: str) -> dict:
        """Long-running → returns job_id; result via ``notion_progress`` event."""
        raise NotImplementedError("send_notion: wired in Phase 2-B")

    # ============================================================ updater (TODO)

    def check_update(self) -> dict:
        raise NotImplementedError("check_update: wired in Phase 4-B")

    # ============================================================ misc

    def open_external(self, url: Any = None) -> dict:
        """Open ``url`` in the user's default system browser (not in-app).

        pywebview renders links inside the app webview by default, which would
        replace the GuruNote UI. The History detail "출처" link calls this so
        the source video opens in the real browser instead.

        Accepts ``api.open_external("https://…")`` and ``api.open_external({url})``
        (pywebview marshals a JS object as a single positional dict). Only
        ``http``/``https`` URLs are honored — other schemes (``file:``,
        ``javascript:``, …) are rejected to avoid local-path / scheme injection.
        """
        import webbrowser  # noqa: PLC0415

        if isinstance(url, dict):
            url = url.get("url")
        if not isinstance(url, str) or not url.strip():
            return self._err("INVALID_URL", "url must be a non-empty string")
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return self._err("INVALID_URL", "only http(s) URLs are allowed")
        try:
            opened = webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001 — browser launch errors are opaque
            return self._err("OPEN_FAILED", f"{type(exc).__name__}: {exc}")
        if not opened:
            return self._err("OPEN_FAILED", "no browser available")
        return {"ok": True, "url": url}

    def show_message(self, title: str, body: str, kind: str = "info") -> dict:
        """Show a simple modal. ``kind`` ∈ {info, warning, error}.

        Phase 1 MVP: routed to JS-side ``alert()`` (no native chrome).
        Phase 2+: proper styled modal in HTML.
        """
        raise NotImplementedError("show_message: wired in Phase 2")

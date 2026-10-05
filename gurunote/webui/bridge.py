"""GuruNote WebView UI — JavaScript Bridge (pywebview js_api).

프런트엔드는 `window.pywebview.api.<method>(...)` 로 부르고 pywebview 가 인자와
반환값을 JSON 으로 옮긴다.

동작 자체는 대부분 `gurunote/service.py` 의 `GuruNoteService` 에 있다. 여기에는 창이
있어야만 되는 것만 남긴다 — window 배선, 파일/폴더 선택 대화상자, 그리고 진행 이벤트를
webview 로 흘려보내는 파이프라인 시작. 나머지는 상속으로 그대로 노출되므로 JS 쪽에서
보이는 메서드 목록은 달라지지 않는다.

반환 형태: 성공은 값이 담긴 dict, 실패는 `{ok: False, error, code}`.
전체 메서드 목록은 `docs/webview-ui/ARCHITECTURE.md` § 3 참고.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import threading
import json

from gurunote.service import GuruNoteService


class Api(GuruNoteService):
    """pywebview 에 넘기는 bridge 객체. 창이 필요한 것만 여기 있다."""

    def __init__(self) -> None:
        self._window = None  # set via bind_window()
        self._serial_queue = None
        self._queue_lock = threading.Lock()

    @property
    def _queue(self):
        with self._queue_lock:
            if self._serial_queue is None:
                from gurunote.webui.session import PipelineSession
                from gurunote.webui.work_queue import PipelineQueue
                def emit(snapshot):
                    self._require_window().evaluate_js(
                        'window.__emit("queue_changed", ' + json.dumps(snapshot, ensure_ascii=False) + ');')
                self._serial_queue = PipelineQueue(
                    lambda source, done, observed: PipelineSession(
                        self._require_window(), source, on_terminal=done, on_event=observed), emit)
            return self._serial_queue

    def _validate_batch_source(self, source):
        if not isinstance(source, dict):
            raise ValueError("source must be a dict")
        for key in ("kind", "value", "engine", "provider"):
            if key not in source:
                raise ValueError("source missing required key: " + key)
        value = source["value"]
        if not isinstance(value, str):
            raise ValueError("source.value must be text")
        value = value.strip()
        from gurunote.audio import is_probably_youtube_url, is_supported_local_file
        if source["kind"] == "youtube":
            if not is_probably_youtube_url(value):
                raise RuntimeError("INVALID_URL:유튜브 URL 형식이 아닙니다.")
        elif source["kind"] == "local":
            if not Path(value).is_file() or not is_supported_local_file(value):
                raise RuntimeError("INVALID_LOCAL_FILE:" + value)
        else:
            raise ValueError("source.kind must be youtube or local")
        import os
        key_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                   "gemini": "GOOGLE_API_KEY", "openai_compatible": "OPENAI_BASE_URL"}
        required = key_map.get(source["provider"])
        if required and not os.environ.get(required):
            raise RuntimeError("API_KEY_MISSING:" + required)
        result = {key: source[key] for key in ("kind", "engine", "provider")}
        result["value"] = value
        mode = source.get("diarization_backend")
        if mode is not None:
            if mode not in ("auto", "resemblyzer", "pyannote", "none"):
                raise ValueError("Invalid diarization backend")
            result["diarization_backend"] = mode
        return result

    def enqueue_pipeline_batch(self, sources):
        self._require_window()
        if not isinstance(sources, list) or len(sources) > 100:
            raise ValueError("sources must be a list with at most 100 entries")
        valid = []; errors = []
        for index, source in enumerate(sources):
            try:
                valid.append(self._validate_batch_source(source))
            except Exception as exc:
                errors.append({"index": index, "error": str(exc)})
        result = self._queue.enqueue(valid)
        result["errors"] = errors
        result["ok"] = bool(valid) or not errors
        return result

    def get_pipeline_queue(self):
        self._require_window()
        return self._queue.snapshot()

    def get_pipeline_queue_result(self, queue_id):
        return self._queue.get_result(queue_id)

    def cancel_pipeline_queue_item(self, queue_id):
        return {"ok": self._queue.cancel(queue_id), "queue": self._queue.snapshot()}

    def pause_pipeline_queue(self):
        return self._queue.pause()

    def resume_pipeline_queue(self):
        return self._queue.resume()

    def clear_finished_pipeline_queue(self):
        return {"removed": self._queue.clear_finished(), "queue": self._queue.snapshot()}

    def bind_window(self, window: Any) -> None:
        """Attach the pywebview Window so the bridge can call its methods."""
        self._window = window

    def _require_window(self) -> Any:
        if self._window is None:
            raise RuntimeError(
                "Api.bind_window() not called — bridge is not ready yet"
            )
        return self._window

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

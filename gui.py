"""
GuruNote 🎙️ — CustomTkinter 네이티브 데스크톱 GUI
====================================================

Streamlit 없이도 독립 실행 가능한 데스크톱 애플리케이션.
`gurunote.*` 패키지를 직접 호출하며, 파이프라인(Step 1~5)은
백그라운드 스레드에서 실행해 UI가 멈추지 않는다.

실행:
    python gui.py

패키징:
    pyinstaller --windowed --onefile gui.py
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional

# 네이티브 라이브러리(pyannote / weasyprint / mlx) 가 import 시점에 FD2 로
# 쏟는 경고가 Terminal 을 포그라운드로 끌어올리는 문제를 막기 위해, 무거운
# 모듈을 import 하기 **전에** stdout/stderr 을 로그 파일로 돌린다.
from gurunote.log_redirect import redirect_to_log as _redirect_to_log
_redirect_to_log()

import customtkinter as ctk
from dotenv import load_dotenv

from gurunote.audio import (
    SUPPORTED_EXTS,
    cleanup_dir,
    download_audio,
    extract_audio_from_file,
    is_probably_youtube_url,
    is_supported_local_file,
)
from gurunote.exporter import autosave_result, build_gurunote_markdown, sanitize_filename
from gurunote.llm import (
    LLMConfig, extract_metadata, summarize_translation,
    test_connection, translate_transcript,
)
from gurunote.progress_tee import install_tee
from gurunote.settings import save_settings
from gurunote.history import (
    JobLogger, delete_job, get_job_log, get_job_markdown,
    load_index, new_job_id, rebuild_index, save_job,
    update_job_markdown,
)
from gurunote.hardware import (
    AUTO_KEY, CUSTOM_KEY, PRESETS,
    detect_description, detect_recommended_preset,
    dropdown_options as hw_dropdown_options,
    key_to_label as hw_key_to_label,
    label_to_key as hw_label_to_key,
)
from gurunote.stt import install_whisperx, is_whisperx_installed, transcribe
from gurunote.stt_mlx import is_apple_silicon
from gurunote.thumbnails import (
    cached_thumbnail_path, download_thumbnail_async, extract_youtube_id,
)
from gurunote.pdf_export import is_pdf_export_available, markdown_to_pdf
from gurunote import pdf_installer
from gurunote.obsidian import (
    find_vault_candidates,
    is_obsidian_vault,
    resolve_subfolder as obsidian_subfolder,
    resolve_vault_path as obsidian_vault,
    save_to_vault as obsidian_save,
)
from gurunote.notion_sync import (
    is_notion_sync_available,
    missing_packages_hint as notion_missing_hint,
    save_to_notion as notion_save,
)
from gurunote.search import (
    clear_cache as search_clear_cache,
    match_body as search_match_body,
)
from gurunote.stats import compute_stats, render_report
from gurunote import semantic as semantic_search
from gurunote.nav_tree import FacetNode, compute_facets, default_expand_state
from gurunote.ui_state import (
    get_nav_expand, load_ui_state, save_ui_state, set_nav_expand,
)
from gurunote.types import _format_ts
from gurunote.updater import (
    GitAuthError,
    check_for_update,
    update_project,
)
from gurunote.app_icon import get_app_icon_path
from gurunote import ui_components as uc
from gurunote import ui_theme as ut

# 환경변수 로드
load_dotenv()


# =============================================================================
# 앱 아이콘 — 메인 윈도우 및 모든 Toplevel 다이얼로그에 적용
# =============================================================================
# Tk PhotoImage 는 같은 윈도우 계층에서 참조가 살아있어야 아이콘이 유지된다.
# Toplevel 이 destroy 되면 해당 PhotoImage 도 해제되지만, 공유 캐시로 하나만
# 유지하면 모든 창이 같은 이미지를 참조할 수 있다.
_ICON_PHOTO = None


def _apply_app_icon(window) -> None:
    """Tk / Toplevel 창에 GuruNote 아이콘 적용. 실패 시 silent no-op."""
    global _ICON_PHOTO
    try:
        path = get_app_icon_path()
        if path is None:
            return
        if _ICON_PHOTO is None:
            import tkinter as _tk
            _ICON_PHOTO = _tk.PhotoImage(file=str(path))
        window.iconphoto(False, _ICON_PHOTO)
    except Exception:  # noqa: BLE001
        pass

# =============================================================================
# 테마 & 상수
# =============================================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "GuruNote"
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 820

STT_OPTIONS = ["auto", "whisperx", "mlx", "assemblyai"]
LLM_OPTIONS = ["openai", "openai_compatible", "anthropic", "gemini"]

# ── 컬러 팔레트 — Material 3 다크 테마 기반 ──
# 톤 기준 (Material 3 reference palette, purple 톤):
#   - Surface 계층은 elevation 별로 점진적으로 밝아짐 (1dp → 12dp)
#   - Primary 는 Purple 40 tone, on_primary 는 Purple 20
#   - 강조 색은 "surface tint" 로 사용해 배경을 은은히 덮음
C_BG = "#141218"          # Material 3 surface (base)
C_SIDEBAR = "#1D1B20"     # Surface + 1dp elevation
C_SURFACE = "#211F26"     # Surface + 2dp (카드/다이얼로그)
C_SURFACE_HI = "#2B2930"  # Surface + 3dp (hover/강조 블록)
C_BORDER = "#49454F"      # Outline variant
# "Primary container" tone (Material 3 tone 30) — 채도 있는 진보라 배경 +
# 흰색 텍스트로 충분한 대비 확보. FAB 용 더 밝은 tone(`#D0BCFF`) 은 별도로
# 정의해 필요한 곳에만 쓴다.
C_PRIMARY = "#4F378B"     # Primary container (purple 30)
C_PRIMARY_HO = "#5D43A8"  # Hover 시 한 단계 밝게
C_PRIMARY_BRIGHT = "#D0BCFF"  # Primary (purple 80) — 아이콘/하이라이트 전용
C_ON_PRIMARY = "#FFFFFF"  # primary container 위 텍스트 색
C_ACCENT = "#CCC2DC"      # Secondary — 소프트 라벤더
C_TEXT = "#E6E0E9"        # On-surface
C_TEXT_DIM = "#938F99"    # On-surface-variant
C_SUCCESS = "#81C995"     # Google Material green 200
C_DANGER = "#F2B8B5"      # Material error container on-dark
STEP_LABELS = ["오디오", "STT", "번역", "요약", "조립"]


# =============================================================================
# 파이프라인 워커 (백그라운드 스레드)
# =============================================================================
class PipelineWorker:
    """
    GUI 스레드를 블로킹하지 않고 파이프라인을 실행한다.
    진행 메시지는 `msg_queue`로, 최종 결과/에러는 `result_queue`로 전달.
    """

    def __init__(
        self,
        engine: str,
        provider: str,
        *,
        youtube_url: str = "",
        local_file: str = "",
    ):
        self.youtube_url = youtube_url
        self.local_file = local_file
        self.engine = engine
        self.provider = provider
        self.job_id = new_job_id()
        self._job_logger = JobLogger(self.job_id)
        self._start_time: Optional[float] = None
        self.msg_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: queue.Queue[float] = queue.Queue()
        self.result_queue: queue.Queue[dict] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _log(self, msg: str) -> None:
        if self._stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")
        import time as _time
        ts = _time.strftime("%H:%M:%S")
        stamped = f"[{ts}] {msg}"
        self.msg_queue.put(stamped)
        self._job_logger.write(msg)

    def _set_progress(self, pct: float) -> None:
        self.progress_queue.put(max(0.0, min(1.0, pct)))

    def request_stop(self) -> None:
        self._stop_event.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import time as _time
        self._start_time = _time.monotonic()
        tmp_dir = tempfile.mkdtemp(prefix="gurunote_")
        # 파이프라인 실행 동안 stderr 를 tee 로 감싸 tqdm 진행률 (HF 모델 다운로드,
        # mlx-whisper / whisperx 전사) 을 GUI 로그 패널에 압축해서 전달.
        with install_tee(self._log):
            self._run_pipeline(tmp_dir)

    def _run_pipeline(self, tmp_dir: str) -> None:
        try:
            self._set_progress(0.02)
            # Step 1
            if self.youtube_url:
                self._log("[Step 1] 유튜브 오디오 추출 중...")
                audio = download_audio(self.youtube_url, tmp_dir)
            else:
                self._log("[Step 1] 로컬 파일에서 오디오 추출 중...")
                audio = extract_audio_from_file(self.local_file, tmp_dir)
            audio_size = os.path.getsize(audio.audio_path) / (1024 * 1024)
            self._log(
                f"[Step 1] OK: {audio.video_title} ({audio_size:.1f} MB, "
                f"{int(audio.duration_sec)}s)"
            )
            if audio.upload_date:
                self._log(f"  > 게시일: {audio.upload_date}")
            if audio.chapters:
                self._log(f"  > 공식 챕터 {len(audio.chapters)}개 감지")
            if audio.subtitles_text:
                self._log(
                    f"  > 기존 자막 감지 ({len(audio.subtitles_text):,} chars)"
                )
            video_ctx = audio.to_context_dict()
            self._set_progress(0.18)
            effective_engine = self.engine

            # Step 2 — 서브스텝 진행률 매핑
            # stt 모듈이 _log() 를 호출할 때 메시지 내용으로 서브 진행률 추정
            _stt_substeps = {
                "모델 로딩": 0.22,
                "전사 중": 0.30,
                "타임스탬프 정렬": 0.40,
                "화자 분리": 0.48,
                "AssemblyAI": 0.30,
            }
            def _stt_progress(msg: str) -> None:
                self._log(msg)
                for keyword, pct in _stt_substeps.items():
                    if keyword in msg:
                        self._set_progress(pct)
                        break

            self._log("[Step 2] 화자 분리 STT 중...")
            transcript = transcribe(
                audio.audio_path,
                engine=effective_engine,
                progress=_stt_progress,
                stop_event=self._stop_event,
            )
            self._log(
                f"[Step 2] OK: {len(transcript.segments)} 세그먼트, "
                f"{len(transcript.speakers)} 화자, 엔진={transcript.engine}"
            )
            self._set_progress(0.55)

            # Step 3 — 한국어 detected 시 번역 단계 skip (Phase 2B-3-backend 3b-1).
            # transcript.language 가 'ko' 면 STT 결과가 이미 한국어 → 별도 LLM 번역
            # 호출 불필요. to_plaintext 가 speaker + timestamp 보존 형식 그대로 반환.
            llm_cfg = LLMConfig.from_env(provider=self.provider)
            detected_lang = (transcript.language or "").lower()
            if detected_lang == "ko":
                self._log("[Step 3] 한국어 detected — 번역 단계 skip.")
                translated = transcript.to_plaintext()
                self._log(f"[Step 3] OK: 한국어 원본 사용 ({len(translated):,} chars)")
            else:
                self._log("[Step 3] LLM 한국어 번역 중...")
                translated = translate_transcript(
                    transcript, config=llm_cfg, progress=self._log,
                    video_context=video_ctx,
                    stop_event=self._stop_event,
                )
                self._log(f"[Step 3] OK: 번역 완료 ({len(translated):,} chars)")
            self._set_progress(0.78)

            # Step 4
            self._log("[Step 4] GuruNote 요약본 생성 중...")
            summary_md = summarize_translation(
                translated,
                title=audio.video_title,
                config=llm_cfg,
                progress=self._log,
                video_context=video_ctx,
                stop_event=self._stop_event,
            )
            self._log("[Step 4] OK: 요약 완료")
            self._set_progress(0.88)

            # Step 4.5 — 메타데이터 자동 추출 (제목/분야/태그)
            self._log("[Step 4.5] 분류 메타데이터(제목/분야/태그) 추출 중...")
            video_meta = {
                "title": audio.video_title,
                "uploader": audio.uploader,
                "tags": getattr(audio, "tags", None) or [],
            }
            metadata = extract_metadata(
                translated, video_meta=video_meta,
                config=llm_cfg, log=self._log,
            )
            if metadata:
                self._log(
                    f"[Step 4.5] OK: 분야='{metadata.get('field', '')}', "
                    f"태그={metadata.get('tags', [])}"
                )
            self._set_progress(0.92)

            # Step 5
            self._log("[Step 5] 마크다운 조립 중...")
            full_md = build_gurunote_markdown(
                title=audio.video_title,
                webpage_url=audio.webpage_url,
                summary_md=summary_md,
                translated_text=translated,
                transcript=transcript,
                uploader=audio.uploader,
                stt_engine=transcript.engine,
                upload_date=audio.upload_date,
                chapters=audio.chapters,
                subtitles_source=audio.subtitles_source,
                organized_title=metadata.get("organized_title", ""),
                field=metadata.get("field", ""),
                tags=metadata.get("tags", []),
                # Phase 2B-3-backend 3b-1: 한국어 분기 + 동적 원문 섹션 헤더에 사용.
                detected_language=transcript.language or None,
            )
            self._log("[Done] GuruNote 생성 완료")
            self._set_progress(1.0)

            # 히스토리에 자동 저장 (분류 메타 포함)
            save_job(
                self.job_id,
                title=audio.video_title,
                source_url=audio.webpage_url,
                stt_engine=transcript.engine,
                llm_provider=self.provider,
                status="completed",
                duration_sec=audio.duration_sec,
                num_speakers=len(transcript.speakers),
                full_md=full_md,
                organized_title=metadata.get("organized_title", ""),
                field=metadata.get("field", ""),
                tags=metadata.get("tags", []),
                uploader=audio.uploader or "",
                upload_date=audio.upload_date or "",
                # Phase 2B-3-backend 3b-1: STT detected language → metadata.json + frontend.
                detected_language=transcript.language or None,
            )
            self._log("[Save] 히스토리에 저장됨")

            # Semantic index incremental update (best-effort, 백그라운드).
            # 인덱스가 이미 빌드돼 있을 때만 — 아직이면 silent no-op.
            try:
                semantic_search.update_job_in_index(
                    self.job_id, full_md,
                    title=metadata.get("organized_title") or audio.video_title,
                    log=self._log,
                )
            except Exception:  # noqa: BLE001 — 어떤 에러도 파이프라인 막지 않음
                pass

            # autosave
            try:
                saved = autosave_result(full_md, audio.video_title)
                self._log(f"[Autosave] {saved}")
            except Exception:  # noqa: BLE001
                pass

            self.result_queue.put(
                {
                    "ok": True,
                    "audio": audio,
                    "transcript": transcript,
                    "translated": translated,
                    "summary_md": summary_md,
                    "full_md": full_md,
                }
            )
        except Exception as exc:
            self.msg_queue.put(f"[Error] {exc}")
            # 실패도 히스토리에 기록 (로그 파일은 이미 저장됨)
            save_job(
                self.job_id,
                title=self.youtube_url or self.local_file or "unknown",
                source_url=self.youtube_url or self.local_file,
                stt_engine=self.engine,
                llm_provider=self.provider,
                status="failed",
                error_message=str(exc),
            )
            self.result_queue.put({"ok": False, "error": str(exc)})
        finally:
            self._job_logger.close()
            cleanup_dir(tmp_dir)


# =============================================================================
# 설정 다이얼로그 (API 키 관리)
# =============================================================================
# LLM Provider 드롭다운 선택지
_LLM_PROVIDERS = ["openai", "anthropic", "gemini", "openai_compatible"]

# 설정 필드 정의: (환경변수명, 라벨, 마스킹 여부)
# `LLM_PROVIDER` 는 CTkOptionMenu 로 렌더링되고, 나머지는 CTkEntry.
# 하드웨어 프리셋이 아래 필드들의 값을 일괄 채운다:
#   WHISPERX_MODEL, WHISPERX_BATCH_SIZE, MLX_WHISPER_MODEL,
#   LLM_TEMPERATURE, LLM_TRANSLATION_MAX_TOKENS, LLM_SUMMARY_MAX_TOKENS
_SETTINGS_FIELDS = [
    ("LLM_PROVIDER", "LLM Provider", False),
    ("OPENAI_API_KEY", "OpenAI API Key", True),
    ("OPENAI_BASE_URL", "OpenAI Base URL (Local/Compatible)", False),
    ("OPENAI_MODEL", "OpenAI 모델", False),
    ("ANTHROPIC_API_KEY", "Anthropic API Key", True),
    ("ANTHROPIC_MODEL", "Anthropic 모델", False),
    ("GOOGLE_API_KEY", "Google Gemini API Key", True),
    ("GEMINI_MODEL", "Gemini 모델", False),
    ("LLM_TEMPERATURE", "LLM Temperature", False),
    ("LLM_TRANSLATION_MAX_TOKENS", "번역 Max Tokens", False),
    ("LLM_SUMMARY_MAX_TOKENS", "요약 Max Tokens", False),
    ("ASSEMBLYAI_API_KEY", "AssemblyAI API Key (폴백용)", True),
    ("WHISPERX_MODEL", "WhisperX 모델 (NVIDIA)", False),
    ("WHISPERX_BATCH_SIZE", "WhisperX 배치 사이즈 (NVIDIA)", False),
    ("MLX_WHISPER_MODEL", "MLX Whisper 모델 (Apple Silicon)", False),
    ("HUGGINGFACE_TOKEN", "HuggingFace 토큰 (화자 분리용)", True),
    # Phase D — Obsidian vault 연동
    ("OBSIDIAN_VAULT_PATH", "Obsidian Vault 경로", False),
    ("OBSIDIAN_SUBFOLDER", "Obsidian 하위 폴더 (기본 GuruNote)", False),
    # Phase E — Notion API 연동
    ("NOTION_TOKEN", "Notion Integration Token", True),
    ("NOTION_PARENT_ID", "Notion Parent ID (database/page UUID)", False),
    ("NOTION_PARENT_TYPE", "Notion Parent Type (database/page)", False),
]


class DashboardDialog(ctk.CTkToplevel):
    """
    거시적 통계 대시보드 (Step 3.3).

    사용자가 쌓아둔 노트 전체에 대해:
      - 총 작업 수 (성공/실패)
      - 총/평균/최장 녹취 시간
      - 분야·업로더·태그 top-N
      - 월별 작업 추이

    차트 라이브러리 의존성 없이 Unicode block 문자 (█) 로 바 차트를
    CTkTextbox 에 렌더링. matplotlib 같은 heavy dep 없음.
    """

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("GuruNote · 대시보드")
        self.geometry("760x640")
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._render()
        self.after(100, self.focus_force)

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            header, text="대시보드 — 지식 라이브러리 거시 지표",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            header, text="Refresh", width=90, height=28,
            command=self._render,
        ).pack(side="right")
        # Step 3.4 — 의미 검색 인덱스 재빌드 (모델 추론이 무거워 명시적 버튼)
        ctk.CTkButton(
            header, text="Semantic Rebuild", width=160, height=28,
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
            command=self._on_rebuild_semantic,
        ).pack(side="right", padx=(0, 6))

        self._tb = ctk.CTkTextbox(
            self, wrap="none",
            font=ctk.CTkFont(family="Menlo", size=12),
            fg_color=C_BG, text_color=C_TEXT, corner_radius=8,
        )
        self._tb.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _render(self) -> None:
        """히스토리 인덱스 재로드 → 통계 계산 → 텍스트 리포트 표시 + 의미 검색 인덱스 상태."""
        try:
            jobs = load_index()
            stats = compute_stats(jobs)
            report = render_report(stats)
        except Exception as exc:  # noqa: BLE001
            report = f"대시보드 계산 실패:\n{exc}"

        # 의미 검색 인덱스 상태 블록
        report += "\n의미 검색 인덱스 (Step 3.4)\n"
        report += "─" * 28 + "\n"
        if not semantic_search.is_available():
            report += "  미설치 — `pip install -r requirements-search.txt`\n"
        else:
            s = semantic_search.index_stats()
            if not s.get("built"):
                report += "  빌드되지 않음 — 상단 'Semantic Rebuild' 버튼 클릭\n"
            elif s.get("error"):
                report += f"  인덱스 로드 실패: {s['error']}\n"
            else:
                report += (
                    f"  모델        {s.get('model', '?')}\n"
                    f"  chunks      {s.get('num_chunks', 0)}\n"
                    f"  작업 수     {s.get('num_jobs', 0)}\n"
                    f"  빌드 시각   {s.get('built_at', '?')[:19]}\n"
                )

        self._tb.configure(state="normal")
        self._tb.delete("1.0", "end")
        self._tb.insert("1.0", report)
        self._tb.configure(state="disabled")

    def _on_rebuild_semantic(self) -> None:
        """의미 검색 인덱스 재빌드. 백그라운드 스레드 + after() 폴링."""
        if not semantic_search.is_available():
            messagebox.showwarning(
                "의미 검색 미지원", semantic_search.missing_packages_hint(),
            )
            return
        if not messagebox.askyesno(
            "의미 검색 인덱스 재빌드",
            "모든 저장된 작업 본문을 embedding 모델로 인덱싱합니다.\n"
            "첫 실행 시 모델 다운로드 (~117MB) 로 수 분 걸릴 수 있습니다.\n\n"
            "계속할까요?",
        ):
            return

        self.configure(cursor="watch")
        result_q: "queue.Queue" = queue.Queue()

        def _worker():
            try:
                jobs = load_index()
                result = semantic_search.build_index(jobs, log=lambda m: None)
                result_q.put(("ok", result))
            except Exception as exc:  # noqa: BLE001
                result_q.put(("err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_semantic_build(result_q)

    def _poll_semantic_build(self, q: "queue.Queue") -> None:
        try:
            status, payload = q.get_nowait()
        except queue.Empty:
            try:
                if self.winfo_exists():
                    self.after(250, lambda: self._poll_semantic_build(q))
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            self.configure(cursor="")
        except Exception:  # noqa: BLE001
            pass
        if status == "ok":
            messagebox.showinfo(
                "의미 검색 인덱스 빌드 완료",
                f"작업 {payload['num_jobs']} 건 · chunks {payload['num_chunks']}"
                + (f" · 스킵 {payload['skipped']}" if payload['skipped'] else ""),
            )
            self._render()
        else:
            messagebox.showerror("의미 검색 빌드 실패", payload)


class NoteEditorDialog(ctk.CTkToplevel):
    """
    저장된 결과 마크다운 인라인 편집기 (Step 3.2).

    LLM 요약/번역 결과는 종종 교정이 필요하다 (오타, 화자 이름 오인식, 태그
    수정 등). 별도 에디터 앱을 쓰지 않고 앱 안에서 바로 고쳐 `result.md` 에
    되저장할 수 있게 한다. frontmatter 포함 전체 마크다운을 단일 textbox 로
    노출 — 사용자가 필요한 부분만 수정.

    저장 시 `history.update_job_markdown()` 로 atomic write. 저장 후 콜백
    (`on_saved`) 이 HistoryDialog 의 그리드를 재로드해 스니펫/카드 갱신.
    """

    def __init__(
        self,
        parent: ctk.CTkToplevel,
        job_id: str,
        title: str,
        initial_md: str,
        on_saved=None,
    ) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title(f"편집 — {title[:60]}")
        self.geometry("1200x680")
        self.transient(parent)
        self.grab_set()
        self._job_id = job_id
        self._original_title = title
        self._initial_md = initial_md
        self._on_saved = on_saved
        # Preview 토글 + 입력 debounce 핸들
        self._preview_visible = True
        self._preview_after_id: Optional[str] = None
        self._build_ui()
        # 닫기(X) 도 dirty 체크 거치도록
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)
        self.after(100, self.focus_force)
        # 첫 렌더
        self._schedule_preview_refresh(delay_ms=0)

    def _build_ui(self) -> None:
        # 헤더
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            header, text="result.md 편집",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=C_TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            header, text="💾 저장", width=96, height=32,
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
            command=self._on_save_click,
        ).pack(side="right")
        ctk.CTkButton(
            header, text="취소", width=72, height=32,
            fg_color="gray35", hover_color="gray45",
            command=self._on_close_attempt,
        ).pack(side="right", padx=6)
        # 프리뷰 토글
        self._preview_btn = ctk.CTkButton(
            header, text="👁 Preview ▼", width=110, height=32,
            fg_color="gray35", hover_color="gray45",
            command=self._toggle_preview,
        )
        self._preview_btn.pack(side="right", padx=6)

        # 안내
        ctk.CTkLabel(
            self,
            text="YAML frontmatter 포함 전체 마크다운을 직접 수정할 수 있습니다. "
                 "저장 시 ~/.gurunote/jobs/<id>/result.md 가 덮어쓰여집니다.",
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            anchor="w", justify="left",
        ).pack(fill="x", padx=16, pady=(0, 8))

        # 분할 영역 — 왼쪽 raw editor, 오른쪽 rendered preview
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1, uniform="split")
        body.grid_columnconfigure(1, weight=1, uniform="split")
        self._body_frame = body

        self._tb = ctk.CTkTextbox(
            body, wrap="word",
            font=ctk.CTkFont(family="Menlo", size=12),
            fg_color=C_BG, text_color=C_TEXT,
            corner_radius=8,
        )
        self._tb.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._tb.insert("1.0", self._initial_md)
        self._tb.bind("<KeyRelease>", lambda _e: self._schedule_preview_refresh())

        self._preview = ctk.CTkTextbox(
            body, wrap="word",
            font=ctk.CTkFont(size=13),
            fg_color=C_BG, text_color=C_TEXT,
            corner_radius=8, state="disabled",
        )
        self._preview.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._configure_preview_tags()

        # 키 바인딩: Cmd/Ctrl+S 로 저장
        import platform as _p
        save_key = "<Command-s>" if _p.system() == "Darwin" else "<Control-s>"
        self.bind(save_key, lambda _e: self._on_save_click())

    def _configure_preview_tags(self) -> None:
        """렌더링 스타일 — Tk Text tag_configure 로 헤더/볼드/이탤릭/코드/인용 지정."""
        tb = self._preview
        tb.tag_config("h1", font=ctk.CTkFont(size=20, weight="bold"))
        tb.tag_config("h2", font=ctk.CTkFont(size=16, weight="bold"))
        tb.tag_config("h3", font=ctk.CTkFont(size=14, weight="bold"))
        tb.tag_config("bold", font=ctk.CTkFont(size=13, weight="bold"))
        tb.tag_config("italic", font=ctk.CTkFont(size=13, slant="italic"))
        tb.tag_config(
            "code",
            font=ctk.CTkFont(family="Menlo", size=11),
            background="#2a2a3e",
        )
        tb.tag_config("quote", foreground="#a78bfa", lmargin1=20, lmargin2=20)
        tb.tag_config("hr", foreground="#555")
        tb.tag_config("link", foreground="#7c3aed", underline=True)
        tb.tag_config("bullet", lmargin1=14, lmargin2=28)

    # -------------------------------------------------------------------------
    # Preview 렌더링
    # -------------------------------------------------------------------------
    def _schedule_preview_refresh(self, delay_ms: int = 250) -> None:
        """Debounce: 마지막 키 입력 후 delay_ms 만 미루어 1회 re-render."""
        if not self._preview_visible:
            return
        if self._preview_after_id is not None:
            try:
                self.after_cancel(self._preview_after_id)
            except Exception:  # noqa: BLE001
                pass
        self._preview_after_id = self.after(delay_ms, self._render_preview)

    def _render_preview(self) -> None:
        """현재 textbox 내용을 마크다운으로 파싱 → preview tag 입력."""
        import re as _re
        md = self._current_md()
        # frontmatter 제거 — 메타는 안내문이라 preview 에 노이즈
        md = _re.sub(r"^---\s*\n.*?\n---\s*\n", "", md, count=1, flags=_re.DOTALL)

        tb = self._preview
        tb.configure(state="normal")
        tb.delete("1.0", "end")

        inline_re = _re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")

        def _insert_inline(text: str) -> None:
            for piece in inline_re.split(text):
                if not piece:
                    continue
                if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
                    tb.insert("end", piece[2:-2], "bold")
                elif piece.startswith("`") and piece.endswith("`") and len(piece) > 2:
                    tb.insert("end", piece[1:-1], "code")
                elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
                    tb.insert("end", piece[1:-1], "italic")
                elif piece.startswith("[") and "](" in piece and piece.endswith(")"):
                    label = piece[1:piece.index("](")]
                    tb.insert("end", label, "link")
                else:
                    tb.insert("end", piece)

        in_code_block = False
        for raw in md.splitlines():
            stripped = raw.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                tb.insert("end", "─" * 40 + "\n", "hr")
                continue
            if in_code_block:
                tb.insert("end", raw + "\n", "code")
                continue
            if not stripped:
                tb.insert("end", "\n")
                continue
            if stripped in ("---", "***", "___"):
                tb.insert("end", "─" * 60 + "\n", "hr")
                continue
            m = _re.match(r"^(#{1,3})\s+(.+)", stripped)
            if m:
                level = len(m.group(1))
                tag = {1: "h1", 2: "h2", 3: "h3"}[level]
                tb.insert("end", m.group(2) + "\n", tag)
                continue
            if stripped.startswith("> "):
                tb.insert("end", "│ ", "quote")
                _insert_inline(stripped[2:])
                tb.insert("end", "\n")
                continue
            if stripped.startswith(("- ", "* ")):
                tb.insert("end", "  • ", "bullet")
                _insert_inline(stripped[2:])
                tb.insert("end", "\n")
                continue
            num_m = _re.match(r"^(\d+)\.\s+(.+)", stripped)
            if num_m:
                tb.insert("end", f"  {num_m.group(1)}. ", "bullet")
                _insert_inline(num_m.group(2))
                tb.insert("end", "\n")
                continue
            _insert_inline(raw)
            tb.insert("end", "\n")

        tb.configure(state="disabled")

    def _toggle_preview(self) -> None:
        if self._preview_visible:
            self._preview.grid_remove()
            self._body_frame.grid_columnconfigure(1, weight=0)
            self._body_frame.grid_columnconfigure(0, weight=1)
            self._preview_btn.configure(text="👁 Preview ▶")
            self._preview_visible = False
        else:
            self._body_frame.grid_columnconfigure(0, weight=1, uniform="split")
            self._body_frame.grid_columnconfigure(1, weight=1, uniform="split")
            self._preview.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
            self._preview_btn.configure(text="👁 Preview ▼")
            self._preview_visible = True
            self._render_preview()

    def _current_md(self) -> str:
        return self._tb.get("1.0", "end-1c")

    def _is_dirty(self) -> bool:
        return self._current_md() != self._initial_md

    def _on_close_attempt(self) -> None:
        if self._is_dirty():
            if not messagebox.askyesno(
                "편집 취소",
                "저장하지 않은 변경 사항이 있습니다. 버리고 닫을까요?",
            ):
                return
        self.destroy()

    def _on_save_click(self) -> None:
        new_md = self._current_md()
        if new_md == self._initial_md:
            messagebox.showinfo("변경 사항 없음", "수정된 내용이 없습니다.")
            return
        try:
            update_job_markdown(self._job_id, new_md)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("저장 실패", str(exc))
            return
        # Semantic index incremental update — best-effort, no-op if 미빌드
        try:
            semantic_search.update_job_in_index(
                self._job_id, new_md, title=self._original_title,
            )
        except Exception:  # noqa: BLE001
            pass
        self._initial_md = new_md
        messagebox.showinfo("저장 완료", "노트가 업데이트됐습니다.")
        if self._on_saved is not None:
            try:
                self._on_saved()
            except Exception:  # noqa: BLE001
                pass
        self.destroy()


class HistoryDialog(ctk.CTkToplevel):
    """완료/실패 작업 목록 — 필터바 + 카드 그리드 (Phase B)."""

    # 카드 레이아웃
    _COLUMNS = 3
    _THUMB_W, _THUMB_H = 256, 144  # mqdefault 비율 유지 (16:9)
    _CARD_W = 280

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("GuruNote · 히스토리")
        self.geometry("1240x680")
        self.transient(parent)
        self.grab_set()
        self._parent = parent

        # 데이터 모델 + 필터 상태
        self._all_jobs: list[dict] = []
        self._filtered_jobs: list[dict] = []
        self._search_var = ctk.StringVar(value="")
        self._field_var = ctk.StringVar(value="모든 분야")
        self._sort_var = ctk.StringVar(value="최신순")
        # Phase F — 본문 전문 검색 토글. 켜면 result.md 본문도 매칭 대상.
        self._search_body_var = ctk.BooleanVar(value=False)
        # Step 3.4 — 의미 검색 토글 (semantic/embedding 기반)
        self._search_semantic_var = ctk.BooleanVar(value=False)
        # Phase 1/2 트리 내비게이션 — 노드 클릭 시 facet job_ids 로 필터
        self._nav_filter: Optional[dict] = None  # {"facet": str, "label": str, "job_ids": set[str]}
        # Phase 2: 영속 상태 로드 (없거나 실패하면 기본값)
        self._ui_state: dict = load_ui_state()
        persisted = get_nav_expand(self._ui_state)
        self._nav_expand: dict[str, bool] = {**default_expand_state(), **persisted}
        # 트리 내 노드 검색 — 세션마다 초기화 (영속 X)
        self._nav_search_var = ctk.StringVar(value="")
        self._nav_body: Optional[ctk.CTkScrollableFrame] = None
        self._nav_chip: Optional[ctk.CTkLabel] = None
        self._nav_clear_btn: Optional[ctk.CTkButton] = None

        # PIL 이미지 참조 유지 (GC 방지) + 렌더링 중 썸네일 요청 중복 방지
        self._thumb_refs: dict[str, object] = {}
        self._pending_thumb_ids: set[str] = set()
        # 메인 스레드에서 받아 처리할 썸네일 완성 알림
        self._thumb_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        # 검색 debounce — 다량 히스토리에서 키 입력마다 full re-render 방지
        self._search_after_id: Optional[str] = None

        self._build_ui()
        self.after(100, self.focus_force)
        self.after(120, self._poll_thumb_queue)

    # =========================================================================
    # UI
    # =========================================================================
    def _build_ui(self) -> None:
        # 상단 헤더
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            header, text="작업 히스토리",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header, text="Refresh", width=90, height=28,
            command=self._reload_and_refresh,
        ).pack(side="right")
        ctk.CTkButton(
            header, text="Rebuild", width=90, height=28,
            fg_color="gray35", hover_color="gray45",
            command=self._on_rebuild_index,
        ).pack(side="right", padx=(0, 6))
        self._count_label = ctk.CTkLabel(
            header, text="", text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
        )
        self._count_label.pack(side="right", padx=(0, 12))

        # 필터 바
        fbar = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=8)
        fbar.pack(fill="x", padx=16, pady=(4, 8))

        ctk.CTkLabel(fbar, text="검색", font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(12, 6), pady=10)
        search_entry = ctk.CTkEntry(
            fbar, textvariable=self._search_var, width=200,
            placeholder_text="제목 / 업로더 / 태그 / (옵션)본문",
        )
        search_entry.pack(side="left", pady=10)
        # 검색 debounce: 200ms 간격으로만 re-render — 빠른 타이핑 중 UI 프리즈 방지
        self._search_var.trace_add("write", lambda *_: self._schedule_refresh())

        # Phase F — 본문 검색 토글 (result.md 본문 lazy load + lru_cache)
        ctk.CTkCheckBox(
            fbar, text="본문 포함", variable=self._search_body_var,
            command=self._refresh_grid,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(8, 0), pady=10)

        # Step 3.4 — 의미 검색 토글 (sentence-transformers + cosine similarity)
        ctk.CTkCheckBox(
            fbar, text="의미 검색", variable=self._search_semantic_var,
            command=self._refresh_grid,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(8, 0), pady=10)

        ctk.CTkLabel(fbar, text="분야", font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(16, 6), pady=10)
        self._field_menu = ctk.CTkOptionMenu(
            fbar, variable=self._field_var, values=["모든 분야"],
            width=150, command=lambda _: self._refresh_grid(),
        )
        self._field_menu.pack(side="left", pady=10)

        ctk.CTkLabel(fbar, text="정렬", font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(16, 6), pady=10)
        ctk.CTkOptionMenu(
            fbar, variable=self._sort_var,
            values=["최신순", "오래된순", "길이 긴 순", "길이 짧은 순", "제목 A-Z"],
            width=130, command=lambda _: self._refresh_grid(),
        ).pack(side="left", pady=10)

        ctk.CTkButton(
            fbar, text="필터 초기화", width=90, height=28,
            fg_color="gray35", hover_color="gray45",
            command=self._reset_filters,
        ).pack(side="right", padx=12, pady=10)

        # 본문: 좌측 그리드 | 우측 트리 내비게이션
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=280)
        body.grid_rowconfigure(0, weight=0)
        body.grid_rowconfigure(1, weight=1)

        # 활성 facet chip + clear 버튼 (좌측 상단)
        chip_bar = ctk.CTkFrame(body, fg_color="transparent")
        chip_bar.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 6))
        self._nav_chip = ctk.CTkLabel(
            chip_bar, text="", text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
        )
        self._nav_chip.pack(side="left")
        self._nav_clear_btn = ctk.CTkButton(
            chip_bar, text="× 필터 해제", width=90, height=24,
            fg_color="gray35", hover_color="gray45",
            font=ctk.CTkFont(size=11),
            command=self._clear_nav_filter,
        )
        # 기본은 숨김 — 필터 활성화 시만 표시

        # 그리드 스크롤 영역
        self._scroll = ctk.CTkScrollableFrame(body, fg_color=C_BG)
        self._scroll.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        for c in range(self._COLUMNS):
            self._scroll.grid_columnconfigure(
                c, weight=1, minsize=self._CARD_W, uniform="card"
            )

        # 우측 트리 내비게이션 패널
        nav_panel = ctk.CTkFrame(body, fg_color=C_SURFACE, corner_radius=8)
        nav_panel.grid(row=0, column=1, rowspan=2, sticky="nsew")
        nav_panel.grid_columnconfigure(0, weight=1)
        nav_panel.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(
            nav_panel, text="내비게이션",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")
        # 노드 라벨 서브스트링 검색 (세션 단위 — 영속 X)
        nav_search = ctk.CTkEntry(
            nav_panel, textvariable=self._nav_search_var,
            placeholder_text="트리 내 검색…",
            height=28,
        )
        nav_search.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self._nav_search_var.trace_add(
            "write", lambda *_: self._render_nav_tree(),
        )
        self._nav_body = ctk.CTkScrollableFrame(nav_panel, fg_color="transparent")
        self._nav_body.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 10))
        self._nav_body.grid_columnconfigure(0, weight=1)

        # Phase 2: 창 닫힐 때 expand 상태 저장
        self.protocol("WM_DELETE_WINDOW", self._on_history_close)

        self._reload_and_refresh()

    # =========================================================================
    # Data flow
    # =========================================================================
    def _reload_and_refresh(self) -> None:
        """인덱스 재로드 + 분야 드롭다운 재구성 + 그리드 재렌더.

        검색 본문 캐시도 함께 무효화해 삭제/신규 작업이 반영되도록 한다.
        """
        search_clear_cache()
        self._all_jobs = load_index()

        # 분야 드롭다운 재구성
        fields = sorted({
            (j.get("field") or "").strip()
            for j in self._all_jobs if (j.get("field") or "").strip()
        })
        self._field_menu.configure(values=["모든 분야", *fields])
        if self._field_var.get() not in ["모든 분야", *fields]:
            self._field_var.set("모든 분야")

        # 활성 nav 필터의 job_ids 가 현재 인덱스에 존재하는지 검증 (삭제 반영)
        if self._nav_filter:
            valid_ids = {j.get("job_id") for j in self._all_jobs}
            self._nav_filter["job_ids"] &= valid_ids
            if not self._nav_filter["job_ids"]:
                self._nav_filter = None

        self._render_nav_tree()
        self._refresh_grid()

    # =========================================================================
    # Tree navigation (Phase 1)
    # =========================================================================
    _FACET_HEADERS = [
        ("field", "주제 (분야)"),
        ("person", "인물 (업로더)"),
        ("title", "제목 (첫글자)"),
        ("tag", "태그"),
    ]

    def _render_nav_tree(self) -> None:
        """우측 패널에 4-facet 트리 재렌더 (서브스트링 검색 반영)."""
        if self._nav_body is None:
            return
        for w in self._nav_body.winfo_children():
            w.destroy()

        if not self._all_jobs:
            ctk.CTkLabel(
                self._nav_body, text="노트를 만들면 자동 분류됩니다.",
                text_color="gray55", font=ctk.CTkFont(size=11),
                wraplength=240, justify="left",
            ).grid(row=0, column=0, padx=8, pady=12, sticky="ew")
            return

        query = self._nav_search_var.get().strip().lower()
        facets = compute_facets(self._all_jobs)
        row = 0
        for key, title in self._FACET_HEADERS:
            expanded = self._nav_expand.get(key, True)
            header = ctk.CTkButton(
                self._nav_body,
                text=f"{'▾' if expanded else '▸'}  {title}",
                anchor="w", height=28,
                fg_color="transparent", hover_color="gray25",
                text_color=C_TEXT_DIM, font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda k=key: self._toggle_facet(k),
            )
            header.grid(row=row, column=0, sticky="ew", padx=4, pady=(6, 2))
            row += 1

            if not expanded:
                continue

            nodes: list[FacetNode] = facets.get(key, [])
            if query:
                nodes = [n for n in nodes if query in n.label.lower()]
            if not nodes:
                msg = "  (검색 결과 없음)" if query else "  (비어 있음)"
                ctk.CTkLabel(
                    self._nav_body, text=msg,
                    text_color="gray55", font=ctk.CTkFont(size=11),
                ).grid(row=row, column=0, sticky="w", padx=14)
                row += 1
                continue

            for node in nodes:
                active = bool(
                    self._nav_filter
                    and self._nav_filter.get("facet") == key
                    and self._nav_filter.get("label") == node.label
                )
                label_txt = node.label
                if len(label_txt) > 22:
                    label_txt = label_txt[:21] + "…"
                btn = ctk.CTkButton(
                    self._nav_body,
                    text=f"  {label_txt}  ({node.count})",
                    anchor="w", height=24,
                    fg_color=C_ACCENT if active else "transparent",
                    hover_color="gray25",
                    text_color="white" if active else C_TEXT,
                    font=ctk.CTkFont(size=11),
                    command=lambda k=key, n=node: self._on_nav_click(k, n),
                )
                btn.grid(row=row, column=0, sticky="ew", padx=14, pady=0)
                row += 1

    def _on_history_close(self) -> None:
        """창 닫기 시 expand 상태 저장 → destroy."""
        try:
            save_ui_state(set_nav_expand(self._ui_state, self._nav_expand))
        except Exception:
            pass
        self.destroy()

    def _toggle_facet(self, key: str) -> None:
        self._nav_expand[key] = not self._nav_expand.get(key, True)
        self._render_nav_tree()

    def _on_nav_click(self, facet: str, node: FacetNode) -> None:
        """동일 노드 재클릭 → 필터 해제. 아니면 새 필터 적용."""
        current = self._nav_filter
        if current and current.get("facet") == facet and current.get("label") == node.label:
            self._nav_filter = None
        else:
            self._nav_filter = {
                "facet": facet,
                "label": node.label,
                "job_ids": set(node.job_ids),
            }
        self._render_nav_tree()
        self._refresh_grid()

    def _clear_nav_filter(self) -> None:
        if self._nav_filter is None:
            return
        self._nav_filter = None
        self._render_nav_tree()
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        # 기존 카드 제거
        for w in self._scroll.winfo_children():
            w.destroy()

        # nav 필터 chip 표시/해제
        if self._nav_chip is not None and self._nav_clear_btn is not None:
            if self._nav_filter:
                facet_title = dict(self._FACET_HEADERS).get(self._nav_filter["facet"], "")
                self._nav_chip.configure(
                    text=f"활성 필터  ·  {facet_title}  ›  {self._nav_filter['label']}"
                )
                self._nav_clear_btn.pack(side="left", padx=(10, 0))
            else:
                self._nav_chip.configure(text="")
                self._nav_clear_btn.pack_forget()

        filtered = self._apply_filters(self._all_jobs)
        self._filtered_jobs = filtered
        self._count_label.configure(
            text=f"{len(filtered)} / {len(self._all_jobs)} 건"
        )

        if not filtered:
            ctk.CTkLabel(
                self._scroll,
                text="조건에 맞는 작업이 없습니다." if self._all_jobs
                     else "아직 작업 기록이 없습니다.",
                text_color="gray55",
            ).grid(row=0, column=0, columnspan=self._COLUMNS, pady=60)
            return

        for i, job in enumerate(filtered):
            r, c = divmod(i, self._COLUMNS)
            self._render_card(r, c, job)

    def _apply_filters(self, jobs: list[dict]) -> list[dict]:
        """검색어 + 분야 + (옵션) 본문/의미 검색 + 정렬 적용.

        - Phase F: `📄 본문 포함` 토글 — result.md substring 매칭
        - Step 3.4: `🔮 의미 검색` 토글 — embedding cosine sim top-K
        매칭된 잡에는 `_body_snippet` 키가 추가되어 카드가 스니펫을 렌더링.
        의미 검색 점수는 스니펫 앞에 `[0.73]` 형태로 포함.
        """
        q = self._search_var.get().strip().lower()
        field = self._field_var.get().strip()
        search_body = bool(self._search_body_var.get())
        search_semantic = bool(self._search_semantic_var.get())

        def meta_match(j: dict) -> bool:
            if not q:
                return True
            hay = " ".join([
                j.get("organized_title") or "",
                j.get("title") or "",
                j.get("uploader") or "",
                " ".join(j.get("tags") or []),
            ]).lower()
            return q in hay

        # 의미 검색이 켜져 있으면 사전에 한 번만 embedding 쿼리 실행
        semantic_hits: dict[str, dict] = {}
        if search_semantic and q:
            try:
                results = semantic_search.search(
                    self._search_var.get().strip(), top_k=20, min_score=0.25,
                )
                for r in results:
                    semantic_hits[r["job_id"]] = r
            except Exception as exc:  # noqa: BLE001
                # 최초 호출 시 안내 (한 번만). 이후는 조용히 무시.
                if not getattr(self, "_semantic_warned", False):
                    messagebox.showwarning("의미 검색 오류", str(exc))
                    self._semantic_warned = True

        nav = self._nav_filter
        nav_ids = nav.get("job_ids") if nav else None

        def passes_filters(j: dict) -> Optional[dict]:
            """매치하면 job 사본 (스니펫 포함 가능) 반환, 아니면 None."""
            if nav_ids is not None and j.get("job_id") not in nav_ids:
                return None
            if field and field != "모든 분야" and (j.get("field") or "") != field:
                return None
            if not q:
                return j
            if meta_match(j):
                return j
            # 의미 검색 히트: 메타 불일치여도 포함 + 스니펫 표시
            jid = j.get("job_id", "")
            if search_semantic and jid in semantic_hits:
                hit = semantic_hits[jid]
                copy = dict(j)
                copy["_body_snippet"] = f"[유사도 {hit['score']:.2f}] {hit['preview']}"
                return copy
            # 본문 substring 검색
            if search_body and j.get("has_markdown"):
                snippet = search_match_body(jid, q)
                if snippet:
                    copy = dict(j)
                    copy["_body_snippet"] = snippet
                    return copy
            return None

        out: list[dict] = []
        for j in jobs:
            res = passes_filters(j)
            if res is not None:
                out.append(res)

        sort_mode = self._sort_var.get()
        if sort_mode == "최신순":
            out.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        elif sort_mode == "오래된순":
            out.sort(key=lambda j: j.get("created_at") or "")
        elif sort_mode == "길이 긴 순":
            out.sort(key=lambda j: j.get("duration_sec") or 0, reverse=True)
        elif sort_mode == "길이 짧은 순":
            out.sort(key=lambda j: j.get("duration_sec") or 0)
        elif sort_mode == "제목 A-Z":
            out.sort(key=lambda j: (j.get("organized_title") or j.get("title") or "").lower())
        return out

    def _reset_filters(self) -> None:
        # trace 가 발동해 _schedule_refresh 가 예약되므로 직접 호출은 불필요
        self._search_var.set("")
        self._field_var.set("모든 분야")
        self._sort_var.set("최신순")
        self._nav_filter = None
        self._render_nav_tree()
        self._refresh_grid()

    def _schedule_refresh(self) -> None:
        """debounce: 타이핑이 빠르면 이전 예약을 취소하고 마지막 키 이후 200ms 에만 re-render."""
        if self._search_after_id is not None:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:  # noqa: BLE001
                pass
        self._search_after_id = self.after(200, self._refresh_grid)

    # =========================================================================
    # Card rendering
    # =========================================================================
    def _render_card(self, row: int, col: int, job: dict) -> None:
        # 카드 크기는 grid 의 컬럼 minsize 로 보장 — grid_propagate 를 풀어
        # 길이 다른 제목/태그에서도 클리핑 없이 높이가 자연스럽게 확장되게.
        card = ctk.CTkFrame(
            self._scroll, fg_color=C_SURFACE, corner_radius=10,
            border_width=1, border_color=C_BORDER,
        )
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        # 썸네일 자리 (비동기 로딩)
        thumb_holder = ctk.CTkFrame(
            card, fg_color=C_BG, corner_radius=6,
            width=self._THUMB_W, height=self._THUMB_H,
        )
        thumb_holder.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="ew")
        thumb_holder.grid_propagate(False)
        self._attach_thumbnail(thumb_holder, job)

        # 상태 뱃지 (좌상단 오버레이 대신 제목 옆 아이콘으로)
        status = job.get("status", "unknown")
        status_icon = "✅" if status == "completed" else "❌"

        # 제목 (정리된 제목 우선)
        title = job.get("organized_title") or job.get("title") or "제목 없음"
        ctk.CTkLabel(
            card, text=f"{status_icon}  {title}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w", justify="left", wraplength=self._CARD_W - 30,
            text_color=C_TEXT,
        ).grid(row=1, column=0, padx=10, pady=(2, 2), sticky="w")

        # 메타 라인 1: 업로더 · 날짜
        uploader = (job.get("uploader") or "").strip()
        created = (job.get("created_at") or "")[:10]
        upload_date = (job.get("upload_date") or "").strip()
        date_part = upload_date or created
        meta1 = " · ".join(filter(None, [uploader, date_part]))
        if meta1:
            ctk.CTkLabel(
                card, text=meta1, font=ctk.CTkFont(size=11),
                anchor="w", text_color=C_TEXT_DIM,
                wraplength=self._CARD_W - 30,
            ).grid(row=2, column=0, padx=10, pady=0, sticky="w")

        # 메타 라인 2: 길이 · STT 엔진 · 화자 수
        dur_s = job.get("duration_sec") or 0
        if dur_s:
            h, rem = divmod(int(dur_s), 3600)
            m, s = divmod(rem, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        else:
            dur_str = ""
        n_sp = job.get("num_speakers") or 0
        engine = job.get("stt_engine") or ""
        meta2 = " · ".join(filter(None, [
            dur_str, engine, f"화자 {n_sp}" if n_sp else "",
        ]))
        if meta2:
            ctk.CTkLabel(
                card, text=meta2, font=ctk.CTkFont(size=11),
                anchor="w", text_color=C_TEXT_DIM,
            ).grid(row=3, column=0, padx=10, pady=(0, 2), sticky="w")

        # 분야 + 태그
        field = (job.get("field") or "").strip()
        tags = job.get("tags") or []
        badge_line = ""
        if field:
            badge_line += f"📁 {field}"
        if tags:
            badge_line += ("   " if badge_line else "") + " ".join(f"#{t}" for t in tags[:5])
        if badge_line:
            ctk.CTkLabel(
                card, text=badge_line, font=ctk.CTkFont(size=10),
                anchor="w", text_color=C_PRIMARY,
                wraplength=self._CARD_W - 30, justify="left",
            ).grid(row=4, column=0, padx=10, pady=(2, 4), sticky="w")

        # 실패 시 에러 메시지
        if status == "failed":
            err = (job.get("error_message") or "").strip()
            if err:
                ctk.CTkLabel(
                    card, text=f"❌ {err[:120]}",
                    font=ctk.CTkFont(size=10), text_color=C_DANGER,
                    wraplength=self._CARD_W - 30, anchor="w", justify="left",
                ).grid(row=5, column=0, padx=10, pady=(2, 4), sticky="w")

        # Phase F — 본문 검색 매칭 시 스니펫 표시
        snippet = job.get("_body_snippet")
        if snippet:
            ctk.CTkLabel(
                card, text=f"🔍 {snippet[:200]}",
                font=ctk.CTkFont(size=10, slant="italic"),
                text_color=C_TEXT_DIM,
                wraplength=self._CARD_W - 30, anchor="w", justify="left",
            ).grid(row=5, column=0, padx=10, pady=(2, 4), sticky="w")

        # 액션 버튼 바 — 그리드 uniform 컬럼으로 7개 버튼 균등 배치
        # (기존 pack side="right" 방식은 카드 좁을 때 Del 버튼이 26px 로
        # 잘리는 문제가 있어 grid + uniform 으로 전환.)
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=6, column=0, padx=8, pady=(4, 10), sticky="ew")
        job_id = job.get("job_id", "")

        # 버튼 목록 — has_markdown 여부에 따라 다른 개수. grid 균등 배치용으로
        # 먼저 모으고 한 번에 column 설정.
        btns: list[ctk.CTkButton] = []
        if job.get("has_markdown"):
            btns.append(ctk.CTkButton(
                btn_row, text=".md", height=28,
                command=lambda jid=job_id, t=title: self._save_md(jid, t),
            ))
            btns.append(ctk.CTkButton(
                btn_row, text="Edit", height=28,
                fg_color=C_SURFACE_HI, hover_color=C_PRIMARY,
                command=lambda jid=job_id, t=title: self._edit_note(jid, t),
            ))
            btns.append(ctk.CTkButton(
                btn_row, text="PDF", height=28,
                command=lambda jid=job_id, t=title: self._save_pdf(jid, t),
            ))
            btns.append(ctk.CTkButton(
                btn_row, text="Obs", height=28,
                fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
                command=lambda jid=job_id, t=title: self._save_obsidian(jid, t),
            ))
            btns.append(ctk.CTkButton(
                btn_row, text="Ntn", height=28,
                fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
                command=lambda jid=job_id, t=title: self._save_notion(jid, t),
            ))
        btns.append(ctk.CTkButton(
            btn_row, text="Log", height=28,
            fg_color="gray35",
            command=lambda jid=job_id: self._show_log(jid),
        ))
        btns.append(ctk.CTkButton(
            btn_row, text="Del", height=28,
            fg_color="gray35", hover_color=C_DANGER,
            command=lambda jid=job_id: self._delete(jid),
        ))

        for col, btn in enumerate(btns):
            btn_row.grid_columnconfigure(col, weight=1, uniform="hist_btn")
            btn.grid(row=0, column=col, padx=1, sticky="ew")

    def _attach_thumbnail(self, holder: ctk.CTkFrame, job: dict) -> None:
        """
        썸네일 이미지 로드 (캐시 즉시, 미캐시 시 비동기 다운로드).
        실패 / 로컬파일 소스 시 회색 플레이스홀더 + 아이콘 라벨.
        """
        url = job.get("source_url") or ""
        video_id = extract_youtube_id(url) if url else None

        if not video_id:
            # 로컬 파일 또는 YouTube 아님
            ctk.CTkLabel(
                holder, text="🎵\n(로컬 파일)" if url else "🎙️",
                font=ctk.CTkFont(size=22), text_color=C_TEXT_DIM,
            ).place(relx=0.5, rely=0.5, anchor="center")
            return

        cache_path = cached_thumbnail_path(video_id)
        if cache_path.exists():
            self._place_thumbnail(holder, cache_path, video_id)
            return

        # 플레이스홀더 먼저 표시
        placeholder = ctk.CTkLabel(
            holder, text="⏳", font=ctk.CTkFont(size=22),
            text_color=C_TEXT_DIM,
        )
        placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # 비동기 다운로드 요청 (중복 방지)
        if video_id not in self._pending_thumb_ids:
            self._pending_thumb_ids.add(video_id)
            def _on_complete(path):
                self._thumb_queue.put((video_id, path))
            download_thumbnail_async(video_id, _on_complete)

        # holder 를 video_id 로 기억해 나중에 찾음
        holder._gurunote_thumb_video_id = video_id  # type: ignore[attr-defined]
        holder._gurunote_placeholder = placeholder  # type: ignore[attr-defined]

    def _place_thumbnail(self, holder: ctk.CTkFrame, image_path, video_id: str) -> None:
        """PIL 로 이미지 로드해 CTkImage 로 holder 에 표시."""
        try:
            from PIL import Image  # type: ignore
            img = Image.open(image_path)
            ctk_img = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(self._THUMB_W, self._THUMB_H),
            )
            # GC 방지용 참조 유지
            self._thumb_refs[video_id] = ctk_img
            label = ctk.CTkLabel(holder, text="", image=ctk_img)
            label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception:  # noqa: BLE001
            ctk.CTkLabel(
                holder, text="🎬", font=ctk.CTkFont(size=22),
                text_color=C_TEXT_DIM,
            ).place(relx=0.5, rely=0.5, anchor="center")

    def _poll_thumb_queue(self) -> None:
        """비동기 다운로드 완료 메시지를 메인 스레드에서 처리.

        다이얼로그가 destroyed 된 뒤 pending `after()` 콜백이 한 번 더 실행되면
        `self._scroll.winfo_children()` 이 `_tkinter.TclError` 를 낼 수 있어
        전체 블록을 try/except 로 감싼다.
        """
        try:
            try:
                while True:
                    video_id, path = self._thumb_queue.get_nowait()
                    self._pending_thumb_ids.discard(video_id)
                    if path is None:
                        # 다운로드 실패: ⏳ 플레이스홀더를 🎬 로 교체
                        self._mark_thumbnail_failed(video_id)
                        continue
                    self._apply_thumbnail_to_cards(video_id, path)
            except queue.Empty:
                pass
        except Exception:  # noqa: BLE001 — TclError 등 widget-destroyed 경로
            return
        # 다이얼로그가 살아있을 때만 다음 poll 예약
        try:
            if self.winfo_exists():
                self.after(200, self._poll_thumb_queue)
        except Exception:  # noqa: BLE001
            pass

    def _apply_thumbnail_to_cards(self, video_id: str, path) -> None:
        """현재 그리드에서 해당 video_id 의 holder 들을 찾아 이미지 삽입."""
        for card in self._scroll.winfo_children():
            for child in card.winfo_children() if hasattr(card, "winfo_children") else []:
                vid = getattr(child, "_gurunote_thumb_video_id", None)
                if vid == video_id:
                    # 플레이스홀더 제거
                    ph = getattr(child, "_gurunote_placeholder", None)
                    if ph is not None:
                        try:
                            ph.destroy()
                        except Exception:  # noqa: BLE001
                            pass
                    self._place_thumbnail(child, path, video_id)

    def _mark_thumbnail_failed(self, video_id: str) -> None:
        """다운로드 실패한 video_id 의 ⏳ 을 🎬 로 교체 (스틱 상태 방지)."""
        for card in self._scroll.winfo_children():
            for child in card.winfo_children() if hasattr(card, "winfo_children") else []:
                vid = getattr(child, "_gurunote_thumb_video_id", None)
                if vid != video_id:
                    continue
                ph = getattr(child, "_gurunote_placeholder", None)
                if ph is not None:
                    try:
                        ph.destroy()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    ctk.CTkLabel(
                        child, text="🎬", font=ctk.CTkFont(size=22),
                        text_color=C_TEXT_DIM,
                    ).place(relx=0.5, rely=0.5, anchor="center")
                except Exception:  # noqa: BLE001
                    pass

    # =========================================================================
    # Actions (기존과 동일)
    # =========================================================================
    def _edit_note(self, job_id: str, title: str) -> None:
        """HistoryDialog 의 Edit 버튼 → 인라인 마크다운 편집기 다이얼로그."""
        md = get_job_markdown(job_id)
        if md is None:
            messagebox.showinfo("없음", "마크다운 파일이 없습니다.")
            return

        def _on_saved() -> None:
            # 저장 후 검색 캐시 무효화 + 그리드 재로드 (스니펫/카드 갱신)
            search_clear_cache()
            self._reload_and_refresh()

        NoteEditorDialog(self, job_id, title, md, on_saved=_on_saved)

    def _save_md(self, job_id: str, title: str) -> None:
        md = get_job_markdown(job_id)
        if not md:
            messagebox.showinfo("없음", "마크다운 파일이 없습니다.")
            return
        from gurunote.exporter import sanitize_filename
        path = filedialog.asksaveasfilename(
            title="마크다운 저장", defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            initialfile=f"GuruNote_{sanitize_filename(title)}.md",
        )
        if path:
            Path(path).write_text(md, encoding="utf-8")
            messagebox.showinfo("완료", f"저장됨:\n{path}")

    def _save_pdf(self, job_id: str, title: str) -> None:
        """저장된 마크다운을 PDF 로 내보낸다 (Phase C).

        패키지 미설치 시 설치 여부를 묻고, 승인하면 자동 설치 후 다시 저장
        플로우를 이어간다.
        """
        md = get_job_markdown(job_id)
        if not md:
            messagebox.showinfo("없음", "마크다운 파일이 없습니다.")
            return

        def _do_save() -> None:
            from gurunote.exporter import sanitize_filename
            path = filedialog.asksaveasfilename(
                title="PDF 저장", defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialfile=f"GuruNote_{sanitize_filename(title)}.pdf",
            )
            if not path:
                return
            try:
                markdown_to_pdf(md, Path(path), title=title)
                messagebox.showinfo("완료", f"PDF 저장됨:\n{path}")
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("PDF 저장 실패", str(e))

        if is_pdf_export_available():
            _do_save()
        else:
            _prompt_pdf_install(self, _do_save)

    def _save_obsidian(self, job_id: str, title: str) -> None:
        """저장된 마크다운을 Obsidian vault 로 전송 (Phase D).

        Vault 미설정 시 경고 대신 `ObsidianSetupDialog` 로 감지된 후보 + 폴더
        피커를 띄워 즉시 설정하고 저장 플로우를 이어간다.
        """
        md = get_job_markdown(job_id)
        if not md:
            messagebox.showinfo("없음", "마크다운 파일이 없습니다.")
            return

        from gurunote.exporter import sanitize_filename
        filename = f"GuruNote_{sanitize_filename(title)}.md"

        def _do_save(vault: Path) -> None:
            try:
                out = obsidian_save(
                    md, filename=filename, vault_path=vault,
                    subfolder=obsidian_subfolder(),
                )
                ObsidianSaveDialog(self, saved_path=out, vault_path=vault)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Obsidian 저장 실패", str(e))

        _prompt_obsidian_setup(self, _do_save)

    def _save_notion(self, job_id: str, title: str) -> None:
        """저장된 마크다운을 Notion 으로 전송 (Phase E).

        API 호출은 worker thread 로 던지고 `after()` 로 결과 폴링 — 히스토리
        다이얼로그가 freeze 되지 않음.
        """
        md = get_job_markdown(job_id)
        if not md:
            messagebox.showinfo("없음", "마크다운 파일이 없습니다.")
            return
        if not is_notion_sync_available():
            messagebox.showwarning("Notion 미지원", notion_missing_hint())
            return
        token = os.environ.get("NOTION_TOKEN", "").strip()
        parent_id = os.environ.get("NOTION_PARENT_ID", "").strip()
        parent_type = (os.environ.get("NOTION_PARENT_TYPE", "database") or "database").strip().lower()
        if not token or not parent_id:
            messagebox.showwarning(
                "Notion 미설정",
                "Settings 에서 `NOTION_TOKEN` 과 `NOTION_PARENT_ID` 를 지정하세요.",
            )
            return

        result_q: queue.Queue = queue.Queue()
        is_db = (parent_type == "database")

        def _worker():
            try:
                url = notion_save(md, title=title, token=token,
                                  parent_id=parent_id, is_database=is_db)
                result_q.put(("ok", url))
            except Exception as exc:  # noqa: BLE001
                result_q.put(("err", str(exc)))

        # 즉시 피드백 다이얼로그 없이 기본 cursor 를 "watch" 로 바꿔 진행 중임을 표시
        self.configure(cursor="watch")
        threading.Thread(target=_worker, daemon=True).start()
        self._poll_notion_from_history(result_q)

    def _poll_notion_from_history(self, q: "queue.Queue") -> None:
        """HistoryDialog 의 Notion 버튼 전용 결과 폴링 (200ms).

        다이얼로그 destroyed 후에도 stale `after()` 가 한 번 더 실행될 수
        있어 `winfo_exists` / `after` / `configure` 모두 TclError 방어.
        """
        try:
            status, payload = q.get_nowait()
        except queue.Empty:
            try:
                if self.winfo_exists():
                    self.after(200, lambda: self._poll_notion_from_history(q))
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            self.configure(cursor="")
        except Exception:  # noqa: BLE001
            pass
        if status == "ok":
            if messagebox.askyesno("Notion 전송 완료", f"{payload}\n\n브라우저에서 열까요?"):
                import webbrowser
                webbrowser.open(payload)
        else:
            messagebox.showerror("Notion 전송 실패", payload)

    def _show_log(self, job_id: str) -> None:
        log = get_job_log(job_id) or "(로그 없음)"
        win = ctk.CTkToplevel(self)
        win.title(f"Log - {job_id}")
        win.geometry("600x400")
        tb = ctk.CTkTextbox(win, font=ctk.CTkFont(size=12), wrap="word")
        tb.pack(fill="both", expand=True, padx=10, pady=10)
        tb.insert("1.0", log)
        tb.configure(state="disabled")

    def _delete(self, job_id: str) -> None:
        if messagebox.askyesno("삭제", "이 작업 기록을 삭제할까요?"):
            delete_job(job_id)
            self._reload_and_refresh()

    def _on_rebuild_index(self) -> None:
        """
        `~/.gurunote/jobs/` 폴더 스캔 → `history.json` 재생성.

        사용 케이스:
          - history.json 삭제/손상 복구
          - 다른 머신에서 jobs/ 폴더만 복사해 왔을 때 마이그레이션
        """
        if not messagebox.askyesno(
            "히스토리 인덱스 재생성",
            "~/.gurunote/jobs/ 폴더를 스캔해 history.json 을 다시 만듭니다.\n"
            "기존 인덱스는 덮어쓰여지며 잡 파일들은 건드리지 않습니다.\n\n"
            "계속할까요?",
        ):
            return
        try:
            result = rebuild_index()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("인덱스 재생성 실패", str(exc))
            return

        msg = (
            f"스캔: {result['total_scanned']} 폴더\n"
            f"인덱스 등록: {result['indexed']} 건"
        )
        if result["errors"]:
            msg += f"\n손상/누락 (건너뜀): {len(result['errors'])}"
            if len(result["errors"]) <= 5:
                msg += "\n  " + "\n  ".join(result["errors"])
        if result["missing_md"]:
            msg += f"\nmetadata 에만 있고 result.md 없음: {len(result['missing_md'])}"
        messagebox.showinfo("인덱스 재생성 완료", msg)
        # 검색 캐시도 함께 클리어하고 다시 그리기
        search_clear_cache()
        self._reload_and_refresh()


class PDFInstallDialog(ctk.CTkToplevel):
    """PDF 출력 의존성 자동 설치 진행 다이얼로그.

    `plan.can_run_automatically` 가 True 면 백그라운드 스레드에서 pip/brew
    커맨드를 순차 실행하며 stdout 을 실시간 표시한다. False (수동 환경) 면
    안내 텍스트만 보여주고 닫기 버튼으로 종료한다.

    `on_success` 콜백은 설치 성공 시 메인 스레드에서 호출돼, 원래 사용자가
    누른 "Save PDF" 액션을 이어 실행할 수 있게 한다.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        plan: "pdf_installer.InstallPlan",
        on_success: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("PDF 출력 패키지 설치")
        self.geometry("560x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._plan = plan
        self._on_success = on_success
        self._msg_queue: queue.Queue[str] = queue.Queue()
        self._done_queue: queue.Queue[dict] = queue.Queue()

        ctk.CTkLabel(
            self, text="PDF 출력 패키지 설치 중...",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(padx=20, pady=(20, 4), anchor="w")

        summary = " → ".join(s.label for s in plan.steps) if plan.steps else "수동 설치 안내"
        ctk.CTkLabel(
            self, text=summary,
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            wraplength=520, justify="left",
        ).pack(padx=20, pady=(0, 8), anchor="w")

        self._log_text = ctk.CTkTextbox(
            self, font=ctk.CTkFont(size=12), state="disabled", wrap="word",
        )
        self._log_text.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._close_btn = ctk.CTkButton(
            self, text="닫기", width=100, height=32, state="disabled",
            command=self.destroy,
        )
        self._close_btn.pack(padx=20, pady=(0, 16), anchor="e")

        if plan.can_run_automatically and plan.steps:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._poll()
        else:
            # 수동 안내만 표시하고 즉시 닫기 활성화
            self._log(plan.manual_instructions or "설치할 것이 없습니다.")
            self._flush()
            self._close_btn.configure(state="normal")

    def _log(self, msg: str) -> None:
        self._msg_queue.put(msg)

    def _run(self) -> None:
        try:
            ok = pdf_installer.run_plan(self._plan, self._log)
        except Exception as exc:  # noqa: BLE001
            self._done_queue.put({"ok": False, "error": str(exc)})
            return
        self._done_queue.put({"ok": ok})

    def _flush(self) -> None:
        while True:
            try:
                msg = self._msg_queue.get_nowait()
                self._log_text.configure(state="normal")
                self._log_text.insert("end", msg + "\n")
                self._log_text.see("end")
                self._log_text.configure(state="disabled")
            except queue.Empty:
                break

    def _poll(self) -> None:
        self._flush()
        try:
            result = self._done_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return

        self._close_btn.configure(state="normal")
        if result.get("ok"):
            messagebox.showinfo(
                "설치 완료",
                "PDF 출력 패키지가 준비되었습니다. 이어서 저장합니다.",
                parent=self,
            )
            self.destroy()
            if self._on_success is not None:
                try:
                    self._on_success()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showerror("PDF 저장 실패", str(exc))
        else:
            messagebox.showerror(
                "설치 실패",
                result.get("error") or "설치 중 오류가 발생했습니다. 로그를 확인하세요.",
                parent=self,
            )


def _prompt_pdf_install(parent: ctk.CTk, on_success: Callable[[], None]) -> None:
    """PDF 의존성 미설치 시 설치 여부를 묻고, 승인하면 PDFInstallDialog 실행."""
    plan = pdf_installer.plan_installation()
    if plan.is_empty:
        # 이미 설치됨 — 곧바로 실행
        on_success()
        return

    if plan.can_run_automatically and plan.steps:
        msg_lines = [
            "PDF 출력에 필요한 패키지가 설치되어 있지 않습니다.",
            "",
            "지금 자동으로 설치하시겠습니까?",
            "",
            "수행할 단계:",
        ]
        msg_lines += [f"  {i+1}. {s.label}" for i, s in enumerate(plan.steps)]
        if not messagebox.askyesno(
            "PDF 출력 패키지 설치",
            "\n".join(msg_lines),
            parent=parent,
        ):
            return
        PDFInstallDialog(parent, plan, on_success=on_success)
    else:
        # 수동 — 안내 다이얼로그만
        PDFInstallDialog(parent, plan, on_success=None)


class ObsidianSetupDialog(ctk.CTkToplevel):
    """Obsidian vault 경로를 간편히 설정하는 다이얼로그.

    자동 감지된 vault 후보를 리스트로 보여주고, 사용자가 한 번의 클릭으로
    선택하거나 "폴더 찾아보기" 버튼으로 직접 피커를 띄울 수 있다. 저장 시
    `save_settings({"OBSIDIAN_VAULT_PATH": ...})` 로 `.env` 에 기록되며,
    메모리 환경변수도 갱신되어 즉시 반영된다.

    `on_vault_set(vault_path)` 콜백이 성공 시 호출되면, 호출자는 원래
    사용자가 누른 "→ Obsidian" 저장 플로우를 이어갈 수 있다.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        on_vault_set: Optional[Callable[[Path], None]] = None,
    ) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("Obsidian Vault 설정")
        self.geometry("620x460")
        self.transient(parent)
        self.grab_set()
        self._on_vault_set = on_vault_set
        self._build_ui()
        self.after(80, self.focus_force)

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="Obsidian Vault 선택",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(padx=20, pady=(18, 4), anchor="w")
        ctk.CTkLabel(
            self,
            text=(
                "선택한 폴더에 GuruNote 노트가 자동으로 저장됩니다. "
                "`.obsidian/` 폴더가 있는 경로가 유효한 vault 입니다."
            ),
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            wraplength=580, justify="left",
        ).pack(padx=20, pady=(0, 10), anchor="w")

        # 자동 감지 목록
        ctk.CTkLabel(
            self, text="자동 감지된 vault",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(padx=20, pady=(4, 2), anchor="w")

        list_frame = ctk.CTkScrollableFrame(self, height=220, fg_color=C_SURFACE)
        list_frame.pack(fill="x", expand=False, padx=20, pady=(0, 10))
        list_frame.grid_columnconfigure(0, weight=1)

        candidates = find_vault_candidates()
        if not candidates:
            ctk.CTkLabel(
                list_frame,
                text=(
                    "감지된 vault 가 없습니다. 아래 '폴더 찾아보기' 로 수동 선택하세요."
                ),
                text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
            ).grid(row=0, column=0, padx=10, pady=12, sticky="w")
        else:
            home = str(Path.home())
            for i, vault in enumerate(candidates):
                display = str(vault)
                # 홈 디렉토리는 `~` 로 줄여서 더 읽기 쉽게
                if display.startswith(home):
                    display = "~" + display[len(home):]
                btn = ctk.CTkButton(
                    list_frame,
                    text=f"✓  {display}",
                    anchor="w", height=32,
                    fg_color="gray25", hover_color=C_PRIMARY,
                    command=lambda v=vault: self._select_vault(v),
                )
                btn.grid(row=i, column=0, sticky="ew", padx=6, pady=3)

        # 하단 버튼 바
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=(6, 16))
        ctk.CTkButton(
            btn_bar, text="폴더 찾아보기...", width=140, height=32,
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
            command=self._on_browse,
        ).pack(side="left")
        ctk.CTkButton(
            btn_bar, text="취소", width=100, height=32,
            fg_color="gray40", command=self.destroy,
        ).pack(side="right")

    # -------------------------------------------------------------------------
    def _on_browse(self) -> None:
        initial = str(Path.home() / "Documents")
        picked = filedialog.askdirectory(
            parent=self, title="Obsidian vault 폴더 선택", initialdir=initial,
        )
        if not picked:
            return
        self._select_vault(Path(picked))

    def _select_vault(self, vault: Path) -> None:
        vault = Path(vault).expanduser().resolve()
        if not vault.is_dir():
            messagebox.showerror(
                "폴더 없음", f"존재하지 않는 폴더입니다:\n{vault}", parent=self,
            )
            return
        if not is_obsidian_vault(vault):
            if not messagebox.askyesno(
                "Obsidian vault 아님",
                (
                    f"이 폴더에 `.obsidian/` 이 없습니다:\n{vault}\n\n"
                    "그래도 이 경로를 사용할까요?\n"
                    "(Obsidian 이 이 폴더를 처음 열면 `.obsidian/` 가 자동 생성됩니다.)"
                ),
                parent=self,
            ):
                return

        # .env 저장 + 환경변수 즉시 반영
        try:
            save_settings({"OBSIDIAN_VAULT_PATH": str(vault)}, create_backup=True)
            os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "저장 실패", f"설정 저장 중 오류가 발생했습니다:\n{exc}", parent=self,
            )
            return

        self.destroy()
        if self._on_vault_set is not None:
            try:
                self._on_vault_set(vault)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Obsidian 저장 실패", str(exc))


def _prompt_obsidian_setup(
    parent: ctk.CTk,
    on_vault_set: Callable[[Path], None],
) -> None:
    """Vault 미설정 시 안내 + 자동 감지/피커 다이얼로그 실행.

    사용자가 이미 경로를 설정했으면 바로 `on_vault_set` 을 호출한다.
    """
    vault = obsidian_vault()
    if vault is not None:
        on_vault_set(vault)
        return
    # 설정되지 않은 경우: 설치형 확인 대신 즉시 ObsidianSetupDialog 오픈.
    # (사용자가 이 단계에서 취소하면 아무 일도 일어나지 않는다.)
    ObsidianSetupDialog(parent, on_vault_set=on_vault_set)


class ObsidianSaveDialog(ctk.CTkToplevel):
    """Obsidian 저장 성공 다이얼로그.

    기존엔 `messagebox.showinfo` 로 긴 파일 경로만 출력하는 "성의 없는 팝업"
    이었던 걸 교체. 파일명 + vault 요약 + 다음 액션 버튼 (Obsidian 에서 열기 /
    폴더 보기 / 닫기) 를 제공한다.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        saved_path: Path,
        vault_path: Path,
    ) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("Obsidian 저장 완료")
        self.geometry("520x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._saved_path = Path(saved_path)
        self._vault_path = Path(vault_path)
        self._build_ui()
        self.after(80, self.focus_force)

    def _build_ui(self) -> None:
        # 제목 + 체크 아이콘
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(22, 8))
        ctk.CTkLabel(
            header, text="Obsidian 에 저장되었습니다",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w")

        # 파일명 + vault 경로 (요약)
        body = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=10)
        body.pack(fill="x", padx=22, pady=(0, 14))
        ctk.CTkLabel(
            body, text=self._saved_path.name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C_TEXT, wraplength=460, anchor="w", justify="left",
        ).pack(fill="x", padx=14, pady=(12, 4), anchor="w")

        try:
            rel = self._saved_path.relative_to(self._vault_path)
            rel_display = f"Vault: {self._vault_path.name}  ·  {rel.parent if str(rel.parent) != '.' else '(루트)'}"
        except ValueError:
            rel_display = str(self._saved_path.parent)
        ctk.CTkLabel(
            body, text=rel_display,
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_DIM, wraplength=460, anchor="w", justify="left",
        ).pack(fill="x", padx=14, pady=(0, 12), anchor="w")

        # 버튼 바
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=22, pady=(0, 20))

        ctk.CTkButton(
            btn_bar, text="Obsidian 에서 열기", width=160, height=34,
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
            font=ctk.CTkFont(weight="bold"),
            command=self._open_in_obsidian,
        ).pack(side="left")
        ctk.CTkButton(
            btn_bar, text="폴더 보기", width=100, height=34,
            fg_color="gray35", hover_color="gray45",
            command=self._reveal_in_finder,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            btn_bar, text="닫기", width=80, height=34,
            fg_color="gray40", command=self.destroy,
        ).pack(side="right")

    # -------------------------------------------------------------------------
    def _open_in_obsidian(self) -> None:
        """`obsidian://open?path=...` URL 스킴으로 Obsidian 앱에서 노트 열기."""
        import subprocess
        import urllib.parse

        url = "obsidian://open?path=" + urllib.parse.quote(str(self._saved_path))
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", url], check=False)
            elif sys.platform.startswith("win"):
                os.startfile(url)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", url], check=False)
            self.destroy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(
                "Obsidian 열기 실패",
                f"Obsidian 앱이 설치되어 있지 않거나 URL 처리에 실패했습니다.\n"
                f"\n{exc}",
                parent=self,
            )

    def _reveal_in_finder(self) -> None:
        """파일이 위치한 폴더를 OS 기본 파일 탐색기에서 열기."""
        import subprocess

        target = self._saved_path
        try:
            if sys.platform == "darwin":
                # `-R` 로 파일을 선택 상태로 보여줌
                subprocess.run(["open", "-R", str(target)], check=False)
            elif sys.platform.startswith("win"):
                subprocess.run(["explorer", "/select,", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target.parent)], check=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(
                "폴더 열기 실패", str(exc), parent=self,
            )


class GitAuthErrorDialog(ctk.CTkToplevel):
    """git pull 인증 실패 시 사용자에게 해결 옵션을 제시하는 다이얼로그.

    시나리오:
      - 사용자가 GitHub 에 OAuth (구글 로그인) 로만 가입해 password 가 없음.
      - 저장소가 **비공개** 면 tarball 도 못 받아서 반드시 인증이 필요.

    제시 옵션 (비공개 저장소 기준 우선순위):
      1. GitHub CLI `gh auth login` — 브라우저 OAuth 플로우, 로그인 후
         git 이 자동으로 credential helper 를 통해 토큰 사용.
         gh 미설치 시 설치 안내.
      2. Personal Access Token — github.com/settings/tokens/new 로 이동.
      3. 공개 저장소라면 tarball 폴백 — 버튼으로 제공.
      4. 닫기.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        on_retry: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("GitHub 인증 필요")
        self.geometry("560x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._on_retry = on_retry
        self._build_ui()
        self.after(80, self.focus_force)

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="GitHub 인증이 필요합니다",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(padx=22, pady=(22, 4), anchor="w")

        ctk.CTkLabel(
            self,
            text=(
                "저장소가 비공개이거나 공개 여부를 확인할 수 없어 인증이 필요합니다.\n"
                "구글 OAuth 로만 로그인한 계정은 password 가 없으므로 "
                "아래 방법 중 하나로 토큰을 발급받으세요.\n"
                "(저장소를 공개로 전환하면 인증 없이 자동 업데이트가 동작합니다.)"
            ),
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            wraplength=500, justify="left",
        ).pack(padx=22, pady=(0, 14), anchor="w")

        # --- 옵션 1: GitHub CLI (권장) ---
        opt1 = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=10)
        opt1.pack(fill="x", padx=22, pady=(0, 8))
        ctk.CTkLabel(
            opt1, text="방법 1  ·  GitHub CLI (권장)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=14, pady=(10, 2), anchor="w")
        ctk.CTkLabel(
            opt1,
            text="brew 로 gh 를 설치한 뒤 브라우저 OAuth 로 로그인합니다. 한 번 로그인하면 git 이 자동으로 토큰을 사용합니다.",
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            wraplength=480, justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")
        ctk.CTkButton(
            opt1, text="GitHub CLI 로 로그인하기",
            width=220, height=32,
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
            command=self._run_gh_auth,
        ).pack(padx=14, pady=(0, 12), anchor="w")

        # --- 옵션 2: PAT ---
        opt2 = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=10)
        opt2.pack(fill="x", padx=22, pady=(0, 8))
        ctk.CTkLabel(
            opt2, text="방법 2  ·  Personal Access Token",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=14, pady=(10, 2), anchor="w")
        ctk.CTkLabel(
            opt2,
            text="github.com 설정에서 repo 권한 토큰을 만들고, git prompt 의 password 자리에 붙여 넣으면 됩니다.",
            font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
            wraplength=480, justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")
        ctk.CTkButton(
            opt2, text="토큰 생성 페이지 열기",
            width=220, height=32,
            fg_color="gray35", hover_color="gray45",
            command=self._open_token_page,
        ).pack(padx=14, pady=(0, 12), anchor="w")

        # --- 하단 버튼 ---
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(fill="x", padx=22, pady=(6, 16))
        ctk.CTkButton(
            btn_bar, text="닫기", width=100, height=32,
            fg_color="gray40", command=self.destroy,
        ).pack(side="right")
        if self._on_retry is not None:
            ctk.CTkButton(
                btn_bar, text="다시 시도", width=120, height=32,
                fg_color=C_PRIMARY, hover_color=C_PRIMARY_HO,
                command=self._retry,
            ).pack(side="right", padx=(0, 8))

    # -------------------------------------------------------------------------
    def _retry(self) -> None:
        cb = self._on_retry
        self.destroy()
        if cb is not None:
            try:
                cb()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("업데이트 실패", str(exc))

    def _open_token_page(self) -> None:
        import webbrowser
        webbrowser.open(
            "https://github.com/settings/tokens/new?"
            "scopes=repo&description=GuruNote%20updater",
        )

    def _run_gh_auth(self) -> None:
        """GitHub CLI 로그인 — gh 설치 체크 → 미설치면 안내, 설치됨이면 실행."""
        import shutil
        import subprocess as _sp

        gh_path = shutil.which("gh")
        if gh_path is None:
            if sys.platform == "darwin":
                install_cmd = "brew install gh"
            elif sys.platform.startswith("win"):
                install_cmd = "winget install GitHub.cli"
            else:
                install_cmd = "sudo apt install gh  (또는 https://cli.github.com/)"
            messagebox.showinfo(
                "GitHub CLI 미설치",
                (
                    "GitHub CLI (gh) 가 설치되어 있지 않습니다.\n\n"
                    "터미널에서 아래 명령으로 설치한 뒤 이 버튼을 다시 누르세요.\n\n"
                    f"    {install_cmd}"
                ),
                parent=self,
            )
            return

        # gh auth login 은 device code 입력을 요구하는 대화형 커맨드.
        # macOS: Terminal.app 에 새 창을 띄워서 실행 → 사용자가 브라우저
        # OAuth 완료 후 Terminal 에서 엔터를 누르면 끝. 끝나면 "다시 시도" 를
        # 눌러 업데이트 재실행 하면 됨.
        try:
            if sys.platform == "darwin":
                # AppleScript 로 새 Terminal 창에서 gh auth login 실행
                script = (
                    "tell application \"Terminal\"\n"
                    "  activate\n"
                    f"  do script \"{gh_path} auth login --hostname github.com "
                    "--git-protocol https --web && "
                    "echo '--- 로그인 완료. 이 창을 닫고 GuruNote 에서 \"다시 시도\" 를 누르세요. ---'\"\n"
                    "end tell"
                )
                _sp.run(["osascript", "-e", script], check=False)
            elif sys.platform.startswith("win"):
                # cmd /K 로 새 콘솔 창에서 실행
                _sp.Popen(
                    ["cmd", "/K", gh_path, "auth", "login",
                     "--hostname", "github.com", "--git-protocol", "https", "--web"],
                    creationflags=0x00000010,  # CREATE_NEW_CONSOLE
                )
            else:
                # Linux: xterm 이나 gnome-terminal 시도
                for term in ("x-terminal-emulator", "gnome-terminal", "xterm"):
                    if shutil.which(term):
                        _sp.Popen([
                            term, "-e", gh_path, "auth", "login",
                            "--hostname", "github.com",
                            "--git-protocol", "https", "--web",
                        ])
                        break
                else:
                    messagebox.showinfo(
                        "터미널 필요",
                        f"터미널에서 직접 실행해주세요:\n\n  {gh_path} auth login --web",
                        parent=self,
                    )
                    return
            messagebox.showinfo(
                "GitHub 로그인 시작",
                (
                    "터미널 창에서 GitHub CLI 로그인을 완료하세요.\n"
                    "브라우저가 열리면 device code 를 입력하고 승인하면 됩니다.\n\n"
                    "완료 후 이 다이얼로그에서 '다시 시도' 를 누르세요."
                ),
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "GitHub CLI 실행 실패", str(exc), parent=self,
            )


class UpdateProgressDialog(ctk.CTkToplevel):
    """업데이트 진행 상황을 실시간 표시하는 다이얼로그."""

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("GuruNote · 업데이트")
        self.geometry("520x340")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._msg_queue: queue.Queue[str] = queue.Queue()
        self._done_queue: queue.Queue[dict] = queue.Queue()

        ctk.CTkLabel(
            self, text="업데이트 진행 중...",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(padx=20, pady=(20, 8), anchor="w")

        self._log_text = ctk.CTkTextbox(self, font=ctk.CTkFont(size=12), state="disabled", wrap="word")
        self._log_text.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._status_label = ctk.CTkLabel(
            self, text="git fetch...", font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM,
        )
        self._status_label.pack(padx=20, pady=(0, 16), anchor="w")

        # 백그라운드 스레드에서 실행
        self._thread = threading.Thread(target=self._run_update, daemon=True)
        self._thread.start()
        self._poll()

    def _log(self, msg: str) -> None:
        self._msg_queue.put(msg)

    def _run_update(self) -> None:
        try:
            update_project(self._log, upgrade_deps=True)
            self._done_queue.put({"ok": True})
        except GitAuthError as exc:
            # 인증 실패 — 메인 스레드가 GitAuthErrorDialog 를 띄울 수 있게 표시.
            self._done_queue.put({"ok": False, "auth_error": True, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._done_queue.put({"ok": False, "error": str(exc)})

    def _poll(self) -> None:
        while True:
            try:
                msg = self._msg_queue.get_nowait()
                self._log_text.configure(state="normal")
                self._log_text.insert("end", msg + "\n")
                self._log_text.see("end")
                self._log_text.configure(state="disabled")
                # 마지막 줄을 status 에도 표시
                short = msg.strip()[:60]
                self._status_label.configure(text=short)
            except queue.Empty:
                break

        try:
            result = self._done_queue.get_nowait()
            if result.get("ok"):
                # 업데이트 성공 → 자동 재시작.
                # 짧은 지연(700ms) 으로 사용자가 "완료 · 재시작 중..." 상태를
                # 인지할 수 있게 함. 이후 `_restart_app` 가 현재 프로세스를
                # 교체 (execv) 또는 subprocess Popen + sys.exit 폴백.
                self._status_label.configure(text="업데이트 완료!  ·  재시작 중…")
                self.after(700, self._restart_app)
            elif result.get("auth_error"):
                # GitHub 인증 실패 — 전용 가이드 다이얼로그 (GitHub CLI / PAT)
                self._status_label.configure(text="GitHub 인증 필요")
                parent = self.master
                self.destroy()
                GitAuthErrorDialog(
                    parent,
                    on_retry=lambda: UpdateProgressDialog(parent),
                )
            else:
                self._status_label.configure(text="업데이트 실패")
                messagebox.showerror("실패", result.get("error", "알 수 없는 오류"))
                self.destroy()
            return
        except queue.Empty:
            pass

        self.after(100, self._poll)

    def _restart_app(self) -> None:
        """현재 Python 프로세스를 교체해 앱을 재시작.

        전략:
        1. PyInstaller 번들: `sys.executable` 자체가 번들 바이너리이므로
           그대로 재실행.
        2. `python gui.py` 실행: `sys.executable + sys.argv` 로 재실행.
        3. `os.execv` 로 in-place 교체 시도 → 실패 시 `subprocess.Popen` +
           `sys.exit` 로 폴백 (일부 macOS .app 번들에서 execv 가 부모
           launchd 와 충돌하는 경우 대비).

        주의:
        - 실행 중인 파이프라인 worker 가 있다면 강제 종료됨 (프로세스 종료
          → daemon 스레드 함께 종료). 업데이트를 시작한 시점에 이미 user
          가 작업 중단을 선택한 것으로 간주.
        - Tkinter root 는 `sys.exit` 직전 destroy 하지 않음 — subprocess
          폴백 시에만 destroy (execv 는 즉시 프로세스 교체라 불필요).
        """
        import subprocess as _sp

        # 재실행 인자 결정
        if getattr(sys, "frozen", False):
            # PyInstaller 번들 — sys.executable 이 곧 앱 바이너리
            args = [sys.executable]
        else:
            # `python gui.py` 계열 실행
            args = [sys.executable, *sys.argv]

        # 1차 시도: os.execv 로 현재 프로세스 in-place 교체
        try:
            os.execv(args[0], args)
            return  # execv 가 성공하면 이 줄은 실행되지 않음
        except OSError:
            pass

        # 2차 폴백: detached subprocess 로 새 프로세스 띄우고 현재 종료
        try:
            _sp.Popen(args, close_fds=True, start_new_session=True)
        except Exception:  # noqa: BLE001
            # 마지막 수단 — 재시작 실패 알림 후 그대로 종료
            messagebox.showwarning(
                "재시작 실패",
                "자동 재시작이 불가능합니다. 앱을 수동으로 다시 실행해주세요.",
            )
        finally:
            # 현재 Tk root 정리 + 프로세스 종료
            try:
                root = self.master
                if root is not None:
                    root.destroy()
            except Exception:  # noqa: BLE001
                pass
            sys.exit(0)


class SettingsDialog(ctk.CTkToplevel):
    """API 키/모델/통합 설정 다이얼로그 — 5섹션 구조 (일반 / AI Provider /
    STT·하드웨어 / 연동 / 고급).

    Phase 2a-i 에서 긴 단일 폼을 섹션형으로 재배치. 필드 자체와 저장/테스트
    로직은 이전과 동일 — `self._entries[env_key]` dict 에 widget 참조를
    보관하므로 `_on_save` / `_on_test_connection` / `_apply_preset` 가 그대로
    동작. Provider 조건부 노출(필드 숨김), secret 지우기 액션, sticky footer,
    dirty state 는 후속 2a-ii / 2a-iii 에서 추가.
    """

    # 하드웨어 프리셋이 자동으로 채워주는 필드 목록
    _PRESET_DRIVEN_FIELDS = (
        "LLM_TEMPERATURE",
        "LLM_TRANSLATION_MAX_TOKENS",
        "LLM_SUMMARY_MAX_TOKENS",
        "WHISPERX_MODEL",
        "WHISPERX_BATCH_SIZE",
        "MLX_WHISPER_MODEL",
    )

    # 섹션별 필드 그룹 — 렌더 순서대로. LLM_PROVIDER 는 '일반' 섹션에서 특수
    # 처리 (드롭다운), 나머지는 Entry. 하드웨어 프리셋 드롭다운은 STT 섹션
    # 헤더 바로 아래에 별도로 삽입.
    _FIELD_GROUPS: dict[str, list[tuple[str, str, bool]]] = {
        "일반": [
            ("LLM_PROVIDER", "LLM Provider", False),
        ],
        "AI Provider": [
            ("OPENAI_API_KEY", "OpenAI API Key", True),
            ("OPENAI_BASE_URL", "OpenAI Base URL (Local/Compatible)", False),
            ("OPENAI_MODEL", "OpenAI 모델", False),
            ("ANTHROPIC_API_KEY", "Anthropic API Key", True),
            ("ANTHROPIC_MODEL", "Anthropic 모델", False),
            ("GOOGLE_API_KEY", "Google Gemini API Key", True),
            ("GEMINI_MODEL", "Gemini 모델", False),
        ],
        "STT · 하드웨어": [
            ("ASSEMBLYAI_API_KEY", "AssemblyAI API Key (폴백용)", True),
            ("WHISPERX_MODEL", "WhisperX 모델 (NVIDIA)", False),
            ("WHISPERX_BATCH_SIZE", "WhisperX 배치 사이즈 (NVIDIA)", False),
            ("MLX_WHISPER_MODEL", "MLX Whisper 모델 (Apple Silicon)", False),
            ("HUGGINGFACE_TOKEN", "HuggingFace 토큰 (화자 분리용)", True),
        ],
        "연동": [
            ("OBSIDIAN_VAULT_PATH", "Obsidian Vault 경로", False),
            ("OBSIDIAN_SUBFOLDER", "Obsidian 하위 폴더 (기본 GuruNote)", False),
            ("NOTION_TOKEN", "Notion Integration Token", True),
            ("NOTION_PARENT_ID", "Notion Parent ID (database/page UUID)", False),
            ("NOTION_PARENT_TYPE", "Notion Parent Type (database/page)", False),
        ],
        "고급": [
            ("LLM_TEMPERATURE", "LLM Temperature", False),
            ("LLM_TRANSLATION_MAX_TOKENS", "번역 Max Tokens", False),
            ("LLM_SUMMARY_MAX_TOKENS", "요약 Max Tokens", False),
        ],
    }

    _PLACEHOLDERS: dict[str, str] = {
        "OPENAI_MODEL": "gpt-5.4",
        "OPENAI_BASE_URL": "http://127.0.0.1:8000/v1",
        "ANTHROPIC_MODEL": "claude-sonnet-4-6",
        "GEMINI_MODEL": "gemini-2.5-flash",
        "LLM_TEMPERATURE": "0.2",
        "LLM_TRANSLATION_MAX_TOKENS": "8192",
        "LLM_SUMMARY_MAX_TOKENS": "4096",
        "WHISPERX_MODEL": "distil-large-v3",
        "WHISPERX_BATCH_SIZE": "16",
        "MLX_WHISPER_MODEL": "mlx-community/whisper-large-v3-mlx",
        "OBSIDIAN_VAULT_PATH": "/Users/me/Documents/MyVault",
        "OBSIDIAN_SUBFOLDER": "GuruNote",
        "NOTION_PARENT_ID": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
        "NOTION_PARENT_TYPE": "database",
    }

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        _apply_app_icon(self)
        self.title("GuruNote · 설정")
        self.geometry("680x760")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=ut.C_BG)

        # env_key → widget (CTkEntry / ctk.StringVar for LLM_PROVIDER)
        self._entries: dict[str, object] = {}
        # env_key → bool (secret 보기 토글 상태)
        self._show_vars: dict[str, bool] = {}
        # env_key → [label, input, aux_btn, ...] — Phase 2a-ii provider 조건부 토글용
        self._field_widgets: dict[str, list] = {}

        self._build_ui()
        # 초기 provider 에 맞춰 조건부 필드 가시성 적용
        initial_provider = self._entries["LLM_PROVIDER"].get()
        self._apply_provider_visibility(initial_provider)
        self.after(100, self.focus_force)

    # ── 레이아웃 ─────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 1) 상단 헤더 (고정)
        self._build_header()
        # 2) 중앙 스크롤 본문 — 5개 섹션
        body = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
        )
        body.pack(fill="both", expand=True, padx=ut.SPACE_LG, pady=(0, ut.SPACE_SM))
        body.grid_columnconfigure(1, weight=1)

        row = 0
        for section_name, fields in self._FIELD_GROUPS.items():
            row = self._render_section_header(body, row, section_name)

            # STT 섹션 헤더 바로 아래에 하드웨어 프리셋 드롭다운 + helper 삽입
            if section_name == "STT · 하드웨어":
                row = self._render_hw_preset_row(body, row)

            for env_key, label, is_secret in fields:
                row = self._render_field_row(body, row, env_key, label, is_secret)

        # 다이얼로그 첫 오픈 시 auto 프리셋을 빈 필드에만 채움 (기존 .env 값 보존)
        self._apply_preset(AUTO_KEY, only_empty=True)

        # 3) 하단 액션 바 (고정)
        self._build_action_bar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=ut.SPACE_LG, pady=(ut.SPACE_LG, ut.SPACE_SM))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="설정",
            font=ctk.CTkFont(size=ut.FONT_HEADING, weight=ut.WEIGHT_BOLD),
            text_color=ut.C_TEXT, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text=".env 에 저장되며 대부분 즉시 반영됩니다.",
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM, anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(ut.SPACE_XXS, 0))

        ctk.CTkLabel(
            header,
            text=f"하드웨어 자동 감지  ·  {detect_description()}",
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_ACCENT, anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(ut.SPACE_XS, 0))

    def _render_section_header(self, parent, row: int, title: str) -> int:
        """섹션 제목 + 얇은 구분선을 row 에 배치하고 다음 row 인덱스 반환."""
        # 첫 섹션이 아니면 위쪽에 여백 + divider
        if row > 0:
            uc.divider(parent).grid(
                row=row, column=0, columnspan=3,
                sticky="ew", pady=(ut.SPACE_LG, ut.SPACE_SM),
            )
            row += 1

        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=ut.FONT_SECTION, weight=ut.WEIGHT_BOLD),
            text_color=ut.C_TEXT, anchor="w",
        ).grid(row=row, column=0, columnspan=3, sticky="w",
               pady=(0, ut.SPACE_SM))
        return row + 1

    def _render_hw_preset_row(self, parent, row: int) -> int:
        """STT 섹션에 하드웨어 프리셋 드롭다운 + helper 삽입."""
        ctk.CTkLabel(
            parent, text="하드웨어 프리셋",
            font=ctk.CTkFont(size=ut.FONT_BODY),
            text_color=ut.C_TEXT,
        ).grid(row=row, column=0, sticky="w", padx=(0, ut.SPACE_MD),
               pady=ut.SPACE_XS)

        self._preset_var = ctk.StringVar(value=hw_key_to_label(AUTO_KEY))
        ctk.CTkOptionMenu(
            parent, variable=self._preset_var,
            values=hw_dropdown_options(),
            command=self._on_preset_change,
            fg_color=ut.C_SURFACE_HI, button_color=ut.C_BORDER,
            text_color=ut.C_TEXT,
        ).grid(row=row, column=1, columnspan=2, sticky="ew", pady=ut.SPACE_XS)

        ctk.CTkLabel(
            parent,
            text="선택 시 아래 WhisperX / MLX / LLM 파라미터가 일괄 갱신됩니다. "
                 "개별 필드를 수정하면 '직접 입력' 모드.",
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM, anchor="w",
            wraplength=540, justify="left",
        ).grid(row=row + 1, column=0, columnspan=3, sticky="w",
               pady=(0, ut.SPACE_SM))
        return row + 2

    def _render_field_row(
        self, parent, row: int, env_key: str, label: str, is_secret: bool,
    ) -> int:
        """단일 필드 — 좌측 라벨, 중앙 입력, 우측 보조 버튼(secret/vault).

        Phase 2a-ii: 필드별 위젯을 `self._field_widgets[env_key]` 리스트로
        기록해 provider 조건부 show/hide 토글 시 한꺼번에 grid/grid_forget
        할 수 있도록 함. Secret 필드는 `보기` + `지우기` 두 버튼을 묶어서
        column 2 에 배치.
        """
        field_widgets: list = []

        lbl = ctk.CTkLabel(
            parent, text=label,
            font=ctk.CTkFont(size=ut.FONT_BODY),
            text_color=ut.C_TEXT, anchor="w",
        )
        lbl.grid(row=row, column=0, sticky="w", padx=(0, ut.SPACE_MD),
                 pady=ut.SPACE_XS)
        field_widgets.append(lbl)

        current_val = os.environ.get(env_key, "")

        # LLM_PROVIDER 는 OptionMenu, 나머지는 Entry
        if env_key == "LLM_PROVIDER":
            default = current_val if current_val in _LLM_PROVIDERS else "openai"
            provider_var = ctk.StringVar(value=default)
            menu = ctk.CTkOptionMenu(
                parent, variable=provider_var, values=_LLM_PROVIDERS,
                fg_color=ut.C_SURFACE_HI, button_color=ut.C_BORDER,
                text_color=ut.C_TEXT,
                command=self._apply_provider_visibility,
            )
            menu.grid(row=row, column=1, columnspan=2, sticky="ew",
                      pady=ut.SPACE_XS)
            field_widgets.append(menu)
            self._entries[env_key] = provider_var
            self._field_widgets[env_key] = field_widgets
            return row + 1

        ph = "미설정" if is_secret else self._PLACEHOLDERS.get(env_key, "")
        entry = ctk.CTkEntry(
            parent,
            show="•" if is_secret and current_val else "",
            placeholder_text=ph,
            fg_color=ut.C_BG, border_color=ut.C_BORDER, text_color=ut.C_TEXT,
        )
        if current_val:
            entry.insert(0, current_val)
        entry.grid(row=row, column=1, sticky="ew", pady=ut.SPACE_XS)
        field_widgets.append(entry)
        self._entries[env_key] = entry
        self._show_vars[env_key] = False

        if is_secret:
            # 보기 + 지우기 두 버튼을 transparent frame 으로 묶어 column 2 배치.
            aux = ctk.CTkFrame(parent, fg_color="transparent", height=1)
            aux.grid(row=row, column=2, padx=(ut.SPACE_XS, 0),
                     pady=ut.SPACE_XS, sticky="w")
            ctk.CTkButton(
                aux, text="보기", width=48, height=ut.HEIGHT_SM,
                corner_radius=ut.RADIUS_SM,
                fg_color=ut.C_SURFACE_HI, hover_color=ut.C_BORDER,
                text_color=ut.C_TEXT,
                font=ctk.CTkFont(size=ut.FONT_META),
                command=lambda k=env_key: self._toggle_show(k),
            ).pack(side="left")
            ctk.CTkButton(
                aux, text="지우기", width=56, height=ut.HEIGHT_SM,
                corner_radius=ut.RADIUS_SM,
                fg_color=ut.C_SURFACE_HI, hover_color=ut.C_DANGER,
                text_color=ut.C_TEXT,
                font=ctk.CTkFont(size=ut.FONT_META),
                command=lambda k=env_key: self._clear_secret(k),
            ).pack(side="left", padx=(ut.SPACE_XS, 0))
            field_widgets.append(aux)

        if env_key == "OBSIDIAN_VAULT_PATH":
            browse = ctk.CTkButton(
                parent, text="찾아보기", width=80, height=ut.HEIGHT_SM,
                corner_radius=ut.RADIUS_SM,
                fg_color=ut.C_PRIMARY, hover_color=ut.C_PRIMARY_HO,
                text_color=ut.C_ON_PRIMARY,
                font=ctk.CTkFont(size=ut.FONT_META),
                command=self._on_browse_vault,
            )
            browse.grid(row=row, column=2, padx=(ut.SPACE_XS, 0),
                        pady=ut.SPACE_XS)
            field_widgets.append(browse)
            # 유효성 chip (다음 row)
            self._vault_chip = ctk.CTkLabel(
                parent, text="",
                font=ctk.CTkFont(size=ut.FONT_META), anchor="w",
            )
            self._vault_chip.grid(
                row=row + 1, column=1, columnspan=2, sticky="w",
                pady=(0, ut.SPACE_XS),
            )
            field_widgets.append(self._vault_chip)
            entry.bind("<KeyRelease>", lambda _e: self._refresh_vault_chip())
            self._refresh_vault_chip()
            self._field_widgets[env_key] = field_widgets
            return row + 2

        self._field_widgets[env_key] = field_widgets
        return row + 1

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=ut.C_SIDEBAR, corner_radius=0)
        bar.pack(fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=ut.SPACE_LG, pady=ut.SPACE_MD)

        # 좌측: 연결 테스트 (ghost)
        uc.button(
            inner, text="연결 테스트", variant=ut.BTN_GHOST,
            command=self._on_test_connection,
            height=ut.HEIGHT_MD, width=110,
        ).pack(side="left")

        # 우측: 저장 (primary) + 취소 (secondary)
        uc.button(
            inner, text="저장", variant=ut.BTN_PRIMARY,
            command=self._on_save,
            height=ut.HEIGHT_MD, width=110,
            font_weight=ut.WEIGHT_BOLD,
        ).pack(side="right")
        uc.button(
            inner, text="취소", variant=ut.BTN_SECONDARY,
            command=self.destroy,
            height=ut.HEIGHT_MD, width=80,
        ).pack(side="right", padx=(0, ut.SPACE_SM))

    # ── Secret 필드 액션 ─────────────────────────────────────
    def _toggle_show(self, env_key: str) -> None:
        self._show_vars[env_key] = not self._show_vars[env_key]
        entry = self._entries[env_key]
        entry.configure(show="" if self._show_vars[env_key] else "•")

    def _clear_secret(self, env_key: str) -> None:
        """API Key 필드 초기화 — 저장 시 .env 에서 해당 항목이 지워짐."""
        entry = self._entries.get(env_key)
        if entry is None:
            return
        try:
            entry.delete(0, "end")
        except Exception:  # noqa: BLE001
            pass

    # ── Provider 조건부 필드 노출 (Phase 2a-ii) ──────────────
    # 선택한 LLM Provider 와 관련 없는 필드는 숨김. 예: anthropic 선택
    # 시 OPENAI_* / GOOGLE_* / GEMINI_* 필드는 grid_forget() 으로 숨김.
    _PROVIDER_FIELD_MAP: dict[str, tuple[str, ...]] = {
        "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"),
        "openai_compatible": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"),
        "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        "gemini": ("GOOGLE_API_KEY", "GEMINI_MODEL"),
    }

    # AI Provider 섹션에 속한 전체 provider-specific 필드 (숨김 후보)
    _ALL_PROVIDER_FIELDS: tuple[str, ...] = (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "GOOGLE_API_KEY", "GEMINI_MODEL",
    )

    def _apply_provider_visibility(self, provider: str) -> None:
        """선택된 provider 에 맞춰 provider-specific 필드만 노출."""
        visible = set(self._PROVIDER_FIELD_MAP.get(provider, ()))
        for env_key in self._ALL_PROVIDER_FIELDS:
            widgets = self._field_widgets.get(env_key, [])
            should_show = env_key in visible
            for w in widgets:
                if should_show:
                    # 최초 빌드 시 지정한 원래 grid 정보를 재사용.
                    try:
                        info = w.grid_info()
                    except Exception:  # noqa: BLE001
                        info = None
                    if info:
                        # 이미 grid 상태 — 아무것도 안 함
                        continue
                    # grid_forget 된 위젯을 다시 보여줘야 함. 하지만 원래
                    # grid 인자(row/column/padx/pady/sticky) 가 저장돼 있지
                    # 않으므로, 이 케이스에서는 재빌드를 요구. 대신 더 간단한
                    # 구현: 위젯의 grid 원래 설정은 `grid_configure` 히스토리
                    # 에서 복원 불가하므로, `_saved_grid_info` 로 이전 상태를
                    # 기록해둠.
                    saved = getattr(w, "_saved_grid_info", None)
                    if saved:
                        w.grid(**saved)
                else:
                    # 숨기기 전에 현재 grid 정보를 보존
                    try:
                        info = w.grid_info()
                        if info:
                            # 'in' 키는 grid() 호출 시 부모 프레임으로 대체
                            saved = {k: v for k, v in info.items() if k != "in"}
                            w._saved_grid_info = saved  # type: ignore[attr-defined]
                            w.grid_forget()
                    except Exception:  # noqa: BLE001
                        pass

    # -------------------------------------------------------------------------
    # Obsidian vault 편의 기능
    # -------------------------------------------------------------------------
    def _on_browse_vault(self) -> None:
        """'찾아보기' 버튼 — 폴더 피커 → OBSIDIAN_VAULT_PATH Entry 업데이트."""
        entry = self._entries.get("OBSIDIAN_VAULT_PATH")
        if entry is None:
            return
        current = entry.get().strip().strip('"').strip("'")
        initial = os.path.expanduser(current) if current else str(Path.home() / "Documents")
        if not os.path.isdir(initial):
            initial = str(Path.home())
        picked = filedialog.askdirectory(
            parent=self, title="Obsidian vault 폴더 선택", initialdir=initial,
        )
        if not picked:
            return
        entry.delete(0, "end")
        entry.insert(0, picked)
        self._refresh_vault_chip()

    def _refresh_vault_chip(self) -> None:
        """vault Entry 의 현재 값이 유효한 vault 인지 chip 으로 표시."""
        if not hasattr(self, "_vault_chip"):
            return
        entry = self._entries.get("OBSIDIAN_VAULT_PATH")
        if entry is None:
            return
        val = entry.get().strip().strip('"').strip("'")
        if not val:
            self._vault_chip.configure(text="", text_color=ut.C_TEXT_DIM)
            return
        try:
            p = Path(os.path.expanduser(val))
            if not p.is_dir():
                self._vault_chip.configure(
                    text="경로 없음", text_color=ut.C_DANGER,
                )
                return
            if is_obsidian_vault(p):
                self._vault_chip.configure(
                    text="✓ vault", text_color=ut.C_SUCCESS,
                )
            else:
                self._vault_chip.configure(
                    text="폴더 있음 (.obsidian/ 없음)", text_color=ut.C_WARNING,
                )
        except Exception:  # noqa: BLE001
            self._vault_chip.configure(text="", text_color=ut.C_TEXT_DIM)

    # -------------------------------------------------------------------------
    # 하드웨어 프리셋
    # -------------------------------------------------------------------------
    def _on_preset_change(self, label: str) -> None:
        """프리셋 드롭다운 선택 시 필드 일괄 갱신."""
        key = hw_label_to_key(label)
        if key == CUSTOM_KEY:
            return  # 사용자가 직접 입력 — 아무것도 안 건드림
        self._apply_preset(key, only_empty=False)

    def _apply_preset(self, key: str, only_empty: bool) -> None:
        """프리셋 값을 `_PRESET_DRIVEN_FIELDS` 에 채워 넣는다."""
        if key == AUTO_KEY:
            key = detect_recommended_preset()
        profile = PRESETS.get(key)
        if profile is None:
            return

        values = {
            "LLM_TEMPERATURE": str(profile.llm_temperature),
            "LLM_TRANSLATION_MAX_TOKENS": str(profile.translation_max_tokens),
            "LLM_SUMMARY_MAX_TOKENS": str(profile.summary_max_tokens),
            "WHISPERX_MODEL": profile.whisperx_model,
            "WHISPERX_BATCH_SIZE": str(profile.whisperx_batch),
            "MLX_WHISPER_MODEL": profile.mlx_model,
        }
        for env_key in self._PRESET_DRIVEN_FIELDS:
            widget = self._entries.get(env_key)
            if widget is None:
                continue
            current = widget.get().strip()
            if only_empty and current:
                continue
            widget.delete(0, "end")
            widget.insert(0, values[env_key])

    # -------------------------------------------------------------------------
    # Save / Test
    # -------------------------------------------------------------------------
    def _on_save(self) -> None:
        payload = {
            key: self._entries[key].get().strip()
            for key, _label, _is_secret in _SETTINGS_FIELDS
        }
        changed, backup = save_settings(payload, create_backup=True)

        if changed:
            backup_name = backup.name if backup else "-"
            messagebox.showinfo(
                "설정 저장",
                f"{changed} 개 항목이 저장되었습니다.\n백업: {backup_name}",
            )
        else:
            messagebox.showinfo("설정 저장", "변경된 항목이 없습니다.")
        self.destroy()

    def _on_test_connection(self) -> None:
        provider = self._entries["LLM_PROVIDER"].get().strip() or "openai"
        cfg = LLMConfig.from_env(provider=provider)
        # Provider 별 올바른 API 키/모델 필드 사용
        #   - anthropic → ANTHROPIC_API_KEY + ANTHROPIC_MODEL
        #   - gemini    → GOOGLE_API_KEY + GEMINI_MODEL
        #   - openai / openai_compatible → OPENAI_API_KEY + OPENAI_BASE_URL +
        #                                   OPENAI_MODEL
        if provider == "anthropic":
            cfg.api_key = self._entries["ANTHROPIC_API_KEY"].get().strip()
            cfg.model = self._entries["ANTHROPIC_MODEL"].get().strip() or cfg.model
        elif provider == "gemini":
            cfg.api_key = self._entries["GOOGLE_API_KEY"].get().strip()
            cfg.model = self._entries["GEMINI_MODEL"].get().strip() or cfg.model
        else:
            cfg.api_key = self._entries["OPENAI_API_KEY"].get().strip()
            cfg.base_url = self._entries["OPENAI_BASE_URL"].get().strip()
            cfg.model = self._entries["OPENAI_MODEL"].get().strip() or cfg.model
        try:
            cfg.temperature = float(self._entries["LLM_TEMPERATURE"].get().strip() or "0.2")
            resp = test_connection(cfg)
            messagebox.showinfo("연결 테스트", f"성공: {resp}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("연결 테스트 실패", str(exc))


# =============================================================================
# 메인 애플리케이션 (사이드바 + 카드 레이아웃 리디자인)
# =============================================================================
def _card(parent, **kw):
    d = dict(fg_color=C_SURFACE, corner_radius=12, border_width=1, border_color=C_BORDER)
    d.update(kw)
    return ctk.CTkFrame(parent, **d)


def _install_clipboard_shortcuts(root) -> None:
    """macOS 에서 Cmd+C/V/X/A 가 CTkEntry 에 전달되지 않는 문제 해결.

    이전 구현은 `event_generate("<<Paste>>")` 로 가상 이벤트를 dispatch 했지만,
    (1) `focus_get()` 가 CTkEntry 의 wrapper Frame 을 돌려주면 가상 이벤트
    바인딩이 없어 무시되고, (2) Tk 가 가상 이벤트를 tail 큐에 넣는 동작이
    macOS Aqua + 한국어 IME 조합에서 종종 누락되어 사용자가 "붙여넣기가
    동작하지 않는다" 고 보고했다.

    이번 구현은 클립보드를 직접 읽어 포커스 위젯에 삽입하므로 Tk 가상
    이벤트 dispatch 를 거치지 않는다. CTkEntry/CTkTextbox 의 내부 tk 위젯
    (`_entry` / `_textbox`) 으로 자동 위임한다.

    Toplevel(SettingsDialog, HistoryDialog 등) 도 같은 Tk 인터프리터를
    공유하므로 `bind_all` 한 번이면 전역 적용됨.
    """
    import platform
    if platform.system() != "Darwin":
        return  # Linux/Windows 는 기본 바인딩이 이미 Ctrl+V 를 매핑

    import tkinter as _tk

    def _resolve(w):
        """CTkEntry/CTkTextbox wrapper → 내부 tk.Entry/tk.Text 위젯으로 위임."""
        if w is None:
            return None
        if isinstance(w, (_tk.Entry, _tk.Text)):
            return w
        for attr in ("_entry", "_textbox"):
            inner = getattr(w, attr, None)
            if isinstance(inner, (_tk.Entry, _tk.Text)):
                return inner
        return w

    def _focused():
        try:
            return _resolve(root.focus_get())
        except Exception:  # noqa: BLE001
            return None

    def _is_text(w):
        return isinstance(w, _tk.Text)

    def _do_paste(_event=None):
        w = _focused()
        if w is None:
            return "break"
        try:
            text = root.clipboard_get()
        except _tk.TclError:
            return "break"  # 클립보드 비어있거나 텍스트 아님
        try:
            try:
                w.delete("sel.first", "sel.last")
            except _tk.TclError:
                pass  # 선택 영역 없음
            w.insert("insert", text)
            if _is_text(w):
                w.see("insert")
        except Exception:  # noqa: BLE001
            pass
        return "break"

    def _do_copy(_event=None):
        w = _focused()
        if w is None:
            return "break"
        try:
            if _is_text(w):
                text = w.get("sel.first", "sel.last")
            else:
                text = w.selection_get()
        except _tk.TclError:
            return "break"
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
        except _tk.TclError:
            pass
        return "break"

    def _do_cut(_event=None):
        w = _focused()
        if w is None:
            return "break"
        try:
            if _is_text(w):
                text = w.get("sel.first", "sel.last")
            else:
                text = w.selection_get()
            w.delete("sel.first", "sel.last")
        except _tk.TclError:
            return "break"
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
        except _tk.TclError:
            pass
        return "break"

    def _do_select_all(_event=None):
        w = _focused()
        if w is None:
            return "break"
        try:
            if _is_text(w):
                w.tag_add("sel", "1.0", "end-1c")
                w.mark_set("insert", "end-1c")
                w.see("insert")
            else:
                w.select_range(0, "end")
                w.icursor("end")
        except Exception:  # noqa: BLE001
            pass
        return "break"

    # 소문자 + 대문자(Shift 동시) 모두 바인딩 — 한국어 IME 가 Cmd 와 함께
    # 대문자 keysym 을 보내는 경우 대비.
    for key, action in (
        ("c", _do_copy), ("C", _do_copy),
        ("v", _do_paste), ("V", _do_paste),
        ("x", _do_cut), ("X", _do_cut),
        ("a", _do_select_all), ("A", _do_select_all),
    ):
        root.bind_all(f"<Command-{key}>", action)

    # 우클릭 컨텍스트 메뉴 — Cmd+V 가 어떤 이유로든 실패해도 마우스로 paste
    # 가능하도록 안전망 제공. macOS 는 Button-2 (한 손가락 우클릭/Ctrl+클릭)
    # 와 Button-3 (두 손가락 클릭) 둘 다 발생할 수 있어 모두 바인딩.
    def _show_context_menu(event):
        try:
            w = _resolve(event.widget)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(w, (_tk.Entry, _tk.Text)):
            return
        try:
            w.focus_set()
        except Exception:  # noqa: BLE001
            pass
        try:
            has_sel = bool(w.tag_ranges("sel")) if _is_text(w) else bool(w.selection_present())
        except Exception:  # noqa: BLE001
            has_sel = False
        try:
            root.clipboard_get()
            has_clip = True
        except _tk.TclError:
            has_clip = False
        menu = _tk.Menu(root, tearoff=0)
        menu.add_command(label="잘라내기", command=_do_cut,
                         state=("normal" if has_sel else "disabled"))
        menu.add_command(label="복사", command=_do_copy,
                         state=("normal" if has_sel else "disabled"))
        menu.add_command(label="붙여넣기", command=_do_paste,
                         state=("normal" if has_clip else "disabled"))
        menu.add_separator()
        menu.add_command(label="전체 선택", command=_do_select_all)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    root.bind_all("<Button-2>", _show_context_menu, add="+")
    root.bind_all("<Button-3>", _show_context_menu, add="+")
    root.bind_all("<Control-Button-1>", _show_context_menu, add="+")


class GuruNoteApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        _apply_app_icon(self)
        self.title(APP_TITLE)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(1000, 700)
        self.configure(fg_color=C_BG)
        self._worker = None
        self._result = None
        self._local_file_path = ""
        self._step_labels = []
        self._last_saved_path: Optional[str] = None  # 폴더 열기 용 — 마지막 .md/.pdf 저장 경로
        # macOS Cmd+C/V/X/A 명시 바인딩 (Toplevel 포함 전역 적용)
        _install_clipboard_shortcuts(self)
        # Non-blocking 토스트 매니저 (저장 성공 등 소소한 피드백용)
        from gurunote.ui_toast import ToastManager as _ToastManager
        self._toast = _ToastManager(self)
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    # ── 사이드바 ─────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C_SIDEBAR, width=220, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        # 버튼 4개 + spacer row 6 + version row 7
        sb.grid_rowconfigure(6, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        # 브랜드 — 세로 배치 (잘림 방지)
        ctk.CTkLabel(
            sb, text="GuruNote",
            font=ctk.CTkFont(size=22, weight="bold"), text_color=C_TEXT,
        ).grid(row=0, column=0, padx=20, pady=(28, 0), sticky="w")
        ctk.CTkLabel(
            sb, text="IT/AI Podcast Summarizer",
            font=ctk.CTkFont(size=10), text_color=C_TEXT_DIM,
        ).grid(row=1, column=0, padx=20, sticky="w", pady=(2, 20))

        # 네비게이션 — 이모지 대신 텍스트 prefix (Windows 호환)
        nav_items = [
            ("  Settings", self._on_settings),
            ("  Dashboard", self._on_dashboard),
            ("  History", self._on_history),
            ("  Update", self._on_update_sb),
        ]
        for i, (txt, cmd) in enumerate(nav_items):
            ctk.CTkButton(
                sb, text=txt, anchor="w", height=36,
                fg_color="transparent", hover_color=C_SURFACE_HI,
                text_color=C_TEXT_DIM, font=ctk.CTkFont(size=13),
                command=cmd,
            ).grid(row=2 + i, column=0, padx=10, pady=2, sticky="ew")

        ctk.CTkLabel(
            sb, text="v1.0.0.1", font=ctk.CTkFont(size=10), text_color=C_TEXT_DIM,
        ).grid(row=7, column=0, padx=20, pady=(0, 16), sticky="sw")

    # ── 메인 영역 ────────────────────────────────────────────
    def _build_main(self):
        m = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        m.grid(row=0, column=1, sticky="nsew")
        m.grid_columnconfigure(0, weight=1)
        m.grid_rowconfigure(2, weight=1)
        self._build_input_card(m, 0)
        self._build_progress_card(m, 1)
        self._build_result_card(m, 2)

    # ── 프리셋 ↔ STT 엔진 매핑 ──
    # 초보자가 엔진 이름(whisperx/mlx/assemblyai) 대신 속도/품질 트레이드오프로
    # 선택할 수 있게 4개 프리셋 제공. 내부적으로는 기존 STT_OPTIONS 로 변환.
    _PRESETS = ("빠름", "균형", "품질", "직접")

    def _preset_to_stt(self, preset: str) -> str | None:
        """프리셋 → STT 엔진. '직접' 이면 None 반환 (사용자 수동 선택 유지)."""
        if preset == "빠름":
            return "assemblyai"  # 클라우드 API — 빠른 시동 + GPU 불필요
        if preset == "품질":
            # 플랫폼별 로컬 GPU 엔진. whisperx 미설치 / 키 없음은 기존
            # _check_whisperx_available() / _check_api_keys() 가 처리.
            return "mlx" if is_apple_silicon() else "whisperx"
        if preset == "균형":
            return "auto"  # 플랫폼별 자동 선택
        return None  # "직접" — 사용자 선택 유지

    def _stt_to_preset(self, stt: str) -> str:
        """STT 엔진 → 현재 프리셋 (초기화용 역매핑)."""
        if stt == "assemblyai":
            return "빠름"
        if stt in ("mlx", "whisperx"):
            return "품질"
        if stt == "auto":
            return "균형"
        return "직접"

    def _build_input_card(self, p, r):
        c = uc.card(p)
        c.grid(row=r, column=0, padx=ut.SPACE_XL, pady=(ut.SPACE_XL, ut.SPACE_SM), sticky="ew")
        c.grid_columnconfigure(0, weight=1)

        # ── 섹션 헤더 ──
        header = uc.section_header(
            c, title="오디오 소스",
            subtitle="유튜브 URL 을 붙여넣거나 로컬 파일을 선택하세요",
        )
        header.grid(row=0, column=0, padx=ut.SPACE_LG,
                    pady=(ut.SPACE_LG, ut.SPACE_MD), sticky="ew")

        # ── 행 1: 파일 선택 버튼 + URL Entry ──
        row1 = ctk.CTkFrame(c, fg_color="transparent")
        row1.grid(row=1, column=0, padx=ut.SPACE_LG,
                  pady=(0, ut.SPACE_MD), sticky="ew")
        row1.grid_columnconfigure(1, weight=1)

        uc.button(
            row1, text="파일 선택", variant=ut.BTN_SECONDARY,
            command=self._on_pick_file, width=100, height=ut.HEIGHT_LG,
        ).grid(row=0, column=0, padx=(0, ut.SPACE_SM))

        self._url_entry = ctk.CTkEntry(
            row1, height=ut.HEIGHT_LG, corner_radius=ut.RADIUS_SM,
            placeholder_text="유튜브 URL 붙여넣기 (예: https://www.youtube.com/watch?v=...)",
            fg_color=ut.C_BG, border_color=ut.C_BORDER, text_color=ut.C_TEXT,
            font=ctk.CTkFont(size=ut.FONT_BODY),
        )
        self._url_entry.grid(row=0, column=1, sticky="ew")

        # ── 행 2: 프리셋 세그먼트 + Primary CTA (GuruNote 생성) ──
        row2 = ctk.CTkFrame(c, fg_color="transparent")
        row2.grid(row=2, column=0, padx=ut.SPACE_LG,
                  pady=(0, ut.SPACE_MD), sticky="ew")
        row2.grid_columnconfigure(0, weight=1)

        preset_wrap = ctk.CTkFrame(row2, fg_color="transparent")
        preset_wrap.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            preset_wrap, text="처리 모드",
            text_color=ut.C_TEXT_DIM, font=ctk.CTkFont(size=ut.FONT_META),
        ).grid(row=0, column=0, padx=(0, ut.SPACE_SM))

        # 초기 preset 은 현재 STT 엔진값에서 역추론 (env GURUNOTE_STT_ENGINE 존중)
        _env_stt = os.environ.get("GURUNOTE_STT_ENGINE", "auto").lower().strip()
        if _env_stt not in STT_OPTIONS:
            _env_stt = "auto"
        _initial_preset = self._stt_to_preset(_env_stt)
        self._processing_preset_var = ctk.StringVar(value=_initial_preset)
        self._processing_preset_segment = ctk.CTkSegmentedButton(
            preset_wrap,
            values=list(self._PRESETS),
            variable=self._processing_preset_var,
            command=self._on_processing_preset_change,
            height=ut.HEIGHT_MD,
            corner_radius=ut.RADIUS_SM,
            fg_color=ut.C_SURFACE_HI,
            selected_color=ut.C_PRIMARY,
            selected_hover_color=ut.C_PRIMARY_HO,
            unselected_color=ut.C_SURFACE_HI,
            unselected_hover_color=ut.C_BORDER,
            text_color=ut.C_TEXT,
            font=ctk.CTkFont(size=ut.FONT_META),
        )
        self._processing_preset_segment.grid(row=0, column=1)

        cta_wrap = ctk.CTkFrame(row2, fg_color="transparent")
        cta_wrap.grid(row=0, column=1, sticky="e")
        self._run_btn = uc.button(
            cta_wrap, text="▶  GuruNote 생성", variant=ut.BTN_PRIMARY,
            command=self._on_run,
            height=ut.HEIGHT_LG, width=200,
            font_size=ut.FONT_BODY, font_weight=ut.WEIGHT_BOLD,
        )
        self._run_btn.grid(row=0, column=0, padx=(ut.SPACE_SM, ut.SPACE_XS))
        self._stop_btn = uc.button(
            cta_wrap, text="⏹", variant=ut.BTN_SECONDARY,
            command=self._on_stop, state="disabled",
            height=ut.HEIGHT_LG, width=40,
        )
        self._stop_btn.grid(row=0, column=1)

        # ── 행 3: 고급 설정 토글 + 숨겨진 STT/LLM 드롭다운 ──
        self._advanced_open = False
        self._advanced_toggle = ctk.CTkButton(
            c, text="▸  고급 설정",
            fg_color="transparent", hover_color=ut.C_SURFACE_HI,
            text_color=ut.C_TEXT_DIM,
            border_width=0, anchor="w",
            height=ut.HEIGHT_MD, corner_radius=ut.RADIUS_SM,
            font=ctk.CTkFont(size=ut.FONT_META),
            command=self._toggle_advanced,
        )
        self._advanced_toggle.grid(row=3, column=0, padx=ut.SPACE_LG,
                                   pady=(0, ut.SPACE_SM), sticky="ew")

        self._advanced_frame = ctk.CTkFrame(c, fg_color="transparent")
        self._advanced_frame.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(
            self._advanced_frame, text="STT 엔진",
            text_color=ut.C_TEXT_DIM, font=ctk.CTkFont(size=ut.FONT_META),
        ).grid(row=0, column=0, padx=(0, ut.SPACE_SM), pady=ut.SPACE_XS, sticky="w")

        self._stt_var = ctk.StringVar(value=_env_stt)
        self._stt_menu = ctk.CTkOptionMenu(
            self._advanced_frame, variable=self._stt_var, values=STT_OPTIONS,
            width=140, height=ut.HEIGHT_MD, corner_radius=ut.RADIUS_SM,
            fg_color=ut.C_SURFACE_HI, button_color=ut.C_BORDER,
            font=ctk.CTkFont(size=ut.FONT_META),
            command=self._on_stt_manual_change,
        )
        self._stt_menu.grid(row=0, column=1, padx=(0, ut.SPACE_LG),
                            pady=ut.SPACE_XS, sticky="w")

        ctk.CTkLabel(
            self._advanced_frame, text="LLM",
            text_color=ut.C_TEXT_DIM, font=ctk.CTkFont(size=ut.FONT_META),
        ).grid(row=0, column=2, padx=(0, ut.SPACE_SM), pady=ut.SPACE_XS, sticky="w")

        self._llm_var = ctk.StringVar(value=os.environ.get("LLM_PROVIDER", "openai"))
        self._llm_menu = ctk.CTkOptionMenu(
            self._advanced_frame, variable=self._llm_var, values=LLM_OPTIONS,
            width=180, height=ut.HEIGHT_MD, corner_radius=ut.RADIUS_SM,
            fg_color=ut.C_SURFACE_HI, button_color=ut.C_BORDER,
            font=ctk.CTkFont(size=ut.FONT_META),
        )
        self._llm_menu.grid(row=0, column=3, padx=(0, 0),
                            pady=ut.SPACE_XS, sticky="w")

        # 기본 preset 이 "직접" 이면 고급 영역 자동 확장 (env 에서 명시 선택된 경우)
        if _initial_preset == "직접":
            self._open_advanced()

    def _on_processing_preset_change(self, preset: str) -> None:
        """처리 모드 프리셋 선택 시 STT 엔진 자동 매핑. '직접' 선택 시 고급 영역 자동 확장.

        이름 주의: `SettingsDialog._on_preset_change` 는 별도 메서드 (하드웨어
        프리셋용). 혼동 방지 위해 이 메서드는 `_on_processing_preset_change`.
        """
        stt = self._preset_to_stt(preset)
        if stt is not None:
            self._stt_var.set(stt)  # variable 변경은 OptionMenu command 를 트리거하지 않음 — 의도된 동작.
        if preset == "직접" and not self._advanced_open:
            self._open_advanced()

    def _on_stt_manual_change(self, _value: str) -> None:
        """사용자가 STT 드롭다운을 직접 변경 → 처리 모드 프리셋을 '직접' 으로 전환."""
        if self._processing_preset_var.get() != "직접":
            self._processing_preset_var.set("직접")

    def _toggle_advanced(self) -> None:
        if self._advanced_open:
            self._close_advanced()
        else:
            self._open_advanced()

    def _open_advanced(self) -> None:
        self._advanced_open = True
        self._advanced_toggle.configure(text="▾  고급 설정")
        self._advanced_frame.grid(row=4, column=0, padx=ut.SPACE_LG,
                                  pady=(0, ut.SPACE_MD), sticky="ew")

    def _close_advanced(self) -> None:
        self._advanced_open = False
        self._advanced_toggle.configure(text="▸  고급 설정")
        self._advanced_frame.grid_forget()

    # 진행률 → 현재 단계 인덱스 매핑 (STEP_LABELS 와 동일한 5단계 기준)
    _STEP_THRESHOLDS = (0.18, 0.55, 0.78, 0.90, 1.0)

    def _current_step_name(self, pct: float) -> str:
        """현재 진행률에 해당하는 단계 이름. pct>=1.0 이면 '완료'."""
        if pct >= 1.0:
            return "완료"
        if pct <= 0.01:
            return "대기 중"
        for i, th in enumerate(self._STEP_THRESHOLDS):
            if pct < th:
                return STEP_LABELS[i]
        return STEP_LABELS[-1]

    def _build_progress_card(self, p, r):
        c = uc.card(p)
        c.grid(row=r, column=0, padx=ut.SPACE_XL, pady=ut.SPACE_SM, sticky="ew")
        c.grid_columnconfigure(0, weight=1)

        # ── 단계 pill (5단계 인디케이터) ──
        sf = ctk.CTkFrame(c, fg_color="transparent")
        sf.grid(row=0, column=0, padx=ut.SPACE_LG,
                pady=(ut.SPACE_LG, ut.SPACE_XS), sticky="ew")
        self._step_labels = []
        for i, lb in enumerate(STEP_LABELS):
            if i > 0:
                ctk.CTkLabel(
                    sf, text="─", text_color=ut.C_BORDER,
                    font=ctk.CTkFont(size=ut.FONT_META),
                ).pack(side="left", padx=ut.SPACE_XXS)
            sl = ctk.CTkLabel(
                sf, text=f" {i+1}. {lb} ",
                font=ctk.CTkFont(size=ut.FONT_META),
                text_color=ut.C_TEXT_DIM,
                fg_color=ut.C_SURFACE_HI,
                corner_radius=ut.RADIUS_SM,
            )
            sl.pack(side="left", padx=ut.SPACE_XXS)
            self._step_labels.append(sl)

        # ── 진행률 bar + 상태 라인 ──
        pw = ctk.CTkFrame(c, fg_color="transparent")
        pw.grid(row=1, column=0, padx=ut.SPACE_LG,
                pady=(ut.SPACE_SM, ut.SPACE_XS), sticky="ew")
        pw.grid_columnconfigure(0, weight=1)
        self._progress = ctk.CTkProgressBar(
            pw, height=6, corner_radius=3,
            fg_color=ut.C_SURFACE_HI, progress_color=ut.C_PRIMARY_BRIGHT,
        )
        self._progress.grid(row=0, column=0, sticky="ew")
        self._progress.set(0)
        # 상태 라인: "번역 중 · 2m 15s 경과 · ~3m 25s 남음" 형식
        self._progress_label = ctk.CTkLabel(
            pw, text="대기 중",
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM, anchor="w",
        )
        self._progress_label.grid(row=1, column=0, sticky="w",
                                  pady=(ut.SPACE_XXS, 0))

        # ── 마지막 로그 1줄 ──
        self._last_log_label = ctk.CTkLabel(
            c, text="",
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM, anchor="w", wraplength=900,
        )
        self._last_log_label.grid(row=2, column=0, padx=ut.SPACE_LG,
                                  pady=(0, ut.SPACE_SM), sticky="ew")

        # ── 처리 로그 드로어 토글 ──
        self._progress_log_open = False
        self._progress_log_toggle = ctk.CTkButton(
            c, text="▸  처리 로그 보기",
            fg_color="transparent", hover_color=ut.C_SURFACE_HI,
            text_color=ut.C_TEXT_DIM,
            border_width=0, anchor="w",
            height=ut.HEIGHT_MD, corner_radius=ut.RADIUS_SM,
            font=ctk.CTkFont(size=ut.FONT_META),
            command=self._toggle_progress_log,
        )
        self._progress_log_toggle.grid(row=3, column=0, padx=ut.SPACE_LG,
                                       pady=(0, ut.SPACE_SM), sticky="ew")

        # 드로어 본문 (기본 숨김 — row 4 에 grid/ungrid 토글)
        self._progress_log_text = ctk.CTkTextbox(
            c, height=160, state="disabled", wrap="word",
            font=ctk.CTkFont(size=ut.FONT_META),
            fg_color=ut.C_BG, text_color=ut.C_TEXT_DIM,
            border_color=ut.C_BORDER, border_width=1,
            corner_radius=ut.RADIUS_SM,
        )
        # 초기 grid() 호출 안 함 — 토글 열릴 때만 grid().

    def _toggle_progress_log(self) -> None:
        if self._progress_log_open:
            self._close_progress_log()
        else:
            self._open_progress_log()

    def _open_progress_log(self) -> None:
        self._progress_log_open = True
        self._progress_log_toggle.configure(text="▾  처리 로그 보기")
        self._progress_log_text.grid(
            row=4, column=0, padx=ut.SPACE_LG,
            pady=(0, ut.SPACE_MD), sticky="ew",
        )

    def _close_progress_log(self) -> None:
        self._progress_log_open = False
        self._progress_log_toggle.configure(text="▸  처리 로그 보기")
        self._progress_log_text.grid_forget()

    # 지원 오디오 파일 확장자 (empty state 표시용) — SUPPORTED_EXTS 는 import 시점에 없을 수 있음
    @property
    def _supported_ext_hint(self) -> str:
        try:
            exts = sorted(SUPPORTED_EXTS)
            return "지원 파일: " + "  ".join(exts)
        except Exception:  # noqa: BLE001
            return "지원 파일: .mp3 .wav .mp4 .m4a .webm .ogg"

    @staticmethod
    def _format_duration_meta(sec: float) -> str:
        """오디오 길이를 '01시간 42분' 또는 '12분 30초' 로 포맷."""
        s = int(sec or 0)
        h, rem = divmod(s, 3600)
        m, ss = divmod(rem, 60)
        if h > 0:
            return f"{h}시간 {m}분"
        return f"{m}분 {ss}초"

    def _build_result_card(self, p, r):
        c = uc.card(p)
        c.grid(row=r, column=0, padx=ut.SPACE_XL,
               pady=(ut.SPACE_SM, ut.SPACE_XL), sticky="nsew")
        c.grid_rowconfigure(1, weight=1)
        c.grid_columnconfigure(0, weight=1)

        # ── 상단 meta 헤더 + 내보내기 버튼 ──
        self._build_result_meta_header(c)

        # ── 결과 tabview (한국어 탭 이름) ──
        self._tabview = ctk.CTkTabview(
            c, height=300, corner_radius=ut.RADIUS_SM,
            fg_color=ut.C_SURFACE,
            segmented_button_fg_color=ut.C_SURFACE_HI,
            segmented_button_selected_color=ut.C_PRIMARY,
            segmented_button_unselected_color=ut.C_SURFACE_HI,
        )
        self._tab_summary = self._tabview.add("요약")
        self._tab_translated = self._tabview.add("한국어 전문")
        self._tab_original = self._tabview.add("원문")
        self._tab_log = self._tabview.add("처리 로그")
        self._summary_text = self._make_tb(self._tab_summary)
        self._translated_text = self._make_tb(self._tab_translated)
        self._original_text = self._make_tb(self._tab_original)
        self._log_text = self._make_tb(self._tab_log)

        # ── Empty state 프레임 ──
        self._empty_state = self._build_result_empty_state(c)
        # 초기 상태: empty state 표시, tabview 숨김
        self._show_empty_state()

    def _build_result_meta_header(self, parent):
        """결과 카드 상단 — 영상 제목 / 메타 row / 내보내기 버튼.

        파이프라인 완료 전: 제목은 "결과가 여기에 표시됩니다", meta row 는 빈 상태.
        완료 후 `_update_result_meta` 가 제목/업로더/게시일/길이/화자수/STT/LLM 을
        채움.
        """
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, padx=ut.SPACE_LG,
                    pady=ut.SPACE_LG, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=0, sticky="ew")
        title_wrap.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            title_wrap, text="결과가 여기에 표시됩니다",
            font=ctk.CTkFont(size=ut.FONT_HEADING, weight=ut.WEIGHT_BOLD),
            text_color=ut.C_TEXT, anchor="w", wraplength=700, justify="left",
        )
        self._title_label.grid(row=0, column=0, sticky="w")

        # Meta row — `_update_result_meta` 가 위젯을 동적으로 채움.
        # CTkFrame 기본 크기가 200×200 이라 빈 상태에서 메타 헤더 행이 200px
        # 이상 세로로 부풀어 empty state 영역을 58px 로 찌그러뜨리는 버그가
        # 있었음 → `height=1` 로 시작해 children(labels/chips) 이 추가되면
        # grid_propagate(True, 기본) 에 의해 자연스럽게 expand 되도록 수정.
        self._meta_row = ctk.CTkFrame(title_wrap, fg_color="transparent", height=1)
        self._meta_row.grid(row=1, column=0, pady=(ut.SPACE_XS, 0), sticky="w")

        # 내보내기 dropdown 트리거 버튼
        self._export_btn = uc.button(
            header, text="내보내기  ▾",
            variant=ut.BTN_PRIMARY,
            command=self._show_export_menu,
            state="disabled",
            height=ut.HEIGHT_LG, width=130,
            font_weight=ut.WEIGHT_BOLD,
        )
        self._export_btn.grid(row=0, column=1, padx=(ut.SPACE_MD, 0), sticky="e")

    def _build_result_empty_state(self, parent) -> ctk.CTkFrame:
        """파이프라인 실행 전 결과 영역에 표시할 안내 프레임."""
        frame = ctk.CTkFrame(
            parent, fg_color=ut.C_BG, corner_radius=ut.RADIUS_SM,
            border_color=ut.C_BORDER, border_width=1,
        )
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.grid(row=0, column=0)

        ctk.CTkLabel(
            inner, text="🎙️",
            font=ctk.CTkFont(size=48),
            text_color=ut.C_PRIMARY_BRIGHT,
        ).grid(row=0, column=0, pady=(ut.SPACE_XL, ut.SPACE_SM))

        ctk.CTkLabel(
            inner, text="아직 결과가 없습니다",
            font=ctk.CTkFont(size=ut.FONT_SECTION, weight=ut.WEIGHT_BOLD),
            text_color=ut.C_TEXT,
        ).grid(row=1, column=0, pady=(0, ut.SPACE_LG))

        steps = (
            "1.   상단 입력창에 유튜브 URL 을 붙여넣거나  '파일 선택'\n"
            "2.   처리 모드 선택  (빠름  ·  균형  ·  품질)\n"
            "3.   ▶   GuruNote 생성   클릭"
        )
        ctk.CTkLabel(
            inner, text=steps,
            font=ctk.CTkFont(size=ut.FONT_BODY),
            text_color=ut.C_TEXT_DIM, justify="left", anchor="w",
        ).grid(row=2, column=0, pady=(0, ut.SPACE_MD))

        ctk.CTkLabel(
            inner, text=self._supported_ext_hint,
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_MUTED,
        ).grid(row=3, column=0, pady=(0, ut.SPACE_XL))

        return frame

    def _show_empty_state(self) -> None:
        """결과 영역을 empty state 로 전환."""
        try:
            self._tabview.grid_forget()
        except Exception:  # noqa: BLE001
            pass
        self._empty_state.grid(
            row=1, column=0, padx=ut.SPACE_LG,
            pady=(0, ut.SPACE_LG), sticky="nsew",
        )

    def _show_result_tabs(self) -> None:
        """결과 영역을 tabview 로 전환."""
        try:
            self._empty_state.grid_forget()
        except Exception:  # noqa: BLE001
            pass
        self._tabview.grid(
            row=1, column=0, padx=ut.SPACE_MD,
            pady=(0, ut.SPACE_MD), sticky="nsew",
        )

    def _update_result_meta(self, audio, transcript) -> None:
        """결과 meta row 를 파이프라인 결과로 채움."""
        for w in self._meta_row.winfo_children():
            w.destroy()

        parts = []
        if getattr(audio, "uploader", None):
            parts.append(audio.uploader)
        if getattr(audio, "upload_date", None):
            parts.append(audio.upload_date)
        parts.append(self._format_duration_meta(getattr(audio, "duration_sec", 0.0)))
        speaker_count = len(transcript.speakers) if transcript.speakers else 0
        if speaker_count > 0:
            parts.append(f"화자 {speaker_count}명")

        meta_text = "  ·  ".join(parts)
        ctk.CTkLabel(
            self._meta_row, text=meta_text,
            font=ctk.CTkFont(size=ut.FONT_META),
            text_color=ut.C_TEXT_DIM,
        ).pack(side="left", padx=(0, ut.SPACE_SM))

        engine = getattr(transcript, "engine", "") or self._stt_var.get() or "—"
        uc.tag_chip(
            self._meta_row, text=f"STT  {engine}", variant="default",
        ).pack(side="left", padx=(0, ut.SPACE_XS))
        uc.tag_chip(
            self._meta_row, text=f"LLM  {self._llm_var.get()}", variant="accent",
        ).pack(side="left")

    @staticmethod
    def _make_tb(parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        tb = ctk.CTkTextbox(parent, font=ctk.CTkFont(size=13), state="disabled",
                            wrap="word", fg_color=C_BG, text_color=C_TEXT, corner_radius=8)
        tb.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        return tb

    def _update_steps(self, pct):
        th = [0.18, 0.55, 0.78, 0.90, 1.0]
        for i, sl in enumerate(self._step_labels):
            if pct >= th[i]:
                sl.configure(fg_color=C_SUCCESS, text_color=C_BG)
            elif i > 0 and pct >= th[i - 1]:
                sl.configure(fg_color=C_PRIMARY, text_color="#FFF")
            elif i == 0 and pct > 0:
                sl.configure(fg_color=C_PRIMARY, text_color="#FFF")
            else:
                sl.configure(fg_color=C_SURFACE_HI, text_color=C_TEXT_DIM)

    # ── 이벤트 핸들러 ────────────────────────────────────────
    def _on_settings(self):
        SettingsDialog(self)

    def _on_dashboard(self):
        DashboardDialog(self)

    def _on_history(self):
        HistoryDialog(self)

    def _on_update_sb(self):
        try:
            info = check_for_update()
        except Exception as e:
            messagebox.showerror("업데이트 확인 실패", str(e))
            return

        if not info["update_available"]:
            messagebox.showinfo("업데이트", info["message"])
            return

        if not messagebox.askyesno(
            "업데이트 가능",
            f"{info['message']}\n\n업데이트를 진행하시겠습니까?",
        ):
            return

        UpdateProgressDialog(self)

    def _on_pick_file(self):
        exts = sorted(SUPPORTED_EXTS)
        path = filedialog.askopenfilename(title="파일 선택",
                                          filetypes=[("미디어", " ".join(f"*{e}" for e in exts)), ("All", "*.*")])
        if not path:
            return
        self._local_file_path = path
        self._url_entry.delete(0, "end")
        self._url_entry.insert(0, f"[File] {Path(path).name}")

    def _check_api_keys(self):
        prov = self._llm_var.get()
        if prov == "openai_compatible":
            if os.environ.get("OPENAI_BASE_URL"):
                return True
            msg = "OPENAI_BASE_URL 이 설정되지 않았습니다.\n설정에서 입력하시겠습니까?"
        else:
            if prov == "anthropic":
                k = "ANTHROPIC_API_KEY"
            elif prov == "gemini":
                k = "GOOGLE_API_KEY"
            else:
                k = "OPENAI_API_KEY"
            if os.environ.get(k):
                return True
            msg = f"{k} 가 설정되지 않았습니다.\n설정에서 입력하시겠습니까?"
        if messagebox.askyesno("설정 필요", msg):
            SettingsDialog(self)
        return False

    def _check_whisperx_available(self) -> bool:
        """WhisperX 미설치 시 설치/AssemblyAI 전환/취소 선택.

        engine 이 mlx/assemblyai 면 WhisperX 가 필요 없고, Apple Silicon 에서는
        auto 라우팅이 MLX 또는 AssemblyAI 로 가므로 WhisperX 설치 안내를 생략한다.
        """
        engine = self._stt_var.get()
        if engine in ("assemblyai", "mlx"):
            return True
        if engine == "auto" and is_apple_silicon():
            # auto 는 macOS arm64 에서 MLX → AssemblyAI 순서로 폴백
            return True
        if is_whisperx_installed():
            return True

        choice = messagebox.askyesnocancel(
            "WhisperX 미설치",
            "WhisperX 패키지가 설치되어 있지 않습니다.\n\n"
            "  [예]    → WhisperX 를 지금 설치 (pip, 수 분 소요)\n"
            "  [아니오] → AssemblyAI 클라우드 API 로 전환\n"
            "  [취소]  → 작업 취소",
        )
        if choice is None:
            return False
        if choice:
            self._append_log("[Install] WhisperX 설치 중...")
            ok = install_whisperx(progress=self._append_log)
            if ok:
                return True
            fallback = messagebox.askyesno(
                "설치 실패",
                "WhisperX 설치에 실패했습니다.\nAssemblyAI 로 전환할까요?",
            )
            if fallback:
                self._stt_var.set("assemblyai")
                self._append_log("[Switch] STT -> AssemblyAI")
                return True
            return False
        else:
            self._stt_var.set("assemblyai")
            self._append_log("[Switch] STT -> AssemblyAI")
            return True

    def _on_run(self):
        txt = self._url_entry.get().strip()
        has_local = bool(self._local_file_path and is_supported_local_file(self._local_file_path))
        use_local = has_local and txt.startswith("[File]")
        if not use_local and not is_probably_youtube_url(txt):
            messagebox.showwarning("소스 필요", "유튜브 URL 또는 [File] 로컬 파일을 선택해주세요.")
            return
        if not self._check_api_keys():
            return
        if not self._check_whisperx_available():
            return
        self._run_btn.configure(state="disabled", text="처리 중…")
        self._stop_btn.configure(state="normal")
        self._export_btn.configure(state="disabled")
        self._clear_log()
        self._clear_results()
        self._show_result_tabs()  # empty state → tabview 전환 (로그 탭에서 라이브 진행 확인)
        self._title_label.configure(text="처리 중…")
        self._set_progress(0.01)
        for sl in self._step_labels:
            sl.configure(fg_color=C_SURFACE_HI, text_color=C_TEXT_DIM)
        kw = dict(engine=self._stt_var.get(), provider=self._llm_var.get())
        if use_local:
            kw["local_file"] = self._local_file_path
        else:
            kw["youtube_url"] = txt
        self._worker = PipelineWorker(**kw)
        self._worker.start()
        self._poll_worker()

    def _poll_worker(self):
        if not self._worker:
            return
        while True:
            try:
                msg = self._worker.msg_queue.get_nowait()
                self._append_log(msg)
                self._last_log_label.configure(text=msg)
            except queue.Empty:
                break
        while True:
            try:
                self._set_progress(self._worker.progress_queue.get_nowait())
            except queue.Empty:
                break
        try:
            self._on_pipeline_done(self._worker.result_queue.get_nowait())
            return
        except queue.Empty:
            pass
        # 경과 시간 실시간 갱신 (progress 업데이트 없어도 라벨은 갱신)
        self._refresh_eta_label()
        self.after(100, self._poll_worker)

    def _on_pipeline_done(self, result):
        self._run_btn.configure(state="normal", text="▶  GuruNote 생성")
        self._stop_btn.configure(state="disabled")
        if not result.get("ok"):
            self._title_label.configure(text="[오류] 파이프라인 실패")
            messagebox.showerror("오류", result.get("error", "알 수 없는 오류"))
            return
        self._result = result
        audio = result["audio"]
        transcript = result["transcript"]
        # 제목 + 메타 + tabview 전환
        self._title_label.configure(text=audio.video_title)
        self._update_result_meta(audio, transcript)
        self._export_btn.configure(state="normal")
        self._set_text(self._summary_text, result["summary_md"])
        self._set_text(self._translated_text, result["translated"])
        lines = [f"[{_format_ts(s.start)}] Speaker {s.speaker}: {s.text}" for s in transcript.segments]
        self._set_text(self._original_text, "\n\n".join(lines))
        self._show_result_tabs()
        self._tabview.set("요약")
        self._set_progress(1.0)
        self._last_log_label.configure(text="[Done] GuruNote 생성 완료")

    # ── 내보내기 dropdown ─────────────────────────────────────
    def _show_export_menu(self) -> None:
        """Primary 버튼에 달린 드롭다운 메뉴 — 복사/저장/보내기/폴더 열기."""
        import tkinter as _tk
        if not self._result:
            return
        menu = _tk.Menu(self, tearoff=0)
        menu.add_command(label="복사", command=self._on_copy_markdown)
        menu.add_separator()
        menu.add_command(label="Markdown 저장", command=self._on_save)
        menu.add_command(label="PDF 저장", command=self._on_save_pdf)
        menu.add_separator()
        menu.add_command(label="Obsidian 으로 보내기", command=self._on_save_obsidian)
        menu.add_command(label="Notion 으로 보내기", command=self._on_save_notion)
        menu.add_separator()
        last = getattr(self, "_last_saved_path", None)
        if last and Path(last).parent.exists():
            menu.add_command(label="폴더 열기", command=self._on_open_saved_folder)
        else:
            menu.add_command(label="폴더 열기", state="disabled")
        # 버튼 바로 아래에 띄우기
        btn = self._export_btn
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_copy_markdown(self) -> None:
        """결과 마크다운 전체를 클립보드로 복사."""
        if not self._result:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._result.get("full_md", ""))
            self._toast.show("클립보드에 복사됨", level="success")
        except Exception as e:  # noqa: BLE001
            self._toast.show(f"복사 실패: {e}", level="error")

    def _on_open_saved_folder(self) -> None:
        """가장 최근 저장된 파일의 폴더를 OS 기본 파일 탐색기로 열기."""
        last = getattr(self, "_last_saved_path", None)
        if not last:
            return
        folder = str(Path(last).parent)
        import platform
        import subprocess
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", folder])
            elif system == "Windows":
                subprocess.Popen(["explorer", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("폴더 열기 실패", str(e))

    def _on_stop(self):
        if self._worker:
            self._worker.request_stop()
            self._stop_btn.configure(state="disabled")
            self._append_log("[Stop] 중지 요청됨")

    def _on_save(self):
        if not self._result:
            return
        name = f"GuruNote_{sanitize_filename(self._result['audio'].video_title)}.md"
        path = filedialog.asksaveasfilename(title="Markdown 저장", defaultextension=".md",
                                            filetypes=[("Markdown", "*.md"), ("All", "*.*")], initialfile=name)
        if not path:
            return
        try:
            Path(path).write_text(self._result["full_md"], encoding="utf-8")
            self._last_saved_path = path
            self._toast.show(f"저장됨  ·  {Path(path).name}", level="success")
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))

    def _on_save_pdf(self):
        """결과 마크다운을 렌더링된 PDF 로 저장 (Phase C).

        패키지 미설치 시 설치 여부를 묻고, 승인하면 자동 설치 후 저장 이어감.
        """
        if not self._result:
            return

        title = self._result["audio"].video_title
        full_md = self._result["full_md"]

        def _do_save() -> None:
            name = f"GuruNote_{sanitize_filename(title)}.pdf"
            path = filedialog.asksaveasfilename(
                title="PDF 저장", defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf"), ("All", "*.*")], initialfile=name,
            )
            if not path:
                return
            try:
                markdown_to_pdf(full_md, Path(path), title=title)
                self._last_saved_path = path
                self._toast.show(f"PDF 저장됨  ·  {Path(path).name}", level="success")
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("PDF 저장 실패", str(e))

        if is_pdf_export_available():
            _do_save()
        else:
            _prompt_pdf_install(self, _do_save)

    def _on_save_obsidian(self):
        """결과 마크다운을 Obsidian vault 로 직접 저장 (Phase D).

        Vault 미설정 시 경고 대신 `ObsidianSetupDialog` 로 감지된 후보 + 폴더
        피커를 띄워 즉시 설정하고 저장 플로우를 이어간다.
        """
        if not self._result:
            return

        title = self._result["audio"].video_title
        filename = f"GuruNote_{sanitize_filename(title)}.md"
        full_md = self._result["full_md"]

        def _do_save(vault: Path) -> None:
            try:
                out = obsidian_save(
                    full_md, filename=filename, vault_path=vault,
                    subfolder=obsidian_subfolder(),
                )
                ObsidianSaveDialog(self, saved_path=out, vault_path=vault)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Obsidian 저장 실패", str(e))

        _prompt_obsidian_setup(self, _do_save)
        return

    def _on_save_notion(self):
        """결과 마크다운을 Notion 페이지로 전송 (Phase E).

        Notion API 호출은 2-10초 블로킹이라 worker thread 로 던지고 main thread
        에선 `after()` 로 결과를 폴링해 UI freeze 회피.
        """
        if not self._result:
            return
        if not is_notion_sync_available():
            messagebox.showwarning("Notion 미지원", notion_missing_hint())
            return
        token = os.environ.get("NOTION_TOKEN", "").strip()
        parent_id = os.environ.get("NOTION_PARENT_ID", "").strip()
        parent_type = (os.environ.get("NOTION_PARENT_TYPE", "database") or "database").strip().lower()
        if not token or not parent_id:
            messagebox.showwarning(
                "Notion 미설정",
                "Settings 에서 `NOTION_TOKEN` 과 `NOTION_PARENT_ID` 를 지정하세요.\n"
                "Integration: https://www.notion.so/my-integrations\n"
                "parent page/DB 에서 해당 Integration 을 Share 해야 접근 가능합니다.",
            )
            return

        title = self._result["audio"].video_title
        md = self._result["full_md"]
        is_db = (parent_type == "database")

        # 전송 중 내보내기 버튼 비활성화 + toast 안내 (blocking 없음)
        self._export_btn.configure(state="disabled")
        self._toast.show("Notion 으로 전송 중…", level="info", duration=4000)
        result_q: queue.Queue = queue.Queue()

        def _worker():
            try:
                url = notion_save(md, title=title, token=token,
                                  parent_id=parent_id, is_database=is_db)
                result_q.put(("ok", url))
            except Exception as exc:  # noqa: BLE001
                result_q.put(("err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self._poll_notion_result(result_q)

    def _poll_notion_result(self, q: "queue.Queue") -> None:
        """result-card 의 Notion 버튼 전용 결과 폴링 (200ms 주기)."""
        try:
            status, payload = q.get_nowait()
        except queue.Empty:
            self.after(200, lambda: self._poll_notion_result(q))
            return
        # 완료: 내보내기 버튼 복구 + 결과 다이얼로그
        self._export_btn.configure(state="normal")
        if status == "ok":
            if messagebox.askyesno("Notion 전송 완료", f"{payload}\n\n브라우저에서 열까요?"):
                import webbrowser
                webbrowser.open(payload)
        else:
            messagebox.showerror("Notion 전송 실패", payload)

    # ── 유틸 ─────────────────────────────────────────────────
    def _append_log(self, msg):
        # 결과 카드의 로그 탭과 진행 카드의 드로어 양쪽에 동일한 로그를 미러.
        for tb in (self._log_text, getattr(self, "_progress_log_text", None)):
            if tb is None:
                continue
            tb.configure(state="normal")
            tb.insert("end", msg + "\n")
            tb.see("end")
            tb.configure(state="disabled")

    def _clear_log(self):
        for tb in (self._log_text, getattr(self, "_progress_log_text", None)):
            if tb is None:
                continue
            tb.configure(state="normal")
            tb.delete("1.0", "end")
            tb.configure(state="disabled")
        self._last_log_label.configure(text="")

    def _set_progress(self, pct):
        import time as _time
        pct = max(0.0, min(1.0, pct))
        self._progress.set(pct)
        self._last_progress_pct = pct
        self._last_progress_time = _time.monotonic()
        self._refresh_eta_label()

    def _refresh_eta_label(self):
        """상태 라인 갱신 — "<단계> 중 · <경과> 경과 · ~<ETA> 남음" 포맷.

        poll 에서도 호출되므로 진행률 업데이트 없이도 경과 시간은 흐름.
        """
        import time as _time
        pct = getattr(self, "_last_progress_pct", 0.0)
        if not (self._worker and self._worker._start_time and pct > 0.01):
            return

        elapsed = _time.monotonic() - self._worker._start_time
        em, es = divmod(int(elapsed), 60)
        elapsed_str = f"{em}m {es}s"

        since_update = _time.monotonic() - getattr(
            self, "_last_progress_time", _time.monotonic()
        )

        step = self._current_step_name(pct)

        if pct >= 1.0:
            self._progress_label.configure(
                text=f"완료  ·  총 {elapsed_str}"
            )
        elif since_update > 30:
            # 30초 이상 진행 없음 → ETA 예측 불가, 경과 시간만 표시
            self._progress_label.configure(
                text=f"{step} 중  ·  {elapsed_str} 경과  ·  진행 대기 중…"
            )
        elif pct > 0.02:
            total_est = elapsed / pct
            remaining = max(0, total_est - elapsed)
            rm, rs = divmod(int(remaining), 60)
            self._progress_label.configure(
                text=f"{step} 중  ·  {elapsed_str} 경과  ·  ~{rm}m {rs}s 남음"
            )
        else:
            self._progress_label.configure(
                text=f"{step} 중  ·  {elapsed_str} 경과"
            )
        self._update_steps(pct)

    @staticmethod
    def _set_text(tb, content):
        tb.configure(state="normal")
        tb.delete("1.0", "end")
        tb.insert("1.0", content)
        tb.configure(state="disabled")

    def _clear_results(self):
        for tb in (self._summary_text, self._translated_text, self._original_text):
            self._set_text(tb, "")
        # Meta row 초기화 — 새 파이프라인 실행 전 UI 상태 리셋
        try:
            for w in self._meta_row.winfo_children():
                w.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _on_closing(self):
        self.destroy()


# =============================================================================
# 엔트리포인트
# =============================================================================
def main() -> None:
    app = GuruNoteApp()
    app.protocol("WM_DELETE_WINDOW", app._on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()

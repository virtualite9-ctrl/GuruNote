"""파이프라인 워커 — 백그라운드 스레드에서 STT/번역 파이프라인을 실행한다.

원래 `gui.py` (CustomTkinter 진입점) 안에 있었다. React/PyWebView UI 가
`gurunote/webui/session.py` 에서 `from gui import PipelineWorker` 로 끌어오는
구조였는데, `gui.py` 는 모듈 레벨에서 customtkinter 를 import 하고 stdout/stderr
를 로그 파일로 돌리는 부수효과를 실행한다. React 진입점이 UI 툴킷과 그 부수효과를
떠안을 이유가 없고, `gui.py` 를 legacy 로 정리할 수도 없었다 (backlog B09).

이 클래스는 UI 툴킷을 참조하지 않는다. 진행 상황은 `msg_queue`, 결과와 에러는
`result_queue` 로만 오간다. 따라서 UI 파일과 분리해도 동작이 달라지지 않는다.

`gui.py` 는 하위 호환을 위해 이 이름을 계속 re-export 한다.
"""
from __future__ import annotations

import os
import queue
import tempfile
import threading
from typing import Optional

from gurunote import semantic as semantic_search
from gurunote.audio import cleanup_dir, download_audio, extract_audio_from_file
from gurunote.exporter import autosave_result, build_gurunote_markdown
from gurunote.history import JobLogger, new_job_id, save_job
from gurunote.llm import (
    LLMConfig,
    extract_metadata,
    summarize_translation,
    translate_transcript,
)
from gurunote.progress_tee import install_tee
from gurunote.stt import transcribe

__all__ = ["PipelineWorker"]


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

"""창 없는 작업 추적 — 파이프라인을 백그라운드로 돌리고 상태를 물어본다.

`webui/session.py` 의 세션 레지스트리는 진행 상황을 webview 이벤트 버스로 밀어넣는
구조라 창이 있어야 한다. 그래서 `stop_pipeline` / `get_pipeline_status` 도 창에 묶여
있다. 창이 없는 호출자(MCP, 스크립트)에게는 같은 역할을 하는 것이 없었다.

여기서는 `run_pipeline` 을 스레드에서 돌리고 로그·진행률·결과를 모아둔다. 호출자는
`start()` 로 job_id 를 받고 `get()` 으로 물어본다. 8분짜리 작업을 한 번의 호출로
붙잡아 두지 않아도 된다.

프로세스 안에서만 유효하다. 영속 기록은 기존 `gurunote.history` 가 맡는다.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Optional

from gurunote.options import DEFAULT_STT_ENGINE, USE_ENV_LLM_PROVIDER
from gurunote.pipeline import PipelineTimeout, resolve_source, run_pipeline
from gurunote.pipeline_worker import PipelineWorker

__all__ = ["JobState", "JobRegistry", "registry", "MAX_LOG_LINES"]

# 로그를 무한정 쌓지 않는다. 진행 확인에 필요한 만큼만 남긴다.
MAX_LOG_LINES = 500


@dataclass
class JobState:
    """작업 하나의 관찰 가능한 상태."""

    job_id: str
    source: str
    status: str = "running"          # running | completed | failed | stopped
    progress: float = 0.0            # 0.0 ~ 1.0
    logs: list[str] = field(default_factory=list)
    full_md: str = ""
    summary_md: str = ""
    error: str = ""
    pipeline_job_id: str = ""        # gurunote.history 의 job_id — 로그 파일 위치

    def snapshot(self, log_tail: int = 20) -> dict:
        """JSON 으로 옮길 수 있는 형태. 본문은 길어서 길이만 알려준다."""
        return {
            "ok": self.status in ("running", "completed"),
            "job_id": self.job_id,
            "source": self.source,
            "status": self.status,
            "progress": round(self.progress, 3),
            "pipeline_job_id": self.pipeline_job_id,
            "log_tail": self.logs[-log_tail:] if log_tail > 0 else [],
            "log_lines": len(self.logs),
            "note_chars": len(self.full_md),
            "error": self.error,
        }


class JobRegistry:
    """프로세스 안에서 도는 작업들."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._workers: dict[str, PipelineWorker] = {}
        self._lock = threading.Lock()

    def start(self, source: str, *, engine: str = DEFAULT_STT_ENGINE,
              provider: str = USE_ENV_LLM_PROVIDER,
              timeout: Optional[float] = None,
              runner=run_pipeline) -> JobState:
        """작업을 띄우고 즉시 돌아온다. `runner` 는 테스트에서 갈아끼우는 지점.

        입력이 URL 도 파일도 아니면 `ValueError` 를 **여기서** 낸다. 스레드 안에서
        터지게 두면 호출자가 폴링할 때까지 모르고, 쓰레기 작업만 목록에 남는다.
        """
        resolve_source(source)
        job_id = uuid.uuid4().hex[:12]
        state = JobState(job_id=job_id, source=source)
        with self._lock:
            self._jobs[job_id] = state

        def capture_worker(**kwargs) -> PipelineWorker:
            # 워커를 붙잡아 둬야 stop() 이 실제로 중지시킬 수 있다.
            worker = PipelineWorker(**kwargs)
            with self._lock:
                self._workers[job_id] = worker
            return worker

        def on_log(line: str) -> None:
            state.logs.append(line)
            if len(state.logs) > MAX_LOG_LINES:
                del state.logs[:-MAX_LOG_LINES]

        def run() -> None:
            try:
                result = runner(source, engine=engine, provider=provider,
                                on_log=on_log,
                                on_progress=lambda pct: setattr(state, "progress", pct),
                                timeout=timeout, worker_factory=capture_worker)
                state.pipeline_job_id = result.job_id
                if result.ok:
                    state.status = "completed"
                    state.full_md = result.full_md
                    state.summary_md = result.summary_md
                    state.progress = 1.0
                elif state.status != "stopped":
                    state.status = "failed"
                    state.error = result.error
                else:
                    # 중지 요청으로 끝난 경우. 파이프라인이 남긴 사유를 참고로 붙인다.
                    state.error = result.error or "중지되었습니다."
            except PipelineTimeout as exc:
                state.status = "failed"
                state.error = str(exc)
            except Exception as exc:  # noqa: BLE001
                # 스레드에서 죽으면 호출자가 영영 모른다. 상태로 남긴다.
                state.status = "failed"
                state.error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._lock:
                    self._workers.pop(job_id, None)

        threading.Thread(target=run, name=f"gurunote-job-{job_id}", daemon=True).start()
        return state

    def get(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobState]:
        with self._lock:
            return list(self._jobs.values())

    def stop(self, job_id: str) -> bool:
        """워커에 중지를 요청한다. 실행 중인 작업이 없으면 False.

        파이프라인은 다음 로그 지점에서 멈춘다 — 즉시 끊기지는 않는다.
        """
        with self._lock:
            state = self._jobs.get(job_id)
            worker = self._workers.get(job_id)
        if state is None or state.status != "running":
            return False
        state.status = "stopped"
        if worker is not None:
            worker.request_stop()
        return True

    def clear_finished(self) -> int:
        """끝난 작업을 목록에서 비우고, 비운 개수를 돌려준다."""
        with self._lock:
            done = [k for k, v in self._jobs.items() if v.status != "running"]
            for k in done:
                self._jobs.pop(k, None)
        return len(done)


registry = JobRegistry()

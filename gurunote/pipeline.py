"""파이프라인의 동기 실행 API — UI 없이 호출하는 진입점.

`PipelineWorker` 는 GUI 를 블로킹하지 않으려고 스레드 + 3 개 큐로 설계돼 있다. 창을
띄우지 않는 호출자(CLI, 에이전트, 스크립트)에게는 그 배선이 부담이므로, 여기서
"끝날 때까지 기다렸다가 결과를 돌려주는" 얇은 층을 제공한다.

파이프라인 로직은 이 모듈에 없다. 큐를 비우고 스레드를 정리하는 일만 한다.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from gurunote.audio import SUPPORTED_EXTS, is_probably_youtube_url
from gurunote.options import (
    STT_ENGINES,
    DEFAULT_STT_ENGINE,
    LLM_PROVIDERS,
    USE_ENV_LLM_PROVIDER,
)
from gurunote.pipeline_worker import PipelineWorker

__all__ = ["PipelineResult", "run_pipeline", "resolve_source"]

_POLL_INTERVAL_SEC = 0.05


@dataclass
class PipelineResult:
    """`run_pipeline` 의 반환값.

    `ok` 가 False 면 `error` 만 의미가 있다. 성공이면 `full_md` 가 완성된 노트이고
    `summary_md` 는 요약 섹션만 따로 담는다. `job_id` 는 실패해도 채워지므로 로그
    (`~/.gurunote/jobs/<job_id>/`) 를 찾아볼 수 있다.
    """

    ok: bool
    job_id: str
    full_md: str = ""
    summary_md: str = ""
    error: str = ""
    logs: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class PipelineTimeout(RuntimeError):
    """`timeout` 안에 파이프라인이 끝나지 않았다. 워커에 중지를 요청한 뒤 발생한다."""


def resolve_source(source: str) -> tuple[str, str]:
    """입력 한 개를 (youtube_url, local_file) 로 가른다.

    URL 인지 파일인지는 호출자가 아니라 여기서 판정한다. CLI 와 에이전트가 같은
    규칙을 쓰게 하려는 것이다. 판정 불가면 `ValueError`.
    """
    text = (source or "").strip()
    if not text:
        raise ValueError("입력이 비어 있습니다. 유튜브 URL 이나 로컬 파일 경로가 필요합니다.")
    if is_probably_youtube_url(text):
        return text, ""

    path = Path(text).expanduser()
    if not path.exists():
        raise ValueError(
            f"유튜브 URL 로도, 존재하는 파일로도 해석되지 않습니다: {text}"
        )
    if not path.is_file():
        raise ValueError(f"파일이 아닙니다: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTS:
        supported = ", ".join(sorted(SUPPORTED_EXTS))
        raise ValueError(f"지원하지 않는 확장자입니다: {path.suffix} (지원: {supported})")
    return "", str(path)


def run_pipeline(
    source: str,
    *,
    engine: str = DEFAULT_STT_ENGINE,
    provider: str = USE_ENV_LLM_PROVIDER,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    timeout: Optional[float] = None,
    worker_factory: Callable[..., PipelineWorker] = PipelineWorker,
) -> PipelineResult:
    """파이프라인을 끝까지 실행하고 결과를 돌려준다.

    Args:
        source: 유튜브 URL 또는 로컬 오디오/영상 파일 경로.
        engine: STT 엔진. `gurunote.options.STT_ENGINES` 중 하나.
        provider: LLM provider. 빈 문자열이면 `LLM_PROVIDER` 환경변수를 따른다.
        on_log: 진행 로그 한 줄마다 호출. 반환값은 무시한다.
        on_progress: 0.0~1.0 진행률마다 호출.
        timeout: 초. 초과하면 워커에 중지를 요청하고 `PipelineTimeout`.
        worker_factory: 테스트에서 워커를 대체하기 위한 주입 지점.

    Raises:
        ValueError: 입력·엔진·provider 가 올바르지 않다.
        PipelineTimeout: `timeout` 초과.
    """
    if engine not in STT_ENGINES:
        raise ValueError(f"engine 은 {list(STT_ENGINES)} 중 하나여야 합니다: {engine!r}")
    if provider and provider not in LLM_PROVIDERS:
        raise ValueError(f"provider 는 {list(LLM_PROVIDERS)} 중 하나여야 합니다: {provider!r}")
    if timeout is not None and timeout <= 0:
        raise ValueError(f"timeout 은 양수여야 합니다: {timeout!r}")

    youtube_url, local_file = resolve_source(source)
    worker = worker_factory(
        engine=engine,
        provider=provider,
        youtube_url=youtube_url,
        local_file=local_file,
    )
    logs: list[str] = []
    deadline = None if timeout is None else time.monotonic() + timeout

    def drain() -> Optional[dict]:
        while True:
            try:
                line = worker.msg_queue.get_nowait()
            except queue.Empty:
                break
            logs.append(line)
            if on_log is not None:
                on_log(line)
        while True:
            try:
                pct = worker.progress_queue.get_nowait()
            except queue.Empty:
                break
            if on_progress is not None:
                on_progress(pct)
        try:
            return worker.result_queue.get_nowait()
        except queue.Empty:
            return None

    worker.start()
    try:
        while True:
            payload = drain()
            if payload is not None:
                break
            thread: Optional[threading.Thread] = getattr(worker, "_thread", None)
            if thread is not None and not thread.is_alive():
                # 스레드가 결과를 남기지 않고 끝났다. 워커가 모든 예외를 잡아
                # result_queue 에 넣도록 되어 있으니 정상 경로는 아니다.
                payload = drain()
                if payload is None:
                    payload = {
                        "ok": False,
                        "error": "파이프라인 스레드가 결과를 남기지 않고 종료했습니다.",
                    }
                break
            if deadline is not None and time.monotonic() > deadline:
                worker.request_stop()
                raise PipelineTimeout(f"{timeout}초 안에 파이프라인이 끝나지 않았습니다.")
            time.sleep(_POLL_INTERVAL_SEC)
    finally:
        thread = getattr(worker, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    drain()  # 종료 직전에 밀린 로그를 흘려보낸다.
    return PipelineResult(
        ok=bool(payload.get("ok")),
        job_id=getattr(worker, "job_id", ""),
        full_md=payload.get("full_md", "") or "",
        summary_md=payload.get("summary_md", "") or "",
        error=payload.get("error", "") or "",
        logs=logs,
        raw=payload,
    )

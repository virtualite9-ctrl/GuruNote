"""GuruNote MCP 서버 — 에이전트가 쓰는 표면.

`GuruNoteService`(창 없는 조작 29개)와 `JobRegistry`(백그라운드 파이프라인) 위에 얹은
얇은 층이다. 여기에 로직은 없다. 도구 이름과 인자를 정하고 결과를 그대로 넘긴다.

노트 생성은 오래 걸린다 — 8분 영상이 8분쯤 걸린다. 그래서 한 번의 호출로 붙잡지 않고
`note_start` 로 job_id 를 받아 `note_status` 로 물어보는 형태로 나눴다. 짧은 조회
(기록·검색·설정)는 바로 돌려준다.

실행:

    gurunote-mcp                 # stdio
    python -m gurunote.mcp_server

의존성은 선택 설치다: `pip install -e ".[mcp]"`.
"""
from __future__ import annotations

from typing import Any, Optional

from gurunote import __version__
from gurunote.jobs import registry
from gurunote.options import (
    DEFAULT_STT_ENGINE,
    LLM_PROVIDERS,
    STT_ENGINES,
    USE_ENV_LLM_PROVIDER,
)
from gurunote.service import GuruNoteService

__all__ = ["build_server", "main"]

_service = GuruNoteService()


def _err(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "error": message}


def build_server():
    """도구가 등록된 MCP 서버를 만든다. import 시점에 mcp 를 요구하지 않는다."""
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover - 설치 안내 경로
        raise ModuleNotFoundError(
            "MCP 서버를 쓰려면 mcp 패키지가 필요합니다: pip install -e \".[mcp]\""
        ) from exc

    server = MCPServer(
        name="gurunote",
        title="GuruNote",
        version=__version__,
        instructions=(
            "영상·오디오를 한국어 노트로 바꾸고, 만들어 둔 노트를 찾고 내보낸다. "
            "노트 생성은 note_start 로 시작해 note_status 로 진행을 확인한다 — "
            "8분 영상이면 8분쯤 걸리므로 한 번에 기다리지 말 것."
        ),
    )

    @server.tool(
        title="노트 생성 시작",
        description=(
            "유튜브 URL 또는 로컬 오디오/영상 파일에서 한국어 노트 생성을 시작한다. "
            "즉시 job_id 를 돌려주고 백그라운드로 진행한다. note_status 로 확인할 것."
        ),
    )
    def note_start(source: str, engine: str = DEFAULT_STT_ENGINE,
                   provider: str = USE_ENV_LLM_PROVIDER,
                   timeout_sec: Optional[float] = None) -> dict:
        if engine not in STT_ENGINES:
            return _err("BAD_ENGINE", f"engine 은 {list(STT_ENGINES)} 중 하나여야 합니다.")
        if provider and provider not in LLM_PROVIDERS:
            return _err("BAD_PROVIDER", f"provider 는 {list(LLM_PROVIDERS)} 중 하나여야 합니다.")
        try:
            state = registry.start(source, engine=engine, provider=provider,
                                   timeout=timeout_sec)
        except ValueError as exc:
            return _err("BAD_SOURCE", str(exc))
        return state.snapshot(log_tail=0)

    @server.tool(
        title="노트 생성 상태",
        description=(
            "note_start 로 띄운 작업의 상태를 돌려준다. status 는 running / completed / "
            "failed / stopped. 완료됐으면 include_note=true 로 본문을 받는다."
        ),
    )
    def note_status(job_id: str, log_tail: int = 20,
                    include_note: bool = False) -> dict:
        state = registry.get(job_id)
        if state is None:
            return _err("NO_SUCH_JOB", f"모르는 job_id 입니다: {job_id}")
        out = state.snapshot(log_tail=max(0, log_tail))
        if include_note and state.status == "completed":
            out["full_md"] = state.full_md
            out["summary_md"] = state.summary_md
        return out

    @server.tool(title="노트 생성 중지",
                 description="진행 중인 작업에 중지를 요청한다. 다음 단계 경계에서 멈춘다.")
    def note_stop(job_id: str) -> dict:
        if registry.get(job_id) is None:
            return _err("NO_SUCH_JOB", f"모르는 job_id 입니다: {job_id}")
        return {"ok": True, "job_id": job_id, "stopped": registry.stop(job_id)}

    @server.tool(title="작업 목록", description="이 프로세스가 띄운 노트 생성 작업 목록.")
    def note_jobs() -> dict:
        return {"ok": True, "jobs": [s.snapshot(log_tail=0) for s in registry.list()]}

    @server.tool(title="저장된 노트 목록",
                 description="지금까지 만든 노트 기록을 최신순으로 돌려준다.")
    def history(limit: int = 20, offset: int = 0) -> dict:
        return _service.list_history(limit=limit, offset=offset)

    @server.tool(title="노트 상세", description="job_id 로 저장된 노트 하나의 내용을 읽는다.")
    def history_detail(job_id: str) -> dict:
        return _service.get_history_detail({"job_id": job_id})

    @server.tool(
        title="의미 검색",
        description=(
            "저장된 노트를 의미 유사도로 찾는다. 인덱스가 없으면 INDEX_NOT_BUILT 를 "
            "돌려주므로, 그때는 사용자에게 인덱스 생성을 안내할 것."
        ),
    )
    def search(query: str, top_k: int = 10) -> dict:
        return _service.semantic_search(query=query, top_k=top_k)

    @server.tool(title="Obsidian 내보내기",
                 description="저장된 노트를 Obsidian vault 로 내보낸다. vault 경로 설정이 필요하다.")
    def export_obsidian(job_id: str, skip_if_exists: bool = False) -> dict:
        return _service.send_obsidian(job_id, skip_if_exists)

    @server.tool(
        title="설정 조회",
        description=(
            "현재 설정을 돌려준다. 비밀값은 설정 여부(true/false)만 나오고 값 자체는 "
            "절대 나오지 않는다."
        ),
    )
    def settings() -> dict:
        return _service.get_settings()

    @server.tool(title="앱 정보", description="GuruNote 버전과 실행 환경.")
    def app_info() -> dict:
        info = _service.get_app_info()
        info["stt_engines"] = list(STT_ENGINES)
        info["llm_providers"] = list(LLM_PROVIDERS)
        info["mcp_version"] = __version__
        return info

    return server


def main(argv: Optional[list[str]] = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="gurunote-mcp", description="GuruNote MCP 서버 (기본 stdio)")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args(argv)
    build_server().run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

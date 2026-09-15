"""MCP 서버와 창 없는 작업 레지스트리 (backlog B13 4단계).

서버는 `GuruNoteService` 와 `JobRegistry` 위의 얇은 층이다. 여기서 볼 것은 로직이
아니라 계약이다 — 도구가 등록되는가, 잘못된 입력을 시작 전에 거르는가, 오래 걸리는
작업을 한 호출로 붙잡지 않는가, 비밀값이 새지 않는가.

실제 STT·LLM 은 부르지 않는다. `runner` 를 갈아끼운다.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import threading
import time

import pytest

from gurunote.jobs import JobRegistry, JobState
from gurunote.pipeline import PipelineResult

mcp_server = pytest.importorskip("gurunote.mcp_server",
                                 reason="mcp 패키지 미설치")

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "note_start", "note_status", "note_stop", "note_jobs",
    "history", "history_detail", "search", "export_obsidian",
    "settings", "app_info",
}


def unwrap(result) -> dict:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    content = getattr(result, "content", None)
    assert content, f"빈 응답: {result!r}"
    return json.loads(content[0].text)


def call(server, name: str, args: dict | None = None) -> dict:
    return unwrap(asyncio.run(server.call_tool(name, args or {})))


@pytest.fixture(scope="module")
def server():
    return mcp_server.build_server()


class TestToolSurface:
    def test_every_expected_tool_is_registered(self, server):
        names = {t.name for t in asyncio.run(server.list_tools())}
        assert EXPECTED_TOOLS <= names, sorted(EXPECTED_TOOLS - names)

    def test_every_tool_describes_itself(self, server):
        undocumented = [t.name for t in asyncio.run(server.list_tools())
                        if not (t.description or "").strip()]
        assert undocumented == [], undocumented

    def test_app_info_reports_the_real_version_and_choices(self, server):
        from gurunote import __version__
        from gurunote.options import LLM_PROVIDERS, STT_ENGINES

        out = call(server, "app_info")
        assert out["ok"] is True
        assert out["version"] == __version__
        assert out["stt_engines"] == list(STT_ENGINES)
        assert out["llm_providers"] == list(LLM_PROVIDERS)


class TestBadInputIsRefusedBeforeWorkStarts:
    def test_unusable_source_makes_no_job(self, server, monkeypatch):
        fresh = JobRegistry()
        monkeypatch.setattr(mcp_server, "registry", fresh)
        out = call(server, "note_start", {"source": "이건-url-도-파일도-아님"})
        assert out["ok"] is False
        assert out["code"] == "BAD_SOURCE"
        assert fresh.list() == [], "실패했는데 작업이 남았다"

    @pytest.mark.parametrize("args,code", [
        ({"source": "https://youtu.be/abcdefghijk", "engine": "없는엔진"}, "BAD_ENGINE"),
        ({"source": "https://youtu.be/abcdefghijk", "provider": "없는provider"}, "BAD_PROVIDER"),
    ])
    def test_unknown_option_is_named(self, server, args, code):
        out = call(server, "note_start", args)
        assert out["ok"] is False and out["code"] == code

    def test_unknown_job_id_is_named_not_crashed(self, server):
        for tool in ("note_status", "note_stop"):
            out = call(server, tool, {"job_id": "그런건없다"})
            assert out["ok"] is False and out["code"] == "NO_SUCH_JOB", tool


class TestLongWorkIsNotHeldInOneCall:
    def test_note_start_returns_before_the_work_finishes(self, server, monkeypatch, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        release = threading.Event()

        def slow_runner(source, **kwargs):
            release.wait(timeout=10)
            return PipelineResult(ok=True, job_id="p1", full_md="# 노트")

        fresh = JobRegistry()
        monkeypatch.setattr(mcp_server, "registry", fresh)
        started = time.monotonic()
        out = call(server, "note_start", {"source": str(audio)})
        elapsed = time.monotonic() - started

        assert out["ok"] is True and out["status"] == "running"
        assert elapsed < 2.0, f"note_start 가 작업을 붙잡고 있었다 ({elapsed:.1f}s)"

        status = call(server, "note_status", {"job_id": out["job_id"]})
        assert status["status"] == "running"
        release.set()

    def test_status_carries_the_note_only_when_asked(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        fresh = JobRegistry()
        state = fresh.start(str(audio), runner=lambda s, **k: PipelineResult(
            ok=True, job_id="p1", full_md="# 본문", summary_md="## 요약"))
        for _ in range(200):
            if state.status != "running":
                break
            time.sleep(0.02)
        assert state.status == "completed"
        assert "full_md" not in state.snapshot()
        assert state.snapshot()["note_chars"] == len("# 본문")


class TestJobRegistry:
    def test_failure_is_recorded_not_swallowed(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        fresh = JobRegistry()
        state = fresh.start(str(audio), runner=lambda s, **k: PipelineResult(
            ok=False, job_id="p2", error="모델 없음"))
        for _ in range(200):
            if state.status != "running":
                break
            time.sleep(0.02)
        assert state.status == "failed"
        assert state.error == "모델 없음"
        assert state.snapshot()["pipeline_job_id"] == "p2"

    def test_a_crashing_runner_still_ends_the_job(self, tmp_path):
        """스레드에서 죽으면 호출자가 영영 모른다 — 상태로 남아야 한다."""
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        fresh = JobRegistry()

        def boom(source, **kwargs):
            raise RuntimeError("갑자기 터짐")

        state = fresh.start(str(audio), runner=boom)
        for _ in range(200):
            if state.status != "running":
                break
            time.sleep(0.02)
        assert state.status == "failed"
        assert "갑자기 터짐" in state.error

    def test_unusable_source_raises_synchronously(self):
        fresh = JobRegistry()
        with pytest.raises(ValueError):
            fresh.start("url-도-파일도-아님")
        assert fresh.list() == []

    def test_logs_are_capped(self, tmp_path):
        from gurunote.jobs import MAX_LOG_LINES

        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        fresh = JobRegistry()

        def chatty(source, **kwargs):
            for i in range(MAX_LOG_LINES + 250):
                kwargs["on_log"](f"line {i}")
            return PipelineResult(ok=True, job_id="p3", full_md="x")

        state = fresh.start(str(audio), runner=chatty)
        for _ in range(300):
            if state.status != "running":
                break
            time.sleep(0.02)
        assert state.status == "completed"
        assert len(state.logs) == MAX_LOG_LINES
        assert state.logs[-1].endswith(str(MAX_LOG_LINES + 249))

    def test_clear_finished_keeps_running_jobs(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        fresh = JobRegistry()
        release = threading.Event()
        done = fresh.start(str(audio), runner=lambda s, **k: PipelineResult(
            ok=True, job_id="p4", full_md="x"))
        running = fresh.start(str(audio),
                              runner=lambda s, **k: (release.wait(timeout=10),
                                                     PipelineResult(ok=True, job_id="p5"))[1])
        for _ in range(200):
            if done.status != "running":
                break
            time.sleep(0.02)
        assert fresh.clear_finished() == 1
        assert [s.job_id for s in fresh.list()] == [running.job_id]
        release.set()


class TestSecretsDoNotLeak:
    def test_settings_reports_presence_not_values(self, server):
        out = call(server, "settings")
        assert out["ok"] is True
        assert all(isinstance(v, bool) for v in out.get("secrets_set", {}).values())
        blob = json.dumps(out, ensure_ascii=False)
        assert "sk-" not in blob

    def test_secret_keys_are_absent_from_plain_values(self, server):
        from gurunote.service import _SECRET_KEYS

        values = call(server, "settings").get("values", {})
        assert set(values) & set(_SECRET_KEYS) == set()


class TestMcpExtraIsSufficient:
    """`pip install -e ".[mcp]"` 만으로 서버가 떠야 한다.

    처음 올렸을 때 이 extra 에 `mcp` 만 넣어서, 실제로 물려보니
    `gurunote.audio` 의 모듈 레벨 `import yt_dlp` 에서 죽었다. import 사슬은
    mcp_server → jobs → pipeline → audio 로 이어진다.
    """

    def _extra(self, name: str) -> list[str]:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        block = text.split(f"{name} = [", 1)[1].split("]", 1)[0]
        return [line.strip().strip('",\'') for line in block.splitlines()
                if line.strip() and not line.strip().startswith("#")]

    def test_extra_declares_every_module_level_dependency_of_the_import_chain(self):
        declared = " ".join(self._extra("mcp")).lower()
        # 서버가 뜰 때 반드시 import 되는 서드파티
        for required in ("mcp", "yt-dlp"):
            assert required in declared, f"{required} 가 [mcp] extra 에 없다: {declared}"

    def test_import_chain_has_no_undeclared_third_party_module(self):
        """사슬 위 모듈들의 모듈 레벨 import 를 훑어 선언과 대조한다."""
        import ast

        declared = " ".join(self._extra("mcp") + ["pyyaml"]).lower().replace("-", "_")
        third_party = set()
        for name in ("mcp_server", "jobs", "pipeline", "audio", "options",
                     "pipeline_worker", "service"):
            path = ROOT / "gurunote" / f"{name}.py"
            if not path.is_file():
                continue
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Import):
                    third_party |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    third_party.add(node.module.split(".")[0])
        import sys

        external = {
            m for m in third_party
            if m not in sys.stdlib_module_names and m not in ("gurunote", "__future__")
        }
        missing = sorted(m for m in external if m.replace("-", "_") not in declared)
        assert missing == [], f"[mcp] extra 에 없는 모듈 레벨 의존성: {missing}"


class TestSkillDocument:
    def test_skill_file_has_frontmatter_and_names_the_tools(self):
        text = (ROOT / "skills/gurunote/SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---")
        header = text.split("---")[1]
        assert "name: gurunote" in header
        assert "description:" in header
        for tool in ("note_start", "note_status", "search", "history"):
            assert tool in text, tool


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

"""UI 없는 파이프라인 진입점 — 동기 래퍼와 CLI.

실제 STT·LLM 을 호출하지 않는다. `run_pipeline` 의 `worker_factory` 로 가짜 워커를
주입해 큐 계약만 검사한다. 큐에 무엇이 들어오고 스레드가 어떻게 끝나는지가 이 층의
책임 전부다.
"""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from gurunote import cli
from gurunote.options import LLM_PROVIDERS, STT_ENGINES
from gurunote.pipeline import (
    PipelineResult,
    PipelineTimeout,
    resolve_source,
    run_pipeline,
)


class FakeWorker:
    """`PipelineWorker` 의 큐 계약만 흉내내는 대역."""

    def __init__(self, engine, provider, *, youtube_url="", local_file="",
                 payload=None, logs=(), progress=(), hang=False, die_silently=False):
        self.engine = engine
        self.provider = provider
        self.youtube_url = youtube_url
        self.local_file = local_file
        self.job_id = "20260914_000000_fake"
        self.msg_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self._thread = None
        self._payload = payload if payload is not None else {"ok": True, "full_md": "# 노트"}
        self._logs = list(logs)
        self._progress = list(progress)
        self._hang = hang
        self._die_silently = die_silently
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        for line in self._logs:
            self.msg_queue.put(line)
        for pct in self._progress:
            self.progress_queue.put(pct)
        if self._hang:
            while not self.stop_requested:
                time.sleep(0.01)
            return
        if self._die_silently:
            return
        self.result_queue.put(self._payload)


def factory(**preset):
    def make(engine, provider, *, youtube_url="", local_file=""):
        return FakeWorker(engine, provider, youtube_url=youtube_url,
                          local_file=local_file, **preset)
    return make


class TestResolveSource:
    def test_youtube_url_goes_to_the_url_slot(self):
        assert resolve_source("https://www.youtube.com/watch?v=abc12345678") == (
            "https://www.youtube.com/watch?v=abc12345678", "")

    def test_existing_supported_file_goes_to_the_file_slot(self, tmp_path):
        audio = tmp_path / "talk.mp3"
        audio.write_bytes(b"\x00")
        url, path = resolve_source(str(audio))
        assert url == ""
        assert path == str(audio)

    @pytest.mark.parametrize("bad,pattern", [
        ("", "비어"),
        ("   ", "비어"),
        ("./does-not-exist.mp3", "해석되지"),
    ])
    def test_unusable_input_is_refused(self, bad, pattern):
        with pytest.raises(ValueError, match=pattern):
            resolve_source(bad)

    def test_unsupported_extension_is_refused(self, tmp_path):
        doc = tmp_path / "notes.txt"
        doc.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="확장자"):
            resolve_source(str(doc))

    def test_directory_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="파일이 아닙니다|해석되지"):
            resolve_source(str(tmp_path))


class TestRunPipeline:
    def test_success_returns_the_note_and_drains_logs(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        seen_logs, seen_pct = [], []
        result = run_pipeline(
            str(audio),
            on_log=seen_logs.append,
            on_progress=seen_pct.append,
            worker_factory=factory(
                payload={"ok": True, "full_md": "# 제목", "summary_md": "## 요약"},
                logs=["[Step 1] 시작", "[Done]"], progress=[0.1, 1.0]),
        )
        assert isinstance(result, PipelineResult)
        assert result.ok is True
        assert result.full_md == "# 제목"
        assert result.summary_md == "## 요약"
        assert result.job_id == "20260914_000000_fake"
        assert seen_logs == ["[Step 1] 시작", "[Done]"]
        assert result.logs == seen_logs
        assert seen_pct == [0.1, 1.0]

    def test_failure_carries_the_error_and_job_id(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        result = run_pipeline(str(audio),
                              worker_factory=factory(payload={"ok": False, "error": "모델 없음"}))
        assert result.ok is False
        assert result.error == "모델 없음"
        assert result.job_id == "20260914_000000_fake"
        assert result.full_md == ""

    def test_source_decides_which_worker_slot_is_filled(self, tmp_path):
        made = {}

        def capture(engine, provider, *, youtube_url="", local_file=""):
            worker = FakeWorker(engine, provider, youtube_url=youtube_url, local_file=local_file)
            made.update(url=youtube_url, path=local_file, engine=engine, provider=provider)
            return worker

        audio = tmp_path / "a.wav"
        audio.write_bytes(b"\x00")
        run_pipeline(str(audio), engine="mlx", provider="anthropic", worker_factory=capture)
        assert made["path"] == str(audio) and made["url"] == ""
        assert made["engine"] == "mlx" and made["provider"] == "anthropic"

        run_pipeline("https://youtu.be/abcdefghijk", worker_factory=capture)
        assert made["url"] == "https://youtu.be/abcdefghijk" and made["path"] == ""

    @pytest.mark.parametrize("kwargs,pattern", [
        ({"engine": "nope"}, "engine"),
        ({"provider": "nope"}, "provider"),
        ({"timeout": 0}, "timeout"),
        ({"timeout": -3}, "timeout"),
    ])
    def test_invalid_options_are_refused_before_any_work(self, tmp_path, kwargs, pattern):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        started = []

        def never(engine, provider, *, youtube_url="", local_file=""):
            started.append(True)
            return FakeWorker(engine, provider)

        with pytest.raises(ValueError, match=pattern):
            run_pipeline(str(audio), worker_factory=never, **kwargs)
        assert started == [], "검증 실패인데 워커를 만들었다"

    def test_empty_provider_is_allowed_and_means_use_the_environment(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        result = run_pipeline(str(audio), provider="", worker_factory=factory())
        assert result.ok is True

    def test_timeout_asks_the_worker_to_stop(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        made = []

        def hanging(engine, provider, *, youtube_url="", local_file=""):
            worker = FakeWorker(engine, provider, hang=True)
            made.append(worker)
            return worker

        with pytest.raises(PipelineTimeout):
            run_pipeline(str(audio), timeout=0.2, worker_factory=hanging)
        assert made[0].stop_requested is True

    def test_thread_ending_without_a_result_is_reported_not_hung(self, tmp_path):
        audio = tmp_path / "a.mp3"
        audio.write_bytes(b"\x00")
        result = run_pipeline(str(audio), timeout=5,
                              worker_factory=factory(die_silently=True))
        assert result.ok is False
        assert "결과를 남기지" in result.error


class TestCli:
    def test_engines_and_providers_match_the_single_source(self, capsys):
        assert cli.main(["engines"]) == 0
        assert capsys.readouterr().out.split() == list(STT_ENGINES)
        assert cli.main(["providers"]) == 0
        assert capsys.readouterr().out.split() == list(LLM_PROVIDERS)

    def test_note_prints_the_markdown_on_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: PipelineResult(
            ok=True, job_id="j1", full_md="# 노트 본문"))
        assert cli.main(["note", "https://youtu.be/abcdefghijk", "--quiet"]) == 0
        assert capsys.readouterr().out.strip() == "# 노트 본문"

    def test_note_writes_to_out_and_prints_only_the_path(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: PipelineResult(
            ok=True, job_id="j1", full_md="# 파일로"))
        target = tmp_path / "sub" / "note.md"
        assert cli.main(["note", "https://youtu.be/abcdefghijk", "--out", str(target), "--quiet"]) == 0
        assert target.read_text(encoding="utf-8") == "# 파일로"
        assert capsys.readouterr().out.strip() == str(target)

    def test_json_output_is_parseable_and_carries_the_fields(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: PipelineResult(
            ok=True, job_id="j2", full_md="# md", summary_md="## s"))
        assert cli.main(["note", "https://youtu.be/abcdefghijk", "--json", "--quiet"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"ok": True, "job_id": "j2", "full_md": "# md",
                           "summary_md": "## s", "error": ""}

    def test_failure_exits_nonzero_and_keeps_stdout_clean(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: PipelineResult(
            ok=False, job_id="j3", error="변환 실패"))
        assert cli.main(["note", "https://youtu.be/abcdefghijk", "--quiet"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "변환 실패" in captured.err and "j3" in captured.err

    def test_bad_input_exits_two(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise ValueError("해석되지 않습니다")
        monkeypatch.setattr(cli, "run_pipeline", boom)
        assert cli.main(["note", "nonsense", "--quiet"]) == 2
        assert "해석되지" in capsys.readouterr().err

    def test_timeout_exits_124(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise PipelineTimeout("30초 안에 끝나지 않았습니다")
        monkeypatch.setattr(cli, "run_pipeline", boom)
        assert cli.main(["note", "https://youtu.be/abcdefghijk", "--timeout", "30", "--quiet"]) == 124
        assert "30초" in capsys.readouterr().err

    def test_progress_logs_go_to_stderr_not_stdout(self, monkeypatch, capsys):
        def echo(source, **kwargs):
            kwargs["on_log"]("[Step 1] 진행 중")
            return PipelineResult(ok=True, job_id="j4", full_md="# 본문")
        monkeypatch.setattr(cli, "run_pipeline", echo)
        assert cli.main(["note", "https://youtu.be/abcdefghijk"]) == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "# 본문"
        assert "[Step 1] 진행 중" in captured.err

    def test_parser_rejects_unknown_engine(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["note", "x", "--engine", "unknown"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

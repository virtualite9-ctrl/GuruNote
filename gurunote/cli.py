"""GuruNote 명령줄 진입점.

창을 띄우지 않고 파이프라인을 돌린다. 사람이 터미널에서 쓰기도 하고, 에이전트가
`--json` 으로 결과를 받아 쓰기도 한다.

    gurunote note "https://youtu.be/..." --out note.md
    gurunote note ./talk.mp3 --engine mlx --json
    gurunote engines
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from gurunote import __version__
from gurunote.options import (
    DEFAULT_STT_ENGINE,
    LLM_PROVIDERS,
    STT_ENGINES,
    USE_ENV_LLM_PROVIDER,
)
from gurunote.pipeline import PipelineTimeout, run_pipeline

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gurunote",
        description="영상·오디오를 한국어 노트로 변환한다 (UI 없이 실행).",
    )
    parser.add_argument("--version", action="version", version=f"gurunote {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    note = sub.add_parser("note", help="파이프라인을 실행해 노트를 만든다")
    note.add_argument("source", help="유튜브 URL 또는 로컬 오디오/영상 파일 경로")
    note.add_argument(
        "--engine", default=DEFAULT_STT_ENGINE, choices=list(STT_ENGINES),
        help=f"STT 엔진 (기본: {DEFAULT_STT_ENGINE})",
    )
    note.add_argument(
        "--provider", default=USE_ENV_LLM_PROVIDER, choices=[""] + list(LLM_PROVIDERS),
        help="LLM provider (기본: LLM_PROVIDER 환경변수)",
    )
    note.add_argument("--out", metavar="FILE", help="노트를 이 경로에 쓴다 (기본: stdout)")
    note.add_argument("--timeout", type=float, metavar="SEC", help="초과 시 중지를 요청한다")
    note.add_argument("--json", action="store_true", help="사람이 읽는 노트 대신 JSON 결과를 낸다")
    note.add_argument("--quiet", action="store_true", help="진행 로그를 stderr 로도 내지 않는다")

    sub.add_parser("engines", help="선택 가능한 STT 엔진을 나열한다")
    sub.add_parser("providers", help="선택 가능한 LLM provider 를 나열한다")
    return parser


def _run_note(args: argparse.Namespace) -> int:
    # 진행 로그는 stderr 로 보낸다. stdout 은 노트/JSON 전용이라 파이프로 받을 수 있다.
    on_log = None if args.quiet else (lambda line: print(line, file=sys.stderr, flush=True))
    try:
        result = run_pipeline(
            args.source,
            engine=args.engine,
            provider=args.provider,
            on_log=on_log,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print(f"gurunote: {exc}", file=sys.stderr)
        return 2
    except PipelineTimeout as exc:
        print(f"gurunote: {exc}", file=sys.stderr)
        return 124

    if args.json:
        payload = {
            "ok": result.ok,
            "job_id": result.job_id,
            "full_md": result.full_md,
            "summary_md": result.summary_md,
            "error": result.error,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    if not result.ok:
        print(f"gurunote: 실패 — {result.error}", file=sys.stderr)
        print(f"gurunote: 로그 job_id={result.job_id}", file=sys.stderr)
        return 1

    if args.out:
        path = Path(args.out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.full_md, encoding="utf-8")
        print(str(path))
    else:
        print(result.full_md)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "note":
        return _run_note(args)
    if args.command == "engines":
        for name in STT_ENGINES:
            print(name)
        return 0
    if args.command == "providers":
        for name in LLM_PROVIDERS:
            print(name)
        return 0
    return 2  # argparse 가 required=True 로 막으므로 정상 경로에서는 닿지 않는다.


if __name__ == "__main__":
    raise SystemExit(main())

"""통합 본체 재분할 + char_limit 검증 — oE5lNDhz9oo (5/24, HEAD 527d2ea).

raw.json (cache) → 통합 본체 _resplit_segments_by_semantics + translate_transcript
로 토글 on/off 비교. STT 재실행 부재 (cache 재사용).

검증:
- 토글 on: 재분할 334→309, char_limit=2000 자동, D leak 해소, 정합 향상
- 토글 off: 재분할 부재, char_limit 기존 (12000) — daily 보호
- 통합 본체 = prototype 일치
"""
from __future__ import annotations

import os
import sys
import re
import json
import time
import shutil
from pathlib import Path
from typing import List

for line in open("/Users/gesicht/GuruNote/.env").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

sys.path.insert(0, "/Users/gesicht/GuruNote")
from gurunote.types import Segment, Transcript
from gurunote.llm import LLMConfig, translate_transcript, chunk_segments
from gurunote.stt.mlx import (
    _resplit_segments_by_semantics,
    _assign_speaker_by_overlap,
    _normalize_speaker_label,
    SEGMENT_RESPLIT_ENV,
)

RAW_PATH = Path("/Users/gesicht/GuruNote/verify_results/community1_3speakers_raw.json")
OUT_DIR = Path("/Users/gesicht/GuruNote/verify_results/integration_verify")
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path.home() / ".gurunote" / "entity_cache"

MODEL = "Qwen3.6-35B-A3B-oQ6-mtp"
VIDEO_ID = "oE5lNDhz9oo"


def isolate_cache(label):
    bak = CACHE_DIR.parent / f"entity_cache.bak.{label}"
    if CACHE_DIR.exists():
        shutil.move(str(CACHE_DIR), str(bak))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return bak


def restore_cache(bak):
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    if bak.exists():
        shutil.move(str(bak), str(CACHE_DIR))


def build_transcript_from_raw(raw_segs: List[dict], turns: List[dict],
                                resplit_on: bool) -> Transcript:
    """통합 본체 path 재현: raw segments → (재분할 on 시 _resplit_segments_by_semantics)
    → noise/dedup loop (stt/mlx.py 동일) → Transcript (raw={"segment_resplit": resplit_on}).
    """
    NOISE = {"", ".", "-", "—", "...", "…"}

    # diarization turns format: [{"start", "end", "speaker"}] → tuple
    turn_tuples = [(t["start"], t["end"], t["speaker"]) for t in turns]

    if resplit_on:
        raw_for_norm = _resplit_segments_by_semantics(raw_segs, turn_tuples)
    else:
        raw_for_norm = raw_segs

    segs = []
    seen = set()
    for s in raw_for_norm:
        text = (s.get("text") or "").strip()
        if text in NOISE:
            continue
        start = float(s.get("start", 0.0))
        end = float(s.get("end", 0.0))
        speaker = _assign_speaker_by_overlap(start, end, turn_tuples) if turn_tuples else "A"
        key = (round(start, 2), speaker, text)
        if key in seen:
            continue
        seen.add(key)
        segs.append(Segment(speaker=speaker, start=start, end=end, text=text))

    return Transcript(
        segments=segs, engine="mlx", language="en",
        raw={"language": "en", "model": "mlx-whisper-large-v3",
              "segment_resplit": resplit_on},
    )


def collect_log(label):
    lines = []
    def fn(msg):
        ts = time.strftime("%H:%M:%S")
        lines.append(f"[{ts}] {msg}")
        if any(k in msg for k in ["⚠", "🛟", "🌐"]):
            print(f"    [{label}] {msg[:160]}", flush=True)
    return fn, lines


def run_translate(transcript, label, video_id):
    os.environ["GURUNOTE_TWO_PASS"] = "1"
    config = LLMConfig.from_env(provider="openai_compatible")
    config.model = MODEL
    vctx = {"id": video_id, "title": "NVIDIA Dell interview",
             "uploader": "Bloomberg Television",
             "description": "Jensen Huang, Michael Dell, Ed Ludlow",
             "url": f"https://youtu.be/{VIDEO_ID}"}
    log_fn, log_lines = collect_log(label)
    t0 = time.time()
    body = translate_transcript(transcript, config=config, progress=log_fn,
                                 video_context=vctx, stop_event=None)
    elapsed = time.time() - t0
    return body, log_lines, elapsed


def analyze_2pass(log_lines):
    pattern = re.compile(r"1단계 출력 — (\d+) lines / N=(\d+)")
    lc = [(int(m.group(1)), int(m.group(2)))
           for m in (pattern.search(ln) for ln in log_lines) if m]
    timeouts = sum(1 for ln in log_lines if "wall-clock timeout — retry" in ln)
    return {
        "total_chunks": len(lc),
        "match_exact": sum(1 for ln, n in lc if ln == n),
        "match_less": sum(1 for ln, n in lc if ln < n),
        "match_extreme": sum(1 for ln, n in lc if ln == 1 and n > 5),
        "timeouts": timeouts,
    }


def check_chunk_sizes(transcript):
    """chunk_segments 호출이 transcript.raw 신호로 두 한도 자동 catch 확인."""
    # translate_transcript 안과 동일 분기 catch
    resplit_applied = bool(getattr(transcript, "raw", None)
                            and transcript.raw.get("segment_resplit"))
    if resplit_applied:
        from gurunote.llm import RESPLIT_CHAR_LIMIT, RESPLIT_SEGMENT_LIMIT
        chunks = chunk_segments(transcript.segments,
                                  char_limit=RESPLIT_CHAR_LIMIT,
                                  segment_limit=RESPLIT_SEGMENT_LIMIT)
    else:
        chunks = chunk_segments(transcript.segments)
    chunk_chars = [sum(len(s.text) + 30 for s in c) for c in chunks]
    return {
        "chunks": len(chunks),
        "chunk_max": max(chunk_chars) if chunk_chars else 0,
        "chunk_avg": sum(chunk_chars) / max(1, len(chunk_chars)),
        "resplit_applied": resplit_applied,
    }


def main():
    print(f"통합 본체 검증 — {VIDEO_ID} (HEAD 527d2ea)")
    print(f"모델: {MODEL}")
    print()

    raw = json.load(open(RAW_PATH))
    raw_segs = raw["segments"]
    turns = raw["diarization"]
    print(f"raw segments: {len(raw_segs)}, diarization turns: {len(turns)}")
    print()

    # ---- 토글 ON 검증
    print("=" * 70)
    print("Step 1: 토글 ON (재분할 + char_limit=2000)")
    print("=" * 70)
    tr_on = build_transcript_from_raw(raw_segs, turns, resplit_on=True)
    print(f"재분할: {len(raw_segs)} → {len(tr_on.segments)} segments")
    print(f"Transcript.raw['segment_resplit']: {tr_on.raw.get('segment_resplit')}")

    chunks_on = check_chunk_sizes(tr_on)
    print(f"chunk: {chunks_on['chunks']} chunks, max={chunks_on['chunk_max']:.0f}, "
          f"avg={chunks_on['chunk_avg']:.0f}, resplit_applied={chunks_on['resplit_applied']}")

    # ---- 토글 OFF 검증
    print()
    print("=" * 70)
    print("Step 3: 토글 OFF (재분할 부재 + char_limit=12000)")
    print("=" * 70)
    tr_off = build_transcript_from_raw(raw_segs, turns, resplit_on=False)
    print(f"재분할 부재: {len(raw_segs)} → {len(tr_off.segments)} segments "
          f"(noise/dedup만 — 기존 path)")
    print(f"Transcript.raw['segment_resplit']: {tr_off.raw.get('segment_resplit')}")

    chunks_off = check_chunk_sizes(tr_off)
    print(f"chunk: {chunks_off['chunks']} chunks, max={chunks_off['chunk_max']:.0f}, "
          f"avg={chunks_off['chunk_avg']:.0f}, resplit_applied={chunks_off['resplit_applied']}")

    # ---- 2-pass 토글 ON 처리
    print()
    print("=" * 70)
    print("Step 2: 2-pass 토글 ON 처리 (prototype 효과 재현)")
    print("=" * 70)
    bak = isolate_cache(f"{VIDEO_ID}_on")
    try:
        body_on, log_on, elapsed_on = run_translate(
            tr_on, label="on", video_id=f"{VIDEO_ID}_integ_on")
        (OUT_DIR / "on_body.md").write_text(body_on, encoding="utf-8")
        (OUT_DIR / "on_log.txt").write_text("\n".join(log_on), encoding="utf-8")
        an_on = analyze_2pass(log_on)
        print(f"  time: {elapsed_on:.0f}s")
        print(f"  1단계 정합: {an_on['match_exact']}/{an_on['total_chunks']} "
              f"({an_on['match_exact']/an_on['total_chunks']*100:.0f}%)")
        print(f"  합침: {an_on['match_less']}, 극단(1줄): {an_on['match_extreme']}")
        print(f"  timeouts: {an_on['timeouts']}")
    finally:
        restore_cache(bak)

    # ---- 종합
    print()
    print("=" * 70)
    print("종합 — 통합 본체 = prototype 일치?")
    print("=" * 70)
    chunk_max_on = chunks_on["chunk_max"]
    chunk_max_off = chunks_off["chunk_max"]
    pct = an_on["match_exact"] / an_on["total_chunks"] * 100 if an_on["total_chunks"] else 0
    print(f"  metric                       | prototype (5/24)    | 본 측정 (통합)")
    print(f"  재분할 334→                  | 309                 | {len(tr_on.segments)}")
    print(f"  토글 on chunk_max            | ~1989 (F3 영상)     | {chunk_max_on:.0f}")
    print(f"  토글 on chunks               | ~26                 | {chunks_on['chunks']}")
    print(f"  2-pass 정합                  | 12/21 (57%)         | "
          f"{an_on['match_exact']}/{an_on['total_chunks']} ({pct:.0f}%)")
    print(f"  2-pass timeouts              | 0                   | {an_on['timeouts']}")
    print(f"  토글 off chunk_max           | ~1631 (cs=15 default) | {chunk_max_off:.0f}")
    print(f"  토글 off chunks              | ~21                 | {chunks_off['chunks']}")

    # save analysis
    (OUT_DIR / "analysis.json").write_text(
        json.dumps({
            "on": {"segments": len(tr_on.segments), **chunks_on, **an_on,
                    "elapsed": elapsed_on},
            "off": {"segments": len(tr_off.segments), **chunks_off},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved: {OUT_DIR}/analysis.json")


if __name__ == "__main__":
    main()

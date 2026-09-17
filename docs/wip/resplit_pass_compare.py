"""재분할 전후 1-pass + 2-pass 직접 측정 (5/24).

영상: oE5lNDhz9oo
입력:
  - 재분할 전: verify_results/community1_3speakers_raw.json 의 segments (334)
  - 재분할 후: verify_results/community1_3speakers_resplit.json (309)
모델: qwen3.6-35b-A3B-oQ6-mtp
측정:
  - 2-pass 재분할 후: 1단계 line 수 / N 분포, SHIFT/빈, 본문 비교
  - 1-pass 재분할 후 vs 전: 미완 segment hallucinate 차이
  - 화자/timestamp/B06 회귀

출력:
  - verify_results/resplit_2pass_body.md  (재분할 + 2-pass)
  - verify_results/resplit_2pass_log.txt  (1단계 line catch log)
  - verify_results/resplit_1pass_body.md  (재분할 + 1-pass)
  - verify_results/orig_1pass_body.md     (원본 segments + 1-pass)
  - verify_results/resplit_pass_compare_report.md
"""
from __future__ import annotations

import os
import sys
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
from gurunote.llm import LLMConfig, translate_transcript

VIDEO_ID = "oE5lNDhz9oo"
OUT_DIR = Path("/Users/gesicht/GuruNote/verify_results")
CACHE_DIR = Path.home() / ".gurunote" / "entity_cache"

RAW_JSON = OUT_DIR / "community1_3speakers_raw.json"
RESPLIT_JSON = OUT_DIR / "community1_3speakers_resplit.json"


def build_transcript_from_raw_segs(segs: List[dict], turns: List[dict]) -> Transcript:
    """raw STT segments → Transcript (화자 재할당 + noise 필터, stt/mlx.py 동일 path)."""
    NOISE = {"", ".", "-", "—", "...", "…"}

    def normalize(raw):
        if raw and raw.startswith("SPEAKER_"):
            try:
                return chr(ord("A") + int(raw.split("_")[-1]))
            except (ValueError, IndexError):
                return raw
        return raw or "A"

    def assign(start, end):
        by = {}
        for t in turns:
            ov = min(end, t["end"]) - max(start, t["start"])
            if ov > 0:
                sp = normalize(t["speaker"])
                by[sp] = by.get(sp, 0) + ov
        if not by:
            return "A"
        return max(by.items(), key=lambda kv: kv[1])[0]

    out = []
    seen = set()
    for s in segs:
        text = (s.get("text") or "").strip()
        if text in NOISE:
            continue
        speaker = s.get("speaker") or assign(s["start"], s["end"])
        key = (round(s["start"], 2), speaker, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(Segment(speaker=speaker, start=float(s["start"]),
                            end=float(s["end"]), text=text))
    return Transcript(segments=out, engine="mlx", language="en",
                       raw={"language": "en", "model": "mlx-whisper-large-v3"})


def build_transcript_from_resplit(resplit: List[dict]) -> Transcript:
    """재분할 segments → Transcript (이미 화자 부착됨)."""
    segs = [Segment(speaker=s["speaker"], start=float(s["start"]),
                     end=float(s["end"]), text=s["text"]) for s in resplit]
    return Transcript(segments=segs, engine="mlx", language="en",
                       raw={"language": "en", "model": "mlx-whisper-large-v3"})


def collect_log(label: str):
    """log_progress — 진행 메시지 모음."""
    lines = []
    def fn(msg):
        ts = time.strftime("%H:%M:%S")
        lines.append(f"[{ts}] {msg}")
        if any(k in msg for k in ["2-pass", "🛟", "⚠", "1단계", "복구", "정렬", "chunk"]):
            print(f"    [{label}] {msg}", flush=True)
    return fn, lines


def run_translate(transcript: Transcript, two_pass: bool, label: str,
                   video_id: str, video_title: str = "test"):
    """translate_transcript 호출 — 결과 + log + 시간 반환."""
    os.environ["GURUNOTE_TWO_PASS"] = "1" if two_pass else "0"

    config = LLMConfig.from_env(provider="openai_compatible")
    # 모델 강제 — daily q5 가 아닌 35b-A3B (D prototype 모델 동일)
    config.model = "Qwen3.6-35B-A3B-oQ6-mtp"

    video_context = {
        "id": video_id,
        "title": "NVIDIA Dell Jensen Huang interview",
        "uploader": "Bloomberg Television",
        "description": "interview with Jensen Huang, Michael Dell, and Ed Ludlow",
        "url": f"https://youtu.be/{video_id}",
    }

    log_fn, log_lines = collect_log(label)
    t0 = time.time()
    result = translate_transcript(
        transcript,
        config=config,
        progress=log_fn,
        video_context=video_context,
        stop_event=None,
    )
    elapsed = time.time() - t0
    return result, log_lines, elapsed


def isolate_cache(label: str):
    """cache 격리 — 실험 간 오염 차단 (label별 cache 디렉터리)."""
    bak = CACHE_DIR.parent / f"entity_cache.bak.{label}"
    if CACHE_DIR.exists():
        shutil.move(str(CACHE_DIR), str(bak))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return bak


def restore_cache(bak: Path):
    """원래 cache 복원."""
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    if bak.exists():
        shutil.move(str(bak), str(CACHE_DIR))


def analyze_2pass_log(log_lines: List[str]) -> dict:
    """1단계 line 수 / N 분포 catch."""
    import re
    pattern = re.compile(r"1단계 출력 — (\d+) lines / N=(\d+)")
    line_counts = []   # (lines, N)
    empty_recoveries = 0
    timeouts = 0
    align_mismatch = 0
    for line in log_lines:
        m = pattern.search(line)
        if m:
            line_counts.append((int(m.group(1)), int(m.group(2))))
        if "🛟 빈 output 복구" in line:
            empty_recoveries += 1
        if "timeout" in line.lower():
            timeouts += 1
        if "정렬 mismatch" in line or "align mismatch" in line.lower():
            align_mismatch += 1
    return {
        "line_counts": line_counts,
        "match_exact": sum(1 for ln, n in line_counts if ln == n),
        "match_less": sum(1 for ln, n in line_counts if ln < n),
        "match_extreme": sum(1 for ln, n in line_counts if ln == 1 and n > 5),
        "total_chunks": len(line_counts),
        "empty_recoveries": empty_recoveries,
        "timeouts": timeouts,
        "align_mismatch": align_mismatch,
    }


def main():
    print("=" * 70)
    print("재분할 전후 1-pass + 2-pass 직접 측정")
    print("=" * 70)

    # ---- 입력 catch
    raw = json.load(open(RAW_JSON))
    resplit = json.load(open(RESPLIT_JSON))
    orig_tr = build_transcript_from_raw_segs(raw["segments"], raw["diarization"])
    resp_tr = build_transcript_from_resplit(resplit)
    print(f"원본 Transcript: {len(orig_tr.segments)} segments")
    print(f"재분할 Transcript: {len(resp_tr.segments)} segments")

    # ---- 1. 재분할 + 2-pass
    print("\n--- 1. 재분할 + 2-pass ---")
    bak = isolate_cache("resplit_2pass")
    try:
        body, log_lines, elapsed = run_translate(resp_tr, two_pass=True,
                                                  label="resp_2pass",
                                                  video_id=f"{VIDEO_ID}_resplit_2pass")
        (OUT_DIR / "resplit_2pass_body.md").write_text(body, encoding="utf-8")
        (OUT_DIR / "resplit_2pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        s2p_resp = analyze_2pass_log(log_lines)
        print(f"  time: {elapsed:.1f}s, body lines: {body.count(chr(10))}")
        print(f"  2-pass 1단계 line==N: {s2p_resp['match_exact']} / {s2p_resp['total_chunks']}")
        print(f"  1단계 line<N (합침): {s2p_resp['match_less']}")
        print(f"  극단 (1줄, N>5): {s2p_resp['match_extreme']}")
        print(f"  빈 복구 발동: {s2p_resp['empty_recoveries']}")
        print(f"  timeouts: {s2p_resp['timeouts']}")
    finally:
        restore_cache(bak)

    # ---- 2. 재분할 + 1-pass
    print("\n--- 2. 재분할 + 1-pass ---")
    bak = isolate_cache("resplit_1pass")
    try:
        body, log_lines, elapsed = run_translate(resp_tr, two_pass=False,
                                                  label="resp_1pass",
                                                  video_id=f"{VIDEO_ID}_resplit_1pass")
        (OUT_DIR / "resplit_1pass_body.md").write_text(body, encoding="utf-8")
        (OUT_DIR / "resplit_1pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        print(f"  time: {elapsed:.1f}s, body lines: {body.count(chr(10))}")
    finally:
        restore_cache(bak)

    # ---- 3. 원본 + 1-pass (재분할 전 1-pass 기준)
    print("\n--- 3. 원본 + 1-pass (재분할 전 기준) ---")
    bak = isolate_cache("orig_1pass")
    try:
        body, log_lines, elapsed = run_translate(orig_tr, two_pass=False,
                                                  label="orig_1pass",
                                                  video_id=f"{VIDEO_ID}_orig_1pass")
        (OUT_DIR / "orig_1pass_body.md").write_text(body, encoding="utf-8")
        (OUT_DIR / "orig_1pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        print(f"  time: {elapsed:.1f}s, body lines: {body.count(chr(10))}")
    finally:
        restore_cache(bak)

    # ---- 4. 원본 + 2-pass (재현 — 35b-A3B 동일 모델로 5/23 catch는 q5 모델 가능성)
    print("\n--- 4. 원본 + 2-pass (35b-A3B 재현) ---")
    bak = isolate_cache("orig_2pass")
    try:
        body, log_lines, elapsed = run_translate(orig_tr, two_pass=True,
                                                  label="orig_2pass",
                                                  video_id=f"{VIDEO_ID}_orig_2pass")
        (OUT_DIR / "orig_2pass_body.md").write_text(body, encoding="utf-8")
        (OUT_DIR / "orig_2pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        s2p_orig = analyze_2pass_log(log_lines)
        print(f"  time: {elapsed:.1f}s, body lines: {body.count(chr(10))}")
        print(f"  2-pass 1단계 line==N: {s2p_orig['match_exact']} / {s2p_orig['total_chunks']}")
        print(f"  1단계 line<N (합침): {s2p_orig['match_less']}")
        print(f"  극단 (1줄, N>5): {s2p_orig['match_extreme']}")
        print(f"  빈 복구 발동: {s2p_orig['empty_recoveries']}")
        print(f"  timeouts: {s2p_orig['timeouts']}")
    finally:
        restore_cache(bak)

    # ---- 5. 종합 비교
    print("\n" + "=" * 70)
    print("종합 비교 — 재분할 전후 2-pass 1단계 합침")
    print("=" * 70)
    print(f"{'metric':<30} {'원본 2-pass':>15} {'재분할 2-pass':>15}")
    print(f"{'-':<30} {'-':>15} {'-':>15}")
    print(f"{'1단계 line==N (정합)':<30} "
          f"{s2p_orig['match_exact']:>5} / {s2p_orig['total_chunks']:<5}     "
          f"{s2p_resp['match_exact']:>5} / {s2p_resp['total_chunks']:<5}")
    print(f"{'1단계 line<N (합침)':<30} "
          f"{s2p_orig['match_less']:>5}{' '*9}     "
          f"{s2p_resp['match_less']:>5}")
    print(f"{'극단 (1줄, N>5)':<30} "
          f"{s2p_orig['match_extreme']:>5}{' '*9}     "
          f"{s2p_resp['match_extreme']:>5}")
    print(f"{'빈 복구 발동':<30} "
          f"{s2p_orig['empty_recoveries']:>5}{' '*9}     "
          f"{s2p_resp['empty_recoveries']:>5}")
    print(f"{'timeouts':<30} "
          f"{s2p_orig['timeouts']:>5}{' '*9}     "
          f"{s2p_resp['timeouts']:>5}")

    # save analysis
    (OUT_DIR / "resplit_pass_analysis.json").write_text(
        json.dumps({"orig_2pass": s2p_orig, "resplit_2pass": s2p_resp},
                   ensure_ascii=False, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

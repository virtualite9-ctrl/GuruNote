"""6개 영상 cs=12 견고성 측정 (5/24).

각 영상: download → STT(MLX) + community-1 diarization → 재분할(word-level 방법 4)
        → 1-pass cs=12 + 2-pass cs=12.

측정:
  - segment 평균/최대 길이 (영상 특성)
  - 1-pass timeout / 길이 미스매치 / 시간
  - 2-pass 1단계 정합 / 합침 / 극단 / 시간
  - 재분할 부재 case: TED 독백/인터뷰/기타 영상

cache 격리: 각 측정마다 entity_cache 격리.
모델: Qwen3.6-35B-A3B-oQ6-mtp.
모든 결과: verify_results/mv/<video_id>/ 디렉터리.
"""
from __future__ import annotations

import os
import sys
import json
import re
import time
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import List, Dict

for line in open("/Users/gesicht/GuruNote/.env").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

sys.path.insert(0, "/Users/gesicht/GuruNote")
sys.path.insert(0, "/Users/gesicht/GuruNote/docs/wip")
import gurunote.llm as llm_mod
from gurunote.audio import download_audio
from gurunote.types import Segment, Transcript
from gurunote.llm import LLMConfig, translate_transcript

from resplit_prototype import resplit_segments  # noqa: E402

VIDEOS = [
    ("C18aaP4lvUk", "TED (긴 발화/독백 1)"),
    ("g3M3WaixeOw", "TED (긴 발화/독백 2)"),
    ("7ZFh7qI1xyg", "인터뷰 1 (주고받기)"),
    ("adgbH9FixW0", "인터뷰 2 (주고받기)"),
    ("F3QDC7HDMyg", "기타 1"),
    ("FG5JsLHPW_I", "기타 2"),
]

OUT_DIR = Path("/Users/gesicht/GuruNote/verify_results/mv")
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path.home() / ".gurunote" / "entity_cache"

MODEL = "Qwen3.6-35B-A3B-oQ6-mtp"
CHUNK_SIZE = 12


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


def stt_raw_dump(video_id: str, video_dir: Path) -> Dict:
    """STT raw + diarization → JSON. 캐시 catch."""
    out = video_dir / "raw.json"
    if out.exists():
        print(f"  [STT] 이미 catch: {out.name}")
        return json.load(open(out))

    print(f"  [STT] download…")
    warnings.filterwarnings("ignore")
    with tempfile.TemporaryDirectory(prefix=f"mv_{video_id}_") as tmp:
        try:
            audio = download_audio(f"https://youtu.be/{video_id}", tmp)
        except Exception as exc:
            print(f"  [STT] download 실패: {exc}")
            return None

        print(f"  [STT] mlx-whisper… (duration {audio.duration_sec:.0f}s)")
        import mlx_whisper
        model_repo = os.environ.get("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")
        t0 = time.time()
        result = mlx_whisper.transcribe(audio.audio_path, path_or_hf_repo=model_repo,
                                         word_timestamps=True, verbose=False)
        raw_segs = result.get("segments", [])
        print(f"  [STT] {time.time()-t0:.0f}s, {len(raw_segs)} segments")

        print(f"  [DIAR] community-1…")
        from gurunote.stt.mlx import _diarize_with_pyannote
        hf_token = os.environ.get("HUGGINGFACE_TOKEN", "")
        try:
            t0 = time.time()
            turns = _diarize_with_pyannote(audio.audio_path, hf_token, print)
            print(f"  [DIAR] {time.time()-t0:.0f}s, {len(turns)} turns")
        except Exception as exc:
            print(f"  [DIAR] 실패: {exc} — 단일 화자 fallback")
            turns = [(0.0, audio.duration_sec, "SPEAKER_00")]

        out_segs = []
        for s in raw_segs:
            words = [{"word": w.get("word", ""), "start": float(w.get("start", 0)),
                       "end": float(w.get("end", 0))} for w in (s.get("words") or [])]
            out_segs.append({"start": float(s.get("start", 0)),
                              "end": float(s.get("end", 0)),
                              "text": (s.get("text") or "").strip(),
                              "words": words})

        dump = {
            "video_id": video_id,
            "duration": audio.duration_sec,
            "subtitles_chars": len(audio.subtitles_text or ""),
            "language": result.get("language", "en"),
            "segments": out_segs,
            "diarization": [{"start": t[0], "end": t[1], "speaker": t[2]} for t in turns],
            "title": audio.video_title or "",
            "uploader": audio.uploader or "",
        }
        out.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  [STT] saved: {out.name}")
        return dump


def build_transcript_from_resplit(resplit: List[dict]) -> Transcript:
    segs = [Segment(speaker=s["speaker"], start=float(s["start"]),
                     end=float(s["end"]), text=s["text"]) for s in resplit]
    return Transcript(segments=segs, engine="mlx", language="en",
                       raw={"language": "en", "model": "mlx-whisper-large-v3"})


def patched_run(transcript, two_pass, chunk_size, label, video_id, video_title):
    """chunk_size monkey-patch + translate_transcript."""
    orig_size = llm_mod.MAX_SEGMENTS_PER_CHUNK
    orig_chunk_fn = llm_mod.chunk_segments
    llm_mod.MAX_SEGMENTS_PER_CHUNK = chunk_size
    def patched_chunk_segments(segments, char_limit=llm_mod.DEFAULT_CHUNK_CHAR_LIMIT,
                                segment_limit=None):
        return orig_chunk_fn(segments, char_limit=char_limit,
                              segment_limit=segment_limit if segment_limit else chunk_size)
    llm_mod.chunk_segments = patched_chunk_segments
    try:
        os.environ["GURUNOTE_TWO_PASS"] = "1" if two_pass else "0"
        config = LLMConfig.from_env(provider="openai_compatible")
        config.model = MODEL
        vctx = {"id": video_id, "title": video_title or "video",
                 "uploader": "", "description": "", "url": f"https://youtu.be/{video_id}"}

        log_lines = []
        def log_fn(msg):
            ts = time.strftime("%H:%M:%S")
            log_lines.append(f"[{ts}] {msg}")
            if any(k in msg for k in ["⚠", "🛟"]):
                print(f"    [{label}] {msg[:140]}", flush=True)
        t0 = time.time()
        body = translate_transcript(transcript, config=config, progress=log_fn,
                                     video_context=vctx, stop_event=None)
        elapsed = time.time() - t0
    finally:
        llm_mod.MAX_SEGMENTS_PER_CHUNK = orig_size
        llm_mod.chunk_segments = orig_chunk_fn
    return body, log_lines, elapsed


def analyze_log(log_lines, two_pass):
    timeouts = sum(1 for ln in log_lines if "wall-clock timeout — retry" in ln)
    length_mismatch = sum(1 for ln in log_lines if "길이 미스매치" in ln)
    pattern = re.compile(r"1단계 출력 — (\d+) lines / N=(\d+)")
    lc = [(int(m.group(1)), int(m.group(2)))
           for m in (pattern.search(ln) for ln in log_lines) if m]
    return {
        "timeouts": timeouts,
        "length_mismatch": length_mismatch,
        "total_chunks": len(lc) if two_pass else None,
        "match_exact": sum(1 for ln, n in lc if ln == n) if two_pass else None,
        "match_less": sum(1 for ln, n in lc if ln < n) if two_pass else None,
        "match_extreme": sum(1 for ln, n in lc if ln == 1 and n > 5) if two_pass else None,
    }


def process_video(video_id, label):
    print(f"\n{'='*70}")
    print(f"영상: {video_id} ({label})")
    print(f"{'='*70}")
    video_dir = OUT_DIR / video_id
    video_dir.mkdir(exist_ok=True)

    # ---- 1. STT + diarization (캐시)
    raw = stt_raw_dump(video_id, video_dir)
    if not raw:
        return None

    # ---- 2. 재분할
    resplit, merge_log = resplit_segments(raw["segments"], raw["diarization"])
    print(f"  [재분할] {len(raw['segments'])} → {len(resplit)} segments ({len(merge_log)} 병합)")

    # segment 특성
    text_lens = [len(s["text"]) for s in resplit]
    orig_text_lens = [len(s["text"]) for s in raw["segments"]
                       if (s.get("text") or "").strip()]
    chunk_chars = []
    for i in range(0, len(resplit), CHUNK_SIZE):
        chunk_chars.append(sum(len(s["text"]) + 30 for s in resplit[i:i + CHUNK_SIZE]))
    speakers = sorted(set(s["speaker"] for s in resplit))

    chars = {
        "orig_count": len(raw["segments"]),
        "resplit_count": len(resplit),
        "merge_count": len(merge_log),
        "orig_avg_chars": sum(orig_text_lens) / max(1, len(orig_text_lens)),
        "resplit_avg_chars": sum(text_lens) / max(1, len(text_lens)),
        "resplit_max_chars": max(text_lens) if text_lens else 0,
        "chunks_cs12": len(chunk_chars),
        "chunk_max_chars": max(chunk_chars) if chunk_chars else 0,
        "chunk_avg_chars": sum(chunk_chars) / max(1, len(chunk_chars)),
        "duration": raw.get("duration", 0),
        "speaker_count": len(speakers),
        "subtitles_chars": raw.get("subtitles_chars", 0),
    }
    print(f"  [특성] dur={chars['duration']:.0f}s, 화자={chars['speaker_count']}, "
          f"avg={chars['resplit_avg_chars']:.0f} chars, max={chars['resplit_max_chars']} chars, "
          f"chunk_max={chars['chunk_max_chars']:.0f}")

    # save resplit
    (video_dir / "resplit.json").write_text(
        json.dumps([{k: v for k, v in s.items() if k != "words"} for s in resplit],
                   ensure_ascii=False, indent=1), encoding="utf-8")

    tr = build_transcript_from_resplit(resplit)

    # ---- 3. 1-pass cs=12
    print(f"  [1-pass cs=12] 진행…")
    bak = isolate_cache(f"{video_id}_1p")
    try:
        body, log_lines, elapsed = patched_run(tr, two_pass=False, chunk_size=CHUNK_SIZE,
                                                 label=f"{video_id}_1p",
                                                 video_id=f"{video_id}_1p",
                                                 video_title=raw.get("title", ""))
        (video_dir / "1pass_body.md").write_text(body, encoding="utf-8")
        (video_dir / "1pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        an1 = analyze_log(log_lines, two_pass=False)
        an1["elapsed"] = elapsed
        an1["body_lines"] = body.count("\n")
        print(f"    1-pass: {elapsed:.0f}s, timeouts={an1['timeouts']}, "
              f"length_mismatch={an1['length_mismatch']}")
    finally:
        restore_cache(bak)

    # ---- 4. 2-pass cs=12
    print(f"  [2-pass cs=12] 진행…")
    bak = isolate_cache(f"{video_id}_2p")
    try:
        body, log_lines, elapsed = patched_run(tr, two_pass=True, chunk_size=CHUNK_SIZE,
                                                 label=f"{video_id}_2p",
                                                 video_id=f"{video_id}_2p",
                                                 video_title=raw.get("title", ""))
        (video_dir / "2pass_body.md").write_text(body, encoding="utf-8")
        (video_dir / "2pass_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        an2 = analyze_log(log_lines, two_pass=True)
        an2["elapsed"] = elapsed
        an2["body_lines"] = body.count("\n")
        print(f"    2-pass: {elapsed:.0f}s, timeouts={an2['timeouts']}, "
              f"정합={an2['match_exact']}/{an2['total_chunks']}, "
              f"합침={an2['match_less']}, 극단={an2['match_extreme']}")
    finally:
        restore_cache(bak)

    return {
        "video_id": video_id,
        "label": label,
        "chars": chars,
        "1pass": an1,
        "2pass": an2,
    }


def main():
    print(f"6개 영상 cs={CHUNK_SIZE} 견고성 측정")
    print(f"모델: {MODEL}")
    results = []
    for video_id, label in VIDEOS:
        try:
            r = process_video(video_id, label)
            if r:
                results.append(r)
        except Exception as exc:
            print(f"  [영상 실패] {video_id}: {exc}")
            import traceback
            traceback.print_exc()

    # 종합 dump
    (OUT_DIR / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{'='*70}")
    print(f"종합 — 영상별 cs={CHUNK_SIZE}")
    print(f"{'='*70}")
    print(f"{'영상':<14} {'특성':<22} {'dur':>5} {'sp':>3} {'segs':>4} "
          f"{'avg':>4} {'max':>4} {'cmax':>6} "
          f"{'1p_t':>5} {'1p_to':>6} {'2p_t':>5} {'2p_to':>6} {'2p_정합':>8}")
    for r in results:
        c = r["chars"]
        a1 = r["1pass"]
        a2 = r["2pass"]
        match_str = f"{a2['match_exact']}/{a2['total_chunks']}" if a2.get("total_chunks") else "-"
        print(f"{r['video_id']:<14} {r['label'][:22]:<22} "
              f"{c['duration']:>5.0f} {c['speaker_count']:>3} {c['resplit_count']:>4} "
              f"{c['resplit_avg_chars']:>4.0f} {c['resplit_max_chars']:>4.0f} "
              f"{c['chunk_max_chars']:>6.0f} "
              f"{a1['elapsed']:>5.0f} {a1['timeouts']:>6} "
              f"{a2['elapsed']:>5.0f} {a2['timeouts']:>6} {match_str:>8}")


if __name__ == "__main__":
    main()

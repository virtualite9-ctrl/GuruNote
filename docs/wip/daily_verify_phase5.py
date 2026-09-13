"""Phase 5 daily 검증 — 본인 영상 2개 토글 on (5/24).

영상: https://youtu.be/xKK5ze3FukQ , https://youtu.be/zNuOOMM20Tk
환경: 정상 cache (격리 부재 — daily처럼)
토글: GURUNOTE_SEGMENT_RESPLIT=1 + GURUNOTE_TWO_PASS=1

측정:
  - 재분할 segment 감소
  - chunk_max (char_limit=2000 작동)
  - 화자 이름 부착 (bootstrap 식별 + 코드 — fallback "화자 N" 아닌 실제 이름)
  - 1단계 정합 / 합침 / timeout
  - 본문 형태 (줄 수, 가독성)
"""
from __future__ import annotations

import os
import sys
import re
import json
import time
import tempfile
import warnings
from pathlib import Path
from collections import Counter

for line in open("/Users/gesicht/GuruNote/.env").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

sys.path.insert(0, "/Users/gesicht/GuruNote")

# 토글 on
os.environ["GURUNOTE_SEGMENT_RESPLIT"] = "1"
os.environ["GURUNOTE_TWO_PASS"] = "1"

from gurunote.audio import download_audio
from gurunote.stt_mlx import transcribe_mlx
from gurunote.llm import LLMConfig, translate_transcript

VIDEOS = [
    "https://youtu.be/xKK5ze3FukQ",
    "https://youtu.be/zNuOOMM20Tk",
]

OUT_DIR = Path("/Users/gesicht/GuruNote/verify_results/daily_phase5")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Model: daily q5 (qwen3.6-35b-q5) — .env catch
MODEL = os.environ.get("OPENAI_MODEL", "qwen3.6-35b-q5")
print(f"모델: {MODEL}")


def log_progress(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", flush=True)


def analyze_log_msgs(log_msgs):
    pattern = re.compile(r"1단계 출력 — (\d+) lines / N=(\d+)")
    lc = [(int(m.group(1)), int(m.group(2)))
           for m in (pattern.search(ln) for ln in log_msgs) if m]
    return {
        "total_chunks": len(lc),
        "match_exact": sum(1 for ln, n in lc if ln == n),
        "match_less": sum(1 for ln, n in lc if ln < n),
        "match_extreme": sum(1 for ln, n in lc if ln == 1 and n > 5),
        "timeouts": sum(1 for ln in log_msgs if "wall-clock timeout — retry" in ln),
        "length_mismatch": sum(1 for ln in log_msgs if "길이 미스매치" in ln),
        "empty_recoveries": sum(1 for ln in log_msgs if "🛟 빈 output 복구" in ln),
    }


def process_video(url):
    video_id = url.split("/")[-1]
    print(f"\n{'='*70}")
    print(f"영상: {url}")
    print(f"{'='*70}")
    video_dir = OUT_DIR / video_id
    video_dir.mkdir(exist_ok=True)

    warnings.filterwarnings("ignore")
    log_msgs = []
    def log_fn(msg):
        log_msgs.append(msg)
        log_progress(msg)

    with tempfile.TemporaryDirectory(prefix=f"daily_{video_id}_") as tmp:
        try:
            t0 = time.time()
            audio = download_audio(url, tmp)
            log_progress(f"download: {time.time()-t0:.0f}s, duration={audio.duration_sec:.0f}s, "
                          f"title={audio.video_title!r}")

            t0 = time.time()
            hotwords = []  # daily 환경처럼
            transcript = transcribe_mlx(audio.audio_path, log=log_fn, hotwords=hotwords)
            stt_elapsed = time.time() - t0
            log_progress(f"STT: {stt_elapsed:.0f}s, {len(transcript.segments)} segments")
            log_progress(f"transcript.raw['segment_resplit']: "
                          f"{transcript.raw.get('segment_resplit')}")

            sp_dist = Counter(s.speaker for s in transcript.segments)
            log_progress(f"화자 분포: {dict(sorted(sp_dist.items()))}")

            t0 = time.time()
            video_context = audio.to_context_dict()
            video_context["id"] = audio.video_id
            config = LLMConfig.from_env(provider="openai_compatible")
            body = translate_transcript(
                transcript, config=config, progress=log_fn,
                video_context=video_context, stop_event=None,
            )
            trans_elapsed = time.time() - t0
            log_progress(f"번역: {trans_elapsed:.0f}s")

            # save
            (video_dir / "body.md").write_text(body, encoding="utf-8")
            (video_dir / "log.txt").write_text("\n".join(log_msgs), encoding="utf-8")

            an = analyze_log_msgs(log_msgs)

            # 본문 화자 분포 (실제 이름 부착 catch)
            speaker_in_body = Counter()
            for line in body.split("\n"):
                m = re.match(r"^\[\d+:\d+\]\s+([^:]+):", line)
                if m:
                    speaker_in_body[m.group(1).strip()] += 1

            # CJK (한자) catch
            cjk_count = sum(1 for ch in body if "一" <= ch <= "鿿")

            result = {
                "url": url, "video_id": video_id,
                "title": audio.video_title or "",
                "duration": audio.duration_sec,
                "segments": len(transcript.segments),
                "speakers_stt": dict(sp_dist),
                "speakers_body": dict(speaker_in_body.most_common()),
                "stt_elapsed": stt_elapsed,
                "trans_elapsed": trans_elapsed,
                "body_lines": body.count("\n"),
                "cjk_chars": cjk_count,
                "segment_resplit_flag": transcript.raw.get("segment_resplit"),
                **an,
            }
            (video_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            return result

        except Exception as exc:
            import traceback
            log_progress(f"❌ 실패: {exc}")
            traceback.print_exc()
            (video_dir / "log.txt").write_text("\n".join(log_msgs), encoding="utf-8")
            return {"url": url, "video_id": video_id, "error": str(exc)}


def main():
    print(f"Phase 5 daily 검증 — 2개 영상 토글 on")
    print(f"GURUNOTE_SEGMENT_RESPLIT: {os.environ.get('GURUNOTE_SEGMENT_RESPLIT')}")
    print(f"GURUNOTE_TWO_PASS: {os.environ.get('GURUNOTE_TWO_PASS')}")
    print()

    results = []
    for url in VIDEOS:
        r = process_video(url)
        results.append(r)

    # save summary
    (OUT_DIR / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"\n{'='*70}")
    print(f"종합 — 2개 영상 daily 검증")
    print(f"{'='*70}")
    for r in results:
        if "error" in r:
            print(f"  {r['video_id']}: ❌ {r['error']}")
            continue
        print(f"\n{r['video_id']} ({r.get('title', '?')[:50]})")
        print(f"  duration: {r['duration']:.0f}s, segments: {r['segments']}")
        print(f"  segment_resplit flag: {r['segment_resplit_flag']}")
        print(f"  STT 화자: {r['speakers_stt']}")
        print(f"  본문 화자 (이름 부착): {r['speakers_body']}")
        print(f"  처리: STT {r['stt_elapsed']:.0f}s + 번역 {r['trans_elapsed']:.0f}s")
        print(f"  본문 줄: {r['body_lines']}, CJK 한자: {r['cjk_chars']}")
        print(f"  2-pass 정합: {r['match_exact']}/{r['total_chunks']}, "
              f"합침: {r['match_less']}, 극단: {r['match_extreme']}")
        print(f"  timeouts: {r['timeouts']}, length_mismatch: {r['length_mismatch']}, "
              f"빈복구: {r['empty_recoveries']}")


if __name__ == "__main__":
    main()

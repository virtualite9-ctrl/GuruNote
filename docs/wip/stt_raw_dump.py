"""oE5lNDhz9oo STT raw segments + words dump (5/24).

목적: 재분할 prototype 입력. raw segments에 words(start/end/word) 포함 catch.
mlx-whisper word_timestamps=True → segments[i]["words"] catch.

출력: verify_results/community1_3speakers_raw.json
  { "segments": [...], "language": "en", "diarization": [...] }
"""
from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import warnings
from pathlib import Path

for line in open("/Users/gesicht/GuruNote/.env").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

sys.path.insert(0, "/Users/gesicht/GuruNote")
from gurunote.audio import download_audio

VIDEO_URL = "https://youtu.be/oE5lNDhz9oo"
OUT_PATH = Path("/Users/gesicht/GuruNote/verify_results/community1_3speakers_raw.json")


def main() -> None:
    if OUT_PATH.exists():
        print(f"이미 catch: {OUT_PATH} — 재실행 부재.")
        return

    print(f"STT raw dump — {VIDEO_URL}")
    with tempfile.TemporaryDirectory(prefix="gn_raw_") as tmp:
        t0 = time.time()
        audio = download_audio(VIDEO_URL, tmp)
        print(f"  download: {time.time()-t0:.1f}s — {audio.audio_path}")

        # mlx-whisper raw (words 포함)
        import mlx_whisper
        warnings.filterwarnings("ignore")
        t0 = time.time()
        model = os.environ.get("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")
        result = mlx_whisper.transcribe(
            audio.audio_path,
            path_or_hf_repo=model,
            word_timestamps=True,
            verbose=False,
        )
        raw_segs = result.get("segments", [])
        print(f"  STT: {time.time()-t0:.1f}s — {len(raw_segs)} segments")
        print(f"  segment[0] keys: {list(raw_segs[0].keys()) if raw_segs else None}")
        if raw_segs and "words" in raw_segs[0]:
            w0 = raw_segs[0]["words"]
            print(f"  segment[0].words count: {len(w0)}")
            if w0:
                print(f"  word[0] keys: {list(w0[0].keys())}, sample: {w0[0]}")

        # diarization (community-1)
        from gurunote.stt.mlx import _diarize_with_pyannote
        def log(m): print(f"    {m}")
        t0 = time.time()
        hf_token = os.environ.get("HUGGINGFACE_TOKEN", "")
        turns = _diarize_with_pyannote(audio.audio_path, hf_token, log)
        print(f"  diarization: {time.time()-t0:.1f}s — {len(turns)} turns")

        # serialize — words 포함
        # segments[i] 의 words[j] = {"word", "start", "end", "probability"}
        out_segs = []
        for s in raw_segs:
            words = []
            for w in s.get("words", []) or []:
                words.append({
                    "word": w.get("word", ""),
                    "start": float(w.get("start", 0)),
                    "end": float(w.get("end", 0)),
                })
            out_segs.append({
                "start": float(s.get("start", 0)),
                "end": float(s.get("end", 0)),
                "text": (s.get("text") or "").strip(),
                "words": words,
            })

        dump = {
            "video_id": audio.video_id,
            "language": result.get("language", "en"),
            "segments": out_segs,
            "diarization": [
                {"start": t[0], "end": t[1], "speaker": t[2]} for t in turns
            ],
        }
        OUT_PATH.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nsaved: {OUT_PATH} ({OUT_PATH.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()

"""STT 직후 의미 단위 재분할 prototype (5/24).

입력: verify_results/community1_3speakers_raw.json (raw segments + words + diarization)
재분할: 방법 4 — 문장 종결(. ? !) 1차 분할 + 끝 검사(comma, conjunction, preposition) 보완
화자: overlap 재계산. 화자 다르면 병합 부재.

측정:
  - 재분할 분포 (334 → N)
  - 미완 case 합쳐졌나 (특히 [365.7][574.0])
  - 화자 전환 병합 부재
  - 휴리스틱 부족 잔존
  - D 재측정 (45 → 의미 단위 N개, leak 사라지나)

출력:
  - verify_results/community1_3speakers_resplit.json (재분할 segments)
  - verify_results/community1_3speakers_resplit_diff.md (분포 + 합친 사례)
"""
from __future__ import annotations

import os
import sys
import json
import re
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Tuple

for line in open("/Users/gesicht/GuruNote/.env").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

RAW_PATH = Path("/Users/gesicht/GuruNote/verify_results/community1_3speakers_raw.json")
OUT_DIR = Path("/Users/gesicht/GuruNote/verify_results")

# =============================================================================
# 끝 검사 사전
# =============================================================================
SENTENCE_END = {".", "?", "!"}     # 명확 종결
# 미완 catch — 다음 segment와 병합
MID_PUNCT = {",", ":", ";", "-", "—"}
CONJUNCTIONS = {
    "and", "or", "but", "nor", "so", "yet", "for",
    "because", "while", "when", "if", "though", "although",
    "as", "than", "that",
}
PREPOSITIONS = {
    "to", "of", "in", "on", "at", "by", "from", "with", "for",
    "about", "into", "during", "over", "under", "between",
    "through", "across", "against", "before", "after", "around",
    "as", "without", "within", "upon",
}
# 형용사/관사/조동사 단독 끝 — 명사 부재
DANGLING_WORDS = {
    "the", "a", "an",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "do", "does", "did", "done",
    "my", "your", "his", "her", "its", "our", "their",
    "this", "that", "these", "those",
    "more", "less", "most", "least", "very", "really", "quite",
}


def _last_token(text: str) -> str:
    """text 마지막 token (구두점 strip)."""
    t = text.strip().lower()
    # 트레일링 구두점 분리
    while t and t[-1] in ".,?!;:\"')]":
        t = t[:-1]
    if not t:
        return ""
    return t.split()[-1] if t.split() else ""


def is_complete(text: str) -> Tuple[bool, str]:
    """segment text가 의미 완결인지 catch.

    Returns: (complete, reason)
    """
    t = text.strip()
    if not t:
        return True, "empty"
    last_char = t[-1]
    if last_char in SENTENCE_END:
        return True, "sentence_end"
    if last_char in MID_PUNCT:
        return False, "mid_punct"
    last_word = _last_token(t)
    if last_word in CONJUNCTIONS:
        return False, "conjunction"
    if last_word in PREPOSITIONS:
        return False, "preposition"
    if last_word in DANGLING_WORDS:
        return False, "dangling"
    # 구두점 부재인데 사전에 없음 → 미완 보수적 판정 (자연 끝일 수도 있지만)
    # 안전: 구두점 부재 = 미완 (mlx-whisper가 자연 종결 시 . 부착)
    if last_char not in ".,?!;:":
        return False, "no_punct"
    return True, "ok"


# =============================================================================
# diarization 활용
# =============================================================================
def _normalize_speaker(raw: str) -> str:
    """SPEAKER_00 → A."""
    if raw and raw.startswith("SPEAKER_"):
        try:
            return chr(ord("A") + int(raw.split("_")[-1]))
        except (ValueError, IndexError):
            return raw
    return raw or "A"


def assign_speaker(start: float, end: float, turns: List[Dict]) -> str:
    """overlap 기반 speaker 할당."""
    overlap_by: Dict[str, float] = {}
    for t in turns:
        ov = min(end, t["end"]) - max(start, t["start"])
        if ov > 0:
            overlap_by[t["speaker"]] = overlap_by.get(t["speaker"], 0.0) + ov
    if not overlap_by:
        return "A"
    best = max(overlap_by.items(), key=lambda kv: kv[1])[0]
    return _normalize_speaker(best)


# =============================================================================
# 재분할
# =============================================================================
def resplit_segments(raw_segs: List[Dict], turns: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """방법 4 — segment 끝 검사 + 다음과 병합. 화자 다르면 병합 부재.

    Returns: (resplit_segments, merge_log)
    merge_log: [{indices: [i, i+1, ...], reason, original_count}]
    """
    # 1차: noise 필터 (stt/mlx.py 동일)
    NOISE = {"", ".", "-", "—", "...", "…"}
    filtered = []
    for s in raw_segs:
        if (s.get("text") or "").strip() in NOISE:
            continue
        filtered.append(s)

    # 2차: 화자 부착 (segment 단위 1차)
    for s in filtered:
        s["speaker"] = assign_speaker(s["start"], s["end"], turns)

    # 3차: 끝 검사 + 병합 (greedy 정방향)
    out = []
    merge_log = []
    i = 0
    while i < len(filtered):
        cur = dict(filtered[i])
        merged_indices = [i]
        merged_reasons = []
        j = i + 1
        while j < len(filtered):
            complete, reason = is_complete(cur["text"])
            if complete:
                break
            nxt = filtered[j]
            # 화자 우선 — 다르면 병합 부재
            if nxt["speaker"] != cur["speaker"]:
                merged_reasons.append(f"stop_speaker_diff@{j}")
                break
            # 시간 갭 — 5초 초과면 병합 부재 (의도적 멈춤)
            gap = nxt["start"] - cur["end"]
            if gap > 5.0:
                merged_reasons.append(f"stop_gap_{gap:.1f}s@{j}")
                break
            # 안전 상한 — 합친 길이 30초 초과 부재
            if (nxt["end"] - cur["start"]) > 30.0:
                merged_reasons.append(f"stop_length_30s@{j}")
                break
            # 병합
            cur["text"] = (cur["text"].rstrip() + " " + nxt["text"].lstrip()).strip()
            cur["end"] = nxt["end"]
            cur["words"] = (cur.get("words", []) or []) + (nxt.get("words", []) or [])
            merged_indices.append(j)
            merged_reasons.append(reason)
            j += 1
        if len(merged_indices) > 1:
            merge_log.append({
                "indices": merged_indices,
                "reasons": merged_reasons,
                "start": cur["start"],
                "end": cur["end"],
                "speaker": cur["speaker"],
                "text": cur["text"],
            })
        # 화자 재할당 (합친 범위 기준)
        if len(merged_indices) > 1:
            cur["speaker"] = assign_speaker(cur["start"], cur["end"], turns)
        out.append(cur)
        i = j if j > i else i + 1

    return out, merge_log


# =============================================================================
# Step 4 — D 재측정 (재분할 segment로)
# =============================================================================
SPEAKER_MAP = {
    "A": "젠슨 황(Jensen Huang)",
    "B": "마이클 델(Michael Dell)",
    "C": "에드 러들로(Ed Ludlow)",
}
TEST_MODEL = "Qwen3.6-35B-A3B-oQ6-mtp"
BASE_URL = os.environ["OPENAI_BASE_URL"]
API_KEY = os.environ["OPENAI_API_KEY"]


def build_d_prompt(target, ctx_before, ctx_after) -> str:
    def fmt(seg):
        sp = seg.get("speaker") or "-"
        return f"  [{sp}] {seg['text']}"
    sp = target.get("speaker") or "-"
    tlabel = SPEAKER_MAP.get(sp, f"화자 {sp}")
    parts = [
        "다음은 영어 인터뷰 발화 1건을 한국어로 번역하는 작업이다.",
        "",
        "규칙:",
        "1. 입력은 [TARGET] 1건이다. 본 1건만 번역하라.",
        "2. [CONTEXT-BEFORE] / [CONTEXT-AFTER] 는 흐름 참고이며, 번역 대상 부재.",
        "3. 출력은 한국어 문장 1줄. 화자 라벨 출력 부재.",
        "4. 한국어 출력에 한자 / 일본어 / 중국어 문자 부재.",
        "5. 본문 내용 추가 / 누락 / 변경 부재.",
        "",
    ]
    if ctx_before:
        parts.append("[CONTEXT-BEFORE]")
        for s in ctx_before:
            parts.append(fmt(s))
        parts.append("")
    parts.append("[TARGET]")
    parts.append(f"  화자: {tlabel}")
    parts.append(f"  영어: {target['text']}")
    parts.append("")
    if ctx_after:
        parts.append("[CONTEXT-AFTER]")
        for s in ctx_after:
            parts.append(fmt(s))
        parts.append("")
    parts.append("위 [TARGET] 1건만 한국어로 번역하라. 한국어 본문 1줄:")
    return "\n".join(parts)


async def translate_one(client, target, ctx_b, ctx_a):
    prompt = build_d_prompt(target, ctx_b, ctx_a)
    t0 = time.time()
    try:
        resp = await client.chat.completions.create(
            model=TEST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.2,
            extra_body={"thinking_budget": 0},
            timeout=90,
        )
        text = (resp.choices[0].message.content or "").strip()
        for sp in ["A:", "B:", "C:", "화자 A:", "화자 B:", "화자 C:"]:
            if text.startswith(sp):
                text = text[len(sp):].strip()
        return {**target, "translated": text, "elapsed": time.time() - t0, "error": None}
    except Exception as exc:
        return {**target, "translated": "", "elapsed": time.time() - t0, "error": str(exc)}


async def run_d_on_resplit(resplit_segs: List[Dict], target_indices: List[int], k: int):
    """재분할 segment 중 target_indices 만 번역."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    tasks = []
    for idx in target_indices:
        tgt = resplit_segs[idx]
        before = resplit_segs[max(0, idx - k):idx]
        after = resplit_segs[idx + 1:idx + 1 + k]
        tasks.append((tgt, before, after))

    t0 = time.time()
    sem = asyncio.Semaphore(32)
    async def bounded(tgt, b, a):
        async with sem:
            return await translate_one(client, tgt, b, a)
    results = await asyncio.gather(*[bounded(t, b, a) for (t, b, a) in tasks])
    total = time.time() - t0
    await client.close()
    return results, total


# =============================================================================
# main
# =============================================================================
async def main():
    print("=" * 70)
    print("STT 재분할 prototype — community1_3speakers (oE5lNDhz9oo)")
    print("=" * 70)

    raw = json.load(open(RAW_PATH))
    raw_segs = raw["segments"]
    turns = raw["diarization"]
    print(f"\nraw segments: {len(raw_segs)}")
    print(f"diarization turns: {len(turns)}")

    # ---- 재분할
    resplit, merge_log = resplit_segments(raw_segs, turns)
    print(f"\n재분할: {len(raw_segs)} → {len(resplit)} segments")
    print(f"병합 건수: {len(merge_log)}")
    print(f"  병합 평균 합친 개수: {sum(len(m['indices']) for m in merge_log)/max(1,len(merge_log)):.2f}")

    # 사유별 분포
    from collections import Counter
    reason_counter = Counter()
    for m in merge_log:
        for r in m["reasons"]:
            if not r.startswith("stop_"):
                reason_counter[r] += 1
    print(f"  병합 사유 분포: {dict(reason_counter)}")
    stop_counter = Counter()
    for m in merge_log:
        for r in m["reasons"]:
            if r.startswith("stop_"):
                stop_counter[r.split("@")[0]] += 1
    print(f"  병합 중단 사유: {dict(stop_counter)}")

    # ---- 화자 우선 검증 (병합된 segment 안에 화자 다른 case 부재 확인)
    speaker_violations = 0
    for seg in resplit:
        if not seg.get("words"):
            continue
        # 합친 segment 안의 사라진 화자 발화 catch — words 단위로 화자 재할당해서 single 화자 확인
        word_speakers = set()
        for w in seg["words"]:
            sp = assign_speaker(w["start"], w["end"], turns)
            word_speakers.add(sp)
        if len(word_speakers) > 1:
            speaker_violations += 1
    print(f"  병합 segment 안 화자 다중 catch: {speaker_violations} / {len(resplit)}")

    # ---- 핵심 case catch
    print("\n핵심 case catch:")
    for target_start in [365.7, 574.0, 320.7]:
        # raw에서 target_start와 가까운 segment 찾고, resplit에서 같은 시점 catch
        # resplit의 어떤 segment가 target_start 포함하는지
        match = None
        for s in resplit:
            if s["start"] <= target_start + 0.01 and s["end"] >= target_start - 0.01:
                match = s
                break
        if match:
            indices = [m["indices"] for m in merge_log if any(
                abs(raw_segs[i]["start"] - target_start) < 0.5 for i in m["indices"]
            )]
            merged_n = len(indices[0]) if indices else 1
            print(f"  [{target_start}] → resplit [{match['start']:.1f}-{match['end']:.1f}] "
                  f"(N={merged_n}): {match['text'][:120]}")

    # ---- save resplit
    out_resplit = OUT_DIR / "community1_3speakers_resplit.json"
    out_resplit.write_text(
        json.dumps([{k: v for k, v in s.items() if k != "words"} for s in resplit],
                   ensure_ascii=False, indent=1),
        encoding="utf-8"
    )
    print(f"\nsaved: {out_resplit}")

    # ---- D 재측정 — 원래 D prototype chunks 7/11/12 (45 segments) 영역의 resplit segment
    # 원래 chunks 7/11/12 의 time range 추출
    orig_segs = json.load(open(OUT_DIR / "community1_3speakers_segments.json"))
    CHUNK_SIZE = 15
    target_time_ranges = []
    for ci in [7, 11, 12]:
        s = (ci - 1) * CHUNK_SIZE
        e = s + CHUNK_SIZE
        target_time_ranges.append((orig_segs[s]["start"], orig_segs[e-1]["end"], ci))

    # resplit에서 해당 time range 인접 segment 모음
    d_target_indices = []
    for i, s in enumerate(resplit):
        for (ts, te, ci) in target_time_ranges:
            if s["start"] >= ts - 0.5 and s["end"] <= te + 0.5:
                d_target_indices.append(i)
                break

    print(f"\n=== D 재측정 (재분할 segment 기준) ===")
    print(f"chunks 7/11/12 영역 resplit segments: {len(d_target_indices)}")

    print(f"\n[K=3 par] 진행…")
    results, total = await run_d_on_resplit(resplit, d_target_indices, k=3)
    print(f"  total: {total:.2f}s")
    print(f"  per-seg avg: {sum(r['elapsed'] for r in results)/len(results):.2f}s")
    empty = sum(1 for r in results if not r["translated"])
    err = sum(1 for r in results if r["error"])
    print(f"  empty: {empty}, errors: {err}")

    # 결과 저장
    out_md = OUT_DIR / "candidate_d_resplit_k3_par.md"
    out_json = OUT_DIR / "candidate_d_resplit_k3_par.json"
    lines = ["# D (재분할 적용) — K=3 par", ""]
    for r in results:
        sp = SPEAKER_MAP.get(r.get("speaker") or "", r.get("speaker") or "-")
        lines.append(f"[{r['start']:.1f}-{r['end']:.1f}] {sp}: {r.get('translated') or '[빈]'}")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_json.write_text(
        json.dumps([{k: v for k, v in r.items() if k != "words"} for r in results],
                   ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"  saved: {out_md.name} / {out_json.name}")

    # ---- leak 검증 (핵심 case)
    print("\nleak 검증:")
    for r in results:
        for target_start in [365.7, 574.0]:
            if r["start"] <= target_start + 0.01 and r["end"] >= target_start - 0.01:
                print(f"  [{r['start']:.1f}-{r['end']:.1f}] (재분할 영역)")
                print(f"    원본: {r['text'][:200]}")
                print(f"    번역: {r['translated'][:200]}")
                print()


if __name__ == "__main__":
    asyncio.run(main())

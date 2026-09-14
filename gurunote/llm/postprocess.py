"""LLM 출력 후처리 — 한자/일본어 차단, 영문 병기 검증, 연속 반복 축약.

모델이 만들어 낸 텍스트를 결정론적으로 손보는 단계다.
"""
from __future__ import annotations

from gurunote.types import Segment
from pathlib import Path
from gurunote.llm._data import DATA_DIR
from typing import List
from typing import Optional
import difflib
import re
import yaml

from gurunote.llm import client
from gurunote.llm import entities

__all__ = [
    '_REPEATED_ANNOTATION_RE',
    '_strip_repeated_annotations',
    '_CJK_LOOKUP_PATH',
    '_CJK_LOOKUP_CACHE',
    '_CJK_DETECT_RE',
    '_BRACKETED_CJK_RE',
    '_SEGMENT_PREFIX_RE',
    '_load_cjk_lookup',
    '_detect_cjk_outside_brackets',
    '_apply_cjk_dict_lookup',
    '_llm_remap_cjk',
    'post_process_cjk',
    'post_process_cjk_text',
    '_ENGLISH_ANNOT_RE',
    '_correct_english_annotations',
    '_KOREAN_ANNOT_RE',
    '_correct_korean_in_annotations',
    '_SPEAKER_PREFIX_RE',
    '_strip_input_speaker_prefix',
    '_DEDUP_LINE_RE',
    '_DEDUP_MIN_LEN',
    '_DEDUP_MIN_RUN',
    '_DEDUP_SKIP_PREFIXES',
    '_collapse_repeated_lines',
]


_REPEATED_ANNOTATION_RE = re.compile(r"(?<=[가-힣])\s?\(([A-Za-z][^()]*?)\)")


def _strip_repeated_annotations(text: str) -> str:
    """첫 등장 후 영문 병기 영역 제거 (Layer 13 정합).

    "판카즈 샤르마(Pankaj Sharma)" → 첫 등장 보존.
    "판카즈 샤르마(Pankaj Sharma)" 두 번째 이후 → "판카즈 샤르마" (괄호 영역 제거).

    Lookbehind (?<=[가-힣]) — 한국어 직후 영역만 catch.
    한국어 prefix 영역 영향 본질 부재 (English key dedup, regex prefix bug 차단).
    """
    seen: set[str] = set()

    def _replace(match: re.Match) -> str:
        english = match.group(1).strip()
        if english in seen:
            return ""  # 두 번째 이후: 괄호 영역 영역 제거
        seen.add(english)
        return match.group(0)  # 첫 등장: 보존

    return _REPEATED_ANNOTATION_RE.sub(_replace, text)


_CJK_LOOKUP_PATH = DATA_DIR / "cjk_lookup.yaml"


_CJK_LOOKUP_CACHE: Optional[dict] = None


_CJK_DETECT_RE = re.compile(r"[一-鿿぀-ヿ]")


_BRACKETED_CJK_RE = re.compile(r"\([^)]*[一-鿿぀-ヿ][^)]*\)")


_SEGMENT_PREFIX_RE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s+([^:]+):\s*(.*)$")


def _load_cjk_lookup() -> dict:
    """yaml 사전 로드 + 캐시. 긴 매칭 우선을 위해 multi-char 를 길이순 정렬.

    Returns:
        {'multi': [(pat, repl), ...], 'single': [(pat, repl), ...]}
    """
    global _CJK_LOOKUP_CACHE
    if _CJK_LOOKUP_CACHE is not None:
        return _CJK_LOOKUP_CACHE
    with open(_CJK_LOOKUP_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    multi: List[tuple] = []
    for section in ("chinese", "japanese"):
        for k, v in (data.get(section) or {}).items():
            multi.append((str(k), str(v)))
    multi.sort(key=lambda x: -len(x[0]))  # 긴 매칭 우선
    single: List[tuple] = [
        (str(k), str(v)) for k, v in (data.get("single_char") or {}).items()
    ]
    _CJK_LOOKUP_CACHE = {"multi": multi, "single": single}
    return _CJK_LOOKUP_CACHE


def _detect_cjk_outside_brackets(text: str) -> List[str]:
    """괄호 밖 CJK 잔재 catch. 빈 리스트면 통과."""
    masked = _BRACKETED_CJK_RE.sub("[BRACKETED]", text)
    return _CJK_DETECT_RE.findall(masked)


def _apply_cjk_dict_lookup(text: str, lookup: dict) -> str:
    """Sub-path A — 사전 lookup. 괄호 안 한자 표기는 보존.

    multi 사전을 긴 매칭 우선으로 적용 후 single 사전 적용.
    """
    # 괄호 영역 보호 — placeholder 로 치환
    bracketed: List[str] = []

    def _save(m: re.Match) -> str:
        bracketed.append(m.group(0))
        return f"\x00BR{len(bracketed)-1}\x00"

    masked = _BRACKETED_CJK_RE.sub(_save, text)
    for pat, repl in lookup["multi"]:
        if pat in masked:
            masked = masked.replace(pat, repl)
    for pat, repl in lookup["single"]:
        if pat in masked:
            masked = masked.replace(pat, repl)
    # 괄호 영역 복원
    return re.sub(r"\x00BR(\d+)\x00", lambda m: bracketed[int(m.group(1))], masked)


def _llm_remap_cjk(
    text: str,
    config: "LLMConfig",
    max_retries: int = 3,
) -> Optional[str]:
    """Sub-path B — LLM 재매핑 retry max_retries회.

    성공 (잔재 0건) 시 결과 반환, 모두 실패 시 None.
    """
    system = (
        "다음 한국어 문장에 한자 또는 일본어 토큰이 남아있다. "
        "본 토큰을 자연스러운 한국어로 모두 치환한 결과만 출력하라. "
        "괄호 안 한자 표기 (예: '양자역학(量子力學)') 는 그대로 둔다. "
        "원문의 화자 라벨과 [MM:SS] 타임스탬프는 보존한다. "
        "설명이나 메타 텍스트 없이 치환된 본문만 한 줄로 출력하라."
    )
    for _ in range(max_retries):
        try:
            result = client._call_llm(config, system, text, max_tokens=2048)
        except Exception:
            continue
        if result and not _detect_cjk_outside_brackets(result):
            return result.strip()
    return None


def post_process_cjk(
    result: str,
    segments: List[Segment],
    config: "LLMConfig",
    log: Optional[client.ProgressFn] = None,
) -> str:
    """Phase 3 후처리 — 한자/일본어 0건 보장 (Sub-path A → B → C).

    Args:
        result: translate_transcript 결과 본문 (segment 라인 \\n\\n join)
        segments: 원본 영문 segments (Sub-path C fallback 시 영문 원문 lookup)
        config: LLMConfig (Sub-path B LLM 호출용)
        log: 진행 콜백

    Returns:
        후처리된 result. 한자/일본어 0건 (Sub-path C fallback 적용된 segment 는
        영문 원문 + [⚠ fallback] 태그) 보장.
    """
    log_fn = log or (lambda _msg: None)
    lookup = _load_cjk_lookup()

    # segments 를 (mm, ss) 키로 인덱싱 — Sub-path C 의 영문 원문 lookup
    seg_by_ts: dict = {}
    for seg in segments:
        mm = int(seg.start) // 60
        ss = int(seg.start) % 60
        seg_by_ts[(mm, ss)] = seg

    sub_a_hits = 0
    sub_b_hits = 0
    sub_c_fallbacks: List[tuple] = []  # (mm, ss)

    parts = result.split("\n\n")
    processed: List[str] = []

    for part in parts:
        if not _detect_cjk_outside_brackets(part):
            processed.append(part)
            continue

        # Sub-path A
        after_a = _apply_cjk_dict_lookup(part, lookup)
        if not _detect_cjk_outside_brackets(after_a):
            sub_a_hits += 1
            processed.append(after_a)
            continue

        # Sub-path B — LLM 재매핑 (Sub-path A 결과를 입력으로)
        after_b = _llm_remap_cjk(after_a, config, max_retries=3)
        if after_b is not None:
            sub_b_hits += 1
            processed.append(after_b)
            continue

        # Sub-path C — 영문 fallback
        m = _SEGMENT_PREFIX_RE.match(part)
        if m:
            mm, ss = int(m.group(1)), int(m.group(2))
            speaker = m.group(3).strip()
            seg = seg_by_ts.get((mm, ss))
            if seg is not None:
                fallback_text = (
                    f"[{mm:02d}:{ss:02d}] {speaker}: {seg.text} [⚠ fallback]"
                )
                sub_c_fallbacks.append((mm, ss))
                processed.append(fallback_text)
                continue

        # segment 매핑 실패 — 잔재 그대로 (검증 단계에서 catch)
        processed.append(part)

    log_fn(
        f"   🔧 Phase 3 후처리 — Sub-A {sub_a_hits}건, "
        f"Sub-B {sub_b_hits}건, Sub-C fallback {len(sub_c_fallbacks)}건"
    )
    if sub_c_fallbacks:
        ts_list = ", ".join(f"[{mm:02d}:{ss:02d}]" for mm, ss in sub_c_fallbacks[:10])
        log_fn(f"   ⚠ Sub-C fallback timestamps: {ts_list}")

    return "\n\n".join(processed)


def post_process_cjk_text(
    text: str,
    config: "LLMConfig",
    log: Optional[client.ProgressFn] = None,
) -> str:
    """segment 없는 텍스트(제목·요약)용 CJK 후처리 — Sub-path A 사전 + B LLM 재매핑.

    본문 ``post_process_cjk`` 와 같은 A/B 골격을 재사용하되, **Sub-path C(영문 fallback)
    는 제외** — 제목·요약은 segment timestamp 매핑이 없기 때문. A·B 후에도 남는 한자는
    그대로 둔다 (드묾 — 사용자 노트 편집으로 보정; 비우거나 추가 재요청 안 함).

    한자 없으면 즉시 반환 (비용 0). 본문 후처리(``post_process_cjk``)는 건드리지 않는다.
    """
    if not text or not _detect_cjk_outside_brackets(text):
        return text
    log_fn = log or (lambda _msg: None)
    lookup = _load_cjk_lookup()
    a_hits = 0
    b_hits = 0
    out: List[str] = []
    for part in text.split("\n\n"):
        if not _detect_cjk_outside_brackets(part):
            out.append(part)
            continue
        # Sub-path A — 사전 lookup
        after_a = _apply_cjk_dict_lookup(part, lookup)
        if not _detect_cjk_outside_brackets(after_a):
            a_hits += 1
            out.append(after_a)
            continue
        # Sub-path B — LLM 재매핑 (성공 시 clean, 실패 시 None)
        after_b = _llm_remap_cjk(after_a, config, max_retries=3)
        if after_b is not None:
            b_hits += 1
            out.append(after_b)
            continue
        # Sub-path C 제외 — A 적용본(최선) 유지, 잔재는 그대로
        out.append(after_a)
    if log and (a_hits or b_hits):
        log_fn(f"   🔧 CJK 후처리(제목·요약) — Sub-A {a_hits}건, Sub-B {b_hits}건")
    return "\n\n".join(out)


_ENGLISH_ANNOT_RE = re.compile(r"(?<=[가-힣])\(([A-Za-z][A-Za-z0-9\s.\-']*)\)")


def _correct_english_annotations(
    text: str, source_corpus: str, log: Optional[client.ProgressFn] = None
) -> str:
    """`한국어(English)` 병기의 영문 철자를 **소스에 실재하는 철자**로 결정론적 검증.

    LLM 이 영문 원어를 자유 생성하다 철자를 오염시키는 문제(예: Anduril→Danduril,
    제목 포함) 차단. 소스(transcript 전문 + 제목)는 정답 철자의 근거.

    각 병기 영문에 대해:
      1. 소스에 (대소문자 무시) 그대로 있으면 → 소스 철자/케이싱으로 정규화.
      2. 단일 토큰이 소스에 없으면 → 소스 단어 중 충분히 가까운 것(보수적 cutoff)으로 교정.
      3. 다단어는 모든 토큰이 소스 근거를 가질 때만 채택, 아니면 생략.
      4. 소스에 근거 없음 → 병기 삭제 (한국어만 남김, 틀린 철자 박지 않음).

    LLM 무관 순수 함수. 한국어 표기·화자 라벨·timestamp 는 건드리지 않는다.
    """
    if not text or not source_corpus:
        return text

    corpus_lower = source_corpus.lower()
    # 소스 영문 단어 풀 + 케이싱 복원 맵 (lower → 첫 등장 원본 케이싱).
    # 순수 알파벳 토큰으로 분리 — 소유격/문장부호 (예: "Anduril's", "U.S.") 가
    # 매칭을 가리지 않도록 ("Anduril's" → "Anduril" + "s").
    case_map: dict = {}
    for w in re.findall(r"[A-Za-z]+", source_corpus):
        case_map.setdefault(w.lower(), w)
    pool_lower = list(case_map.keys())  # 대소문자 무시 fuzzy 매칭용

    stats = {"corrected": 0, "dropped": 0}

    def _restore_case(tokens: list) -> str:
        return " ".join(case_map.get(t.lower(), t) for t in tokens)

    def _fix(eng: str):
        e = eng.strip()
        toks = e.split()
        # 1) 전체 구가 소스에 그대로 → 케이싱만 소스 정규화 (과교정 부재).
        if e.lower() in corpus_lower:
            return _restore_case(toks)
        # 2) 단일 토큰 → 소스 단어 중 보수적 최근접 교정 (대소문자 무시 비교).
        if len(toks) == 1:
            m = difflib.get_close_matches(e.lower(), pool_lower, n=1, cutoff=0.84)
            if m:
                stats["corrected"] += 1
                return case_map[m[0]]
            stats["dropped"] += 1
            return None
        # 3) 다단어 → 토큰별 소스 근거(정확/최근접) 전부 확보 시만 채택.
        fixed = []
        for t in toks:
            if t.lower() in corpus_lower:
                fixed.append(case_map[t.lower()])
            else:
                mm = difflib.get_close_matches(t.lower(), pool_lower, n=1, cutoff=0.84)
                if not mm:
                    stats["dropped"] += 1
                    return None
                fixed.append(case_map[mm[0]])
        if fixed != toks:
            stats["corrected"] += 1
        return " ".join(fixed)

    def _repl(m: "re.Match") -> str:
        fixed = _fix(m.group(1))
        return "" if fixed is None else f"({fixed})"

    out = _ENGLISH_ANNOT_RE.sub(_repl, text)
    if log and (stats["corrected"] or stats["dropped"]):
        log(
            f"   🔧 영문 병기 소스 검증: 교정 {stats['corrected']}건 / "
            f"생략 {stats['dropped']}건"
        )
    return out


_KOREAN_ANNOT_RE = re.compile(
    r"([가-힣]+(?:[ ·][가-힣]+)*)\(([A-Za-z][A-Za-z\s.\-']*)\)"
)


def _correct_korean_in_annotations(text: str, canonical: dict) -> str:
    """`한국어(English)` 병기에서 **English key 가 통용 dict 에 있으면 한국어를 dict 표기로
    강제 교정** (제목용). LLM 이 인명을 오음차해도(예: 스타니슬라프 드루킨밀러(Stan
    Druckenmiller)) 영문 원어로 dict 조회 → 통용 표기(스탠 드러켄밀러)로 교체.

    `_correct_english_annotations`(영문 철자 검증)와 방향이 반대 — 이쪽은 한국어를 고친다.
    dict 미수록 영문은 불변 (과교정 부재). 영문 병기 없는 인명은 매칭 불가 → 그대로.
    """
    if not text or not canonical:
        return text
    eff = entities._canonical_effective(canonical)  # {english.lower(): 통용 한국어}
    if not eff:
        return text

    def _repl(m: "re.Match") -> str:
        korean, english = m.group(1), m.group(2)
        canon = eff.get(english.strip().lower())
        if canon and canon != korean:
            return f"{canon}({english})"
        return m.group(0)

    return _KOREAN_ANNOT_RE.sub(_repl, text)


_SPEAKER_PREFIX_RE = re.compile(r"^[A-Z]:\s+")


def _strip_input_speaker_prefix(text: str) -> str:
    """input 의 'A:'/'B:' 같은 단일 영문 대문자 prefix 를 제거.

    35b 가 1단계 자유 번역에서 input 의 `"A: text"` 형식 prefix 를 한국어 라벨 앞에
    잔존시킬 case 차단 (1단계 prompt rule 5 모호성, 5/23 진단).

    정상 형식 보호:
        - "한국어 화자명: 본문" — 한국어는 영문 대문자 부재 → 매치 부재 ✅
        - "한국어 화자명(English Name): 본문" — 영문 병기는 line 시작 부재 → 매치 부재 ✅
        - "Jensen Huang: 본문" — 영문 단어는 다음 글자가 소문자 → 매치 부재 ✅
        - "A: 티파니 잔젠: 본문" — 단일 대문자 + 콜론 + 공백 → 매치 → "티파니 잔젠: 본문" ✅

    Args:
        text: chunk output 한 항목.

    Returns:
        prefix strip 후 text. 매치 부재 시 원본 그대로.
    """
    return _SPEAKER_PREFIX_RE.sub("", text)


_DEDUP_LINE_RE = re.compile(r"^(\[\d{1,2}:\d{2}(?::\d{2})?\])\s+([^:]+):\s*(.*)$", re.DOTALL)


_DEDUP_MIN_LEN = 10   # 텍스트 길이 < 이 값이면 횟수 무관 보존 (짧은 동의/감사/단어연상)


_DEDUP_MIN_RUN = 3    # 연속 동일 라인이 이 횟수 이상이면 축약


_DEDUP_SKIP_PREFIXES = ("[번역 누락]", "[⚠", "(음성 인식 오류")


def _collapse_repeated_lines(text: str, log: Optional[client.ProgressFn] = None) -> str:
    """같은 화자 + 같은 텍스트가 `_DEDUP_MIN_RUN` 회 이상 연속이고 텍스트가
    `_DEDUP_MIN_LEN` 자 이상이면 **첫 라인만 남기고 제거** (timestamp 는 첫 라인 것).

    1-pass·2-pass 공통 본문 조립 직후 적용. 짧은 발화(네./맞습니다.)·다른 화자 동일
    발화·marker([번역 누락]/[⚠ timeout]/음성 인식 오류) 는 보존 (실데이터 임계 근거).
    """
    parts = text.split("\n\n")
    out: List[str] = []
    collapsed = 0
    i, n = 0, len(parts)
    while i < n:
        m = _DEDUP_LINE_RE.match(parts[i].strip())
        if not m:
            out.append(parts[i])
            i += 1
            continue
        sp, tx = m.group(2).strip(), m.group(3).strip()
        # 연속 동일 (화자+텍스트) 그룹 길이 측정
        j = i + 1
        while j < n:
            mj = _DEDUP_LINE_RE.match(parts[j].strip())
            if not mj or mj.group(2).strip() != sp or mj.group(3).strip() != tx:
                break
            j += 1
        run = j - i
        is_marker = any(tx.startswith(p) for p in _DEDUP_SKIP_PREFIXES)
        if run >= _DEDUP_MIN_RUN and len(tx) >= _DEDUP_MIN_LEN and not is_marker:
            out.append(parts[i])  # 첫 라인만 유지
            collapsed += run - 1
        else:
            out.extend(parts[i:j])
        i = j
    if log and collapsed:
        log(f"   🔧 연속 반복 라인 축약 — {collapsed}줄 제거 (더듬거림 회귀 차단)")
    return "\n\n".join(out)

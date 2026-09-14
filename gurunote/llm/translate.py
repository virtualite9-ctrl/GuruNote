"""번역 — 2-pass DCCD, index mapping, 빈 출력 복구.
"""
from __future__ import annotations

from gurunote.types import Segment
from gurunote.types import Transcript
from gurunote.types import _format_ts
from typing import Callable
from typing import List
from typing import Optional
import json
import os
import time

from gurunote.llm import chunking
from gurunote.llm import client
from gurunote.llm import context
from gurunote.llm import entities
from gurunote.llm import postprocess
from gurunote.llm import prompts

__all__ = [
    'translate_transcript',
    'TIMEOUT_PADDING_MARKER',
    '_build_freeform_translation_prompt',
    '_build_alignment_prompt',
    '_build_index_mapping_prompt',
    '_call_llm_with_index_mapping',
    '_post_process_two_pass_outputs',
    '_resolve_speaker_label',
    '_translate_chunk_two_pass',
    '_recover_empty_outputs',
    'translate_chunk_index_mapping_v2',
]


def translate_transcript(
    transcript: Transcript,
    config: Optional[client.LLMConfig] = None,
    progress: Optional[client.ProgressFn] = None,
    video_context: Optional[dict] = None,
    stop_event=None,  # threading.Event — chunk 사이 polling
    search_fn: Optional[Callable] = None,  # 검색 그라운딩 의존성 주입 (인명·회사명 교정)
) -> str:
    """
    Transcript → 한국어로 번역된 스크립트 (문자열).
    화자 라벨과 타임스탬프는 보존된다.

    Args:
        transcript: STT 결과
        config: LLM 설정
        progress: 진행 콜백
        video_context: YouTube 메타데이터 dict (AudioDownloadResult.to_context_dict()
            형태). 제공되면 LLM 의 화자 이름 추론과 챕터 유지에 활용된다.
        stop_event: threading.Event — set 되면 청크 사이에 RuntimeError raise.
            gui.PipelineWorker._stop_event 와 같은 인스턴스를 넘겨 사용자
            중지 요청을 단계 내부에서 catch.
    """
    log = progress or (lambda _msg: None)
    config = config or client.LLMConfig.from_env()

    # 5/23 — omlx xgrammar 사전 점검 (structured output 강제 부재 시 timeout 다발 catch).
    if not client._check_xgrammar_available(config, log):
        raise RuntimeError(
            "omlx xgrammar 미작동 — structured output 강제 부재 → 처리 시 timeout 다발 + "
            "품질 저하 위험. Episilon 서버에서 복구 필요:\n"
            "  brew reinstall omlx --with-grammar\n"
            "  brew services restart jundot/omlx/omlx"
        )

    # 5/24 — STT 의미 단위 재분할 적용 시 chunk size 자동 축소.
    # transcript.raw["segment_resplit"]=True (stt_mlx.py 토글 on) → cs=12, char_limit=2000.
    # off → 기존 (cs=15, char_limit=12000) — daily 1-pass 동작 보존.
    resplit_applied = bool(getattr(transcript, "raw", None)
                            and transcript.raw.get("segment_resplit"))
    if resplit_applied:
        chunks = chunking.chunk_segments(
            transcript.segments,
            char_limit=chunking.RESPLIT_CHAR_LIMIT,
            segment_limit=chunking.RESPLIT_SEGMENT_LIMIT,
        )
        log(f"🌐 LLM 번역 시작 — {len(chunks)} 청크 (cs={chunking.RESPLIT_SEGMENT_LIMIT}, "
            f"char_limit={chunking.RESPLIT_CHAR_LIMIT}, 재분할 적용) ({config.provider}/{config.model})")
    else:
        chunks = chunking.chunk_segments(transcript.segments)
        log(f"🌐 LLM 번역 시작 — {len(chunks)} 청크 ({config.provider}/{config.model})")

    context_block = context.build_video_context_block(video_context)
    if context_block:
        log("📖 영상 컨텍스트(게시일/챕터/자막)를 LLM 에 주입합니다.")

    # Phase 2 (B01) — entity cache + 화자 cache.
    # (b) Two-Stage 부분 적용: 영상 메타 + 자막에서 사전 entity 추출 → chunk 1 차단 catch.
    # (e) Entity Cache: chunk 출력 → entity 추출 → 다음 chunk context prepend.
    # 5/23 — speakers 식별 추가 (영상당 1회 LLM, 2-pass 화자 라벨 코드 부착용).
    entity_cache: dict = {}
    speaker_cache: dict = {}
    if config.enable_phase2:
        subtitles_text = (video_context or {}).get("subtitles_text") if video_context else None
        bootstrap = entities._bootstrap_entity_cache_from_metadata(video_context, subtitles_text, config)
        if bootstrap:
            # 5/23 — bootstrap 결과의 __speakers__ 마커 추출 (cache file 와 caller 분리).
            speaker_cache = bootstrap.pop("__speakers__", {}) or {}
            entity_cache.update(bootstrap)
            log(f"   📚 entity cache bootstrap — {len(bootstrap)}건 사전 추출")
            if speaker_cache:
                log(f"   🎤 speaker cache bootstrap — {len(speaker_cache)}명 식별")

    # A 보완 (5/26) — 통용 표기 결정론적 교정. bootstrap(디스크 캐시 hit 포함) 직후·
    #   chunk loop 전에 적용 → cache_block prepend + 화자 라벨이 교정된 표기로. 저장(아래)
    #   은 이 뒤라 디스크 캐시도 self-heal (옛 "팰머 러커이" → "팔머 럭키").
    canonical_names = entities._load_canonical_names() if config.enable_phase2 else {}
    auto_acc: dict = {}  # English → 교정 전 raw 표기 (작업 끝에 auto 로 누적 저장)
    if config.enable_phase2:
        # 자동 채움 — 교정 전 raw 표기를 먼저 캡처 (user 가 auto 로 덮이지 않게).
        entities._record_auto_spellings(auto_acc, entity_cache, "entity")
        entities._record_auto_spellings(auto_acc, speaker_cache, "speaker")
        entities._apply_canonical_to_entity_cache(entity_cache, canonical_names, log)
        entities._apply_canonical_to_speaker_cache(speaker_cache, canonical_names, log)

    # 5/23 — 영상 단위 첫 등장 catch (화자 라벨 영문 병기 first-occurrence, 2-pass 전용).
    seen_speakers: set = set()

    translated_parts: List[str] = []
    for i, chunk in enumerate(chunks, start=1):
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")
        # 청크 간 쿨다운 — API Rate Limit 방지 (첫 청크는 건너뜀)
        if i > 1:
            time.sleep(chunking.CHUNK_DELAY_SEC)
        log(f"   ↳ 청크 {i}/{len(chunks)} 번역 중…")

        # Phase 2 — context_block 에 entity_cache 블록 prepend (chunk 간 일관성).
        cache_block = entities._build_entity_cache_block(entity_cache) if config.enable_phase2 else ""
        extended_context = f"{context_block}\n\n{cache_block}" if cache_block else context_block

        # Phase 1 Redesign — Structured Output Index Mapping + finish_reason Continuation.
        # 본질 cause 차단: (1) Content drift — LLM 이 timestamp 출력 부재 → 순서만 매핑
        # (zip 100% 결정론). (2) Truncation — finish_reason='length' 명시 catch + retry.
        # 기존 Phase 1 retry/marker 로직 (5/12 trajectory) 영역 제거 — Index Mapping path
        # 가 두 본질 cause 모두 근본 차단.
        # 5/23 — 2-pass 시 speaker_cache + seen_speakers 전달 (화자 라벨 코드 부착).
        translated = translate_chunk_index_mapping_v2(
            chunk, extended_context, config, log,
            speaker_cache=speaker_cache,
            seen_speakers=seen_speakers,
        )
        translated_parts.append(translated)

        # Phase 2 — chunk 출력의 speaker line prefix entity 추출 + cache 갱신.
        if config.enable_phase2:
            new_entities = entities._extract_entities(translated)
            if new_entities:
                added = {k: v for k, v in new_entities.items() if k not in entity_cache}
                if added:
                    entity_cache.update(added)
                    # 자동 채움 — chunk 신규 entity 의 raw 표기 캡처 (교정 전).
                    entities._record_auto_spellings(auto_acc, added, "entity")
                    # A 보완 — chunk 신규 entity 도 통용 표기 교정.
                    entities._apply_canonical_to_entity_cache(added, canonical_names, log)
                    log(f"   📚 entity cache 갱신: +{len(added)}건 (누적 {len(entity_cache)}건)")

    log("✅ 번역 완료")

    # 검색 그라운딩 (GURUNOTE_SEARCH_GROUNDING, 기본 off) — 인명·회사명 STT 오인식을
    # 주입받은 search_fn 으로 교정. entity_cache 의 english key 를 정답으로 교체(원래 키는
    # original_english 로 보존) + source="search" 마킹(재검색 방지). 디스크 저장(아래) 전에
    # 실행해 교정된 cache 가 영속. 반환 {원래 english: 교정 english} 는 본문/원문/frontmatter
    # 전파에 쓴다. 토글 off·search_fn 부재·예외는 교정 없이 graceful skip.
    stt_corrections: dict = {}
    if (config.enable_phase2 and search_fn is not None
            and os.environ.get("GURUNOTE_SEARCH_GROUNDING", "0") == "1"):
        # 캐시-히트 재처리 — 이미 교정된 entity(source="search")는 _verify 가 건너뛰므로,
        # original_english 로 교정 쌍을 먼저 복원해야 본문 병기·소스 주입이 일관 유지된다.
        for _eng, _meta in entity_cache.items():
            if isinstance(_meta, dict) and _meta.get("original_english"):
                stt_corrections[_meta["original_english"]] = _eng
        # 신규(아직 검색 안 한) entity 교정을 누적.
        stt_corrections.update(entities._verify_entities_with_search(entity_cache, search_fn, log))

    # A-2 ① — 자동 채움: 작업 중 본 고유명사의 raw 표기를 통용 dict 의 auto 로 누적 저장.
    #   user 는 불변. ②편집 UI 가 auto 를 보여주고 사용자가 user 로 수정 → 다음 작업부터 적용.
    if config.enable_phase2 and auto_acc:
        entities._persist_auto_spellings(auto_acc)

    # B06 — 영상 처리 완료 시 entity_cache 디스크 저장 (spec §4.4).
    # cache key 는 video_id 우선, 부재 시 video_title hash fallback.
    # speaker_cache 만 있고 entity 0건인 영상도 저장 — 안 그러면 영어 원문 화자 실명이
    # 디스크에 안 남아 load_speaker_names 가 {} → 라벨 fallback (번역본 실명/원문 라벨 불일치).
    if config.enable_phase2 and (entity_cache or speaker_cache):
        video_title_for_cache = (video_context or {}).get("title", "") if video_context else ""
        cache_key = (
            (video_context or {}).get("id")
            or (video_context or {}).get("video_id")
            or entities._compute_cache_key_from_title(video_title_for_cache)
        )
        if cache_key:
            try:
                entities._save_entity_cache(
                    cache_key, video_title_for_cache, entity_cache,
                    speakers=speaker_cache,
                )
                log(
                    f"   💾 entity cache 저장: {len(entity_cache)}건 / "
                    f"speakers {len(speaker_cache)}명 → {cache_key}"
                )
            except Exception as exc:
                log(f"   ⚠ entity cache 저장 실패 (무시): {exc}")

    # Index Mapping path 의 출력은 결정론적 \n\n 정합 — Layer 14 lookahead regex
    # 정규화 영역 부재 (chunk join 만으로 충분).
    normalized_parts = translated_parts
    result = "\n\n".join(normalized_parts).strip()
    # C (5/28) — 본문 라인 레벨 연속 반복 축약 (더듬거림 구간을 2-pass 가 같은 문장으로
    #   채우는 회귀 차단). 1-pass·2-pass 공통 조립 직후, 다른 후처리 전.
    result = postprocess._collapse_repeated_lines(result, log)
    # Phase 3 — 한자/일본어 잔재 후처리 (Sub-path A → B → C).
    # Sub-path A 사전 lookup → 미적중 시 Sub-path B LLM 재매핑 → 그래도 잔재 시
    # Sub-path C 영문 원문 fallback. 본 단계로 한자/일본어 0건 보장.
    result = postprocess.post_process_cjk(result, transcript.segments, config, log)
    # B06 §4.3 — entity 표기 통일 (한자/일본어 0건 보장 후 한국어 본문에 적용).
    # entity_cache 의 canonical 표기 + 외래어 표기법 short version 으로 chunk drift 통일.
    if config.enable_phase2:
        result = entities._canonicalize_entity_names(result, entity_cache, config, log)
    # 검색 그라운딩 — 한국어 본문 병기의 교정 영문 전파 (Wurst)→(Warsh).
    #   result 텍스트 치환 (병기는 괄호 안 영문). 영어 원문 섹션·frontmatter 는 exporter 가
    #   디스크 cache(original_english)에서 따로 전파 (load_stt_corrections).
    for _orig, _corr in stt_corrections.items():
        result = result.replace(f"({_orig})", f"({_corr})")
    # B (5/26) — 영문 병기 철자를 소스(transcript 전문 + 제목)로 결정론적 검증.
    #   LLM 이 영문 원어를 자유 생성하다 오염(Anduril→Danduril)시키는 것 차단.
    _src_title = (video_context or {}).get("title", "") if video_context else ""
    source_corpus = " ".join(s.text for s in transcript.segments)
    if _src_title:
        source_corpus = f"{source_corpus} {_src_title}"
    # 검색 그라운딩 — 교정 영문을 소스 풀에 주입해 postprocess._correct_english_annotations 가 교정
    #   병기((Warsh))를 소스 부재로 DROP 하지 않게 (소스는 raw STT=Wurst 라 누락 위험).
    if stt_corrections:
        source_corpus = f"{source_corpus} " + " ".join(stt_corrections.values())
    result = postprocess._correct_english_annotations(result, source_corpus, log)
    # 영상 단위 영문 병기 첫 등장만 남기고 반복 병기 dedup (Layer 13 정합).
    return postprocess._strip_repeated_annotations(result)


TIMEOUT_PADDING_MARKER = "[⚠ timeout]"


def _build_freeform_translation_prompt(inputs: list, context: str) -> str:
    """(가) 옵션 A 1단계 — schema 부재 자유 번역 prompt (5/23 — 화자 라벨 제거).

    DCCD 패턴: 1단계 자유 추론 (schema 부담 부재) → 2단계 정렬 (schema strict).
    5/23 — 화자 라벨이 LLM 처리에서 제외 (client zip 코드 부착). 입력 형식 변경:
    "A: text" → "text" 만. 모델이 본문 번역에만 집중.

    Args:
        inputs: ["text", ...] N개 (speaker prefix 제거된 본문만).
        context: 영상 컨텍스트 + entity_cache markdown block (B06 §4.1 정합).

    Returns:
        user prompt 문자열. system = prompts.TRANSLATION_SYSTEM_PROMPT 재사용.
    """
    return f"""[자유 번역 영역 — (가) 옵션 A 1단계, schema 부재, 5/23 화자 라벨 제거]

다음 {len(inputs)}개 segment 본문을 한국어로 번역하라:

1. 형식 제약 부재. 원문의 모든 절·정보를 빠짐없이 충실하게 한국어로 옮기되, 한국어로 자연스럽게 재구성. 환각·누락·일반 영어 leak 금지.
2. **각 segment 를 빈 줄 (`\\n\\n`) 로 구분하여 정확히 {len(inputs)}개 출력**.
3. **화자 라벨 출력 절대 부재** — 입력에 화자 prefix 부재, 출력도 화자 부재.
   본문 한국어 번역만 출력 (예: "안녕하세요. 오늘은…" 형식, "이름: 본문" 형식 절대 부재).
4. timestamp 출력 절대 부재 (클라이언트가 별도 부착).
5. 다른 모든 규칙 (Rule 3~11 + _SHARED_LANG_RULES) 정합 유지.
6. segment 를 합치거나 나누지 말 것 — 입력 {len(inputs)}개 ↔ 출력 {len(inputs)}개.

{context}

Input ({len(inputs)}개 segment 본문, 영어 text 만):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

Output (정확히 {len(inputs)}개 한국어 본문, `\\n\\n` 구분, 화자/timestamp 부재):"""


def _build_alignment_prompt(inputs: list, freeform_translation: str) -> str:
    """(가) 옵션 A prototype 2단계 — 자유 번역 정렬 prompt (schema strict 강제).

    1단계 자유 번역을 입력 N개에 1:1 매핑하는 N개 outputs 배열로 정렬.
    번역 내용 변경 부재 — 재정렬·재조립만.

    Args:
        inputs: 원본 ["Speaker A: text", ...] N개.
        freeform_translation: 1단계 자유 번역 결과 (line break 구분 추정).

    Returns:
        user prompt 문자열. system = prompts.TRANSLATION_SYSTEM_PROMPT 재사용.
    """
    return f"""[정렬 영역 — (가) 옵션 A 2단계, schema strict, 5/23 화자 라벨 제거]

다음 자유 번역의 내용을 입력 {len(inputs)}개 segment 에 1:1 대응하는 {len(inputs)}개 outputs 배열로 재배치하라:

**핵심 원칙**:
1. **번역 내용/의미 보존 — 재배치만, 새 번역 생성 부재** — 1단계 자유 번역의 단어와 표현을 그대로 사용하되 (내용 추가·삭제·수정 절대 부재, 새로 번역하지 말 것), 입력 {len(inputs)}개 segment 경계에 맞춰 재배치만 한다.
2. **outputs 배열은 정확히 {len(inputs)} 개 항목, 입력 순서 유지**.

**재배치 규칙 (rule 1/3 충돌 해소)**:
3. 1단계 자유 번역이 segment 합쳤으면 (예: 입력 3개 → 자유 번역 2개), 자연스러운 의미 경계로 다시 나눠 {len(inputs)}개로 만들 것.
4. 1단계 자유 번역이 segment 나눴으면 (예: 입력 2개 → 자유 번역 3개), 의미 단위로 합쳐 {len(inputs)}개로 만들 것.

**금지 사항 (빈/반복/화자 차단)**:
5. **빈 string output 절대 부재** — 모든 outputs 항목은 비어있지 않은 한국어 번역. 부족분을 빈 칸으로 채우지 말 것.
6. **같은 본문 반복 절대 부재** — outputs 항목들이 서로 다른 내용. 부족분을 라인 반복으로 채우지 말 것.
7. 입력 {len(inputs)}개가 모두 비슷한 짧은 발화여도, 자유 번역의 해당 부분을 각각 정확히 매핑할 것.
8. **화자 라벨 출력 절대 부재** (5/23 — 코드 부착으로 분리) — 각 output 은 본문 한국어만. "이름:" 같은 화자 prefix 절대 부재.

**출력 형식**:
9. JSON 형식: {{"outputs": [str, str, ...]}}
10. timestamp 출력 절대 부재.

Input ({len(inputs)}개 원본 segment 본문, 영어 text 만):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

자유 번역 결과 (1단계 출력):
{freeform_translation}

Output (JSON 만, 화자/timestamp 부재, 다른 텍스트 부재):"""


def _build_index_mapping_prompt(inputs: list, context: str) -> str:
    """Index Mapping 영역의 user prompt — prompts.TRANSLATION_SYSTEM_PROMPT 가 system 영역
    이라 가정. 본 user prompt 는 출력 형식 override 만 명시 (entity / Layer 8/11/13/15
    규칙은 system 에서 catch).

    Rule 1, 2 (timestamp 보존 / [HH:MM] 형식) override:
      - 출력 형식 = JSON {"outputs": [...]}
      - timestamp 영역 부재 (클라이언트가 zip 으로 별도 부착)
      - speaker label 영역 = Rule 2 의 한국어 화자명 정합 (예: "판카즈 샤르마(Pankaj Sharma): 본문")
    """
    return f"""[출력 형식 영역 — Rule 1, 2 의 timestamp 부분 override]

이번 호출은 Index Mapping path 영역. 출력 형식을 다음과 같이 변경한다:

1. 응답은 반드시 JSON 형식: {{"outputs": [str, str, ...]}}
2. outputs 배열은 정확히 {len(inputs)}개 항목 (같은 순서)
3. timestamp 출력 절대 부재 (클라이언트가 별도 부착)
4. 각 output string 형식: "한국어 화자명(English Name): 본문" (첫 등장) 또는 "한국어 화자명: 본문" (이후)
5. "Speaker A/B/C" 영문 라벨 출력 절대 부재 — Rule 2 정합 한국어 화자명
6. 다른 모든 규칙 (Rule 3~11 + _SHARED_LANG_RULES) 정합 유지

{context}

Input ({len(inputs)}개 항목, 각 "Speaker X: 영어 text" 형식):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

Output (JSON 만, 다른 텍스트 부재):"""


def _call_llm_with_index_mapping(
    config: client.LLMConfig,
    prompt: str,
    expected_count: int,
    max_retries: int = 3,
    log: Optional[client.ProgressFn] = None,
    enable_loose_on_timeout: bool = False,
    reject_empty_outputs: bool = False,
) -> list:
    """Index Mapping + 길이 검증 + retry feedback.

    Args:
        enable_loose_on_timeout: True 시 timeout 발생 → strict→loose 전환 (R3-수정,
            (가) 옵션 A 2단계 전용). 기본 False — 1-pass 동작 보존.
        reject_empty_outputs: True 시 outputs 안에 빈 string 있으면 retry 트리거
            (5/23 — 2-pass 빈 output 복구 1차). 기본 False — 1-pass 동작 보존
            (1-pass 는 화자 라벨 포함 출력이라 빈 비현실적이지만 명시 분리).

    Returns:
        List[str]: outputs 배열 (길이 = expected_count 보장, fallback 시 [번역 누락] padding)
    """
    log_fn = log or print
    # System = prompts.TRANSLATION_SYSTEM_PROMPT (Layer 8/11/13/15 entity 규칙 포함).
    # User = _build_index_mapping_prompt 의 출력 형식 override (JSON outputs 배열).
    messages: list = [
        {"role": "system", "content": prompts.TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    # json_schema strict 모드 — minItems/maxItems 로 정확히 N개 강제.
    # 5/13 E2E 결과의 길이 미스매치 (23/22 outputs vs 25 expected) 근본 차단.
    # 5/12 endpoint verify: qwen3.6-35b-q5 의 json_schema strict + additionalProperties=False 정합.
    strict_response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "translation_outputs",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "outputs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": expected_count,
                        "maxItems": expected_count,
                    },
                },
                "required": ["outputs"],
                "additionalProperties": False,
            },
        },
    }
    # Phase 4a-1 — xgrammar grammar-recovery loop 회피용 fallback mode.
    # 5/16 진단: xgrammar 0.2.0 + strict schema 에서 일부 입력이 grammar-recovery
    # loop 진입 → 8192 tokens 까지 rejected token 재샘플링 (slow chunk 245~281초).
    # 첫 시도 strict, 실패 시 json_object mode 로 전환:
    #   - JSON parse fail 또는 finish_reason=length → loose mode 전환 후 retry
    #   - json_object 는 JSON 구문만 강제, 스키마 길이 강제 없음 → grammar 복잡도 낮음
    #   - 기존 length mismatch retry 가 결과 검증 담당 (양 환경 safety net)
    #
    # 5/17 시도 (실패, dead code 제거됨):
    #   - A-3 (strict 첫 시도 + 30초 timeout): httpx read timeout 한계로 wall-clock
    #     강제 불가 (chunk 9 가 281초 소비했지만 timeout 미발동). retry loop 의
    #     try/except APITimeoutError 블록은 dead code 가 되어 제거. helper 함수
    #     timeout 파라미터 시그니처는 future hook (wall-clock timeout 도입 시
    #     재활용) 으로 유지.
    loose_response_format = {"type": "json_object"}
    max_tokens = config.translation_max_tokens or client.TRANSLATION_MAX_TOKENS
    outputs: list = []
    use_strict_mode = True
    # R2 (5/23) — timeout 시 마지막 시도가 timeout 이었는지 추적 (fallback marker 결정).
    last_error_was_timeout = False

    for retry in range(max_retries):
        active_response_format = strict_response_format if use_strict_mode else loose_response_format
        try:
            content, finish_reason = client._call_llm_with_continuation(
                config, messages, max_tokens, response_format=active_response_format
            )
            last_error_was_timeout = False
        except TimeoutError as exc:
            # R2 (5/23) — wall-clock timeout 시 strict mode 유지 retry. 90초 차단(f314d6e)
            # 후 간헐적 폭주 chunk 가 다음 시도에서 풀릴 가능성 catch.
            # R3-수정 (5/23, (가) 옵션 A 2단계 전용): enable_loose_on_timeout=True 시
            # strict → loose 전환. 1-pass 동작 보존을 위해 기본 False.
            log_fn(
                f"   ⚠ chunk wall-clock timeout — retry {retry + 1}/{max_retries}: {exc}"
            )
            if enable_loose_on_timeout and use_strict_mode:
                log_fn(f"   ↳ R3-수정: timeout 시 json_object mode 전환 (strict 부담 회피)")
                use_strict_mode = False
            last_error_was_timeout = True
            continue
        # JSON 파싱
        try:
            parsed = json.loads(content)
            outputs = parsed.get("outputs", []) or []
        except json.JSONDecodeError as exc:
            log_fn(f"   ⚠ JSON 파싱 부재 (retry {retry + 1}/{max_retries}): {exc}")
            # 첫 실패 시 loose mode 전환 (xgrammar grammar-recovery loop 회피)
            if use_strict_mode:
                log_fn(f"   ↳ json_object mode 전환 (xgrammar 우회)")
                use_strict_mode = False
            messages.append({
                "role": "user",
                "content": (
                    f"Previous response was not valid JSON. Return only "
                    f'{{"outputs": [...]}} with exactly {expected_count} items.'
                ),
            })
            continue

        # 길이 검증 — drift 근본 차단
        if len(outputs) == expected_count:
            # 5/23 — 빈 string 검출 (reject_empty_outputs=True 시, 2-pass 전용).
            # 1-pass 는 화자 라벨 포함 출력이라 빈 비현실적 — 기본 False 로 동작 보존.
            empty_indices = [
                i for i, o in enumerate(outputs)
                if not isinstance(o, str) or not o.strip()
            ]
            if reject_empty_outputs and empty_indices:
                log_fn(
                    f"   ⚠ 빈 output {len(empty_indices)}건 catch "
                    f"(idx={empty_indices[:5]}{'...' if len(empty_indices) > 5 else ''}, "
                    f"retry {retry + 1}/{max_retries})"
                )
                # strict mode 라면 loose 전환 (자유도 catch — 본문 채우기 가능성 ↑)
                if use_strict_mode:
                    log_fn(f"   ↳ 빈 output retry — json_object mode 전환")
                    use_strict_mode = False
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Previous output had {len(empty_indices)} empty items "
                        f"at indices {empty_indices[:10]}. "
                        f"All {expected_count} outputs MUST be non-empty Korean translations. "
                        f"Do NOT use empty strings or placeholders. Return complete JSON."
                    ),
                })
                continue
            log_fn(f"   ✅ Index Mapping 정합 — {len(outputs)} outputs (finish_reason={finish_reason})")
            return outputs

        # finish_reason=length + strict mode → grammar-recovery loop 가능성 → mode 전환
        if finish_reason == "length" and use_strict_mode:
            log_fn(f"   ↳ finish_reason=length 감지, json_object mode 전환 (xgrammar 우회)")
            use_strict_mode = False

        log_fn(
            f"   ⚠ 길이 미스매치: {len(outputs)} != {expected_count} "
            f"(retry {retry + 1}/{max_retries}, finish_reason={finish_reason})"
        )
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                f"Previous output had {len(outputs)} items. Need exactly "
                f"{expected_count} items in same order. Return complete JSON: "
                '{"outputs": [...]}.'
            ),
        })

    # 3 retries 모두 실패 — fallback (padding 또는 truncate).
    # R2 (5/23): 마지막 시도가 timeout 이면 [⚠ timeout] marker, 그 외 일반 [번역 누락].
    fallback_marker = TIMEOUT_PADDING_MARKER if last_error_was_timeout else "[번역 누락]"
    log_fn(
        f"   ⚠ Index Mapping retry {max_retries}회 실패 — fallback "
        f"({len(outputs)} → {expected_count}, marker={fallback_marker!r})"
    )
    if len(outputs) < expected_count:
        outputs = list(outputs) + [fallback_marker] * (expected_count - len(outputs))
    else:
        outputs = list(outputs)[:expected_count]
    return outputs


def _post_process_two_pass_outputs(
    outputs: list,
    expected_count: int,
    log: Optional[client.ProgressFn] = None,
) -> list:
    """A5 — 2-pass outputs deterministic 후처리 (5/23).

    1. **prefix strip**: 각 output 의 'A:'/'B:' 같은 입력 prefix 잔존 제거.
    2. **빈 segment 검출**: 빈 string output 을 "[번역 누락]" marker 로 교체.
    3. **반복 라인 검출**: consecutive 동일 output 발견 시 log 경고 (자동 제거 부재
       — 짧은 발화의 정상 반복 오인 방지).

    Args:
        outputs: _call_llm_with_index_mapping 결과 list.
        expected_count: 기대 길이 (안전 검사용).
        log: 진행 콜백.

    Returns:
        후처리된 outputs list (길이 = expected_count 보존).
    """
    log_fn = log or (lambda _m: None)
    processed = [postprocess._strip_input_speaker_prefix(o or "") for o in outputs]

    # 빈 segment → [번역 누락] marker
    empty_count = 0
    for i, o in enumerate(processed):
        if not o or not o.strip():
            processed[i] = "[번역 누락]"
            empty_count += 1
    if empty_count:
        log_fn(f"   ⚠ 2-pass 빈 output {empty_count}건 → [번역 누락] padding")

    # 연속 동일 라인 검출 (경고만)
    repeat_count = 0
    for i in range(1, len(processed)):
        if processed[i] == processed[i - 1] and processed[i] != "[번역 누락]":
            repeat_count += 1
    if repeat_count:
        log_fn(
            f"   ⚠ 2-pass 연속 동일 output {repeat_count}건 catch — 정상 반복 가능성"
        )

    return processed


def _resolve_speaker_label(
    speaker: str,
    speaker_cache: Optional[dict],
    seen_speakers: set,
) -> str:
    """5/23 — STT speaker label ("A","B",...) → 한국어 화자 라벨 결정론적 부착.

    영상 단위 첫 등장 영문 병기 catch (Layer 13 정합). cache 부재 fallback "화자 N".

    Args:
        speaker: STT label (예: "A","B","C",...).
        speaker_cache: {"A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"}, ...}.
            None 또는 빈 dict 가능 (fallback 진입).
        seen_speakers: 영상 단위 첫 등장 catch set. 호출 후 본 함수가 add.

    Returns:
        라벨 문자열 (예: "판카즈 샤르마(Pankaj Sharma)" 첫 등장 / "판카즈 샤르마" 이후 / "화자 1" fallback).
    """
    is_first = speaker not in seen_speakers
    seen_speakers.add(speaker)

    meta = (speaker_cache or {}).get(speaker)
    if meta and meta.get("korean"):
        korean = meta["korean"]
        english = meta.get("english", "")
        if is_first and english:
            return f"{korean}({english})"
        return korean

    # fallback: "A" → "화자 1", "B" → "화자 2", ...
    try:
        idx = ord(speaker.upper()[0]) - ord("A") + 1
        if 1 <= idx <= 26:
            return f"화자 {idx}"
    except (IndexError, TypeError):
        pass
    return f"화자 {speaker or '?'}"


def _translate_chunk_two_pass(
    chunk: List[Segment],
    context_block: str,
    config: client.LLMConfig,
    log: Optional[client.ProgressFn] = None,
) -> List[str]:
    """(가) 옵션 A prototype — 2-pass 자유 번역 + 정렬.

    1단계: schema 부재 자유 번역 (`_build_freeform_translation_prompt`).
        - `client._call_llm` 경유 (f314d6e wall-clock + HTTP timeout 안전망 적용).
        - response_format 부재 — 모델이 추론 부담 부재로 자연 한국어 catch.
    2단계: 자유 번역 결과를 N개 outputs 로 정렬 (`_build_alignment_prompt`).
        - `_call_llm_with_index_mapping` 재사용 + enable_loose_on_timeout=True (R3-수정).
        - schema strict (minItems/maxItems=N) 으로 N개 정합 보장.

    5/23 — 입력에서 speaker prefix 제거 ("A: text" → "text"). 화자 라벨은 client zip
    에서 코드 부착 (translate_chunk_index_mapping_v2). rule 1 딜레마 근본 해소.

    Args:
        chunk: 입력 segment N개.
        context_block: 영상 컨텍스트 + entity_cache (B06 §4.1).
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        List[str]: 정렬된 outputs N개 (본문만, 화자 부재). fallback 시 padding 적용.
    """
    log_fn = log or (lambda _m: None)
    # 5/23 — speaker prefix 제거. 본문만 입력 → LLM 화자 처리 부재.
    inputs = [s.text for s in chunk]

    # 1단계 — 자유 번역.
    log_fn(f"   ↳ 2-pass 1단계: 자유 번역 ({len(inputs)} segments)")
    freeform_prompt = _build_freeform_translation_prompt(inputs, context_block)
    try:
        freeform = client._call_llm(
            config,
            system=prompts.TRANSLATION_SYSTEM_PROMPT,
            user=freeform_prompt,
            max_tokens=config.translation_max_tokens or client.TRANSLATION_MAX_TOKENS,
        )
    except TimeoutError as exc:
        # 1단계 timeout — 2단계 정렬 input 부재 → 즉시 fallback padding.
        log_fn(f"   ⚠ 2-pass 1단계 timeout — 전체 fallback ({len(inputs)} segments): {exc}")
        return [TIMEOUT_PADDING_MARKER] * len(inputs)

    if not freeform or not freeform.strip():
        log_fn(f"   ⚠ 2-pass 1단계 빈 응답 — 전체 fallback ({len(inputs)} segments)")
        return ["[번역 누락]"] * len(inputs)

    # 5/23 — 1단계 결과 로깅 (책임 단계 확정 + 옵션 나 활용 자료).
    freeform_lines = [line.strip() for line in freeform.split("\n\n") if line.strip()]
    log_fn(
        f"   📝 2-pass 1단계 출력 — {len(freeform_lines)} lines / N={len(inputs)}, "
        f"empty lines: {sum(1 for ln in freeform_lines if not ln)}"
    )

    # 2단계 — 정렬 (schema strict + R3-수정 loose 전환 + 빈 output retry).
    log_fn(f"   ↳ 2-pass 2단계: 정렬 ({len(inputs)} outputs schema strict)")
    alignment_prompt = _build_alignment_prompt(inputs, freeform)
    outputs = _call_llm_with_index_mapping(
        config,
        alignment_prompt,
        expected_count=len(inputs),
        max_retries=3,
        log=log,
        enable_loose_on_timeout=True,
        reject_empty_outputs=True,   # 5/23 — 1차 복구: 빈 string retry
    )

    # 5/23 — 복구 시퀀스 (2차 + 3차).
    outputs = _recover_empty_outputs(
        outputs, freeform_lines, inputs, chunk, config, log,
    )

    # A5 (5/23) — deterministic 후처리 (prefix strip + 잔존 빈 → marker + 반복 경고).
    return _post_process_two_pass_outputs(outputs, len(inputs), log)


def _recover_empty_outputs(
    outputs: List[str],
    freeform_lines: List[str],
    inputs: List[str],
    chunk: List[Segment],
    config: client.LLMConfig,
    log: Optional[client.ProgressFn] = None,
) -> List[str]:
    """5/23 — 2-pass 빈 output 복구 시퀀스 (2차 + 3차).

    2차 (옵션 나): 1단계 자유 번역 line 수가 N 과 정합하면 해당 index 의 1단계 본문 활용
        → LLM 호출 0 으로 복구.
    3차 (옵션 다): 1단계도 빈 또는 line 수 불일치 → 해당 segment STT text 단독 재번역
        (1-pass 방식, 본 segment 하나만 client._call_llm 호출).

    Args:
        outputs: 2단계 정렬 결과 N개 (일부 빈 가능).
        freeform_lines: 1단계 자유 번역 결과를 빈 줄 구분으로 split.
        inputs: 원본 STT text N개.
        chunk: 원본 segment N개 (speaker 정보 등).
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        복구된 outputs N개 (실패 시 빈 잔존 — A5 가 marker 교체).
    """
    log_fn = log or (lambda _m: None)
    processed = list(outputs)

    # 2차 — 1단계 자유 번역 활용 (line 수 정합 시).
    if len(freeform_lines) == len(inputs):
        recovered_2nd = 0
        for i, out in enumerate(processed):
            if not isinstance(out, str) or not out.strip():
                candidate = freeform_lines[i].strip() if i < len(freeform_lines) else ""
                if candidate:
                    processed[i] = candidate
                    recovered_2nd += 1
        if recovered_2nd:
            log_fn(f"   🛟 빈 output 복구 2차 (1단계 활용): {recovered_2nd}건")

    # 3차 — 단독 재번역 (해당 segment STT text 만).
    still_empty = [
        i for i, o in enumerate(processed)
        if not isinstance(o, str) or not o.strip()
    ]
    if still_empty:
        log_fn(f"   🛟 빈 output 복구 3차 (단독 재번역): {len(still_empty)}건 시도")
        recovered_3rd = 0
        for i in still_empty:
            seg_text = inputs[i] if i < len(inputs) else ""
            if not seg_text or not seg_text.strip():
                continue   # STT 원본도 빈 — 복구 부재 → 최종 marker
            try:
                solo = client._call_llm(
                    config,
                    system=prompts.TRANSLATION_SYSTEM_PROMPT,
                    user=(
                        f"[단독 재번역 — (가) 2-pass 3차 복구]\n\n"
                        f"다음 영어 발화 1건을 자연스러운 한국어로 번역하라. "
                        f"화자 라벨/timestamp 출력 부재 — 본문 한국어만.\n\n"
                        f"Input: {seg_text!r}\n\n"
                        f"Output (한국어 본문만):"
                    ),
                    max_tokens=512,
                )
                if solo and solo.strip():
                    processed[i] = solo.strip()
                    recovered_3rd += 1
            except Exception as exc:
                log_fn(f"   ⚠ 빈 output 복구 3차 idx={i} 실패: {exc}")
        if recovered_3rd:
            log_fn(f"   🛟 빈 output 복구 3차 (단독 재번역): {recovered_3rd}건 catch")
        remaining = sum(
            1 for o in processed
            if not isinstance(o, str) or not o.strip()
        )
        if remaining:
            log_fn(f"   ⚠ 복구 후에도 잔존 빈 output: {remaining}건 → 최종 marker")

    return processed


def translate_chunk_index_mapping_v2(
    chunk: List[Segment],
    context_block: str,
    config: client.LLMConfig,
    log: Optional[client.ProgressFn] = None,
    speaker_cache: Optional[dict] = None,
    seen_speakers: Optional[set] = None,
) -> str:
    """단일 chunk 영역의 Index Mapping 적용 — 체크포인트 2 verify 영역.

    체크포인트 3 시 translate_transcript 영역 통합 결정.

    (가) 옵션 A prototype 토글 (5/23):
        GURUNOTE_TWO_PASS 환경변수 (기본 on). off 강제: GURUNOTE_TWO_PASS=0.
        2-pass 분리 (자유 번역 → 정렬). off 시 기존 1-pass 보존.

    5/23 — speaker_cache + seen_speakers 인자 추가 (2-pass 화자 라벨 코드 부착).
        1-pass path 영향 부재 (인자 사용 부재).
    """
    is_two_pass = os.environ.get("GURUNOTE_TWO_PASS", "1") == "1"

    if is_two_pass:
        # 2-pass — 입력 본문만 (speaker prefix 부재), 화자 라벨은 client zip 코드 부착.
        outputs = _translate_chunk_two_pass(chunk, context_block, config, log)
    else:
        # 1-pass — 기존 path 보존 (speaker prefix 포함된 input, LLM 이 화자 라벨 출력).
        inputs = [f"{s.speaker}: {s.text}" for s in chunk]
        prompt = _build_index_mapping_prompt(inputs, context_block)
        outputs = _call_llm_with_index_mapping(
            config, prompt, expected_count=len(inputs), max_retries=3, log=log,
        )

    # 클라이언트 측 timestamp 부착 — zip 으로 결정론적 매핑 (drift 불가능).
    # Line break = \n\n (Layer 14 정합 — Index Mapping 영역 결정론적 정합).
    # 5/23 — 2-pass 시 화자 라벨도 client zip 코드 부착 (식별 1회 + 결정론적).
    # 1-pass 시 LLM output 에 화자 라벨 포함됨 → korean 그대로 사용 (기존 동작).
    result_lines: List[str] = []
    # 2-pass 경로의 seen_speakers — caller (translate_transcript) 가 영상 단위 공유.
    # caller 부재 시 chunk 단위 로컬 set (단독 호출 case).
    local_seen = seen_speakers if seen_speakers is not None else set()
    for segment, korean in zip(chunk, outputs):
        ts = f"[{_format_ts(segment.start)}]"
        if is_two_pass:
            speaker_label = _resolve_speaker_label(segment.speaker, speaker_cache, local_seen)
            result_lines.append(f"{ts} {speaker_label}: {korean}")
        else:
            result_lines.append(f"{ts} {korean}")
    return "\n\n".join(result_lines)

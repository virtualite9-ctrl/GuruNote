"""검색 그라운딩 — 인명·회사명 STT 오인식 교정 (mock 검증).

실제 AgentSearch·Docker·네트워크는 범위 밖. 가짜 검색 함수를 의존성 주입해 교정
로직만 검증한다 (Wurst→Warsh, Besson→Bessent).

성공 기준:
    (a) 한국어 본문 병기 (Wurst)→(Warsh)
    (b) 영어 원문 스크립트 표시 Wurst→Warsh (segments 원본 불변)
    (c) frontmatter stt_corrections 기록
    (d) 같은 영상 재처리 시 재검색 안 함 (source="search" 마킹)
    검색 off 면 아무 교정 없이 현행 그대로.
"""
from __future__ import annotations

from unittest.mock import patch

from gurunote import llm
from gurunote.exporter import build_gurunote_markdown, build_original_script_section
from gurunote.llm import (
    LLMConfig,
    _compute_cache_key_from_title,
    _save_entity_cache,
    _verify_entities_with_search,
    load_stt_corrections,
    translate_transcript,
)
from gurunote.types import Segment, Transcript


def _fake_search(mapping):
    """{원래: 교정} dict 로 가짜 search_fn 생성. 미수록은 None."""
    def _fn(name, hint=None):
        return mapping.get(name)
    return _fn


# =============================================================================
# _verify_entities_with_search — 단위 (entity_cache 변형)
# =============================================================================
class TestVerifyEntities:
    def test_corrects_person_key_and_marks(self):
        cache = {"Kevin Wurst": {"korean": "케빈 워스트", "type": "person", "source": "bootstrap"}}
        corr = _verify_entities_with_search(cache, _fake_search({"Kevin Wurst": "Kevin Warsh"}))
        assert corr == {"Kevin Wurst": "Kevin Warsh"}
        assert "Kevin Wurst" not in cache
        assert cache["Kevin Warsh"]["source"] == "search"
        assert cache["Kevin Warsh"]["original_english"] == "Kevin Wurst"
        assert cache["Kevin Warsh"]["korean"] == "케빈 워스트"  # 한국어 보존

    def test_company_type_also_corrected(self):
        cache = {"Besson": {"korean": "베송", "type": "company", "source": "bootstrap"}}
        corr = _verify_entities_with_search(cache, _fake_search({"Besson": "Bessent"}))
        assert corr == {"Besson": "Bessent"}
        assert cache["Bessent"]["original_english"] == "Besson"

    def test_skips_non_person_company_types(self):
        cache = {
            "Tokyo": {"korean": "도쿄", "type": "place", "source": "bootstrap"},
            "iPhone": {"korean": "아이폰", "type": "product", "source": "bootstrap"},
        }
        spy = {"calls": 0}

        def _fn(name, hint=None):
            spy["calls"] += 1
            return "WRONG"

        corr = _verify_entities_with_search(cache, _fn)
        assert corr == {}
        assert spy["calls"] == 0  # place/product 는 검색 대상 아님
        assert "Tokyo" in cache and "iPhone" in cache  # 불변

    def test_unifies_duplicate_misspelling(self):
        """한 영상에 Wurst·Warsh 둘 다 → 정답 Warsh 로 통일."""
        cache = {
            "Kevin Wurst": {"korean": "케빈 워스트", "type": "person", "source": "bootstrap"},
            "Kevin Warsh": {"korean": "케빈 워시", "type": "person", "source": "bootstrap"},
        }
        corr = _verify_entities_with_search(
            cache, _fake_search({"Kevin Wurst": "Kevin Warsh", "Kevin Warsh": "Kevin Warsh"})
        )
        assert "Kevin Wurst" not in cache
        assert "Kevin Warsh" in cache
        assert corr.get("Kevin Wurst") == "Kevin Warsh"

    def test_already_searched_not_recalled(self):
        """source=='search' entity 는 재검색 안 함 (재처리 방지)."""
        cache = {"Kevin Warsh": {"korean": "케빈 워시", "type": "person", "source": "search"}}
        spy = {"calls": 0}

        def _fn(name, hint=None):
            spy["calls"] += 1
            return "Something"

        corr = _verify_entities_with_search(cache, _fn)
        assert spy["calls"] == 0
        assert corr == {}

    def test_search_exception_does_not_mark(self):
        """검색 실패(예외)는 교정 없이 진행 + source 마킹 안 함 (transient 재시도 보호)."""
        cache = {"Kevin Wurst": {"korean": "케빈 워스트", "type": "person", "source": "bootstrap"}}

        def _fn(name, hint=None):
            raise RuntimeError("offline")

        corr = _verify_entities_with_search(cache, _fn)
        assert corr == {}
        assert cache["Kevin Wurst"]["source"] == "bootstrap"  # 마킹 안 됨 → 다음에 재시도

    def test_search_none_marks_searched(self):
        """검색 성공·교정 불필요(None)는 source='search' 마킹 (재검색 방지)."""
        cache = {"Real Name": {"korean": "리얼 네임", "type": "person", "source": "bootstrap"}}
        corr = _verify_entities_with_search(cache, _fake_search({}))  # 항상 None
        assert corr == {}
        assert cache["Real Name"]["source"] == "search"


# =============================================================================
# load_stt_corrections — 디스크 round-trip
# =============================================================================
def test_load_stt_corrections_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    video_context = {"title": "Druckenmiller Interview"}
    cache_key = _compute_cache_key_from_title(video_context["title"])
    entities = {
        "Kevin Warsh": {"korean": "케빈 워시", "type": "person", "source": "search",
                        "original_english": "Kevin Wurst"},
        "Jane Doe": {"korean": "제인 도", "type": "person", "source": "bootstrap"},  # 비교정
    }
    _save_entity_cache(cache_key, video_context["title"], entities=entities)
    assert load_stt_corrections(video_context) == {"Kevin Wurst": "Kevin Warsh"}


def test_load_stt_corrections_none_context():
    assert load_stt_corrections(None) == {}


def test_load_stt_corrections_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    assert load_stt_corrections({"title": "No Cache"}) == {}


# =============================================================================
# exporter — 영어 원문 표시 치환 + frontmatter 기록
# =============================================================================
def test_original_script_applies_corrections():
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="I met Kevin Wurst today.")],
        language="en",
    )
    md = build_original_script_section(
        transcript, language="en", stt_corrections={"Kevin Wurst": "Kevin Warsh"}
    )
    assert "Kevin Warsh" in md
    assert "Kevin Wurst" not in md
    # segments 원본 불변
    assert transcript.segments[0].text == "I met Kevin Wurst today."


def test_frontmatter_records_corrections():
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="Kevin Wurst spoke.")],
        language="en",
    )
    md = build_gurunote_markdown(
        title="Demo", webpage_url="https://youtu.be/x", summary_md="s",
        translated_text="ko", transcript=transcript, field="금융",
        detected_language="en",
        stt_corrections={"Kevin Wurst": "Kevin Warsh", "Besson": "Bessent"},
    )
    assert 'stt_corrections: ["Kevin Wurst→Kevin Warsh", "Besson→Bessent"]' in md
    # 영어 원문 표시도 교정
    assert "**[00:00] Speaker A:** Kevin Warsh spoke." in md


def test_frontmatter_omits_field_when_no_corrections():
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="hi")], language="en",
    )
    md = build_gurunote_markdown(
        title="Demo", webpage_url="https://youtu.be/x", summary_md="s",
        translated_text="ko", transcript=transcript, field="금융", detected_language="en",
    )
    assert "stt_corrections:" not in md  # 교정 없으면 필드 생략


# =============================================================================
# translate_transcript 통합 — 본문 병기 전파 + 디스크 영속 + 토글
# =============================================================================
def _run_translate(search_on, search_fn, monkeypatch, tmp_path, video_context, bootstrap=None):
    monkeypatch.setattr(llm, "_CANONICAL_NAMES_PATH", tmp_path / "canonical_names.json")
    if search_on:
        monkeypatch.setenv("GURUNOTE_SEARCH_GROUNDING", "1")
    else:
        monkeypatch.delenv("GURUNOTE_SEARCH_GROUNDING", raising=False)
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="I met Kevin Wurst.")],
        language="en",
    )
    cfg = LLMConfig(
        provider="openai_compatible", model="mock", api_key="mock", base_url="http://mock.local/v1",
    )
    if bootstrap is None:
        bootstrap = {"Kevin Wurst": {"korean": "케빈 워스트", "type": "person", "source": "bootstrap"}}
    chunk_out = "[00:00] 케빈 워스트(Kevin Wurst): 안녕하세요."
    with patch.object(llm, "_check_xgrammar_available", return_value=True), \
         patch.object(llm, "_bootstrap_entity_cache_from_metadata", return_value=bootstrap), \
         patch.object(llm, "translate_chunk_index_mapping_v2", return_value=chunk_out), \
         patch.object(llm, "post_process_cjk", side_effect=lambda result, *a, **k: result), \
         patch.object(llm, "_canonicalize_entity_names", side_effect=lambda result, *a, **k: result):
        # _canonicalize_entity_names 는 entity_cache 비지 않으면 실제 LLM 호출 → mock 차단.
        # 검색 본문 전파는 이 후처리 뒤라 identity mock 이 전파 단언에 영향 없음.
        return translate_transcript(
            transcript, config=cfg, video_context=video_context, search_fn=search_fn
        )


def test_translate_search_on_propagates_and_persists(tmp_path, monkeypatch):
    video_context = {"title": "Search On Video"}
    result = _run_translate(
        True, _fake_search({"Kevin Wurst": "Kevin Warsh"}), monkeypatch, tmp_path, video_context
    )
    # (a) 한국어 본문 병기 교정
    assert "(Kevin Warsh)" in result
    assert "(Kevin Wurst)" not in result
    # (c)/(d) 디스크에 교정 영속 → load_stt_corrections + 재검색 마커
    assert load_stt_corrections(video_context) == {"Kevin Wurst": "Kevin Warsh"}


def test_translate_search_off_no_correction(tmp_path, monkeypatch):
    """토글 off — search_fn 줘도 검색 안 돎, 현행 그대로 (회귀 없음)."""
    video_context = {"title": "Search Off Video"}
    result = _run_translate(
        False, _fake_search({"Kevin Wurst": "Kevin Warsh"}), monkeypatch, tmp_path, video_context
    )
    assert "(Kevin Wurst)" in result  # 교정 없음
    assert "(Kevin Warsh)" not in result
    assert load_stt_corrections(video_context) == {}


def test_translate_cache_hit_reapplies_corrections(tmp_path, monkeypatch):
    """P2-A 회귀: 재처리(캐시-히트)에서 source='search' entity 는 _verify 가 건너뛰지만,
    original_english 로 stt_corrections 를 seed 해 본문 병기가 (Warsh)로 유지된다.

    수정 전(seed 없음): search_fn 이 None 만 주면 stt_corrections={} → 본문 (Kevin Wurst)
    잔존 → 단언 실패. 즉 이 테스트는 seed 수정 전 코드에서 실패한다.
    """
    video_context = {"title": "Cache Hit Reprocess"}
    # 캐시-히트 모사 — 이미 교정된 entity 가 bootstrap 으로 로드된 상태.
    cached = {"Kevin Warsh": {
        "korean": "케빈 워시", "type": "person", "source": "search",
        "original_english": "Kevin Wurst",
    }}
    spy = {"calls": 0}

    def _no_op_search(name, hint=None):
        spy["calls"] += 1  # 재검색 안 해야 함 (source=search 라 _verify 가 skip)
        return None

    result = _run_translate(
        True, _no_op_search, monkeypatch, tmp_path, video_context, bootstrap=cached
    )
    assert "(Kevin Warsh)" in result      # seed 로 본문 병기 교정 유지
    assert "(Kevin Wurst)" not in result
    assert spy["calls"] == 0              # 재검색 안 함 (마커 존중)


def test_original_script_corrects_speaker_prefix():
    """P2-B 회귀: 교정명이 화자 실명이기도 하면 영어 원문 prefix(화자명)도 교정.

    수정 전(prefix 치환 없음): prefix 가 speaker_names 의 'Kevin Wurst' 그대로 → 단언 실패.
    """
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="Kevin Wurst said hi.")],
        language="en",
    )
    md = build_original_script_section(
        transcript, language="en",
        speaker_names={"A": "Kevin Wurst"},
        stt_corrections={"Kevin Wurst": "Kevin Warsh"},
    )
    assert "**[00:00] Kevin Warsh:** Kevin Warsh said hi." in md
    assert "Kevin Wurst" not in md

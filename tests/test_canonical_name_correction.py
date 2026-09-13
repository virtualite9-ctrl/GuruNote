"""인명 통용 표기 결정론적 교정 (A 보완) — 단위 테스트.

entity_cache / speaker_cache 의 한국어 표기가 bootstrap LLM(또는 디스크 캐시)에서
"팰머 러커이" 로 고정되던 것을, 편집 가능한 통용 dict(English→한국어)로 결정론적
교정한다. dict 미수록 인명은 건드리지 않는다 (과교정 부재). LLM 호출 부재.
"""
from __future__ import annotations

from gurunote.llm import (
    _apply_canonical_to_entity_cache,
    _apply_canonical_to_speaker_cache,
)

CANON = {"Palmer Luckey": "팔머 럭키", "Rick Rieder": "릭 리더"}


def test_entity_cache_typo_corrected():
    """디스크 캐시에서 로드된 옛 표기(팰머 러커이)를 통용 표기로 강제 교정."""
    ec = {
        "Palmer Luckey": {"korean": "팰머 러커이", "type": "person", "source": "bootstrap"},
        "Rick Rieder": {"korean": "리크 리더", "type": "person", "source": "bootstrap"},
    }
    n = _apply_canonical_to_entity_cache(ec, CANON)
    assert n == 2
    assert ec["Palmer Luckey"]["korean"] == "팔머 럭키"
    assert ec["Rick Rieder"]["korean"] == "릭 리더"


def test_entity_cache_not_in_dict_untouched():
    """통용 dict 미수록 인명은 교정하지 않는다 (과교정 부재)."""
    ec = {"Demis Hassabis": {"korean": "데미스 하사비스", "type": "person"}}
    n = _apply_canonical_to_entity_cache(ec, CANON)
    assert n == 0
    assert ec["Demis Hassabis"]["korean"] == "데미스 하사비스"


def test_speaker_cache_corrected():
    """화자 라벨(본문 prefix 지배)도 같은 dict 로 교정 — Palmer Luckey 인터뷰 335회 케이스."""
    sc = {
        "A": {"english": "Palmer Luckey", "korean": "팰머 러커이"},
        "B": {"english": "Colin Demarest", "korean": "콜린 데마레스트"},
    }
    n = _apply_canonical_to_speaker_cache(sc, CANON)
    assert n == 1
    assert sc["A"]["korean"] == "팔머 럭키"
    assert sc["B"]["korean"] == "콜린 데마레스트"  # 미수록 — 불변


def test_case_insensitive_match():
    ec = {"palmer luckey": {"korean": "X", "type": "person"}}
    _apply_canonical_to_entity_cache(ec, CANON)
    assert ec["palmer luckey"]["korean"] == "팔머 럭키"


def test_speakers_marker_skipped():
    """entity_cache 의 __speakers__ 마커 키는 건드리지 않는다 (구조 다름)."""
    ec = {"__speakers__": {"A": {"english": "X", "korean": "Y"}}}
    n = _apply_canonical_to_entity_cache(ec, CANON)
    assert n == 0


def test_empty_inputs_safe():
    assert _apply_canonical_to_entity_cache({}, CANON) == 0
    assert _apply_canonical_to_entity_cache({"Palmer Luckey": {"korean": "x"}}, {}) == 0
    assert _apply_canonical_to_speaker_cache({}, CANON) == 0


def test_already_correct_no_change():
    """이미 통용 표기면 교정 건수 0 (불필요한 변경 부재)."""
    ec = {"Palmer Luckey": {"korean": "팔머 럭키", "type": "person"}}
    assert _apply_canonical_to_entity_cache(ec, CANON) == 0

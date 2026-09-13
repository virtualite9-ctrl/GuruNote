"""제목 인명 통용 표기 교정 (제목 품질) — `_correct_korean_in_annotations` 단위 테스트.

`한국어(English)` 병기에서 English key 로 통용 dict 조회 → 한국어를 dict 표기로 강제.
`_correct_english_annotations`(영문 철자 검증)와 방향 반대 — 이쪽은 한국어를 고친다.
LLM 이 인명을 오음차해도(스타니슬라프 드루킨밀러) 영문 원어로 통용 표기 복원. LLM 부재.
"""
from __future__ import annotations

from gurunote.llm import _correct_korean_in_annotations as fix

CANON = {
    "Stan Druckenmiller": {"auto": "스탠 드럭킨밀러", "user": "스탠 드러켄밀러"},
    "Jensen Huang": {"auto": "젠슨 황", "user": ""},
}


def test_mispronounced_name_corrected_user_priority():
    """오음차 한국어를 영문 key 로 통용(user) 표기로 교정."""
    out = fix("스타니슬라프 드루킨밀러(Stan Druckenmiller): 금리 전망", CANON)
    assert out == "스탠 드러켄밀러(Stan Druckenmiller): 금리 전망"


def test_auto_applied_when_no_user():
    """user 없으면 auto 적용 (이미 맞으면 변동 없음)."""
    assert fix("젠슨 황(Jensen Huang): NVIDIA", CANON) == "젠슨 황(Jensen Huang): NVIDIA"


def test_prefix_and_already_canonical_preserved():
    txt = "보너스: 경제 단어 연상 — 스탠 드러켄밀러(Stan Druckenmiller)"
    assert fix(txt, CANON) == txt


def test_not_in_dict_untouched():
    txt = "어떤 사람(Unknown Person)이 말했다"
    assert fix(txt, CANON) == txt


def test_no_annotation_no_match():
    """영문 병기 없는 음차 한국어는 매칭 불가 → 그대로 (English key 부재)."""
    txt = "스타니슬라프 드루킨밀러: 금리 전망"
    assert fix(txt, CANON) == txt


def test_empty_inputs_safe():
    assert fix("", CANON) == ""
    assert fix("스탠(Stan Druckenmiller)", {}) == "스탠(Stan Druckenmiller)"


def test_case_insensitive_english_key():
    out = fix("스타니슬라프(stan druckenmiller)", CANON)
    assert out == "스탠 드러켄밀러(stan druckenmiller)"

"""영문 병기 철자 소스 검증 (B) — `_correct_english_annotations` 단위 테스트.

LLM 이 `한국어(English)` 병기의 영문 원어를 자유 생성하다 철자를 오염시키는 문제
(예: Anduril → Danduril) 를 소스(transcript + 제목)에 실재하는 철자로 결정론적
교정/생략하는 helper. LLM 호출 부재 — 순수 함수.
"""
from __future__ import annotations

from gurunote.llm import _correct_english_annotations as fix

# 현실적 소스 corpus — transcript 전문 + 제목 (standalone 고유명사 다수).
SRC = (
    "Anduril makes autonomous drones. Anduril and Palmer Luckey left Oculus. "
    "Rick Rieder at BlackRock discussed rates. OpenAI and Anthropic compete. "
    "Schneider Electric builds AI factories."
)


def test_typo_corrected_to_source_spelling():
    """소스에 standalone 으로 있는 철자로 오타 교정 (Danduril → Anduril)."""
    assert fix("안두릴(Danduril) 발표", SRC) == "안두릴(Anduril) 발표"


def test_casing_normalized_to_source():
    """철자는 맞고 케이싱만 다르면 소스 케이싱으로 정규화 (Blackrock → BlackRock)."""
    assert fix("블랙록(Blackrock)", SRC) == "블랙록(BlackRock)"


def test_correct_multiword_name_preserved():
    """소스에 그대로 있는 다단어 인명은 보존 (과교정 부재)."""
    assert fix("팰머 럭키(Palmer Luckey)가", SRC) == "팰머 럭키(Palmer Luckey)가"
    assert fix("릭 리더(Rick Rieder)는", SRC) == "릭 리더(Rick Rieder)는"


def test_annotation_dropped_when_absent_from_source():
    """소스에 근거 없는 영문 병기는 삭제 — 틀린 철자를 박지 않는다 (한국어만 남김)."""
    assert fix("어떤회사(Foobarbaz)가", SRC) == "어떤회사가"


def test_korean_inside_parens_untouched():
    """괄호 안이 한글이면 영문 병기가 아니므로 건드리지 않는다 (OpenAI(오픈AI) 형식)."""
    assert fix("오픈AI(오픈에이아이)", SRC) == "오픈AI(오픈에이아이)"


def test_non_annotation_text_unchanged():
    """화자 라벨/timestamp/일반 본문은 불변."""
    line = "[01:23] 화자 1: 안녕하세요. 소프트웨어 이야기입니다."
    assert fix(line, SRC) == line


def test_empty_inputs_safe():
    assert fix("", SRC) == ""
    assert fix("안두릴(Anduril)", "") == "안두릴(Anduril)"


def test_no_overcorrection_of_present_name():
    """소스에 정확히 있는 단일 토큰은 fuzzy 교정 경로로 빠지지 않는다."""
    assert fix("앤트로픽(Anthropic)", SRC) == "앤트로픽(Anthropic)"

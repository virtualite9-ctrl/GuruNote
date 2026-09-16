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


class TestSubstringIsNotWordEvidence:
    """토큰이 소스 단어의 **일부**일 뿐인 경우.

    `corpus_lower` 는 소스 전문을 이어붙인 문자열이라 `in` 이 부분 문자열 검사가 된다.
    병기 "(Gen AI)" 의 토큰 "Gen" 은 소스의 "generative" 안에 들어 있어 통과했지만,
    케이싱 복원 맵은 온전한 단어로만 만들어져 "gen" 키가 없었다 → KeyError 로 작업 전체가
    죽었다. 실제 영상("Attention mechanism: Overview")에서 5분을 돌린 뒤 이 지점에서
    실패했다.
    """

    CORPUS = "Today we talk about generative AI and the attention mechanism."

    def test_partial_word_token_does_not_crash(self):
        out = fix("생성형 인공지능(Gen AI)이 온다", self.CORPUS)
        assert isinstance(out, str)
        assert "생성형 인공지능" in out

    def test_partial_word_token_is_not_accepted_as_evidence(self):
        """"Gen" 은 소스에 단어로 없다 → 규칙 3 에 따라 병기를 생략한다."""
        out = fix("생성형 인공지능(Gen AI)이 온다", self.CORPUS)
        assert "(Gen AI)" not in out
        assert "(gen" not in out.lower()

    def test_whole_word_evidence_still_works(self):
        out = fix("어텐션(Attention) 메커니즘", self.CORPUS)
        assert "attention" in out.lower()

    def test_various_partial_prefixes_are_safe(self):
        """소스 단어의 앞부분을 잘라 만든 토큰들 — 전부 죽지 않아야 한다."""
        for annotation in ("Gen AI", "Att Mechanism", "Mech AI", "Tod AI"):
            out = fix(f"어떤 한국어 말({annotation})이다", self.CORPUS)
            assert isinstance(out, str), annotation

    def test_single_token_partial_is_also_safe(self):
        """단일 토큰 경로(규칙 2)는 difflib 만 쓰므로 원래 안전하지만 함께 고정한다."""
        out = fix("생성(Gen)이다", self.CORPUS)
        assert isinstance(out, str)

"""제목·요약 CJK 후처리 (Phase 3 보완) — `post_process_cjk_text` 단위 테스트.

본문 post_process_cjk 의 Sub-path A(사전)+B(LLM 재매핑)를 재사용하되 C(영문 fallback,
segment 의존)는 제외한 segment-less 변형. 제목(extract_metadata)·요약(summarize_translation)
에 적용. 사전 적중 케이스는 LLM 미호출 결정론적이라 config 없이 검증 가능.
"""
from __future__ import annotations

from gurunote.llm import post_process_cjk_text


class _DummyConfig:
    """Sub-path A 사전에서 다 잡히면 LLM(config) 미호출 — 더미로 충분."""


CFG = _DummyConfig()


def test_title_simplified_chinese_replaced():
    """제목 leak — 谈话(간체) → 담화 (5/26 실측)."""
    out = post_process_cjk_text("달러 미래 직격谈话", CFG)
    assert out == "달러 미래 직격담화"
    assert "谈" not in out and "话" not in out


def test_summary_hanja_replaced():
    """요약 leak — 設計→설계, 評価→평가 (5/26 실측)."""
    assert post_process_cjk_text("이 設計는 좋다", CFG) == "이 설계는 좋다"
    assert post_process_cjk_text("評価가 필요하다", CFG) == "평가가 필요하다"


def test_clean_korean_untouched():
    """한자 없는 정상 한국어는 무동작 (과처리 부재, LLM 미호출)."""
    txt = "팔머 럭키는 안두릴을 설립했다."
    assert post_process_cjk_text(txt, CFG) == txt


def test_bracketed_cjk_preserved():
    """괄호 안 한자 표기는 보존 (본문 후처리와 동일 규칙)."""
    txt = "양자역학(量子力學) 설명"
    assert post_process_cjk_text(txt, CFG) == txt


def test_empty_input_safe():
    assert post_process_cjk_text("", CFG) == ""
    assert post_process_cjk_text("일반 텍스트", CFG) == "일반 텍스트"


def test_multiline_paragraphs():
    """\\n\\n 분할 — 한자 있는 단락만 처리, 나머지 보존."""
    txt = "정상 단락입니다.\n\n設計 評価 단락"
    out = post_process_cjk_text(txt, CFG)
    assert out == "정상 단락입니다.\n\n설계 평가 단락"

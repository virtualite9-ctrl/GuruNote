"""요약 섹션 충실도 (5/28) — `summarize_translation` 출력에 dict 인명 교정 적용 검증.

요약 LLM 이 본문 표기('스탠 드러켄밀러')를 자율 변형('스턴 드러켄밀러')해도,
요약 결과의 `한국어(English)` 병기를 영문 key 로 통용 dict 조회해 결정론적으로 통일한다.
프롬프트(환각·영어 leak·인명 일관 조항)는 확률적이라 단위 테스트 부재 — LLM 출력 mock 으로
후처리(결정론)만 검증한다.
"""
from __future__ import annotations

import gurunote.llm as llm
from gurunote.llm import LLMConfig, summarize_translation

CFG = LLMConfig(provider="openai", model="dummy", api_key="dummy")

CANON = {
    "Stan Druckenmiller": {"auto": "스탠 드럭킨밀러", "user": "스탠 드러켄밀러"},
}


def _patch(monkeypatch, summary_text: str):
    """요약 LLM 응답을 고정하고 통용 dict 를 주입."""
    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: summary_text)
    monkeypatch.setattr(llm, "_load_canonical_names", lambda: CANON)


def test_summary_name_unified_to_dict(monkeypatch):
    """요약이 본문과 다른 음차('스턴')를 써도 dict 통용 표기('스탠')로 교정."""
    summary = (
        "# 📌 영상 제목 및 핵심 주제 요약\n"
        "- 스턴 드러켄밀러(Stan Druckenmiller)가 금리 전망을 논한다."
    )
    _patch(monkeypatch, summary)
    out = summarize_translation("본문 번역본", title="제목", config=CFG)
    assert "스탠 드러켄밀러(Stan Druckenmiller)" in out
    assert "스턴 드러켄밀러" not in out


def test_summary_already_canonical_untouched(monkeypatch):
    """이미 통용 표기면 변동 없음 (과교정 부재)."""
    summary = "- 스탠 드러켄밀러(Stan Druckenmiller)는 매크로 투자자다."
    _patch(monkeypatch, summary)
    out = summarize_translation("본문", title="제목", config=CFG)
    assert out == summary


def test_summary_no_annotation_unchanged(monkeypatch):
    """영문 병기 없는 인명은 매칭 불가 → 그대로 (English key 부재)."""
    summary = "- 스턴 드러켄밀러는 금리 전망을 논한다."
    _patch(monkeypatch, summary)
    out = summarize_translation("본문", title="제목", config=CFG)
    assert out == summary

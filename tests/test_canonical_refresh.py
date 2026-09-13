"""노트 통용 표기 새로고침 (A-2 ③) — `refresh_canonical_in_markdown` 단위 테스트.

완성된 노트(md)의 auto 표기를 user 표기로 텍스트 치환. auto·user 둘 다 있는 항목만.
일반형 + 태그 언더스코어형. 단일 패스 정규식이라 연쇄 치환 없음. 영어 원문은 auto 가
한국어라 자동 무영향. LLM/파일 I/O 부재 — 순수 함수.
"""
from __future__ import annotations

from gurunote.llm import refresh_canonical_in_markdown as fix

CANON = {
    "Palmer Luckey": {"auto": "팰머 러커이", "user": "팔머 럭키"},  # 둘 다 → 대상
    "Sam Altman": {"auto": "샘 알트만", "user": ""},                # auto 만 → skip
    "Rick Rieder": {"auto": "", "user": "릭 리더"},                  # user 만 → skip
}

NOTE = """---
title: "팰머 러커이(Palmer Luckey) 인터뷰"
tags: ["팰머_러커이", "AI"]
---
[00:17] 팰머 러커이(Palmer Luckey): 안녕하세요.
[00:22] 팰머 러커이: 네.
샘 알트만(Sam Altman)도 언급.
# 🇺🇸 원문 스크립트 (English)
Palmer Luckey: Hello. Palmer Luckey and Anduril."""


def test_only_auto_and_user_present_replaced():
    _, n = fix(NOTE, CANON)
    assert n == 1  # Palmer 만 (Sam=auto만, Rick=user만 → skip)


def test_all_korean_forms_replaced():
    new, _ = fix(NOTE, CANON)
    assert "팔머 럭키(Palmer Luckey): 안녕하세요." in new   # 병기 + 화자 라벨
    assert "[00:22] 팔머 럭키: 네." in new                  # 단독 화자 라벨
    assert '"팔머 럭키(Palmer Luckey) 인터뷰"' in new        # 제목
    assert "팰머 러커이" not in new                          # 옛 한국어 표기 잔존 없음


def test_tag_underscore_form():
    new, _ = fix(NOTE, CANON)
    assert "팔머_럭키" in new and "팰머_러커이" not in new


def test_english_section_untouched():
    """auto 가 한국어라 영어 원문/제목/병기의 영어는 그대로."""
    new, _ = fix(NOTE, CANON)
    assert "Palmer Luckey: Hello. Palmer Luckey and Anduril." in new
    assert "(Palmer Luckey)" in new  # 병기 영문 보존


def test_auto_only_and_user_only_skipped():
    new, _ = fix(NOTE, CANON)
    assert "샘 알트만(Sam Altman)" in new  # auto 만 → 변경 없음


def test_no_chained_replacement():
    """단일 패스 — 삽입된 user 텍스트 안의 부분이 재치환되지 않는다."""
    canon = {"A": {"auto": "가", "user": "나다"}, "B": {"auto": "나", "user": "X"}}
    new, _ = fix("가 나", canon)
    # 가→나다 (삽입된 '나다' 안의 '나'는 재치환 안 됨), 원본 standalone '나'→X
    assert new == "나다 X"


def test_empty_and_no_targets():
    assert fix("", CANON) == ("", 0)
    assert fix("내용", {}) == ("내용", 0)
    # 대상 없음 (전부 한쪽만) → 원본 그대로
    md = "팰머 러커이 등장"
    assert fix(md, {"X": {"auto": "에이", "user": ""}}) == (md, 0)


def test_no_change_when_already_user():
    """노트가 이미 user 표기면 auto 가 없으니 변경 0."""
    md = "[00:01] 팔머 럭키: 안녕"
    new, n = fix(md, CANON)
    assert n == 0 and new == md

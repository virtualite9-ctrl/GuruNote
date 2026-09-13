"""본문 라인 레벨 연속 반복 축약 (C) — `_collapse_repeated_lines` 단위 테스트.

더듬거림 구간을 2-pass 2단계가 같은 문장으로 채우는 회귀 차단. 같은 화자 + 같은
텍스트가 N회+(_DEDUP_MIN_RUN) 연속이고 텍스트가 충분히 길면(_DEDUP_MIN_LEN자+) 첫
라인만 남긴다. 짧은 발화·다른 화자 동일 발화·marker 는 보존 (실데이터 임계 근거).
"""
from __future__ import annotations

from gurunote.llm import _collapse_repeated_lines as fix


def _lines(text, n, ts0=0):
    return "\n\n".join(f"[00:{ts0 + i:02d}] 화자 1: {text}" for i in range(n))


def test_long_repeat_collapsed_to_one():
    md = _lines("모두 이것이 바보 같은 짓이라고 했습니다.", 16)
    out = fix(md)
    assert out.count("바보 같은 짓이라고 했습니다") == 1
    # 첫 timestamp 유지
    assert out.startswith("[00:00] 화자 1: 모두 이것이")


def test_short_utterance_preserved():
    """짧은 발화(< 10자)는 연속 5회여도 보존 (동의/감사 정상 반복)."""
    md = _lines("맞습니다.", 5)
    assert fix(md).count("맞습니다.") == 5


def test_nine_char_boundary_preserved():
    """경계 — 9자 3회는 임계(10자) 미만이라 보존."""
    md = _lines("네, 감사합니다.", 3)  # 9자
    assert fix(md).count("감사합니다") == 3


def test_different_speaker_same_text_preserved():
    """다른 화자가 같은 긴 문장을 번갈아 말하면 연속 아님 → 보존."""
    md = (
        "[00:01] 화자 1: 정말 흥미로운 통찰이라고 생각합니다.\n\n"
        "[00:02] 화자 2: 정말 흥미로운 통찰이라고 생각합니다.\n\n"
        "[00:03] 화자 1: 정말 흥미로운 통찰이라고 생각합니다."
    )
    assert fix(md).count("흥미로운 통찰") == 3


def test_marker_lines_preserved():
    """[번역 누락]/[⚠ timeout] 등 marker 연속은 축약 대상 아님."""
    assert fix(_lines("[번역 누락]", 4)).count("[번역 누락]") == 4
    assert fix(_lines("[⚠ timeout]", 4)).count("[⚠ timeout]") == 4


def test_two_long_repeats_below_run_threshold_preserved():
    """긴 문장이라도 2회 연속(< 3회)이면 보존 (정상 강조 반복 여지)."""
    md = _lines("이것은 매우 중요한 지적이라고 봅니다.", 2)
    assert fix(md).count("중요한 지적") == 2


def test_normal_body_unchanged():
    md = "[00:00] 화자 1: 안녕하세요.\n\n[00:05] 화자 2: 반갑습니다. 오늘 주제는 인공지능입니다."
    assert fix(md) == md


def test_collapse_then_continues():
    """축약 후 뒤따르는 다른 라인은 그대로 이어진다."""
    md = _lines("같은 긴 문장을 계속 반복합니다 여기.", 5) + "\n\n[00:30] 화자 1: 이제 다른 말을 합니다."
    out = fix(md)
    assert out.count("같은 긴 문장") == 1
    assert "이제 다른 말을 합니다." in out


def test_empty_safe():
    assert fix("") == ""

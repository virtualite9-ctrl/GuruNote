"""Phase 3 한자/일본어 후처리 단위 + 통합 테스트.

테스트 클래스:
    TestCJKDetection         — 정규식 검출 + 괄호 안 한자 예외
    TestSubPathA             — 사전 lookup (결정론)
    TestSubPathBMock         — LLM 재매핑 mock retry 흐름
    TestSubPathC             — 영문 fallback + inline 태그
    TestIntegration          — Sub-A → B → C 전체 흐름
    TestSubPathBIntegration  — 실제 omlx 호출 (slow marker)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from gurunote.llm import (
    _apply_cjk_dict_lookup,
    _detect_cjk_outside_brackets,
    _llm_remap_cjk,
    _load_cjk_lookup,
    post_process_cjk,
)


# =============================================================================
# TestCJKDetection — 정규식 검출 + 괄호 예외
# =============================================================================
class TestCJKDetection:
    def test_detect_simple_hanzi(self):
        residue = _detect_cjk_outside_brackets("我们")
        assert residue == ["我", "们"]

    def test_detect_simple_hiragana(self):
        residue = _detect_cjk_outside_brackets("ます")
        assert residue == ["ま", "す"]

    def test_detect_katakana(self):
        residue = _detect_cjk_outside_brackets("コンピュータ")
        assert len(residue) > 0
        # 모든 검출 문자가 입력 안에 존재
        for ch in residue:
            assert ch in "コンピュータ"

    def test_bracketed_hanzi_excluded(self):
        residue = _detect_cjk_outside_brackets("양자역학(量子力學)")
        assert residue == []

    def test_mixed_bracketed_and_unbracketed(self):
        residue = _detect_cjk_outside_brackets("我们는 양자(量子)다")
        # 괄호 밖의 我, 们 만 검출
        assert residue == ["我", "们"]

    def test_korean_only(self):
        residue = _detect_cjk_outside_brackets("안녕하세요 여러분")
        assert residue == []

    def test_english_only(self):
        residue = _detect_cjk_outside_brackets("Hello world, this is English.")
        assert residue == []

    def test_mixed_korean_english(self):
        residue = _detect_cjk_outside_brackets("Hello 안녕 World 세계")
        assert residue == []


# =============================================================================
# TestSubPathA — 사전 lookup (결정론)
# =============================================================================
class TestSubPathA:
    @pytest.fixture(scope="class")
    def lookup(self):
        return _load_cjk_lookup()

    def test_lookup_chinese_compound(self, lookup):
        result = _apply_cjk_dict_lookup("我认为 좋다", lookup)
        assert "我认为" not in result
        assert "저는 ~라고 생각합니다" in result

    def test_lookup_chinese_zhenshi(self, lookup):
        # "正是" multi 매핑
        result = _apply_cjk_dict_lookup("그것 正是 답", lookup)
        assert "正是" not in result
        assert "바로 그것" in result

    def test_lookup_japanese_compound(self, lookup):
        result = _apply_cjk_dict_lookup("取り組んでいる", lookup)
        assert "取り組んでいる" not in result
        assert "다루고 있다" in result

    def test_lookup_humanoid(self, lookup):
        result = _apply_cjk_dict_lookup("机器人이 작동", lookup)
        assert "机器人" not in result
        assert "로봇" in result

    def test_longer_match_priority(self, lookup):
        # "我认为" (3자) 가 "我" (1자) single 보다 우선 매칭
        result = _apply_cjk_dict_lookup("我认为", lookup)
        assert "저는 ~라고 생각합니다" in result
        # single 의 "我" → "나" 가 잔존 부재 (multi 가 먼저 처리)
        assert "我" not in result
        assert "나" not in result  # single 으로 떨어지지 않음 확인

    def test_no_match_returns_unchanged_or_partial(self, lookup):
        # "高血压" 는 yaml 부재 (의료 미등록 케이스)
        result = _apply_cjk_dict_lookup("高血压", lookup)
        # 高, 血, 压 single 부재 → 변경 부재
        assert result == "高血压"

    def test_bracketed_preserved(self, lookup):
        result = _apply_cjk_dict_lookup("양자역학(量子力學)을 다루다", lookup)
        # 괄호 안 보존 정합
        assert "(量子力學)" in result

    def test_multiple_replacements(self, lookup):
        result = _apply_cjk_dict_lookup("我们对吧", lookup)
        # "我们" → "우리", "对吧" → "맞죠"
        assert "我们" not in result
        assert "对吧" not in result
        assert "우리" in result
        assert "맞죠" in result

    def test_residue_after_subpath_a(self, lookup):
        # Sub-A 가 부분만 처리 가능한 케이스 — 본인 5/17 측정 패턴
        # "我认为很重要" → "我认为" + "重要" 처리, "很" 잔존
        result = _apply_cjk_dict_lookup("我认为很重要", lookup)
        residue = _detect_cjk_outside_brackets(result)
        # "我认为" + "重要" 처리됨, "很" single_char 부재로 잔존
        assert "我认为" not in result
        assert "重要" not in result
        assert "很" in residue


# =============================================================================
# TestSubPathBMock — LLM 재매핑 (mock)
# =============================================================================
class TestSubPathBMock:
    def test_llm_mock_success_first_try(self, mock_llm_config):
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "이것은 깨끗한 한국어입니다"
            result = _llm_remap_cjk("我认为 some text", mock_llm_config, max_retries=3)
            assert result == "이것은 깨끗한 한국어입니다"
            assert mock_call.call_count == 1

    def test_llm_mock_retry_then_success(self, mock_llm_config):
        # 첫 2회 한자 잔재, 3회차 한국어 정합
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.side_effect = [
                "여전히 我们 잔재",
                "또 잔재 对吧",
                "마지막으로 깨끗한 한국어",
            ]
            result = _llm_remap_cjk("我们 입력", mock_llm_config, max_retries=3)
            assert result == "마지막으로 깨끗한 한국어"
            assert mock_call.call_count == 3

    def test_llm_mock_all_fail_returns_none(self, mock_llm_config):
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "잔재 我们 한자 잔존"
            result = _llm_remap_cjk("입력 我们", mock_llm_config, max_retries=3)
            assert result is None
            assert mock_call.call_count == 3

    def test_llm_mock_exception_then_success(self, mock_llm_config):
        # 첫 호출 예외 → 두 번째 한국어 정합
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.side_effect = [
                RuntimeError("network fail"),
                "깨끗한 한국어 결과",
            ]
            result = _llm_remap_cjk("입력 我们", mock_llm_config, max_retries=3)
            assert result == "깨끗한 한국어 결과"
            assert mock_call.call_count == 2

    def test_llm_mock_max_retries_respected(self, mock_llm_config):
        # max_retries=1 — 1회만 호출
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "여전히 我们 잔재"
            result = _llm_remap_cjk("입력", mock_llm_config, max_retries=1)
            assert result is None
            assert mock_call.call_count == 1


# =============================================================================
# TestSubPathC — 영문 fallback + inline 태그
# =============================================================================
class TestSubPathC:
    def test_fallback_appended_inline_tag(self, mock_llm_config, sample_segments):
        # Sub-B 가 3회 모두 잔재 반환 → Sub-C 발동
        input_text = "[02:15] 화자 A: 这是完全的中文文本难以翻译"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "여전히 中文 잔재"
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        # 영문 원문 등장 + [⚠ fallback] 태그
        assert "This is the first English segment." in result
        assert "[⚠ fallback]" in result
        # speaker 라벨 보존
        assert "화자 A:" in result
        # timestamp 보존
        assert "[02:15]" in result

    def test_no_segment_match_residue_preserved(self, mock_llm_config):
        # segments 부재 → Sub-C 진입 부재, 원본 잔재 잔존
        input_text = "[99:59] Unknown: 这是中文"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "여전히 中文"
            result = post_process_cjk(input_text, [], mock_llm_config)
        # 원본 잔존 (Sub-C segment 매칭 실패)
        assert "[99:59]" in result
        # [⚠ fallback] 태그 부재
        assert "[⚠ fallback]" not in result

    def test_multiple_segments_correct_lookup(self, mock_llm_config, sample_segments):
        # [05:30] 발화 → sample_segments 의 두 번째 (start=330.0)
        input_text = "[05:30] 화자 B: 中文 잔재 텍스트"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "여전히 中文"
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        # 두 번째 segment 의 영문 원문 등장
        assert "Second segment with longer English content." in result
        assert "[⚠ fallback]" in result


# =============================================================================
# TestIntegration — Sub-A → B → C 전체 흐름
# =============================================================================
class TestIntegration:
    def test_dict_only_clean(self, mock_llm_config, sample_segments):
        """Sub-A 만으로 한자 0건 — Sub-B 호출 부재."""
        input_text = "[02:15] 화자 A: 我们 정합"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        # Sub-B 호출 부재
        assert mock_call.call_count == 0
        # Sub-A 결과 적용
        assert "我们" not in result
        assert "우리" in result

    def test_dict_then_llm_first_try(self, mock_llm_config, sample_segments):
        """Sub-A 미적중 → Sub-B 첫 시도 정합."""
        input_text = "[02:15] 화자 A: 高血压 미등록"  # yaml 부재 패턴
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "깨끗한 한국어 출력"
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        assert mock_call.call_count == 1
        # Sub-B 결과로 part 가 완전 치환
        assert result == "깨끗한 한국어 출력"

    def test_dict_llm_fallback_to_c(self, mock_llm_config, sample_segments):
        """Sub-A 미적중 + Sub-B 3회 모두 실패 → Sub-C fallback."""
        input_text = "[02:15] 화자 A: 这是难以翻译的中文文本"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "여전히 中文 잔재"
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        # Sub-B 3회 호출
        assert mock_call.call_count == 3
        # Sub-C 영문 fallback
        assert "This is the first English segment." in result
        assert "[⚠ fallback]" in result

    def test_no_cjk_no_processing(self, mock_llm_config, sample_segments):
        """CJK 0건 입력 → 후처리 미발동, 결과 동일."""
        input_text = "[02:15] 화자 A: 깨끗한 한국어 입력입니다"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        assert mock_call.call_count == 0
        assert result == input_text

    def test_multiple_parts_mixed(self, mock_llm_config, sample_segments):
        """\\n\\n 으로 join 된 multi-part 입력 — 각 part 별 처리."""
        input_text = (
            "[02:15] 화자 A: 我们\n\n"
            "[05:30] 화자 B: 깨끗한 한국어\n\n"
            "[10:00] 화자 A: 对吧"
        )
        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = post_process_cjk(input_text, sample_segments, mock_llm_config)
        # 모두 Sub-A 만으로 처리됨 → Sub-B 호출 부재
        assert mock_call.call_count == 0
        # 3 parts 가 \\n\\n 으로 보존
        assert "\n\n" in result
        assert "우리" in result
        assert "깨끗한 한국어" in result
        assert "맞죠" in result


# =============================================================================
# TestSubPathBIntegration — 실제 omlx 호출 (slow marker)
# =============================================================================
@pytest.mark.slow
class TestSubPathBIntegration:
    """실제 omlx 호출 — `pytest -m slow` 로만 실행. .env 로딩 + endpoint 존재 전제."""

    def test_real_llm_remap_simple_chinese(self, real_llm_config):
        # 단순 한자 잔재 입력 → 실제 LLM 호출 → 한국어 결과 정합
        input_text = "오늘 我们 함께 작업했다"
        result = _llm_remap_cjk(input_text, real_llm_config, max_retries=3)
        assert result is not None, "실제 LLM 호출 부재 (None 반환)"
        assert not _detect_cjk_outside_brackets(result), f"잔재 잔존: {result!r}"

    def test_real_llm_preserves_brackets(self, real_llm_config):
        # 괄호 안 한자 표기는 보존
        input_text = "양자역학(量子力學)에 대한 我们的 토론"
        result = _llm_remap_cjk(input_text, real_llm_config, max_retries=3)
        if result is None:
            pytest.skip("실제 LLM 호출 부재 (None 반환)")
        # 괄호 안 한자 표기 유지 정합
        assert "(量子力學)" in result, f"괄호 안 표기 손실: {result!r}"

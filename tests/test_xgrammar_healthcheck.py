"""omlx xgrammar 사전 점검 + thinking_budget 송신 단위 테스트 (5/23).

배경:
    omlx 0.3.8→0.3.9 업그레이드가 xgrammar 모듈 제거 → schema strict 무시 → 전체
    chunk timeout 다발 (5/22~5/23 4개 모델 비교에서 27b 모델 두 개 case catch).
    GuruNote 가 사전 점검하여 부재 시 RuntimeError + 복구 안내.

캐싱:
    `/v1/models` 응답의 `created` (서버 시작 시점 단일값) 를 signature 로 사용 →
    omlx 재시작 정확 감지. 6시간 TTL fallback.

cache 격리:
    conftest 의 `_reset_xgrammar_check_cache` autouse fixture 가 매 test 시작 시
    `_XGRAMMAR_CHECK_CACHE` 초기화.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import gurunote.llm as _llm
from gurunote.llm import (
    _XGRAMMAR_CHECK_CACHE,
    _XGRAMMAR_CHECK_TTL_SEC,
    _check_xgrammar_available,
)


@pytest.fixture
def mock_cfg():
    """openai_compatible mock LLMConfig — 본 test 전용."""
    from gurunote.llm import LLMConfig
    return LLMConfig(
        provider="openai_compatible",
        model="mock-model",
        api_key="mock-key",
        base_url="http://mock.local/v1",
    )


# =============================================================================
# TestXgrammarHealthcheck — 점검 함수 동작
# =============================================================================
class TestXgrammarHealthcheck:
    def test_returns_true_on_valid_json(self, mock_cfg):
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = "1779000000"
            mock_call.return_value = ('{"ok": "yes"}', "stop")
            result = _check_xgrammar_available(mock_cfg)
        assert result is True
        assert _XGRAMMAR_CHECK_CACHE["result"] is True

    def test_returns_false_on_exception(self, mock_cfg):
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = "1779000000"
            mock_call.side_effect = RuntimeError("xgrammar absent")
            result = _check_xgrammar_available(mock_cfg)
        assert result is False
        assert _XGRAMMAR_CHECK_CACHE["result"] is False

    def test_returns_false_on_invalid_json(self, mock_cfg):
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = "1779000000"
            mock_call.return_value = ("not valid json", "stop")
            result = _check_xgrammar_available(mock_cfg)
        assert result is False

    def test_skips_check_for_non_openai_provider(self, mock_cfg):
        # provider 가 openai_compatible 부재 시 즉시 True (점검 대상 부재)
        from gurunote.llm import LLMConfig
        cfg_anthropic = LLMConfig(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key="mock",
        )
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            result = _check_xgrammar_available(cfg_anthropic)
        assert result is True
        assert mock_call.call_count == 0  # LLM 호출 부재


# =============================================================================
# TestCacheBehavior — signature + TTL invalidate
# =============================================================================
class TestCacheBehavior:
    def test_cache_hit_skips_call(self, mock_cfg):
        # 1회 호출 후 같은 signature + TTL 내 → 2회 호출 시 LLM 호출 부재
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = "1779000000"
            mock_call.return_value = ('{"ok": "yes"}', "stop")
            _check_xgrammar_available(mock_cfg)
            _check_xgrammar_available(mock_cfg)
            _check_xgrammar_available(mock_cfg)
        # signature catch 는 매 호출, LLM 호출은 1회만 (캐시 hit)
        assert mock_call.call_count == 1

    def test_cache_invalidate_on_signature_change(self, mock_cfg):
        # signature 변경 (omlx 재시작) → 재확인
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.side_effect = ["1779000000", "1779999999"]  # 재시작
            mock_call.return_value = ('{"ok": "yes"}', "stop")
            _check_xgrammar_available(mock_cfg)
            _check_xgrammar_available(mock_cfg)
        # signature 다름 → 재확인 → LLM 호출 2회
        assert mock_call.call_count == 2

    def test_cache_invalidate_on_ttl_expiry(self, mock_cfg):
        # TTL 초과 → 재확인
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = "1779000000"
            mock_call.return_value = ('{"ok": "yes"}', "stop")
            _check_xgrammar_available(mock_cfg)
            # checked_at 을 TTL 이전 시점으로 강제
            _llm._XGRAMMAR_CHECK_CACHE["checked_at"] = time.time() - _XGRAMMAR_CHECK_TTL_SEC - 10
            _check_xgrammar_available(mock_cfg)
        assert mock_call.call_count == 2

    def test_signature_none_skips_cache_hit(self, mock_cfg):
        # signature None (omlx 접근 실패) 시 cache hit 부재 (재확인 진입)
        with patch("gurunote.llm.client._get_omlx_signature") as mock_sig, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_sig.return_value = None
            mock_call.return_value = ('{"ok": "yes"}', "stop")
            _check_xgrammar_available(mock_cfg)
            _check_xgrammar_available(mock_cfg)
        assert mock_call.call_count == 2


# =============================================================================
# TestTranslateTranscriptIntegration — xgrammar 부재 시 RuntimeError
# =============================================================================
class TestTranslateTranscriptIntegration:
    def test_raises_runtime_error_on_xgrammar_absent(self, mock_cfg):
        from gurunote.llm import translate_transcript
        from gurunote.types import Segment, Transcript
        seg = Segment(speaker="A", start=0.0, end=1.0, text="hello")
        transcript = Transcript(segments=[seg], language="en", engine="mlx")
        with patch("gurunote.llm.client._check_xgrammar_available") as mock_check:
            mock_check.return_value = False
            with pytest.raises(RuntimeError) as exc_info:
                translate_transcript(transcript, config=mock_cfg)
        msg = str(exc_info.value)
        assert "xgrammar" in msg
        assert "복구" in msg


# =============================================================================
# TestThinkingBudget — _call_llm + _call_llm_once_with_reason 송신 catch
# =============================================================================
class TestThinkingBudget:
    def test_call_llm_sends_thinking_budget_zero(self, mock_cfg):
        from gurunote.llm import _call_llm
        with patch("openai.OpenAI") as mock_openai_cls:
            mock_client = mock_openai_cls.return_value
            mock_completion = mock_client.chat.completions.create.return_value
            mock_completion.choices = [
                type("C", (), {
                    "message": type("M", (), {"content": "안녕"})(),
                    "finish_reason": "stop",
                })()
            ]
            _call_llm(mock_cfg, "sys", "user", max_tokens=100)
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        # extra_body 안에 thinking_budget=0 catch
        extra = call_kwargs.get("extra_body", {})
        assert extra.get("thinking_budget") == 0

    def test_call_llm_once_with_reason_sends_thinking_budget(self, mock_cfg):
        from gurunote.llm import _call_llm_once_with_reason
        with patch("openai.OpenAI") as mock_openai_cls, \
             patch("gurunote.llm.client._call_with_wall_clock_timeout") as mock_wrap:
            mock_client = mock_openai_cls.return_value  # noqa: F841
            mock_resp = type("R", (), {
                "choices": [type("C", (), {
                    "message": type("M", (), {"content": '{"outputs":["x"]}'})(),
                    "finish_reason": "stop",
                })()],
            })
            mock_wrap.return_value = mock_resp
            _call_llm_once_with_reason(mock_cfg, [{"role": "user", "content": "x"}], 100)
            # wall_clock_timeout 에 넘긴 kwargs catch
            forwarded = mock_wrap.call_args.kwargs
        extra = forwarded.get("extra_body", {})
        assert extra.get("thinking_budget") == 0

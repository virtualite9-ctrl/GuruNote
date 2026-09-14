"""B02 slow chunk wall-clock timeout 단위 테스트.

Phase 4a-1 httpx read timeout 의 한계 (streaming read 시 wall-clock 부재) 차단.
ThreadPoolExecutor + future.result(timeout) 으로 sync 함수의 wall-clock 강제 catch.
B02 한계 1 보완 (5/22): timeout 후 R1 padding fallback — TIMEOUT_PADDING_MARKER.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from gurunote.llm import (
    DEFAULT_LLM_CHUNK_TIMEOUT_SEC,
    TIMEOUT_PADDING_MARKER,
    _call_llm_with_index_mapping,
    _call_with_wall_clock_timeout,
)


class TestDefaultTimeout:
    def test_default_value_is_60(self):
        assert DEFAULT_LLM_CHUNK_TIMEOUT_SEC == 60.0


class TestWallClockTimeout:
    def test_fast_call_returns_normally(self):
        # 빠른 호출 → 정상 return
        result = _call_with_wall_clock_timeout(lambda x: x * 2, 1.0, 21)
        assert result == 42

    def test_slow_call_raises_timeout(self):
        # 2초 sleep + 0.3초 timeout → TimeoutError raise
        with pytest.raises(TimeoutError) as exc_info:
            _call_with_wall_clock_timeout(time.sleep, 0.3, 2.0)
        # 메시지에 timeout 값 catch
        assert "0.3" in str(exc_info.value)
        assert "B02" in str(exc_info.value)

    def test_timeout_message_includes_seconds(self):
        with pytest.raises(TimeoutError) as exc_info:
            _call_with_wall_clock_timeout(time.sleep, 0.1, 1.0)
        msg = str(exc_info.value)
        assert "wall-clock timeout" in msg
        assert "0.1초" in msg

    def test_function_exception_propagates(self):
        # fn 자체가 raise → 본 exception 그대로 propagate (TimeoutError 부재)
        def raising_fn():
            raise ValueError("inner error")

        with pytest.raises(ValueError) as exc_info:
            _call_with_wall_clock_timeout(raising_fn, 1.0)
        assert "inner error" in str(exc_info.value)

    def test_args_kwargs_passed_correctly(self):
        # *args + **kwargs 모두 fn 에 전달
        def fn(a, b, c=None, d=None):
            return (a, b, c, d)

        result = _call_with_wall_clock_timeout(fn, 1.0, 1, 2, c=3, d=4)
        assert result == (1, 2, 3, 4)

    def test_return_value_passthrough(self):
        # complex return (dict, list 등) 그대로 통과
        complex_obj = {"key": [1, 2, {"nested": True}]}
        result = _call_with_wall_clock_timeout(lambda: complex_obj, 1.0)
        assert result == complex_obj

    def test_zero_timeout_raises_immediately(self):
        # 매우 짧은 timeout → 즉시 TimeoutError
        with pytest.raises(TimeoutError):
            _call_with_wall_clock_timeout(time.sleep, 0.01, 1.0)

    def test_long_timeout_allows_completion(self):
        # 긴 timeout → 짧은 sleep 완료 catch
        start = time.time()
        result = _call_with_wall_clock_timeout(
            lambda: (time.sleep(0.05), "done")[1], 5.0
        )
        elapsed = time.time() - start
        assert result == "done"
        assert elapsed < 1.0  # 5초 기다리지 않음


# =============================================================================
# B02 한계 1 R2 (5/23) — timeout strict retry + 3회 모두 timeout 시 padding fallback
# =============================================================================
# 의도 변경: R1(즉시 padding, retry 부재) → R2(strict retry 후 fallback)
# 배경: f314d6e 가 timeout 90초 즉시 차단 → retry 토대 마련. 간헐적 폭주 chunk 복구.
class TestTimeoutRetryR2:
    def _mock_cfg(self):
        from gurunote.llm import LLMConfig
        return LLMConfig(
            provider="openai_compatible",
            model="mock-model",
            api_key="mock-key",
            base_url="http://mock.local/v1",
        )

    def test_three_consecutive_timeouts_fallback_to_timeout_marker(self):
        # R2 — 3회 모두 timeout 시 [⚠ timeout] marker 로 fallback
        cfg = self._mock_cfg()
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = TimeoutError("LLM 호출 wall-clock timeout — 60.0초 초과 (B02)")
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=15, max_retries=3
            )
        # 모두 TIMEOUT_PADDING_MARKER 로 padding (마지막 시도 timeout → marker 결정)
        assert all(o == TIMEOUT_PADDING_MARKER for o in outputs)
        assert len(outputs) == 15

    def test_timeout_triggers_retry_not_immediate_padding(self):
        # R2 핵심 — timeout 시 즉시 padding 부재, retry 진입 (max_retries 만큼 호출)
        cfg = self._mock_cfg()
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = TimeoutError("timeout")
            _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=10, max_retries=3
            )
        # R1 (이전): 즉시 padding → 1회만 호출
        # R2 (현행): retry 3회 진입
        assert mock_call.call_count == 3

    def test_timeout_then_success_recovers(self):
        # R2 본질 의도 — 1회 timeout 후 2회차 정상 → 정상 출력 복구
        import json as _json
        cfg = self._mock_cfg()
        valid_outputs = [f"item_{i}" for i in range(5)]
        valid_json = _json.dumps({"outputs": valid_outputs}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = [
                TimeoutError("timeout"),
                (valid_json, "stop"),
            ]
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=5, max_retries=3
            )
        # padding 부재 + 정상 outputs 복구
        assert outputs == valid_outputs
        assert mock_call.call_count == 2

    def test_two_timeouts_then_success_recovers(self):
        # R2 — 2회 연속 timeout 후 3회차 정상 → 정상 출력 복구 (max_retries 한계 안)
        import json as _json
        cfg = self._mock_cfg()
        valid_outputs = ["a", "b", "c"]
        valid_json = _json.dumps({"outputs": valid_outputs}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = [
                TimeoutError("timeout"),
                TimeoutError("timeout"),
                (valid_json, "stop"),
            ]
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=3, max_retries=3
            )
        assert outputs == valid_outputs
        assert mock_call.call_count == 3

    def test_json_fail_then_timeout_uses_timeout_marker(self):
        # 마지막 시도가 timeout 이면 marker = [⚠ timeout] (last_error_was_timeout 추적 catch)
        cfg = self._mock_cfg()
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = [
                ("invalid json", "stop"),
                ("invalid json", "stop"),
                TimeoutError("timeout"),
            ]
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=4, max_retries=3
            )
        # 3회 모두 실패, 마지막 timeout → [⚠ timeout] padding
        assert all(o == TIMEOUT_PADDING_MARKER for o in outputs)

    def test_timeout_then_json_fail_uses_translation_missing_marker(self):
        # 마지막 시도가 JSON 실패면 marker = [번역 누락] (timeout 부재로 reset 정합)
        cfg = self._mock_cfg()
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = [
                TimeoutError("timeout"),
                ("invalid json", "stop"),
                ("invalid json", "stop"),
            ]
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=4, max_retries=3
            )
        # 마지막이 JSON 실패 → [번역 누락] marker (timeout marker 부재)
        assert all(o == "[번역 누락]" for o in outputs)
        assert all(o != TIMEOUT_PADDING_MARKER for o in outputs)

    def test_timeout_marker_distinct_from_translation_missing(self):
        # TIMEOUT_PADDING_MARKER 가 일반 "[번역 누락]" 과 구분
        assert TIMEOUT_PADDING_MARKER != "[번역 누락]"
        assert TIMEOUT_PADDING_MARKER == "[⚠ timeout]"


# =============================================================================
# B02 한계 1 수정 (5/23) — manual shutdown(wait=False) 즉시 raise 검증
# =============================================================================
class TestImmediateRaiseOnTimeout:
    """5/23 수정: `with ThreadPoolExecutor` 의 shutdown(wait=True) 결함 catch.

    수정 전: timeout 후 thread 완료까지 대기 → 실질 wall-clock 부재 (964초 폭주).
    수정 후: manual shutdown(wait=False) → caller 즉시 raise.

    본 test 는 wall-clock 측정으로 결함 catch — 매우 긴 sleep 의 fn 을 짧은 timeout 으로
    호출 시 caller 가 timeout 직후 즉시 진입하는지 검증.
    """

    def test_caller_returns_immediately_on_timeout(self):
        # 매우 긴 sleep (10초) + 짧은 timeout (0.5초) → caller 가 ~0.5초 안에 raise 받음
        start = time.time()
        with pytest.raises(TimeoutError):
            _call_with_wall_clock_timeout(time.sleep, 0.5, 10.0)
        elapsed = time.time() - start
        # 수정 전: ~10초 대기 (with 블록 shutdown wait=True 결함)
        # 수정 후: ~0.5초에 즉시 raise (manual shutdown wait=False)
        assert elapsed < 2.0, (
            f"caller 가 timeout 후 즉시 진입 부재 — elapsed={elapsed:.2f}s "
            f"(with 블록 shutdown(wait=True) 결함 의심)"
        )

    def test_very_long_blocking_fn_does_not_block_caller(self):
        # 30초 sleep + 0.3초 timeout — 수정 전이면 30초 대기, 수정 후 ~0.3초.
        start = time.time()
        with pytest.raises(TimeoutError):
            _call_with_wall_clock_timeout(time.sleep, 0.3, 30.0)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"30초 blocking fn 이 caller 차단 — elapsed={elapsed:.2f}s"

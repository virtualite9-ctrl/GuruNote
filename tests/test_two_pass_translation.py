"""(가) 옵션 A prototype — 2-pass 분리 unit test (5/23).

토글:
    GURUNOTE_TWO_PASS=1 환경변수 시 2-pass (자유 번역 → 정렬).
    기본 off 시 기존 1-pass — daily 환경 보존.

검증:
    - 1단계/2단계 prompt 형식
    - 2-pass 통합 (mock 1단계 자유 → mock 2단계 정렬 → N개 출력)
    - 토글 off 시 1-pass 경로 통과 (기존 동작 보존)
    - 1단계 timeout fallback
    - R3-수정 (enable_loose_on_timeout) 2단계 적용
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from gurunote.llm import (
    TIMEOUT_PADDING_MARKER,
    _build_alignment_prompt,
    _build_freeform_translation_prompt,
    _call_llm_with_index_mapping,
    _post_process_two_pass_outputs,
    _strip_input_speaker_prefix,
    _translate_chunk_two_pass,
    translate_chunk_index_mapping_v2,
)
from gurunote.types import Segment


@pytest.fixture
def mock_cfg():
    from gurunote.llm import LLMConfig
    return LLMConfig(
        provider="openai_compatible",
        model="mock-model",
        api_key="mock-key",
        base_url="http://mock.local/v1",
    )


@pytest.fixture
def sample_chunk():
    # 5/23 — STT speaker 실제 형식 ("A"/"B" 단일 영문 1글자, checkpoint4 verify 정합).
    return [
        Segment(speaker="A", start=10.0, end=12.0, text="Hello world"),
        Segment(speaker="B", start=13.0, end=15.0, text="How are you"),
        Segment(speaker="A", start=16.0, end=18.0, text="I am fine"),
    ]


# =============================================================================
# Prompt 구조 — 1단계/2단계 형식
# =============================================================================
class TestPromptBuild:
    def test_freeform_prompt_has_no_schema_marker(self):
        inputs = ["Speaker A: hello", "Speaker B: hi"]
        prompt = _build_freeform_translation_prompt(inputs, "")
        # 자유 번역 영역 명시
        assert "자유 번역" in prompt or "자유롭게" in prompt
        # JSON outputs 형식 강제 부재 (1단계는 schema 부담 부재)
        assert '{"outputs"' not in prompt
        # N개 강제는 prompt 차원 (segment 합치기/나누기 방지)
        assert "2 개" in prompt or "정확히 2" in prompt

    def test_alignment_prompt_has_schema_format(self):
        inputs = ["Speaker A: hello", "Speaker B: hi"]
        freeform = "[자유 번역 본문]"
        prompt = _build_alignment_prompt(inputs, freeform)
        # 정렬 영역 + N개 outputs 명시
        assert "재배치" in prompt or "정렬" in prompt
        assert '{"outputs"' in prompt
        # 1단계 자유 번역이 prompt 안에 포함
        assert "[자유 번역 본문]" in prompt
        # 5/23 보강 — 빈/반복 차단 + 새 번역 부재 명시
        assert "빈 string" in prompt or "빈 칸" in prompt
        assert "반복" in prompt and ("부재" in prompt or "절대" in prompt)
        # rule 1 강화 — 새 번역 생성 부재
        assert "새 번역" in prompt or "새로 번역" in prompt


# =============================================================================
# _translate_chunk_two_pass — 통합 동작
# =============================================================================
class TestTwoPassIntegration:
    def test_normal_two_pass_returns_outputs(self, mock_cfg, sample_chunk):
        freeform_text = "티파니: 안녕\n\n판카즈: 잘 지내?\n\n티파니: 좋아"
        # 2단계가 정상 한국어 화자명 형식으로 반환 시 A5 strip 영향 부재
        aligned_outputs = ["티파니: 안녕", "판카즈: 잘 지내?", "티파니: 좋아"]
        aligned_json = json.dumps({"outputs": aligned_outputs}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.return_value = freeform_text
            mock_align.return_value = (aligned_json, "stop")
            outputs = _translate_chunk_two_pass(sample_chunk, "", mock_cfg)
        assert outputs == aligned_outputs
        # 1단계 1회, 2단계 1회
        assert mock_freeform.call_count == 1
        assert mock_align.call_count == 1

    def test_freeform_timeout_returns_timeout_padding(self, mock_cfg, sample_chunk):
        # 1단계 timeout → 2단계 진입 부재, 즉시 [⚠ timeout] padding
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.side_effect = TimeoutError("freeform timeout")
            outputs = _translate_chunk_two_pass(sample_chunk, "", mock_cfg)
        assert outputs == [TIMEOUT_PADDING_MARKER] * 3
        # 2단계 호출 부재
        assert mock_align.call_count == 0

    def test_freeform_empty_returns_translation_missing_padding(self, mock_cfg, sample_chunk):
        # 1단계 빈 응답 → [번역 누락] padding
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.return_value = ""
            outputs = _translate_chunk_two_pass(sample_chunk, "", mock_cfg)
        assert outputs == ["[번역 누락]"] * 3
        assert mock_align.call_count == 0


# =============================================================================
# 토글 — GURUNOTE_TWO_PASS 환경변수
# =============================================================================
class TestToggle:
    def test_explicit_off_uses_one_pass(self, mock_cfg, sample_chunk, monkeypatch):
        # GURUNOTE_TWO_PASS=0 명시 → 1-pass
        monkeypatch.setenv("GURUNOTE_TWO_PASS", "0")
        outputs_json = json.dumps({"outputs": ["a", "b", "c"]}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_one_pass:
            mock_one_pass.return_value = (outputs_json, "stop")
            result = translate_chunk_index_mapping_v2(sample_chunk, "", mock_cfg)
        # 1-pass 경로 — _call_llm (freeform) 호출 부재
        assert mock_freeform.call_count == 0
        # _call_llm_with_continuation 1회 (1-pass)
        assert mock_one_pass.call_count == 1
        assert "[00:10]" in result and "[00:13]" in result and "[00:16]" in result

    def test_toggle_on_uses_two_pass(self, mock_cfg, sample_chunk, monkeypatch):
        monkeypatch.setenv("GURUNOTE_TWO_PASS", "1")
        # 5/23 — 2-pass 입력 본문만 (화자 부재), 출력도 본문만
        freeform_text = "안녕\n\n안녕\n\n좋아"
        aligned_json = json.dumps({"outputs": ["안녕", "안녕", "좋아"]}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.return_value = freeform_text
            mock_align.return_value = (aligned_json, "stop")
            result = translate_chunk_index_mapping_v2(sample_chunk, "", mock_cfg)
        # 2-pass — 1단계 + 2단계 각 1회
        assert mock_freeform.call_count == 1
        assert mock_align.call_count == 1
        # 5/23 — client zip 코드 부착: timestamp + 화자 라벨 (cache 부재 fallback "화자 N") + 본문
        assert "[00:10] 화자 1: 안녕" in result  # speaker "A" → "화자 1" fallback
        assert "[00:13] 화자 2: 안녕" in result  # speaker "B" → "화자 2"
        assert "[00:16] 화자 1: 좋아" in result  # speaker "A" → "화자 1" (이후)

    def test_toggle_value_other_than_one_uses_one_pass(self, mock_cfg, sample_chunk, monkeypatch):
        # "0", "false", 임의 값 모두 1-pass (오로지 "1"만 활성)
        for v in ["0", "false", "yes", ""]:
            monkeypatch.setenv("GURUNOTE_TWO_PASS", v)
            outputs_json = json.dumps({"outputs": ["x", "y", "z"]}, ensure_ascii=False)
            with patch("gurunote.llm.client._call_llm") as mock_freeform, \
                 patch("gurunote.llm.client._call_llm_with_continuation") as mock_one_pass:
                mock_one_pass.return_value = (outputs_json, "stop")
                translate_chunk_index_mapping_v2(sample_chunk, "", mock_cfg)
            assert mock_freeform.call_count == 0, f"v={v!r} 시 1-pass 진입 부재"


# =============================================================================
# R3-수정 — enable_loose_on_timeout=True 시 strict → loose 전환
# =============================================================================
class TestR3LooseOnTimeout:
    def test_default_disabled_keeps_strict_on_timeout(self, mock_cfg):
        # 기본 enable_loose_on_timeout=False — 1-pass 동작 보존
        cfg = mock_cfg
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            # 3회 모두 timeout
            mock_call.side_effect = TimeoutError("timeout")
            outputs = _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=5, max_retries=3
            )
        # 3회 retry catch, strict 유지 (loose 전환 log 부재)
        assert mock_call.call_count == 3
        assert all(o == TIMEOUT_PADDING_MARKER for o in outputs)

    def test_enabled_switches_to_loose_on_timeout(self, mock_cfg):
        # enable_loose_on_timeout=True — 2단계 전용 — timeout 시 loose 전환
        cfg = mock_cfg
        log_messages = []
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = TimeoutError("timeout")
            _call_llm_with_index_mapping(
                cfg, "prompt", expected_count=5, max_retries=3,
                log=log_messages.append,
                enable_loose_on_timeout=True,
            )
        # R3-수정 log catch
        assert any("R3-수정" in m or "json_object mode 전환" in m for m in log_messages), (
            f"loose 전환 log 부재 — log={log_messages!r}"
        )


# =============================================================================
# A5 (5/23) — deterministic 후처리 (prefix strip + 빈 검출 + 반복 경고)
# =============================================================================
class TestStripSpeakerPrefix:
    def test_strips_single_uppercase_prefix(self):
        # "A: " "B: " 단일 대문자 + 콜론 + 공백 strip
        assert _strip_input_speaker_prefix("A: 티파니 잔젠: 안녕하세요") == "티파니 잔젠: 안녕하세요"
        assert _strip_input_speaker_prefix("B: 판카즈 샤르마: 본문") == "판카즈 샤르마: 본문"
        assert _strip_input_speaker_prefix("Z: 한국어 화자명: 본문") == "한국어 화자명: 본문"

    def test_preserves_normal_korean_label(self):
        # 정상 한국어 화자 라벨 보존 (단일 대문자 부재)
        assert _strip_input_speaker_prefix("티파니 잔젠: 본문") == "티파니 잔젠: 본문"
        assert _strip_input_speaker_prefix("판카즈 샤르마: 본문") == "판카즈 샤르마: 본문"

    def test_preserves_english_annotation(self):
        # 영문 병기 보존 — line 시작이 한국어이므로 매치 부재
        assert (
            _strip_input_speaker_prefix("티파니 잔젠(Tiffany Janzen): 본문")
            == "티파니 잔젠(Tiffany Janzen): 본문"
        )

    def test_preserves_english_name_starting_word(self):
        # 영문 단어로 시작 — 다음 글자가 소문자 → 매치 부재 ("Jensen Huang: " 등)
        assert _strip_input_speaker_prefix("Jensen Huang: 본문") == "Jensen Huang: 본문"
        assert _strip_input_speaker_prefix("Pankaj Sharma: 안녕") == "Pankaj Sharma: 안녕"

    def test_preserves_multi_letter_uppercase(self):
        # "AI: ..." 같은 대문자 약어 다음에 콜론 — 매치 부재 (단일 대문자만 catch)
        assert _strip_input_speaker_prefix("AI: 이것은 매핑 부재") == "AI: 이것은 매핑 부재"
        assert _strip_input_speaker_prefix("CEO: 본문") == "CEO: 본문"

    def test_preserves_empty_and_none_safe(self):
        # 빈 string 안전
        assert _strip_input_speaker_prefix("") == ""

    def test_only_strips_line_start_prefix(self):
        # 본문 중간의 "A: " 패턴은 보존 (line 시작 영문 대문자만)
        assert (
            _strip_input_speaker_prefix("티파니 잔젠: A: 인용 본문")
            == "티파니 잔젠: A: 인용 본문"
        )


class TestPostProcessTwoPassOutputs:
    def test_empty_output_replaced_with_translation_missing(self):
        # 빈 string → [번역 누락] 교체
        outputs = ["정상 본문 1", "", "정상 본문 2"]
        log_messages = []
        result = _post_process_two_pass_outputs(outputs, 3, log_messages.append)
        assert result == ["정상 본문 1", "[번역 누락]", "정상 본문 2"]
        # log 경고 catch
        assert any("빈 output" in m for m in log_messages)

    def test_whitespace_only_output_replaced(self):
        # whitespace 만 있는 output 도 빈 catch → [번역 누락]
        outputs = ["정상", "   ", "\n\n", "정상2"]
        result = _post_process_two_pass_outputs(outputs, 4)
        assert result[1] == "[번역 누락]"
        assert result[2] == "[번역 누락]"

    def test_prefix_strip_applied_to_all_outputs(self):
        # 모든 output 에 prefix strip 적용
        outputs = ["A: 티파니 잔젠: 본문 1", "B: 판카즈 샤르마: 본문 2", "정상: 본문 3"]
        result = _post_process_two_pass_outputs(outputs, 3)
        assert result == [
            "티파니 잔젠: 본문 1",
            "판카즈 샤르마: 본문 2",
            "정상: 본문 3",
        ]

    def test_consecutive_repeat_log_warning(self):
        # 연속 동일 output → log 경고 (자동 제거 부재)
        outputs = ["본문 X", "본문 Y", "본문 Y", "본문 Z"]
        log_messages = []
        result = _post_process_two_pass_outputs(outputs, 4, log_messages.append)
        # 자동 제거 부재 — 원본 그대로 (단 prefix strip 적용)
        assert result == ["본문 X", "본문 Y", "본문 Y", "본문 Z"]
        # 경고 log catch
        assert any("연속 동일 output" in m for m in log_messages)

    def test_no_repeat_no_warning(self):
        # 반복 부재 시 경고 부재
        outputs = ["본문 1", "본문 2", "본문 3"]
        log_messages = []
        _post_process_two_pass_outputs(outputs, 3, log_messages.append)
        assert not any("연속 동일 output" in m for m in log_messages)

    def test_translation_missing_repeat_not_warned(self):
        # 연속 [번역 누락] 은 정상 fallback 패턴 — 경고 부재 (조건: != "[번역 누락]")
        outputs = ["[번역 누락]", "[번역 누락]", "정상"]
        log_messages = []
        _post_process_two_pass_outputs(outputs, 3, log_messages.append)
        assert not any("연속 동일 output" in m for m in log_messages)

    def test_preserves_output_length(self):
        # 후처리가 길이 변경 부재 catch (expected_count 보존)
        outputs = ["A: x", "", "Y: y", ""]
        result = _post_process_two_pass_outputs(outputs, 4)
        assert len(result) == 4


class TestTwoPassWithPostProcess:
    def test_two_pass_strips_prefix_in_final_outputs(self, mock_cfg, sample_chunk):
        # _translate_chunk_two_pass 의 최종 outputs 에 prefix strip 적용 확인
        freeform_text = "A: 티파니 잔젠: 안녕\n\nB: 판카즈 샤르마: 인사\n\nA: 티파니 잔젠: 답변"
        # 2단계가 1단계 prefix 잔존 출력했을 case
        aligned_json = json.dumps({
            "outputs": [
                "A: 티파니 잔젠: 안녕",
                "B: 판카즈 샤르마: 인사",
                "A: 티파니 잔젠: 답변",
            ]
        }, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.return_value = freeform_text
            mock_align.return_value = (aligned_json, "stop")
            outputs = _translate_chunk_two_pass(sample_chunk, "", mock_cfg)
        # 모든 output 에서 A:/B: 제거 catch
        assert outputs == ["티파니 잔젠: 안녕", "판카즈 샤르마: 인사", "티파니 잔젠: 답변"]

    def test_two_pass_empty_segment_replaced(self, mock_cfg, sample_chunk):
        # 5/23 — 복구 시퀀스 추가 후 의도 변경:
        # 2단계 빈 → 2차 복구 (1단계 본문 활용) catch (marker 부재)
        aligned_json = json.dumps({
            "outputs": ["정상 본문 1", "", "정상 본문 3"]
        }, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_freeform, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_freeform.return_value = "정상 1\n\n정상 2\n\n정상 3"
            mock_align.return_value = (aligned_json, "stop")
            outputs = _translate_chunk_two_pass(sample_chunk, "", mock_cfg)
        # 2차 복구 — 1단계 line 2 ("정상 2") 활용, marker 부재
        assert outputs == ["정상 본문 1", "정상 2", "정상 본문 3"]


# =============================================================================
# 5/23 — 화자 라벨 코드 부착 (식별 1회 + 결정론적 표기)
# =============================================================================
from gurunote.llm import (
    CACHE_SCHEMA_VERSION,
    _bootstrap_entity_cache_from_metadata,
    _load_entity_cache_full,
    _resolve_speaker_label,
    _save_entity_cache,
)


class TestResolveSpeakerLabel:
    def test_first_occurrence_with_cache_uses_english_annotation(self):
        cache = {"A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"}}
        seen: set = set()
        label = _resolve_speaker_label("A", cache, seen)
        assert label == "판카즈 샤르마(Pankaj Sharma)"
        assert "A" in seen   # 첫 등장 catch 후 set 추가

    def test_subsequent_occurrence_no_english_annotation(self):
        cache = {"A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"}}
        seen: set = {"A"}   # 이미 catch
        label = _resolve_speaker_label("A", cache, seen)
        assert label == "판카즈 샤르마"

    def test_fallback_when_cache_missing(self):
        # cache 부재 fallback "화자 N" (A→1, B→2, ...)
        seen: set = set()
        assert _resolve_speaker_label("A", {}, seen) == "화자 1"
        assert _resolve_speaker_label("B", None, seen) == "화자 2"
        assert _resolve_speaker_label("C", {}, seen) == "화자 3"
        assert _resolve_speaker_label("Z", {}, seen) == "화자 26"

    def test_fallback_for_unknown_speaker_in_cache(self):
        # cache 에 있는 speaker 외엔 fallback
        cache = {"A": {"english": "Pankaj", "korean": "판카즈"}}
        seen: set = set()
        label = _resolve_speaker_label("B", cache, seen)
        assert label == "화자 2"

    def test_fallback_for_empty_korean(self):
        # korean 빈 string 시 fallback
        cache = {"A": {"english": "Pankaj", "korean": ""}}
        seen: set = set()
        label = _resolve_speaker_label("A", cache, seen)
        assert label == "화자 1"

    def test_first_etc_after_initial_visit(self):
        # 영상 단위 첫 등장 catch — set 변화
        cache = {"A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"}}
        seen: set = set()
        first = _resolve_speaker_label("A", cache, seen)
        second = _resolve_speaker_label("A", cache, seen)
        assert first == "판카즈 샤르마(Pankaj Sharma)"   # 영문 병기
        assert second == "판카즈 샤르마"                   # 영문 병기 부재


class TestBootstrapWithSpeakers:
    def test_bootstrap_extracts_speakers(self, mock_cfg):
        ctx = {
            "title": "NVIDIA GTC Studio",
            "description": "Pankaj Sharma from Schneider Electric and Tiffany Janzen.",
        }
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = (
                "Pankaj Sharma → 판카즈 샤르마 [person]\n"
                "Tiffany Janzen → 티파니 잔젠 [person]\n"
                "Schneider Electric → 슈나이더 일렉트릭 [company]\n"
                "SPEAKER A => Pankaj Sharma | 판카즈 샤르마\n"
                "SPEAKER B => Tiffany Janzen | 티파니 잔젠"
            )
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_cfg)
        # __speakers__ 마커 catch
        speakers = result.pop("__speakers__", {})
        assert speakers == {
            "A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"},
            "B": {"english": "Tiffany Janzen", "korean": "티파니 잔젠"},
        }
        # entity 도 catch
        assert "Pankaj Sharma" in result
        assert "Schneider Electric" in result

    def test_bootstrap_speakers_absent_when_llm_skips(self, mock_cfg):
        # SPEAKER 라인 부재 시 speakers 부재 (entity 만)
        ctx = {"title": "Test"}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "Pankaj Sharma → 판카즈 샤르마 [person]"
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_cfg)
        # 마커 키 부재 catch
        assert "__speakers__" not in result
        assert "Pankaj Sharma" in result


class TestCacheSchemaV2:
    def test_save_load_with_speakers(self):
        entities = {"P": {"korean": "판카즈", "type": "person", "source": "bootstrap"}}
        speakers = {"A": {"english": "Pankaj", "korean": "판카즈"}}
        _save_entity_cache("vid_v2", "Test V2", entities, speakers=speakers)
        loaded = _load_entity_cache_full("vid_v2")
        assert loaded is not None
        assert loaded["entities"] == entities
        assert loaded["speakers"] == speakers

    def test_save_without_speakers_empty_dict(self):
        entities = {"P": {"korean": "판카즈", "type": "person", "source": "bootstrap"}}
        _save_entity_cache("vid_no_sp", "No Speakers", entities)
        loaded = _load_entity_cache_full("vid_no_sp")
        assert loaded is not None
        assert loaded["speakers"] == {}

    def test_v1_cache_invalidated(self, tmp_path, monkeypatch):
        # v1 cache (cache_schema_version 부재) → load None
        import gurunote.llm as _llm
        monkeypatch.setattr("gurunote.llm.entities.CACHE_DIR", tmp_path / "ec")
        (tmp_path / "ec").mkdir()
        old_data = {
            "video_id": "vid_old",
            "video_title": "Old V1",
            "created_at": "2026-05-20T00:00:00+09:00",
            "loanword_spec_version": "2017-14",
            "entities": [{"english": "X", "korean": "엑스", "type": "unknown", "source": "bootstrap"}],
            # cache_schema_version 부재 → v1
        }
        (tmp_path / "ec" / "vid_old.json").write_text(
            json.dumps(old_data, ensure_ascii=False), encoding="utf-8"
        )
        loaded = _load_entity_cache_full("vid_old")
        assert loaded is None   # v1 invalidate

    def test_current_schema_version_value(self):
        assert CACHE_SCHEMA_VERSION == "2"


# =============================================================================
# 5/23 — 2-pass 빈 output 복구 시퀀스 (옵션 라 — 3단계 안전망)
# =============================================================================
from gurunote.llm import _recover_empty_outputs


class TestRejectEmptyOutputs:
    def test_default_off_one_pass_passes_with_empty(self, mock_cfg):
        # 1-pass 동작 보존 — 빈 string 있어도 length 정합이면 return
        outputs_json = json.dumps({"outputs": ["a", "", "c"]}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.return_value = (outputs_json, "stop")
            result = _call_llm_with_index_mapping(
                mock_cfg, "prompt", expected_count=3, max_retries=3,
                # reject_empty_outputs 기본 False
            )
        assert result == ["a", "", "c"]
        assert mock_call.call_count == 1   # 1회 통과

    def test_two_pass_rejects_empty_and_retries(self, mock_cfg):
        # 2-pass 전용 — reject_empty_outputs=True 시 빈 있으면 retry
        empty_then_full = [
            (json.dumps({"outputs": ["a", "", "c"]}, ensure_ascii=False), "stop"),
            (json.dumps({"outputs": ["a", "b", "c"]}, ensure_ascii=False), "stop"),
        ]
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.side_effect = empty_then_full
            result = _call_llm_with_index_mapping(
                mock_cfg, "prompt", expected_count=3, max_retries=3,
                reject_empty_outputs=True,
            )
        assert result == ["a", "b", "c"]
        assert mock_call.call_count == 2   # 빈 1회 → retry 1회

    def test_all_retries_empty_returns_outputs_for_recovery(self, mock_cfg):
        # 3회 모두 빈 잔존 시 outputs 반환 (recovery 시퀀스가 잡음)
        outputs_json = json.dumps({"outputs": ["a", "", "c"]}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm_with_continuation") as mock_call:
            mock_call.return_value = (outputs_json, "stop")
            result = _call_llm_with_index_mapping(
                mock_cfg, "prompt", expected_count=3, max_retries=3,
                reject_empty_outputs=True,
            )
        # fallback: length 정합 후 빈 잔존 → "[번역 누락]" 으로 padding 부재 (length 그대로)
        # → outputs 그대로 반환 (3차 복구가 잡도록)
        # 단 retry 소진 후 fallback 분기 진입 — 빈 잔존 시 [번역 누락] 으로 채우는 분기 부재
        # 실제: length 정합이라 retry loop 끝까지 진행, fallback 분기 부재 → 마지막 outputs 그대로
        # 단 본 test 는 retry 진행만 확인 (recovery 시퀀스 별 test)
        assert mock_call.call_count == 3
        # 빈 잔존 — recovery 시퀀스가 잡아야 함
        assert "" in result or "[번역 누락]" in result


class TestRecoverEmptyOutputs:
    def _make_chunk(self, n: int):
        return [
            Segment(speaker="A", start=float(i*5), end=float(i*5+3), text=f"text {i}")
            for i in range(n)
        ]

    def test_2nd_recovery_uses_freeform_when_line_count_matches(self, mock_cfg):
        # 2차 복구: 1단계 line 수 == N → 빈 index 의 1단계 본문 활용
        outputs = ["번역 1", "", "번역 3"]
        freeform_lines = ["freeform 1", "freeform 2", "freeform 3"]
        inputs = ["en 1", "en 2", "en 3"]
        chunk = self._make_chunk(3)
        result = _recover_empty_outputs(
            outputs, freeform_lines, inputs, chunk, mock_cfg
        )
        assert result == ["번역 1", "freeform 2", "번역 3"]

    def test_2nd_recovery_skips_when_freeform_line_count_differs(self, mock_cfg):
        # 1단계 line 수 != N → 2차 복구 skip → 3차로
        outputs = ["번역 1", "", "번역 3"]
        freeform_lines = ["freeform 합쳐짐"]   # N=3 인데 1줄
        inputs = ["en 1", "en 2", "en 3"]
        chunk = self._make_chunk(3)
        # 3차 단독 재번역 mock
        with patch("gurunote.llm.client._call_llm") as mock_solo:
            mock_solo.return_value = "단독 재번역 결과"
            result = _recover_empty_outputs(
                outputs, freeform_lines, inputs, chunk, mock_cfg
            )
        # 2차 skip + 3차 catch
        assert result == ["번역 1", "단독 재번역 결과", "번역 3"]
        assert mock_solo.call_count == 1   # 빈 1건만 단독 재번역

    def test_3rd_recovery_solo_translate(self, mock_cfg):
        # 1단계도 비고 line 수 정합 → 2차 skip → 3차 단독 재번역
        outputs = ["번역 1", "", "번역 3"]
        freeform_lines = ["fl 1", "", "fl 3"]   # idx 1 도 빈 → 2차 복구 부재
        inputs = ["en 1", "en 2", "en 3"]
        chunk = self._make_chunk(3)
        with patch("gurunote.llm.client._call_llm") as mock_solo:
            mock_solo.return_value = "단독 결과"
            result = _recover_empty_outputs(
                outputs, freeform_lines, inputs, chunk, mock_cfg
            )
        # 2차: freeform_lines[1] 도 빈 → skip → 3차 LLM 호출
        assert result == ["번역 1", "단독 결과", "번역 3"]
        assert mock_solo.call_count == 1

    def test_3rd_recovery_failure_keeps_empty_for_marker(self, mock_cfg):
        # 3차도 실패 (LLM 빈 응답) → 빈 잔존 → A5 marker 가 catch
        outputs = ["번역 1", "", "번역 3"]
        freeform_lines = ["", "", ""]   # 1단계 모두 빈
        inputs = ["en 1", "en 2", "en 3"]
        chunk = self._make_chunk(3)
        with patch("gurunote.llm.client._call_llm") as mock_solo:
            mock_solo.return_value = ""   # 3차도 빈 응답
            result = _recover_empty_outputs(
                outputs, freeform_lines, inputs, chunk, mock_cfg
            )
        # 빈 잔존 — A5 가 marker 교체 catch
        assert result[1] == ""

    def test_no_empty_no_recovery(self, mock_cfg):
        # 빈 부재 시 복구 호출 부재
        outputs = ["a", "b", "c"]
        with patch("gurunote.llm.client._call_llm") as mock_solo:
            result = _recover_empty_outputs(
                outputs, ["fl1", "fl2", "fl3"], ["en1", "en2", "en3"],
                self._make_chunk(3), mock_cfg
            )
        assert result == ["a", "b", "c"]
        assert mock_solo.call_count == 0


class TestTwoPassEmptyRecoveryIntegration:
    def test_full_recovery_sequence_2nd_catches(self, mock_cfg):
        # 2-pass 전체: 2단계가 빈 1건 → retry 후에도 빈 → 2차 1단계 활용 catch
        # 1단계 freeform 정합, 2단계 빈 1건 (idx 1)
        chunk = [
            Segment(speaker="A", start=10.0, end=12.0, text="Hello"),
            Segment(speaker="B", start=13.0, end=15.0, text="World"),
            Segment(speaker="A", start=16.0, end=18.0, text="Bye"),
        ]
        freeform_text = "안녕\n\n세계\n\n잘 가"
        # 2단계는 retry 후에도 빈 잔존 (3회 모두 빈)
        empty_json = json.dumps({"outputs": ["안녕 정렬", "", "잘 가 정렬"]}, ensure_ascii=False)
        with patch("gurunote.llm.client._call_llm") as mock_solo, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            mock_solo.return_value = freeform_text   # 1단계
            mock_align.return_value = (empty_json, "stop")
            outputs = _translate_chunk_two_pass(chunk, "", mock_cfg)
        # 2차 복구로 idx 1 = "세계" catch (1단계 line 2)
        assert outputs[0] == "안녕 정렬"
        assert outputs[1] == "세계"   # 2차 복구
        assert outputs[2] == "잘 가 정렬"

    def test_recovery_logs_book_keeping(self, mock_cfg):
        # 복구 단계별 log 출력 catch
        chunk = [
            Segment(speaker="A", start=0.0, end=2.0, text="text1"),
            Segment(speaker="B", start=3.0, end=5.0, text="text2"),
        ]
        freeform_text = "안녕\n\n세계"
        empty_json = json.dumps({"outputs": ["", ""]}, ensure_ascii=False)
        log_msgs = []
        with patch("gurunote.llm.client._call_llm") as mock_solo, \
             patch("gurunote.llm.client._call_llm_with_continuation") as mock_align:
            # 1단계 freeform 반환 + 3차 단독 재번역 mock (idx 1 호출 시)
            mock_solo.side_effect = [freeform_text]
            mock_align.return_value = (empty_json, "stop")
            _translate_chunk_two_pass(chunk, "", mock_cfg, log=log_msgs.append)
        # 1단계 로깅 + 2차 복구 log catch
        assert any("📝 2-pass 1단계 출력" in m for m in log_msgs)
        assert any("복구 2차" in m for m in log_msgs)

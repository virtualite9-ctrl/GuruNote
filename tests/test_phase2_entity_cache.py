"""Phase 2 entity cache + 화자 cache helper 단위 + 통합 테스트.

테스트 클래스:
    TestExtractEntities           — speaker line prefix entity 추출 (결정론)
    TestBuildEntityCacheBlock     — entity_cache → markdown block 변환
    TestBootstrapEntityCacheMock  — Two-Stage bootstrap LLM mock retry 흐름
    TestBootstrapIntegration      — 실제 omlx 호출 (slow marker)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from gurunote.llm import (
    _bootstrap_entity_cache_from_metadata,
    _build_entity_cache_block,
    _extract_entities,
)


# =============================================================================
# TestExtractEntities — speaker line prefix entity 추출
# =============================================================================
class TestExtractEntities:
    def test_first_occurrence_with_english(self):
        text = "[00:10] 티파니 잔젠(Tiffany Janzen): 안녕하세요"
        result = _extract_entities(text)
        assert result == {
            "Tiffany Janzen": {
                "korean": "티파니 잔젠",
                "type": "speaker",
                "source": "chunk_extract",
            }
        }

    def test_subsequent_korean_only_returns_empty(self):
        text = "[00:13] 티파니 잔젠: 제 이름은 티파니 잔젠입니다"
        result = _extract_entities(text)
        assert result == {}

    def test_multiple_speakers_first_occurrence(self):
        text = (
            "[00:10] 티파니 잔젠(Tiffany Janzen): 안녕하세요\n\n"
            "[00:21] 판카즈 샤르마(Pankaj Sharma): 감사합니다"
        )
        result = _extract_entities(text)
        assert result == {
            "Tiffany Janzen": {
                "korean": "티파니 잔젠",
                "type": "speaker",
                "source": "chunk_extract",
            },
            "Pankaj Sharma": {
                "korean": "판카즈 샤르마",
                "type": "speaker",
                "source": "chunk_extract",
            },
        }

    def test_body_english_annotation_ignored(self):
        # 본문 중간의 영문 병기는 line prefix 아니라 entity 부재
        text = (
            "[00:13] 티파니 잔젠: 오늘 슈나이더 일렉트릭의 판카즈 샤르마(Pankaj Sharma)께서 함께"
        )
        result = _extract_entities(text)
        # "판카즈 샤르마" 는 본문 안 영문 병기 → entity 부재
        assert result == {}

    def test_empty_input(self):
        assert _extract_entities("") == {}

    def test_no_speaker_lines(self):
        text = "안녕하세요. 본 문장은 speaker prefix 부재"
        assert _extract_entities(text) == {}

    def test_complex_english_name_with_dots(self):
        # 점이 포함된 영문명 (예: "J.P. Morgan" 같은 케이스)
        text = "[12:34] 제이피(J.P. Morgan): 본문"
        result = _extract_entities(text)
        assert result == {
            "J.P. Morgan": {
                "korean": "제이피",
                "type": "speaker",
                "source": "chunk_extract",
            }
        }

    def test_invalid_english_filtered(self):
        # 영문 자리에 한국어/한자 섞임 → skip
        text = "[00:10] 잘못된(잘못된 영문): 본문"
        result = _extract_entities(text)
        assert result == {}

    def test_first_then_subsequent_same_speaker(self):
        # 첫 등장은 catch, 이후는 skip — dict 중복 갱신 부재
        text = (
            "[00:10] 티파니 잔젠(Tiffany Janzen): 첫 등장\n\n"
            "[00:13] 티파니 잔젠: 이후 발화\n\n"
            "[00:17] 티파니 잔젠: 또 다른 발화"
        )
        result = _extract_entities(text)
        assert result == {
            "Tiffany Janzen": {
                "korean": "티파니 잔젠",
                "type": "speaker",
                "source": "chunk_extract",
            }
        }

    def test_two_digit_minute_timestamp(self):
        # [15:45] 같은 2자리 timestamp catch
        text = "[15:45] 판카즈 샤르마(Pankaj Sharma): 본문"
        result = _extract_entities(text)
        assert result == {
            "Pankaj Sharma": {
                "korean": "판카즈 샤르마",
                "type": "speaker",
                "source": "chunk_extract",
            }
        }


# =============================================================================
# TestBuildEntityCacheBlock — dict → markdown block 변환
# =============================================================================
class TestBuildEntityCacheBlock:
    def test_empty_dict_returns_empty_string(self):
        assert _build_entity_cache_block({}) == ""

    def test_single_entity(self):
        result = _build_entity_cache_block(
            {"Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}}
        )
        expected = "### 영상 entity 표기 일관\n- Pankaj Sharma → 판카즈 샤르마"
        assert result == expected

    def test_multiple_entities(self):
        cache = {
            "Tiffany Janzen": {"korean": "티파니 잔젠", "type": "person", "source": "bootstrap"},
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"},
        }
        result = _build_entity_cache_block(cache)
        assert "### 영상 entity 표기 일관" in result
        assert "- Tiffany Janzen → 티파니 잔젠" in result
        assert "- Pankaj Sharma → 판카즈 샤르마" in result
        # 두 entity 라인 catch
        assert result.count("\n-") == 2

    def test_preserves_insertion_order(self):
        # Python 3.7+ dict 순서 보존 catch
        cache = {
            "Zelda": {"korean": "젤다", "type": "person", "source": "bootstrap"},
            "Adam": {"korean": "아담", "type": "person", "source": "bootstrap"},
        }
        result = _build_entity_cache_block(cache)
        lines = result.splitlines()
        # 첫 entity 라인이 Zelda (insertion 첫 번째)
        assert lines[1] == "- Zelda → 젤다"
        assert lines[2] == "- Adam → 아담"


# =============================================================================
# TestBootstrapEntityCacheMock — (b) Two-Stage bootstrap LLM mock
# =============================================================================
class TestBootstrapEntityCacheMock:
    def test_video_context_only_success(self, mock_llm_config):
        ctx = {
            "title": "NVIDIA GTC Studio with Insights from Schneider Electric",
            "uploader": "NVIDIA",
            "description": "Pankaj Sharma from Schneider Electric discusses AI infrastructure.",
        }
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = (
                "Pankaj Sharma → 판카즈 샤르마 [person]\n"
                "Schneider Electric → 슈나이더 일렉트릭 [company]\n"
                "NVIDIA → 엔비디아 [company]"
            )
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert mock_call.call_count == 1
        assert result == {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"},
            "Schneider Electric": {"korean": "슈나이더 일렉트릭", "type": "company", "source": "bootstrap"},
            "NVIDIA": {"korean": "엔비디아", "type": "company", "source": "bootstrap"},
        }

    def test_subtitles_only(self, mock_llm_config):
        subs = "Hello, I'm Tiffany Janzen and today I'm joined by Pankaj Sharma."
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = (
                "Tiffany Janzen → 티파니 잔젠 [person]\n"
                "Pankaj Sharma → 판카즈 샤르마 [person]"
            )
            result = _bootstrap_entity_cache_from_metadata(None, subs, mock_llm_config)
        assert mock_call.call_count == 1
        assert result == {
            "Tiffany Janzen": {"korean": "티파니 잔젠", "type": "person", "source": "bootstrap"},
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"},
        }

    def test_both_metadata_and_subtitles(self, mock_llm_config):
        ctx = {"title": "AI Conference", "description": "Talks"}
        subs = "Speakers: Jensen Huang, Pankaj Sharma."
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "Jensen Huang → 젠슨 황\nPankaj Sharma → 판카즈 샤르마"
            result = _bootstrap_entity_cache_from_metadata(ctx, subs, mock_llm_config)
        assert mock_call.call_count == 1
        # LLM 호출 인자에 두 source 모두 포함 catch
        call_args = mock_call.call_args
        user_text = call_args[0][2]  # _call_llm(config, system, user, max_tokens)
        assert "AI Conference" in user_text
        assert "Jensen Huang" in user_text
        assert len(result) == 2

    def test_no_input_returns_empty(self, mock_llm_config):
        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = _bootstrap_entity_cache_from_metadata(None, None, mock_llm_config)
        assert mock_call.call_count == 0
        assert result == {}

    def test_empty_video_context_no_input(self, mock_llm_config):
        # 모든 필드가 빈 video_context
        ctx = {"title": "", "description": "", "uploader": ""}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        # 추출할 텍스트 부재 → LLM 호출 부재
        assert mock_call.call_count == 0
        assert result == {}

    def test_llm_exception_returns_empty(self, mock_llm_config):
        ctx = {"title": "Test Video"}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.side_effect = RuntimeError("network fail")
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert result == {}

    def test_llm_empty_response_returns_empty(self, mock_llm_config):
        ctx = {"title": "Test Video"}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = ""
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert result == {}

    def test_malformed_llm_response_skips_bad_lines(self, mock_llm_config):
        ctx = {"title": "Test"}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            # 일부 라인은 정합, 일부는 → 부재. type 부재 라인은 unknown 으로 fallback.
            mock_call.return_value = (
                "Pankaj Sharma → 판카즈 샤르마 [person]\n"
                "잘못된 라인 (no arrow)\n"
                "Jensen Huang → 젠슨 황\n"  # type 부재 → unknown
                "\n"  # 빈 라인
            )
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        # 정합 라인 2건 catch, 부정합 라인 skip
        assert result == {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"},
            "Jensen Huang": {"korean": "젠슨 황", "type": "unknown", "source": "bootstrap"},
        }

    def test_long_subtitles_truncated_to_3000(self, mock_llm_config):
        # 3000자 이상 자막 → 첫 3000자만 LLM 에 전달
        long_subs = "X" * 5000
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = ""
            _bootstrap_entity_cache_from_metadata(None, long_subs, mock_llm_config)
        # LLM 호출 인자에 5000자가 아닌 첫 3000자만 포함
        user_text = mock_call.call_args[0][2]
        # 3000자 부분 catch + 5000자는 부재
        assert "X" * 3000 in user_text
        assert "X" * 3001 not in user_text

    def test_dash_prefix_stripped(self, mock_llm_config):
        # markdown 의 "- Name → 표기 [type]" 형식 인풋도 catch
        ctx = {"title": "Test"}
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "- Pankaj Sharma → 판카즈 샤르마 [person]"
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert result == {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }


# =============================================================================
# TestBootstrapIntegration — 실제 omlx 호출 (slow marker)
# =============================================================================
@pytest.mark.slow
class TestBootstrapIntegration:
    """실제 omlx 호출 — `pytest -m slow` 로만 실행."""

    def test_real_llm_bootstrap_basic(self, real_llm_config):
        ctx = {
            "title": "NVIDIA GTC Studio with Insights from Schneider Electric",
            "uploader": "NVIDIA",
            "description": "Pankaj Sharma from Schneider Electric discusses AI infrastructure.",
        }
        result = _bootstrap_entity_cache_from_metadata(ctx, None, real_llm_config)
        # 실제 omlx 호출 결과 — 최소 1건 entity 추출 기대
        assert isinstance(result, dict)
        # NVIDIA / Schneider Electric / Pankaj Sharma 중 하나 이상 catch 기대
        keys_lower = {k.lower() for k in result.keys()}
        catch_keys = {"nvidia", "schneider electric", "pankaj sharma"}
        assert keys_lower & catch_keys, f"기대 entity 부재: {result}"

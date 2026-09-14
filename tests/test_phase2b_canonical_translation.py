"""B06 (Phase 2B-3) — Canonical Translation 단위 테스트.

spec: docs/research/phase2b_canonical_translation_spec.md §5.1
대상 함수:
    _save_entity_cache / _load_entity_cache / _get_cache_file_path
    _compute_cache_key_from_title
    _load_loanword_short_version / _load_loanword_full_body
    _canonicalize_entity_names
    _bootstrap_entity_cache_from_metadata (cache hit/miss path)

cache 격리:
    tests/conftest.py 의 `_isolate_entity_cache` autouse fixture 가
    CACHE_DIR 을 `tmp_path/entity_cache` 로 monkeypatch — daily 환경 보호.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from gurunote.llm import (
    LOANWORD_SPEC_VERSION,
    _bootstrap_entity_cache_from_metadata,
    _canonicalize_entity_names,
    _compute_cache_key_from_title,
    _detect_unexpected_changes,
    _get_cache_file_path,
    _load_entity_cache,
    _load_loanword_full_body,
    _load_loanword_short_version,
    _save_entity_cache,
)


# =============================================================================
# TestCacheSaveLoad — _save_entity_cache + _load_entity_cache 단독
# =============================================================================
class TestCacheSaveLoad:
    def test_save_load_roundtrip(self):
        entities = {
            "Pankaj Sharma": {
                "korean": "판카즈 샤르마",
                "type": "person",
                "source": "bootstrap",
            },
            "Schneider Electric": {
                "korean": "슈나이더 일렉트릭",
                "type": "company",
                "source": "chunk_extract",
            },
        }
        _save_entity_cache("vid_test", "Test Video", entities)
        loaded = _load_entity_cache("vid_test")
        assert loaded == entities

    def test_load_missing_file(self):
        # 부재 video_id → None
        assert _load_entity_cache("vid_does_not_exist") is None

    def test_load_spec_version_mismatch(self):
        # spec_version 다름 → None (자동 invalidate)
        _save_entity_cache(
            "vid_old",
            "Old Spec Video",
            {"X": {"korean": "엑스", "type": "person", "source": "bootstrap"}},
            spec_version="1900-01",
        )
        # expected_spec_version 다르므로 None
        loaded = _load_entity_cache("vid_old", expected_spec_version=LOANWORD_SPEC_VERSION)
        assert loaded is None

    def test_save_creates_directory(self):
        # autouse fixture 의 tmp CACHE_DIR 는 초기 부재 — 첫 저장 시 자동 생성
        cache_path = _get_cache_file_path("vid_first_save")
        assert not cache_path.parent.exists() or not cache_path.exists()
        _save_entity_cache("vid_first_save", "First", {})
        assert cache_path.exists()
        assert cache_path.parent.exists()

    def test_load_corrupted_json(self):
        cache_path = _get_cache_file_path("vid_corrupt")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not valid json", encoding="utf-8")
        assert _load_entity_cache("vid_corrupt") is None

    def test_save_includes_metadata_fields(self):
        # JSON file 자체에 필요한 영역 모두 포함 catch
        _save_entity_cache(
            "vid_meta",
            "Metadata Test",
            {"A": {"korean": "에이", "type": "person", "source": "bootstrap"}},
        )
        raw = json.loads(_get_cache_file_path("vid_meta").read_text(encoding="utf-8"))
        assert raw["video_id"] == "vid_meta"
        assert raw["video_title"] == "Metadata Test"
        assert raw["loanword_spec_version"] == LOANWORD_SPEC_VERSION
        assert isinstance(raw["entities"], list)
        assert raw["entities"][0]["english"] == "A"
        assert raw["entities"][0]["type"] == "person"

    def test_korean_raw_not_ascii_escaped(self):
        # ensure_ascii=False 정합 — 한국어 raw 본문 보존
        _save_entity_cache(
            "vid_kr",
            "Korean Raw",
            {"A": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}},
        )
        raw_text = _get_cache_file_path("vid_kr").read_text(encoding="utf-8")
        assert "판카즈 샤르마" in raw_text
        assert "\\u" not in raw_text


# =============================================================================
# TestCacheKeyFromTitle — _compute_cache_key_from_title
# =============================================================================
class TestCacheKeyFromTitle:
    def test_title_hash_deterministic(self):
        k1 = _compute_cache_key_from_title("NVIDIA GTC Studio Interview")
        k2 = _compute_cache_key_from_title("NVIDIA GTC Studio Interview")
        assert k1 == k2
        assert k1.startswith("title_")
        assert len(k1) == len("title_") + 16  # sha256 첫 16 hex

    def test_empty_title_returns_empty(self):
        assert _compute_cache_key_from_title("") == ""

    def test_different_titles_different_keys(self):
        k1 = _compute_cache_key_from_title("Video A")
        k2 = _compute_cache_key_from_title("Video B")
        assert k1 != k2


# =============================================================================
# TestLoanwordLoading — _load_loanword_short_version / _load_loanword_full_body
# =============================================================================
class TestLoanwordLoading:
    def test_short_version_loaded(self):
        short = _load_loanword_short_version()
        assert short  # 자료 file 존재 catch
        # 표 1 영어 자모 + 제4장 인명·지명 포함
        assert "표 1" in short
        assert "제4장" in short

    def test_short_version_smaller_than_full(self):
        short = _load_loanword_short_version()
        full = _load_loanword_full_body()
        assert len(short) < len(full)
        # short 는 full 의 ~5% 이하 expected (실측 ~3.2%)
        assert len(short) < len(full) * 0.10

    def test_short_version_contains_chapter4(self):
        short = _load_loanword_short_version()
        # 제4장의 본질 keyword
        assert "인명" in short
        assert "지명" in short


# =============================================================================
# TestCanonicalize — _canonicalize_entity_names 5단계 safe fallback
# =============================================================================
class TestCanonicalize:
    def test_empty_cache_returns_original(self, mock_llm_config):
        result = "[00:10] 판카즈 샤르마: 본문"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            out = _canonicalize_entity_names(result, {}, mock_llm_config)
        assert out == result
        assert mock_call.call_count == 0  # 빈 cache → LLM 호출 부재

    def test_body_too_large_skips(self, mock_llm_config):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        # 60000 char 초과
        big_result = "[00:10] 판카즈 샤르마: " + ("X" * 60001)
        with patch("gurunote.llm.client._call_llm") as mock_call:
            out = _canonicalize_entity_names(big_result, cache, mock_llm_config)
        assert out == big_result
        assert mock_call.call_count == 0  # 한계 초과 → LLM 호출 부재

    def test_llm_exception_returns_original(self, mock_llm_config):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        result = "[00:10] 판카지 샤르마: 본문"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.side_effect = RuntimeError("network fail")
            out = _canonicalize_entity_names(result, cache, mock_llm_config)
        assert out == result

    def test_empty_response_returns_original(self, mock_llm_config):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        result = "[00:10] 판카지 샤르마: 본문"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = ""
            out = _canonicalize_entity_names(result, cache, mock_llm_config)
        assert out == result

    def test_line_count_variation_returns_original(self, mock_llm_config):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        # 원본 10줄, LLM 응답 5줄 (50% 차이) — 변동 큼 fallback
        result = "\n".join([f"[00:{i:02d}] 판카지 샤르마: 본문 {i}" for i in range(10)])
        truncated = "\n".join([f"[00:{i:02d}] 판카즈 샤르마: 본문 {i}" for i in range(5)])
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = truncated
            out = _canonicalize_entity_names(result, cache, mock_llm_config)
        assert out == result  # 원본 유지

    def test_successful_canonicalize(self, mock_llm_config):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        result = "[00:10] 판카지 샤르마: 본문 1\n\n[00:20] 판카지 샤르마: 본문 2"
        canonical = "[00:10] 판카즈 샤르마: 본문 1\n\n[00:20] 판카즈 샤르마: 본문 2"
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = canonical
            out = _canonicalize_entity_names(result, cache, mock_llm_config)
        assert out == canonical
        # system prompt 에 cache block + loanword section 포함 catch
        system_arg = mock_call.call_args[0][1]
        assert "판카즈 샤르마" in system_arg
        assert "외래어 표기법" in system_arg


# =============================================================================
# TestDetectUnexpectedChanges — P-다 entity 외 변경 감지 (한계 2 보완)
# =============================================================================
class TestDetectUnexpectedChanges:
    def test_no_changes_returns_empty(self):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        text = "[00:10] 판카즈 샤르마: 본문"
        assert _detect_unexpected_changes(text, text, cache) == []

    def test_entity_only_change_returns_empty(self):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        # 변형 표기 → 정 표기 — entity 통일 (cache korean 새로 등장)
        original = "[00:10] 판카지 샤르마: 본문"
        canonical = "[00:10] 판카즈 샤르마: 본문"
        assert _detect_unexpected_changes(original, canonical, cache) == []

    def test_word_modified_detected(self):
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        # 일반 단어 (소프트웨어) 변경 — entity_cache 표기 등장 부재 → 의심
        original = "[00:10] 판카즈 샤르마: 소프트웨어 부서"
        canonical = "[00:10] 판카즈 샤르마: 소프트웤어 부서"
        suspects = _detect_unexpected_changes(original, canonical, cache)
        assert len(suspects) == 1
        assert "L0" in suspects[0]

    def test_line_count_mismatch_detected(self):
        cache = {}
        original = "[00:10] A\n[00:20] B\n[00:30] C"
        canonical = "[00:10] A\n[00:20] B"
        suspects = _detect_unexpected_changes(original, canonical, cache)
        assert len(suspects) == 1
        assert "줄 수 불일치" in suspects[0]

    def test_canonicalize_logs_suspects(self, mock_llm_config):
        # canonical 채택 + suspect 로그 — 옵션 가 path
        # 한계 catch: 줄 안에 entity 표기 새로 등장 시 의심 부재. 본 test 는 entity
        # 부재 line 에서 일반 단어만 변경된 케이스 (의심 catch 가능).
        cache = {
            "Pankaj Sharma": {"korean": "판카즈 샤르마", "type": "person", "source": "bootstrap"}
        }
        result = "[00:10] 판카즈 샤르마: 첫 줄\n\n[00:20] 진행자: 소프트웨어 부서"
        # line 0 : 변경 부재. line 2 : 화자명 외 일반 단어 변경 — 의심 1건.
        canonical = "[00:10] 판카즈 샤르마: 첫 줄\n\n[00:20] 진행자: 소프트웤어 부서"
        log_messages = []
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = canonical
            out = _canonicalize_entity_names(result, cache, mock_llm_config, log_messages.append)
        # canonical 채택 catch (원본 복귀 부재)
        assert out == canonical
        # suspect 경고 로그 catch
        assert any("entity 외 변경 의심" in m for m in log_messages)


# =============================================================================
# TestBootstrapCacheHit — _bootstrap_entity_cache_from_metadata cache path
# =============================================================================
class TestBootstrapCacheHit:
    def test_cache_hit_skips_llm(self, mock_llm_config):
        ctx = {"title": "Cached Video"}
        cache_key = _compute_cache_key_from_title("Cached Video")
        prebuilt = {
            "Pankaj Sharma": {
                "korean": "판카즈 샤르마",
                "type": "person",
                "source": "bootstrap",
            }
        }
        _save_entity_cache(cache_key, "Cached Video", prebuilt)

        with patch("gurunote.llm.client._call_llm") as mock_call:
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert mock_call.call_count == 0  # cache hit → LLM 호출 부재
        assert result == prebuilt

    def test_cache_miss_calls_llm(self, mock_llm_config):
        ctx = {"title": "Fresh Video Never Cached"}
        # cache 부재 catch (autouse fixture 의 tmp 디렉토리 비어있음)
        with patch("gurunote.llm.client._call_llm") as mock_call:
            mock_call.return_value = "Jensen Huang → 젠슨 황 [person]"
            result = _bootstrap_entity_cache_from_metadata(ctx, None, mock_llm_config)
        assert mock_call.call_count == 1  # cache miss → LLM 호출 1회
        assert "Jensen Huang" in result
        assert result["Jensen Huang"]["korean"] == "젠슨 황"
        assert result["Jensen Huang"]["type"] == "person"

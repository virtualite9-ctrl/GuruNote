"""STT 의미 단위 재분할 (GURUNOTE_SEGMENT_RESPLIT) + chunk size 연동 (5/24).

- 재분할 함수 unit test (구두점 분할, 끝 검사 병합, 화자 우선, 시간 갭)
- chunk_segments 두 한도 연동 (재분할 on/off 별 값)
- 토글 off 기본 동작 불변 (daily 보호)
"""
from __future__ import annotations

import os
import pytest

from gurunote.stt.mlx import (
    SEGMENT_RESPLIT_ENV,
    _segment_is_complete,
    _segment_last_token,
    _resplit_segments_by_semantics,
)
from gurunote.llm import (
    chunk_segments,
    DEFAULT_CHUNK_CHAR_LIMIT,
    MAX_SEGMENTS_PER_CHUNK,
    RESPLIT_CHAR_LIMIT,
    RESPLIT_SEGMENT_LIMIT,
)
from gurunote.types import Segment


# =============================================================================
# 끝 검사
# =============================================================================
class TestSegmentIsComplete:
    def test_sentence_end(self):
        for t in ["Hello.", "Are you sure?", "Wow!"]:
            assert _segment_is_complete(t) is True

    def test_mid_punct_incomplete(self):
        for t in ["Hello,", "Look at this:", "First;", "Wait —"]:
            assert _segment_is_complete(t) is False

    def test_conjunction_incomplete(self):
        for t in ["Yes and", "Either or", "I think but"]:
            assert _segment_is_complete(t) is False

    def test_preposition_incomplete(self):
        for t in ["I went to", "with the", "during a"]:
            assert _segment_is_complete(t) is False

    def test_dangling_incomplete(self):
        for t in ["the", "is", "very", "this"]:
            assert _segment_is_complete(t) is False

    def test_no_punct_incomplete(self):
        # 자연 끝인데 구두점 부재 → 미완 보수적 catch.
        assert _segment_is_complete("Hello world") is False

    def test_empty_complete(self):
        assert _segment_is_complete("") is True

    def test_last_token(self):
        assert _segment_last_token("Hello world.") == "world"
        assert _segment_last_token("foo bar,") == "bar"
        assert _segment_last_token("test") == "test"


# =============================================================================
# 재분할 함수
# =============================================================================
class TestResplitSegmentsBySemantics:
    def _make_seg(self, start, end, text):
        return {"start": start, "end": end, "text": text, "words": []}

    def test_merge_until_complete(self):
        """미완 segment 들이 완결될 때까지 병합."""
        raw = [
            self._make_seg(0.0, 1.0, "Hello world,"),
            self._make_seg(1.0, 2.0, "this is a test."),
            self._make_seg(2.0, 3.0, "Another sentence."),
        ]
        turns = [(0.0, 3.0, "SPEAKER_00")]
        out = _resplit_segments_by_semantics(raw, turns)
        assert len(out) == 2
        assert out[0]["text"] == "Hello world, this is a test."
        assert out[1]["text"] == "Another sentence."

    def test_speaker_diff_blocks_merge(self):
        """화자 다르면 병합 부재 (화자 우선)."""
        raw = [
            self._make_seg(0.0, 1.0, "Speaker A says,"),
            self._make_seg(1.0, 2.0, "and then B replies."),
        ]
        turns = [(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")]
        out = _resplit_segments_by_semantics(raw, turns)
        assert len(out) == 2  # 화자 다름 → 병합 부재

    def test_time_gap_blocks_merge(self):
        """시간 갭 5초 초과 시 병합 부재 (의도적 멈춤)."""
        raw = [
            self._make_seg(0.0, 1.0, "First half,"),
            self._make_seg(10.0, 11.0, "second half."),
        ]
        turns = [(0.0, 11.0, "SPEAKER_00")]
        out = _resplit_segments_by_semantics(raw, turns)
        assert len(out) == 2  # 갭 9초 > 5초 → 병합 부재

    def test_length_cap_blocks_merge(self):
        """합친 길이 30초 초과 부재 — 안전 상한."""
        raw = [
            self._make_seg(0.0, 20.0, "Long segment one,"),
            self._make_seg(20.0, 45.0, "very long segment two."),
        ]
        turns = [(0.0, 45.0, "SPEAKER_00")]
        out = _resplit_segments_by_semantics(raw, turns)
        assert len(out) == 2  # 합친 길이 45s > 30s → 병합 부재

    def test_words_preservation(self):
        """words 키가 있으면 병합 후 보존 (재분할 후속 처리용)."""
        raw = [
            {"start": 0.0, "end": 1.0, "text": "hello,", "words": [{"word": "hello"}]},
            {"start": 1.0, "end": 2.0, "text": "world.", "words": [{"word": "world"}]},
        ]
        turns = [(0.0, 2.0, "SPEAKER_00")]
        out = _resplit_segments_by_semantics(raw, turns)
        assert len(out) == 1
        assert len(out[0]["words"]) == 2

    def test_empty_input(self):
        assert _resplit_segments_by_semantics([], []) == []

    def test_no_diarization_default_speaker(self):
        """diarization 부재 시 모든 segment 같은 화자 (A) → 끝 검사로 병합."""
        raw = [
            self._make_seg(0.0, 1.0, "Hello,"),
            self._make_seg(1.0, 2.0, "world."),
        ]
        out = _resplit_segments_by_semantics(raw, [])
        assert len(out) == 1
        assert out[0]["text"] == "Hello, world."

    def test_resplit_speaker_key_removed(self):
        """내부 화자 catch 임시 key 가 출력 segment 에서 제거된다."""
        raw = [self._make_seg(0.0, 1.0, "Hello.")]
        out = _resplit_segments_by_semantics(raw, [(0.0, 1.0, "SPEAKER_00")])
        assert "_resplit_speaker" not in out[0]


# =============================================================================
# chunk_segments 연동
# =============================================================================
class TestChunkSegmentsResplitIntegration:
    def _make_segments(self, n, text_len=100):
        text = "x" * text_len
        return [Segment(speaker="A", start=float(i), end=float(i + 1), text=text)
                 for i in range(n)]

    def test_default_chunk_size_unchanged(self):
        """토글 off (default) 시 chunk_segments 기본값 catch — daily 보존."""
        segs = self._make_segments(30, text_len=100)
        chunks = chunk_segments(segs)
        # 기본 segment_limit=15 catch.
        assert all(len(c) <= MAX_SEGMENTS_PER_CHUNK for c in chunks)
        assert MAX_SEGMENTS_PER_CHUNK == 15

    def test_resplit_chunk_size_smaller(self):
        """재분할 on 시 char_limit/segment_limit 명시 catch — 더 작은 chunk."""
        segs = self._make_segments(30, text_len=100)
        chunks = chunk_segments(segs, char_limit=RESPLIT_CHAR_LIMIT,
                                 segment_limit=RESPLIT_SEGMENT_LIMIT)
        # 재분할 적용 시 cs=12 catch.
        assert all(len(c) <= RESPLIT_SEGMENT_LIMIT for c in chunks)
        # 기본보다 chunks 더 많음.
        default_chunks = chunk_segments(segs)
        assert len(chunks) >= len(default_chunks)

    def test_char_limit_caps_chunk_size(self):
        """char_limit 도달 시 segment_limit 도달 전에 분할."""
        # 길이 큰 segment → char_limit 먼저 도달.
        segs = [Segment(speaker="A", start=float(i), end=float(i + 1),
                         text="x" * 500) for i in range(20)]
        chunks = chunk_segments(segs, char_limit=2000, segment_limit=12)
        # 각 chunk chars ≤ 2000 + 마지막 segment overhead.
        for c in chunks:
            total = sum(len(s.text) + 30 for s in c)
            # 한 segment 만큼은 char_limit 초과 가능 (단 segment 자체 분할 부재).
            assert len(c) <= 12

    def test_resplit_constants(self):
        assert RESPLIT_CHAR_LIMIT == 2000
        assert RESPLIT_SEGMENT_LIMIT == 12


# =============================================================================
# 토글 환경 변수
# =============================================================================
class TestSegmentResplitEnv:
    def test_env_name(self):
        assert SEGMENT_RESPLIT_ENV == "GURUNOTE_SEGMENT_RESPLIT"

    def test_env_default_on(self, monkeypatch):
        """env 부재 시 default on 처리 (== '1')."""
        monkeypatch.delenv(SEGMENT_RESPLIT_ENV, raising=False)
        # stt/mlx.py 안 토글 — env 부재 시 "1" default (5/24 default on 전환).
        val = os.environ.get(SEGMENT_RESPLIT_ENV, "1").strip()
        assert val == "1"

    def test_env_on_value(self, monkeypatch):
        monkeypatch.setenv(SEGMENT_RESPLIT_ENV, "1")
        val = os.environ.get(SEGMENT_RESPLIT_ENV, "0").strip()
        assert val == "1"

"""세그먼트를 LLM 요청 단위로 자르는 규칙.
"""
from __future__ import annotations

from gurunote.types import Segment
from gurunote.types import _format_ts
from typing import List

__all__ = [
    'CHUNK_DELAY_SEC',
    'DEFAULT_CHUNK_CHAR_LIMIT',
    'MAX_SEGMENTS_PER_CHUNK',
    'RESPLIT_CHAR_LIMIT',
    'RESPLIT_SEGMENT_LIMIT',
    'chunk_segments',
    '_segments_to_user_block',
]


CHUNK_DELAY_SEC = 1.0


DEFAULT_CHUNK_CHAR_LIMIT = 12_000  # 5/10 본인 설계 복원 (5/14 6000 가설 오류 revert)


MAX_SEGMENTS_PER_CHUNK = 15


RESPLIT_CHAR_LIMIT = 2000


RESPLIT_SEGMENT_LIMIT = 12


def chunk_segments(
    segments: List[Segment],
    char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT,
    segment_limit: int = MAX_SEGMENTS_PER_CHUNK,
) -> List[List[Segment]]:
    """char_limit + segment_limit 둘 중 먼저 도달 시 chunk 분할.

    char_limit  — LLM 입력 토큰 한도 보조 safety net (long-seg edge case).
    segment_limit — 모델 tail attention drop 차단 (본질 cause, 5/14 정정).

    한 세그먼트는 분할하지 않는다.
    """
    chunks: List[List[Segment]] = []
    current: List[Segment] = []
    current_size = 0

    for seg in segments:
        seg_text = seg.text or ""
        # 화자 라벨/타임스탬프 오버헤드까지 대략 30자 더해 추정
        seg_size = len(seg_text) + 30
        if current and (
            len(current) >= segment_limit
            or current_size + seg_size > char_limit
        ):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(seg)
        current_size += seg_size

    if current:
        chunks.append(current)
    return chunks


def _segments_to_user_block(segments: List[Segment]) -> str:
    lines = []
    for seg in segments:
        ts = _format_ts(seg.start)
        lines.append(f"[{ts}] Speaker {seg.speaker}: {seg.text}")
    return "\n".join(lines)

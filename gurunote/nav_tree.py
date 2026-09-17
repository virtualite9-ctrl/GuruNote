"""
히스토리 그리드용 3-facet 트리 내비게이션.

Phase 1: Topic(분야) / Person(업로더) / Title(첫글자 버킷) 3축 고정 facet.
각 facet 은 `(label, count, job_ids)` tuple 리스트로 반환된다. UI 가 노드를
클릭하면 `job_ids` 를 필터로 쓰면 되므로, 그리드 쪽은 이 세트 멤버십만
검사하면 된다.

추가 facet(Tag 등) 은 Phase 2 에서 확장.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class FacetNode:
    label: str
    count: int
    job_ids: list[str]


# 제목 첫 문자 → 버킷 라벨
_ASCII_BUCKETS = [
    ("A — G", lambda c: "A" <= c.upper() <= "G"),
    ("H — N", lambda c: "H" <= c.upper() <= "N"),
    ("O — T", lambda c: "O" <= c.upper() <= "T"),
    ("U — Z", lambda c: "U" <= c.upper() <= "Z"),
]
_HANGUL_BUCKETS = [
    ("가 — 마", lambda c: "\uac00" <= c < "\ubc14"),  # 바 앞
    ("바 — 아", lambda c: "\ubc14" <= c < "\uc790"),  # 자 앞
    ("자 — 하", lambda c: "\uc790" <= c <= "\ud7a3"),
]


def _title_bucket(title: str) -> str:
    """제목 첫 유효 문자에서 버킷 라벨 결정. 숫자/특수문자는 '기타'."""
    t = (title or "").strip()
    if not t:
        return "기타"
    c = t[0]
    for label, pred in _ASCII_BUCKETS:
        if pred(c):
            return label
    for label, pred in _HANGUL_BUCKETS:
        if pred(c):
            return label
    return "기타"


def compute_facets(jobs: list[dict]) -> dict[str, list[FacetNode]]:
    """
    `load_index()` 결과를 받아 4-facet 트리 데이터를 생성.

    Returns:
        {
            "field":  [FacetNode, ...]  # 분야별, count 내림차순
            "person": [FacetNode, ...]  # 업로더별, count 내림차순
            "title":  [FacetNode, ...]  # 제목 첫글자 버킷, 라벨 사전순
            "tag":    [FacetNode, ...]  # 태그별 (한 잡이 여러 버킷 기여), count 내림차순
        }
        빈 라벨(`"" / "Unknown"`) 은 "미분류" 로 대체.
    """
    by_field: dict[str, list[str]] = defaultdict(list)
    by_person: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    by_tag: dict[str, list[str]] = defaultdict(list)

    for j in jobs:
        jid = j.get("job_id", "")
        if not jid:
            continue

        field = (j.get("field") or "").strip() or "미분류"
        by_field[field].append(jid)

        person = (j.get("uploader") or "").strip() or "미상"
        by_person[person].append(jid)

        # 제목은 organized_title 우선, 없으면 title
        title = (j.get("organized_title") or j.get("title") or "").strip()
        by_title[_title_bucket(title)].append(jid)

        # 태그: 한 잡이 여러 태그 → 각 태그 버킷에 jid append
        for raw_tag in j.get("tags") or []:
            tag = str(raw_tag).strip()
            if tag:
                by_tag[tag].append(jid)

    def _sort_by_count(d: dict[str, list[str]]) -> list[FacetNode]:
        return [
            FacetNode(label=k, count=len(v), job_ids=v)
            for k, v in sorted(d.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ]

    def _sort_by_label(d: dict[str, list[str]]) -> list[FacetNode]:
        return [
            FacetNode(label=k, count=len(v), job_ids=v)
            for k, v in sorted(d.items(), key=lambda kv: kv[0])
        ]

    return {
        "field": _sort_by_count(by_field),
        "person": _sort_by_count(by_person),
        "title": _sort_by_label(by_title),
        "tag": _sort_by_count(by_tag),
    }


# =============================================================================
# UI state 영속화 (Phase 2 — load/save 는 gurunote/ui/state.py)
# =============================================================================
def default_expand_state() -> dict[str, bool]:
    """기본 4 facet 모두 펼침."""
    return {"field": True, "person": True, "title": True, "tag": True}

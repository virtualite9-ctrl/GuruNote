"""통용 표기 dict auto/user 구조 (A-2 ①) — 단위 테스트.

구조: {English: {"auto": GuruNote 자동 표기, "user": 사용자 수정 표기}}.
- 교정은 user 우선 (user 있으면 user, 없으면 auto).
- 자동 채움은 교정 전 raw 표기를 auto 로 기록, user 는 불변.
- 옛 flat {English: "한국어"} 는 값을 user 로 마이그레이션.
LLM 호출 부재 — 파일 I/O 는 임시 경로로 격리.
"""
from __future__ import annotations

import json

import pytest

import gurunote.llm as L


@pytest.fixture
def tmp_canonical(tmp_path, monkeypatch):
    """canonical_names.json 경로를 임시로 격리 (실제 ~/.gurunote 무변경)."""
    p = tmp_path / "canonical_names.json"
    monkeypatch.setattr(L, "_CANONICAL_NAMES_PATH", p)
    return p


def test_flat_migrated_to_user(tmp_canonical):
    tmp_canonical.write_text(
        json.dumps({"Palmer Luckey": "팔머 럭키"}, ensure_ascii=False), encoding="utf-8"
    )
    d = L._load_canonical_names()
    assert d["Palmer Luckey"] == {"auto": "", "user": "팔머 럭키"}


def test_user_priority_over_auto():
    """user 있으면 user, user 비고 auto 만이면 auto, 둘 다 없으면 미적용."""
    canon = {
        "Palmer Luckey": {"auto": "팰머 러커이", "user": "팔머 럭키"},
        "Demis Hassabis": {"auto": "데미스 하사비스", "user": ""},
    }
    ec = {
        "Palmer Luckey": {"korean": "팰머 러커이", "type": "person"},
        "Demis Hassabis": {"korean": "데미스 하사비스", "type": "person"},
        "Foo Bar": {"korean": "푸 바", "type": "person"},
    }
    L._apply_canonical_to_entity_cache(ec, canon)
    assert ec["Palmer Luckey"]["korean"] == "팔머 럭키"      # user 우선
    assert ec["Demis Hassabis"]["korean"] == "데미스 하사비스"  # auto 적용 (변동 없음)
    assert ec["Foo Bar"]["korean"] == "푸 바"                 # 미수록 불변


def test_autofill_records_raw_preserves_user(tmp_canonical):
    """자동 채움: raw 표기를 auto 로 기록, 기존 user 는 불변."""
    tmp_canonical.write_text(
        json.dumps({"Palmer Luckey": {"auto": "옛auto", "user": "팔머 럭키"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    acc: dict = {}
    raw_cache = {"Palmer Luckey": {"korean": "팰머 러커이"}, "Sam Altman": {"korean": "샘 올트먼"}}
    L._record_auto_spellings(acc, raw_cache, "entity")
    L._persist_auto_spellings(acc)
    saved = json.loads(tmp_canonical.read_text(encoding="utf-8"))
    assert saved["Palmer Luckey"]["auto"] == "팰머 러커이"   # auto 갱신
    assert saved["Palmer Luckey"]["user"] == "팔머 럭키"     # user 보존
    assert saved["Sam Altman"] == {"auto": "샘 올트먼", "user": ""}  # 신규


def test_autofill_speaker_kind():
    acc: dict = {}
    sc = {"A": {"english": "Palmer Luckey", "korean": "팰머 러커이"}}
    L._record_auto_spellings(acc, sc, "speaker")
    assert acc == {"Palmer Luckey": "팰머 러커이"}


def test_effective_user_priority_helper():
    canon = {
        "A Name": {"auto": "에이", "user": "에이유저"},
        "B Name": {"auto": "비", "user": ""},
        "C Name": {"auto": "", "user": ""},
    }
    eff = L._canonical_effective(canon)
    assert eff["a name"] == "에이유저"
    assert eff["b name"] == "비"
    assert "c name" not in eff  # 둘 다 빈값 → 제외


def test_save_atomic_excludes_empty(tmp_canonical):
    L._save_canonical_names({
        "X": {"auto": "엑스", "user": ""},
        "Y": {"auto": "", "user": ""},  # 제외돼야
    })
    saved = json.loads(tmp_canonical.read_text(encoding="utf-8"))
    assert "X" in saved and "Y" not in saved
    assert not (tmp_canonical.parent / (tmp_canonical.name + ".tmp")).exists()


def test_apply_accepts_legacy_flat_dict():
    """기존 호출부(flat canonical 전달)도 _canonical_effective 가 수용 — 하위 호환."""
    ec = {"Palmer Luckey": {"korean": "팰머 러커이", "type": "person"}}
    L._apply_canonical_to_entity_cache(ec, {"Palmer Luckey": "팔머 럭키"})
    assert ec["Palmer Luckey"]["korean"] == "팔머 럭키"

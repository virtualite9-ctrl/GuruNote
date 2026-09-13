"""영어 원문 스크립트 섹션 화자 실명 표기 테스트.

의도: 한국어 번역본은 번역 중 화자 실명이 본문에 들어가는데 영어 원문 섹션은
화자 라벨(Speaker A/B)뿐이라 비대칭이었다. 같은 speaker_cache 매핑을 영어 원문에도
적용해 라벨 → English 실명으로 찍되, 매핑 없는 라벨은 라벨 그대로 fallback(깨지지 않음).

대상:
    - exporter.build_original_script_section (표시 — speaker_names 인자)
    - llm.load_speaker_names (디스크 cache 재사용 헬퍼)
"""
from __future__ import annotations

from unittest.mock import patch

from gurunote import llm
from gurunote.exporter import build_original_script_section
from gurunote.llm import (
    LLMConfig,
    _compute_cache_key_from_title,
    _save_entity_cache,
    load_speaker_names,
    translate_transcript,
)
from gurunote.types import Segment, Transcript


def _make_transcript() -> Transcript:
    return Transcript(
        segments=[
            Segment(speaker="A", start=0.0, end=2.0, text="Hello there."),
            Segment(speaker="B", start=2.0, end=4.0, text="Hi, nice to meet you."),
            Segment(speaker="C", start=4.0, end=6.0, text="Unknown speaker line."),
        ],
        language="en",
    )


def test_speaker_names_replace_labels_with_english():
    """speaker_names 주면 라벨이 English 실명으로, 매핑 없는 라벨은 그대로 fallback."""
    transcript = _make_transcript()
    speaker_names = {"A": "Pankaj Sharma", "B": "Jane Doe"}  # C 는 일부러 누락

    md = build_original_script_section(
        transcript, language="en", speaker_names=speaker_names
    )

    assert "**[00:00] Pankaj Sharma:** Hello there." in md
    assert "**[00:02] Jane Doe:** Hi, nice to meet you." in md
    # 매핑 없는 라벨 C → 기존 라벨 형식 fallback (비거나 깨지지 않음).
    assert "**[00:04] Speaker C:** Unknown speaker line." in md
    # 실명으로 바뀐 라벨은 "Speaker A" 형태로 남지 않는다.
    assert "Speaker A" not in md
    assert "Speaker B" not in md


def test_no_speaker_names_keeps_labels():
    """speaker_names 부재(None) — app.py·cache miss 경로. 기존 라벨 표기 그대로(회귀 없음)."""
    transcript = _make_transcript()

    md = build_original_script_section(transcript, language="en")  # speaker_names 기본 None

    assert "**[00:00] Speaker A:** Hello there." in md
    assert "**[00:02] Speaker B:** Hi, nice to meet you." in md
    assert "**[00:04] Speaker C:** Unknown speaker line." in md


def test_empty_speaker_names_behaves_like_none():
    """빈 dict 도 fallback (load_speaker_names 의 miss 반환값)."""
    transcript = _make_transcript()
    md = build_original_script_section(transcript, language="en", speaker_names={})
    assert "**[00:00] Speaker A:** Hello there." in md


def test_load_speaker_names_roundtrip(tmp_path, monkeypatch):
    """디스크 cache 저장 → load_speaker_names 가 {라벨: english} 반환. prod ~/.gurunote 미접근."""
    # CACHE_DIR 를 tmp 로 격리 (save·load 둘 다 같은 상수를 본다).
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)

    video_context = {"title": "Some Interview Video"}
    # gui.py 와 동일하게 to_context_dict 엔 id 가 없어 cache_key = title hash 로 귀결.
    cache_key = _compute_cache_key_from_title(video_context["title"])
    speakers = {
        "A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"},
        "B": {"english": "Jane Doe", "korean": "제인 도"},
    }
    _save_entity_cache(cache_key, video_context["title"], entities={}, speakers=speakers)

    names = load_speaker_names(video_context)
    assert names == {"A": "Pankaj Sharma", "B": "Jane Doe"}


def test_load_speaker_names_cache_miss_returns_empty(tmp_path, monkeypatch):
    """cache 파일 부재 — 빈 dict (호출자는 라벨 fallback)."""
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    assert load_speaker_names({"title": "No Cache Video"}) == {}


def test_load_speaker_names_none_context_returns_empty():
    """video_context 부재 — 빈 dict."""
    assert load_speaker_names(None) == {}


def test_save_gate_persists_speakers_when_no_entities(tmp_path, monkeypatch):
    """P2 회귀: entity 0건 + speaker 존재 영상도 화자 매핑을 디스크에 저장한다.

    이전 게이트 `if config.enable_phase2 and entity_cache:` 는 entity_cache 가 비면
    speaker_cache 까지 저장을 건너뛰어, load_speaker_names 가 {} → 영어 원문이 라벨로
    fallback (번역본 실명/원문 라벨 불일치). 게이트를 `entity_cache or speaker_cache` 로
    넓힌 뒤로는 화자 매핑이 남아야 한다. 이 테스트는 **수정 전 코드에서 실패**한다.

    translate_transcript 의 외부 경계만 mock — bootstrap(화자만, entity 0건),
    청크 번역(영문 병기 없는 한국어 → entity 추출 0건 유지), xgrammar 점검, CJK 후처리.
    저장 게이트는 실제 코드가 실행된다. CACHE_DIR 는 autouse fixture 로 tmp 격리,
    canonical_names 는 prod 쓰기 방지를 위해 tmp 로 격리.
    """
    monkeypatch.setattr(llm, "_CANONICAL_NAMES_PATH", tmp_path / "canonical_names.json")

    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="Hello there.")],
        language="en",
    )
    video_context = {"title": "Entity-less Conversation"}
    cfg = LLMConfig(
        provider="openai_compatible", model="mock", api_key="mock", base_url="http://mock.local/v1",
    )  # enable_phase2 기본 True

    speakers_only = {"__speakers__": {"A": {"english": "Iliana Bouzali", "korean": "일리아나 부잘리"}}}
    # 영문 병기 없는 한국어 → _extract_entities 가 0건 → entity_cache 빈 채 유지.
    chunk_out = "[00:00] 일리아나 부잘리: 안녕하세요."

    with patch.object(llm, "_check_xgrammar_available", return_value=True), \
         patch.object(llm, "_bootstrap_entity_cache_from_metadata", return_value=speakers_only), \
         patch.object(llm, "translate_chunk_index_mapping_v2", return_value=chunk_out), \
         patch.object(llm, "post_process_cjk", side_effect=lambda result, *a, **k: result):
        translate_transcript(transcript, config=cfg, video_context=video_context)

    # entity 0건이지만 화자 매핑이 디스크에 남아 load 가 실명을 돌려준다 (이전엔 {}).
    assert load_speaker_names(video_context) == {"A": "Iliana Bouzali"}


def test_save_gate_skips_when_phase2_off(tmp_path, monkeypatch):
    """회귀 방어: enable_phase2 off 면 speaker 가 있어도 저장 안 함 (게이트의 phase2 조건 유지)."""
    monkeypatch.setattr(llm, "_CANONICAL_NAMES_PATH", tmp_path / "canonical_names.json")
    transcript = Transcript(
        segments=[Segment(speaker="A", start=0.0, end=2.0, text="Hello there.")],
        language="en",
    )
    video_context = {"title": "Phase2 Off Video"}
    cfg = LLMConfig(
        provider="openai_compatible", model="mock", api_key="mock", base_url="http://mock.local/v1",
        enable_phase2=False,
    )
    with patch.object(llm, "_check_xgrammar_available", return_value=True), \
         patch.object(llm, "translate_chunk_index_mapping_v2", return_value="[00:00] 안녕하세요."), \
         patch.object(llm, "post_process_cjk", side_effect=lambda result, *a, **k: result):
        translate_transcript(transcript, config=cfg, video_context=video_context)

    assert load_speaker_names(video_context) == {}

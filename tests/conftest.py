"""pytest fixtures — Phase 3 CJK post-process 테스트.

본 conftest 는:
- mock_llm_config: 실제 호출 부재, _call_llm 패치 전제
- real_llm_config: 실제 omlx 호출 (slow marker)
- sample_segments: Sub-C fallback 테스트용 Segment 리스트
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path 에 추가 (tests/ 가 패키지 안이 아니라 인접 디렉토리)
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture
def mock_llm_config():
    """Mock LLMConfig — 실제 호출 부재. _call_llm 패치 전제."""
    from gurunote.llm import LLMConfig

    return LLMConfig(
        provider="openai_compatible",
        model="mock-model",
        api_key="mock-key",
        base_url="http://mock.local/v1",
    )


@pytest.fixture(scope="session")
def real_llm_config():
    """실제 omlx 호출용 LLMConfig — .env 로딩 후 from_env. slow marker 와 결합."""
    from gurunote.llm import LLMConfig

    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    return LLMConfig.from_env(provider="openai_compatible")


@pytest.fixture(autouse=True)
def _isolate_entity_cache(tmp_path, monkeypatch):
    """B06 — CACHE_DIR 을 매 test 마다 tmp 로 격리.

    본인 daily 환경의 `~/.gurunote/entity_cache/` 가 test 결과에 영향 주지 부재
    catch (RULE feedback_repl_no_prod_writes 정합). monkeypatch 가 test 종료
    시 자동 복원.
    """
    import gurunote.llm as _llm

    monkeypatch.setattr("gurunote.llm.entities.CACHE_DIR", tmp_path / "entity_cache")


@pytest.fixture(autouse=True)
def _reset_xgrammar_check_cache():
    """5/23 — `_XGRAMMAR_CHECK_CACHE` 를 매 test 시작 시 초기화.

    test 간 cache 오염 차단 — 한 test 의 결과가 다음 test 에 영향 부재.
    """
    import gurunote.llm as _llm

    _llm._XGRAMMAR_CHECK_CACHE["checked_at"] = 0.0
    _llm._XGRAMMAR_CHECK_CACHE["omlx_signature"] = None
    _llm._XGRAMMAR_CHECK_CACHE["result"] = None
    yield


@pytest.fixture
def sample_segments():
    """Sub-C fallback 테스트용 Segment 리스트.

    각 segment 의 start 가 (mm, ss) 매핑 기준 — 02:15, 05:30, 10:00 catch.
    """
    from gurunote.types import Segment

    return [
        Segment(speaker="A", start=135.0, end=138.0, text="This is the first English segment."),
        Segment(speaker="B", start=330.0, end=335.0, text="Second segment with longer English content."),
        Segment(speaker="A", start=600.0, end=605.0, text="Third segment, the last one."),
    ]

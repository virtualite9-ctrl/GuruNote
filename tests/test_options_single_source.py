"""선택지 목록이 진입점마다 다시 복사되지 않는지 검사.

STT 엔진과 LLM provider 목록은 `gui.py`, `app.py`, `MainScreen.jsx` 에 각각 하드코딩돼
있었다. 진입점이 늘어날수록(이제 CLI 도 있다) 조용히 어긋날 자리가 늘어난다.
Python 쪽은 `gurunote.options` 를 참조하게 바꿨고, React 쪽은 리터럴로 남아 있어
드리프트만 잡는다.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from gurunote.options import (
    DEFAULT_STT_ENGINE,
    ENV_FALLBACK_LLM_PROVIDER,
    LLM_PROVIDERS,
    STT_ENGINES,
    USE_ENV_LLM_PROVIDER,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
HARDCODED_STT = re.compile(r'''\[\s*['"]auto['"]\s*,\s*['"]whisperx['"]''')
HARDCODED_LLM = re.compile(r'''\[\s*['"]openai['"]\s*,\s*['"]openai_compatible['"]''')


def jsx_array(source: str, name: str) -> list[str]:
    match = re.search(rf'const\s+{name}\s*=\s*\[(.*?)\]\s*;', source, re.S)
    assert match, f'{name} 리터럴을 찾지 못했다'
    return re.findall(r"""['"]([^'"]+)['"]""", match.group(1))


class TestCanonicalValues:
    def test_defaults_are_members_of_their_lists(self):
        assert DEFAULT_STT_ENGINE in STT_ENGINES
        assert ENV_FALLBACK_LLM_PROVIDER in LLM_PROVIDERS
        # 빈 문자열은 "환경변수를 따른다" 는 뜻이므로 목록에 있어선 안 된다.
        assert USE_ENV_LLM_PROVIDER == ""
        assert USE_ENV_LLM_PROVIDER not in LLM_PROVIDERS

    def test_lists_are_immutable_tuples_without_duplicates(self):
        for values in (STT_ENGINES, LLM_PROVIDERS):
            assert isinstance(values, tuple)
            assert len(set(values)) == len(values)
            assert all(v and v.strip() == v for v in values)

    def test_stt_docstring_in_the_engine_module_still_lists_the_same_engines(self):
        source = (ROOT / 'gurunote/stt.py').read_text(encoding='utf-8')
        for engine in STT_ENGINES:
            assert engine in source, engine


class TestNoEntryPointRedefinesTheLists:
    @pytest.mark.parametrize('relative', ['gui.py', 'app.py'])
    def test_python_entry_points_reference_the_module(self, relative):
        source = (ROOT / relative).read_text(encoding='utf-8')
        assert not HARDCODED_STT.search(source), f'{relative} 이 STT 목록을 다시 하드코딩한다'
        assert not HARDCODED_LLM.search(source), f'{relative} 이 provider 목록을 다시 하드코딩한다'
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == 'gurunote.options'
            for alias in node.names
        }
        assert {'STT_ENGINES', 'LLM_PROVIDERS'} <= imported, imported

    def test_cli_and_pipeline_reference_the_module(self):
        for relative in ['gurunote/cli.py', 'gurunote/pipeline.py']:
            source = (ROOT / relative).read_text(encoding='utf-8')
            assert 'gurunote.options' in source, relative
            assert not HARDCODED_STT.search(source), relative
            assert not HARDCODED_LLM.search(source), relative


class TestReactStaysInStep:
    def test_react_stt_list_matches_the_python_source(self):
        source = (ROOT / 'gurunote/webui/components/MainScreen.jsx').read_text(encoding='utf-8')
        assert jsx_array(source, 'STT_OPTIONS') == list(STT_ENGINES)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__]))

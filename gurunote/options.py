"""파이프라인 선택지의 단일 출처.

STT 엔진과 LLM provider 목록은 `gui.py`(CustomTkinter), `app.py`(Streamlit),
`webui/components/MainScreen.jsx`(React) 에 각각 복사돼 있었다. 진입점이 늘어날수록
어긋날 자리가 늘어나므로 패키지 안의 이 모듈을 정본으로 삼는다.

UI 가 아닌 곳(CLI, 에이전트, 테스트)에서도 같은 목록을 참조할 수 있어야 한다.
"""
from __future__ import annotations

# `gurunote.stt.transcribe(engine=...)` 가 받는 값. "auto" 는 하드웨어를 보고 고른다.
STT_ENGINES = ("auto", "whisperx", "mlx", "assemblyai")
DEFAULT_STT_ENGINE = "auto"

# `gurunote.llm.LLMConfig(provider=...)` 가 받는 값.
LLM_PROVIDERS = ("openai", "openai_compatible", "anthropic", "gemini")

# provider 를 빈 문자열로 넘기면 `LLMConfig.from_env` 가 `LLM_PROVIDER` 환경변수를
# 읽고, 그것도 없으면 아래 값으로 떨어진다. 호출자가 굳이 고르지 않아도 되게
# 빈 문자열을 기본으로 쓰고, 이 상수는 그때 실제로 선택되는 값을 가리킨다.
ENV_FALLBACK_LLM_PROVIDER = "openai"
USE_ENV_LLM_PROVIDER = ""

__all__ = [
    "STT_ENGINES",
    "DEFAULT_STT_ENGINE",
    "LLM_PROVIDERS",
    "ENV_FALLBACK_LLM_PROVIDER",
    "USE_ENV_LLM_PROVIDER",
]

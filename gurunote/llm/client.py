"""LLM provider 호출 경계 — 설정, 재시도, 타임아웃, xgrammar 사전 점검.

이 모듈만 실제 네트워크 호출을 한다. 나머지 llm 하위 모듈은 여기를 통해서만 모델과
이야기한다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Callable
from typing import Optional
import json
import logging
import os
import time

__all__ = [
    'ProgressFn',
    'LLMConfig',
    '_int_env',
    '_float_env',
    '_log',
    '_MAX_RETRIES',
    '_INITIAL_BACKOFF',
    '_call_llm',
    '_call_llm_once',
    'TRANSLATION_MAX_TOKENS',
    'SUMMARY_MAX_TOKENS',
    '_XGRAMMAR_CHECK_CACHE',
    '_XGRAMMAR_CHECK_TTL_SEC',
    '_get_omlx_signature',
    '_check_xgrammar_available',
    'test_connection',
    '_positive_float_env',
    'DEFAULT_LLM_CHUNK_TIMEOUT_SEC',
    'LLM_HTTP_TIMEOUT_SEC',
    '_call_with_wall_clock_timeout',
    '_call_llm_once_with_reason',
    '_call_llm_with_continuation',
]


ProgressFn = Callable[[str], None]


@dataclass
class LLMConfig:
    provider: str            # "openai" | "openai_compatible" | "anthropic" | "gemini"
    model: str
    api_key: str
    base_url: str = ""
    temperature: float = 0.2
    translation_max_tokens: int = 8192
    summary_max_tokens: int = 4096
    # Phase 2 (B01) — entity cache + 화자 cache toggle.
    # True: chunk 1 차단 가능 (bootstrap LLM 호출 1회 + chunk loop 안 cache 갱신).
    # False: 종전 path (chunk 독립 처리, hallucinate 회귀 위험).
    enable_phase2: bool = True

    @classmethod
    def from_env(cls, provider: Optional[str] = None) -> "LLMConfig":
        """
        환경변수에서 LLMConfig 를 생성한다.

        provider 인자를 명시하면 그 값이 우선이고, 없으면 LLM_PROVIDER 환경변수를
        쓴다. 이 인자 덕분에 호출자는 process-wide `os.environ` 을 건드리지
        않고도 요청별로 provider 를 바꿀 수 있다 (Streamlit 같은 멀티 세션
        환경에서 race condition 회피).
        """
        provider = (provider or os.environ.get("LLM_PROVIDER", "openai")).lower().strip()
        temp = _float_env("LLM_TEMPERATURE", 0.2)
        translation_max_tokens = _int_env("LLM_TRANSLATION_MAX_TOKENS", 8192)
        summary_max_tokens = _int_env("LLM_SUMMARY_MAX_TOKENS", 4096)
        if provider == "anthropic":
            return cls(
                provider="anthropic",
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        if provider == "gemini":
            return cls(
                provider="gemini",
                model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        if provider == "openai_compatible":
            return cls(
                provider="openai_compatible",
                model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
                api_key=os.environ.get("OPENAI_API_KEY", "local"),
                base_url=os.environ.get("OPENAI_BASE_URL", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        # 'openai' provider intentionally ignores OPENAI_BASE_URL — that env
        # is only honored by 'openai_compatible'. Otherwise selecting "openai"
        # in the UI while OPENAI_BASE_URL points at oMLX/vLLM would silently
        # route through the local server, defeating the pill's meaning.
        return cls(
            provider="openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            temperature=temp,
            translation_max_tokens=translation_max_tokens,
            summary_max_tokens=summary_max_tokens,
        )


def _int_env(key: str, default: int) -> int:
    try:
        val = int(os.environ.get(key, "").strip())
        return val if val > 0 else default
    except Exception:  # noqa: BLE001
        return default


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip())
    except Exception:  # noqa: BLE001
        return default


def _positive_float_env(key: str, default: float) -> float:
    """0 이하가 의미 없는 값(타임아웃) 전용.

    `_float_env` 에 양수 가드를 넣지 않는 이유는 `LLM_TEMPERATURE=0` 이 정당한
    설정이기 때문이다. 잘못된 입력과 0 이하는 조용히 기본값으로 떨어진다 —
    타임아웃이 0 이면 모든 호출이 즉시 실패한다.
    """
    try:
        value = float(os.environ.get(key, "").strip())
    except Exception:  # noqa: BLE001
        return default
    return value if value > 0 else default


_log = logging.getLogger(__name__)


_MAX_RETRIES = 4


_INITIAL_BACKOFF = 2.0  # 초


def _call_llm(config: LLMConfig, system: str, user: str, max_tokens: int = 4096) -> str:
    """
    단일 LLM 호출 — provider 에 맞춰 디스패치.

    Rate Limit(HTTP 429 / overloaded) 발생 시 지수 백오프(2s → 4s → 8s → 16s)로
    최대 _MAX_RETRIES 회 자동 재시도한다.
    """
    if config.provider in {"openai", "anthropic", "gemini"} and not config.api_key:
        raise RuntimeError(
            f"{config.provider.upper()}_API_KEY 가 .env 에 설정돼 있지 않습니다."
        )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return _call_llm_once(config, system, user, max_tokens)
        except Exception as exc:  # noqa: BLE001
            # Rate Limit / Overloaded 에러만 재시도, 나머지는 즉시 raise
            err_str = str(exc).lower()
            is_retryable = any(
                kw in err_str
                for kw in ("rate limit", "429", "overloaded", "too many requests")
            )
            if not is_retryable or attempt == _MAX_RETRIES:
                raise
            wait = _INITIAL_BACKOFF * (2 ** attempt)
            _log.warning("Rate limit hit (attempt %d/%d). %.1fs 후 재시도…", attempt + 1, _MAX_RETRIES, wait)
            last_exc = exc
            time.sleep(wait)

    # unreachable, but for type checker
    raise last_exc  # type: ignore[misc]


def _call_llm_once(config: LLMConfig, system: str, user: str, max_tokens: int) -> str:
    """실제 1 회 LLM 호출."""
    if config.provider == "anthropic":
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=config.api_key)
        msg = client.messages.create(
            model=config.model,
            max_tokens=max_tokens,
            temperature=config.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"
        ).strip()

    if config.provider == "gemini":
        from google import genai  # type: ignore

        client = genai.Client(api_key=config.api_key)
        resp = client.models.generate_content(
            model=config.model,
            contents=f"{system}\n\n{user}",
            config=genai.types.GenerateContentConfig(
                temperature=config.temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return (resp.text or "").strip()

    # default: openai
    from openai import OpenAI  # type: ignore

    openai_kwargs: dict = {"api_key": (config.api_key or "local")}
    if config.base_url:
        openai_kwargs["base_url"] = config.base_url
    client = OpenAI(**openai_kwargs)
    # thinking_budget=0 — omlx 정식 thinking 강제 (omlx 설정 무관 일관성, 5/23 진단).
    # OpenAI 호환 API 관례상 모르는 파라미터는 무시 — 다른 provider 호환 영향 부재.
    # timeout — HTTP-level read timeout (batch 응답 정확 작동, 5/23 진단 stream=False catch).
    # ThreadPoolExecutor wrap (Step 3 통합)이 manual shutdown 안전망 결합.
    def _create():
        return client.chat.completions.create(
            model=config.model,
            max_tokens=max_tokens,
            temperature=config.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            extra_body={"thinking_budget": 0},
            timeout=LLM_HTTP_TIMEOUT_SEC,
        )
    resp = _call_with_wall_clock_timeout(_create, LLM_HTTP_TIMEOUT_SEC)
    return (resp.choices[0].message.content or "").strip()


TRANSLATION_MAX_TOKENS = 8192


SUMMARY_MAX_TOKENS = 4096


_XGRAMMAR_CHECK_CACHE: dict = {
    "checked_at": 0.0,
    "omlx_signature": None,
    "result": None,
}


_XGRAMMAR_CHECK_TTL_SEC = 21600  # 6시간 fallback


def _get_omlx_signature(config: "LLMConfig") -> Optional[str]:
    """omlx 서버 재시작 감지용 signature — `/v1/models` 응답의 `created` 첫 timestamp.

    omlx 의 모든 model `created` 필드는 서버 시작 시점 단일값 (5/23 실측 catch).
    재시작 시 변경 → cache invalidate.

    Returns:
        signature str, omlx 접근 실패 시 None (TTL fallback 사용).
    """
    if not config.base_url:
        return None
    try:
        import httpx  # noqa: PLC0415
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        resp = httpx.get(
            f"{config.base_url.rstrip('/')}/models",
            headers=headers,
            timeout=5.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        models = data.get("data", [])
        if not models:
            return None
        return str(models[0].get("created", ""))
    except Exception:
        return None


def _check_xgrammar_available(
    config: "LLMConfig",
    log: Optional[ProgressFn] = None,
) -> bool:
    """omlx xgrammar 작동 사전 점검 — 최소 json_schema 요청 1회. 캐싱 적용.

    omlx 0.3.9 의 xgrammar 모듈이 부재 시 schema strict 가 무시되어 구조 강제 부재
    → grammar-recovery loop → wall-clock timeout 다발 (5/22 catch).

    Args:
        config: LLM 호출용. provider 가 openai_compatible 부재 시 skip (True).
        log: 진행 콜백.

    Returns:
        True: xgrammar 정상 (또는 점검 대상 부재). False: 부재 — 호출자가 차단.
    """
    log_fn = log or (lambda _m: None)
    # openai_compatible 외 provider 는 본 점검 부재 (anthropic / gemini 등은 schema path 다름).
    if config.provider != "openai_compatible":
        return True

    now = time.time()
    sig = _get_omlx_signature(config)
    cache = _XGRAMMAR_CHECK_CACHE
    if (
        cache["result"] is not None
        and cache["omlx_signature"] == sig
        and sig is not None
        and (now - cache["checked_at"]) < _XGRAMMAR_CHECK_TTL_SEC
    ):
        return cache["result"]

    test_schema = {
        "type": "object",
        "properties": {"ok": {"type": "string"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    try:
        content, _fr = _call_llm_with_continuation(
            config,
            [{"role": "user", "content": 'Return JSON: {"ok": "yes"}'}],
            max_tokens=32,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "xgrammar_healthcheck",
                    "schema": test_schema,
                    "strict": True,
                },
            },
        )
        parsed = json.loads(content)
        result = isinstance(parsed, dict) and "ok" in parsed
    except Exception as exc:
        log_fn(f"   ⚠ xgrammar 점검 실패: {exc}")
        result = False

    cache["checked_at"] = now
    cache["omlx_signature"] = sig
    cache["result"] = result
    return result


def test_connection(config: Optional[LLMConfig] = None) -> str:
    """현재 설정으로 LLM API 연결을 테스트한다."""
    cfg = config or LLMConfig.from_env()
    text = _call_llm(
        cfg,
        system="You are a connection tester. Reply only with: OK",
        user="ping",
        max_tokens=16,
    )
    if not text.strip():
        raise RuntimeError("LLM 응답이 비어 있습니다.")
    return text.strip()


# chunk 한 건에 허용하는 wall-clock 상한 (B02). 로컬 모델이 느리면 늘린다.
# 프로세스 시작 시 한 번 읽는다 — 값을 바꾸면 앱을 다시 띄워야 반영된다.
DEFAULT_LLM_CHUNK_TIMEOUT_SEC = _positive_float_env("LLM_CHUNK_TIMEOUT_SEC", 60.0)


# HTTP read timeout. wall-clock 상한과 이중 안전장치로 함께 쓴다.
LLM_HTTP_TIMEOUT_SEC = _positive_float_env("LLM_HTTP_TIMEOUT_SEC", 90.0)


def _call_with_wall_clock_timeout(fn, timeout_sec: float, *args, **kwargs):
    """sync 함수를 별 thread 에서 실행 + wall-clock timeout 강제 (B02).

    5/23 수정: `with ThreadPoolExecutor` 의 __exit__ shutdown(wait=True) 가 timeout
    raise 후에도 thread 완료까지 대기하던 결함 catch 후, manual `shutdown(wait=False)`
    로 변경. timeout 시 caller 즉시 raise, thread 는 백그라운드 잔류 (HTTP-level
    timeout 으로 thread 자체도 곧 종료).

    Args:
        fn: sync callable.
        timeout_sec: wall-clock 한계 (초).
        *args, **kwargs: fn 인자.

    Returns:
        fn 의 return 값.

    Raises:
        TimeoutError: timeout_sec 초과 시 즉시 raise (thread 완료 대기 부재).
        fn 자체 raise 시 본 exception propagate.
    """
    ex = ThreadPoolExecutor(max_workers=1)
    future = ex.submit(fn, *args, **kwargs)
    try:
        result = future.result(timeout=timeout_sec)
        # 정상 완료 시 immediate cleanup (wait=True 정합, thread 이미 종료).
        ex.shutdown(wait=True)
        return result
    except FutureTimeoutError:
        # 핵심: wait=False — thread 완료 대기 부재로 caller 즉시 raise.
        # cancel_futures=True — 미시작 future cancel (Python 3.9+).
        ex.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(
            f"LLM 호출 wall-clock timeout — {timeout_sec}초 초과 (B02)"
        )


def _call_llm_once_with_reason(
    config: LLMConfig,
    messages: list,
    max_tokens: int,
    response_format: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> tuple:
    """단일 LLM 호출 — (content, finish_reason) tuple 반환.

    기존 `_call_llm_once` 는 content string 만 반환 (Layer 13 / Layer 14 / Step 3b-3
    등 다른 호출자가 finish_reason 불필요). 본 함수는 Index Mapping path 전용 —
    truncation 명시적 catch + JSON 응답 길이 검증을 위해 finish_reason 노출.

    openai / openai_compatible provider 만 지원 (anthropic / gemini 는 별도 mapping
    필요 — 본 path 의 endpoint 가 OpenAI compat 영역).

    Args:
        timeout: request-level timeout (초). None 이면 SDK 기본값 사용. Phase 4a-1
            에서 xgrammar grammar-recovery loop 조기 차단용으로 사용 (첫 시도 strict
            mode 에 30초 적용). timeout 초과 시 openai.APITimeoutError 발생.

    Wall-clock timeout (B02, 5/20):
        본 함수 안의 client.chat.completions.create 호출은 ThreadPoolExecutor +
        future.result(timeout=DEFAULT_LLM_CHUNK_TIMEOUT_SEC) wrap 으로 wall-clock
        강제. httpx timeout 의 한계 (read streaming 시 wall-clock 부재) catch.

    Returns:
        tuple[str, str]: (content, finish_reason ∈ {"stop", "length", "content_filter", ...})
    """
    from openai import OpenAI  # noqa: PLC0415

    openai_kwargs: dict = {"api_key": (config.api_key or "local")}
    if config.base_url:
        openai_kwargs["base_url"] = config.base_url
    client = OpenAI(**openai_kwargs)

    kwargs: dict = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": config.temperature,
        # thinking_budget=0 — omlx 정식 thinking 강제 (5/23 진단). openai SDK extra_body
        # 경유로 알려지지 않은 파라미터 호환성 catch.
        "extra_body": {"thinking_budget": 0},
        # HTTP-level read timeout (5/23 수정) — batch 응답에서 정확 작동 (stream=False catch).
        # ThreadPool wrapper 결합으로 이중 안전장치.
        "timeout": LLM_HTTP_TIMEOUT_SEC,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if timeout is not None:
        # caller 가 명시 timeout 지정 시 override (xgrammar healthcheck path 등).
        kwargs["timeout"] = timeout

    # B02 — wall-clock timeout 강제 (slow chunk grammar-recovery loop 차단).
    # 5/23 수정: manual shutdown(wait=False) 적용 — timeout 시 caller 즉시 raise.
    resp = _call_with_wall_clock_timeout(
        client.chat.completions.create,
        DEFAULT_LLM_CHUNK_TIMEOUT_SEC,
        **kwargs,
    )
    choice = resp.choices[0]
    return (choice.message.content or ""), (choice.finish_reason or "unknown")


def _call_llm_with_continuation(
    config: LLMConfig,
    messages: list,
    max_tokens: int,
    response_format: Optional[dict] = None,
    max_continuations: int = 3,
    timeout: Optional[float] = None,
) -> tuple:
    """finish_reason='length' 시 자동 continuation.

    truncation 명시 검출 + 이어쓰기 (drift 차단). JSON mode 영역의 continuation
    은 구조 보존 영역에서 본질 한계 영역 — 체크포인트 2 영역은 작은 chunk
    영역 → truncation 부재 가정. 진짜 truncation 시 _call_llm_with_index_mapping
    의 outer retry 영역에서 길이 미스매치 영역 catch + feedback retry.

    Args:
        timeout: request-level timeout (초). None 이면 SDK 기본값. Phase 4a-1 의
            xgrammar grammar-recovery loop 조기 차단용으로 inner 호출에 forward.

    Returns:
        tuple[str, str]: (accumulated_content, last_finish_reason)
    """
    accumulated = ""
    last_finish_reason = "unknown"
    current_messages = list(messages)

    for _cont in range(max_continuations + 1):
        content, finish_reason = _call_llm_once_with_reason(
            config, current_messages, max_tokens, response_format, timeout=timeout
        )
        accumulated += content
        last_finish_reason = finish_reason

        if finish_reason == "stop":
            return accumulated, finish_reason
        if finish_reason == "length":
            # JSON mode 영역의 continuation 은 본질 한계 영역 — outer retry 영역에서 처리
            if response_format and response_format.get("type", "").startswith("json"):
                return accumulated, finish_reason
            # Non-JSON 영역만 continuation
            current_messages = current_messages + [
                {"role": "assistant", "content": accumulated},
                {"role": "user", "content": "Continue from where you stopped. Do not repeat previous content."},
            ]
            continue
        # content_filter 등 — break
        break

    return accumulated, last_finish_reason

"""
GuruNote 🎙️ — 글로벌 IT/AI 구루들의 인사이트
============================================

해외 IT/AI 권위자(Guru)들의 유튜브 인터뷰/팟캐스트 링크를 입력하면
오디오 추출 → **WhisperX-ASR** 화자 분리 STT → LLM 한국어 번역 →
GuruNote 스타일 마크다운 요약까지 단번에 만들어주는 Streamlit 웹 앱.

요구사항:
    - Python 3.10+
    - ffmpeg (yt-dlp 의 mp3 변환)
    - GPU (WhisperX-ASR 7B 추론에 권장. 없으면 AssemblyAI 폴백)
    - requirements.txt 의 패키지들

실행:
    streamlit run app.py
"""

from __future__ import annotations

import os
import tempfile

import streamlit as st
from dotenv import load_dotenv

from gurunote.options import LLM_PROVIDERS, STT_ENGINES
from gurunote.audio import (
    SUPPORTED_EXTS,
    AudioDownloadResult,
    cleanup_dir,
    download_audio,
    extract_audio_from_file,
    is_probably_youtube_url,
)
from gurunote.exporter import autosave_result, build_gurunote_markdown, sanitize_filename
from gurunote.llm import (
    LLMConfig, extract_metadata, summarize_translation,
    test_connection, translate_transcript,
)
from gurunote.settings import save_settings
from gurunote.history import (
    JobLogger, get_job_log, get_job_markdown,
    load_index, new_job_id, save_job,
)
from gurunote import semantic as semantic_search
from gurunote.nav_tree import compute_facets
from gurunote.stats import compute_stats, render_report
from gurunote.stt import install_whisperx, is_whisperx_installed, transcribe
from gurunote.stt_mlx import is_apple_silicon
from gurunote.types import Transcript, _format_ts
from gurunote.updater import check_updates, update_project

# -----------------------------------------------------------------------------
# 부팅
# -----------------------------------------------------------------------------
load_dotenv()

st.set_page_config(
    page_title="GuruNote 🎙️",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------------------------------------------------------
# 헤더 & 사이드바
# -----------------------------------------------------------------------------
def render_header() -> None:
    st.title("GuruNote 🎙️: 글로벌 IT/AI 구루들의 인사이트")
    st.caption(
        "유튜브 링크 하나로 해외 IT/AI 팟캐스트와 인터뷰를 "
        "**화자 분리된 한국어 요약본**으로 변환합니다."
    )
    st.divider()


def render_sidebar() -> dict:
    """사이드바 — 설정값을 dict 로 반환."""
    with st.sidebar:
        st.header("✨ GuruNote 란?")
        st.markdown(
            "- **STT + 화자 분리** — Microsoft WhisperX-ASR (오픈소스)\n"
            "- **IT/AI 전문 톤 한국어 번역** — gpt-5.4 / claude-sonnet-4-6\n"
            "- **인사이트 / 타임라인 / 전체 스크립트** 마크다운 요약\n"
            "- 결과를 `.md` 파일로 다운로드"
        )
        st.divider()

        st.subheader("⚙️ 설정")
        stt_options = list(STT_ENGINES)
        env_stt = os.environ.get("GURUNOTE_STT_ENGINE", "auto").lower().strip()
        stt_default = stt_options.index(env_stt) if env_stt in stt_options else 0
        engine_label = st.selectbox(
            "STT 엔진",
            options=stt_options,
            index=stt_default,
            help=(
                "auto: NVIDIA → WhisperX, Apple Silicon → MLX, 그 외 → AssemblyAI (권장).\n"
                "whisperx: 항상 WhisperX (Distil-Whisper + pyannote, NVIDIA GPU 필요).\n"
                "mlx: 항상 MLX Whisper (macOS Apple Silicon 전용, Metal/MPS 가속).\n"
                "assemblyai: 항상 AssemblyAI Cloud API."
            ),
        )

        env_provider = os.environ.get("LLM_PROVIDER", "openai")
        provider = st.selectbox(
            "LLM Provider",
            options=list(LLM_PROVIDERS),
            index=0 if env_provider == "openai" else (2 if env_provider == "anthropic" else 1),
        )

        st.divider()
        st.subheader("📋 사용법")
        st.markdown(
            "1. 유튜브 인터뷰/팟캐스트 URL 입력\n"
            "2. **GuruNote 생성하기** 클릭\n"
            "3. 결과 탭에서 요약/번역/원문 확인\n"
            "4. `.md` 파일 다운로드"
        )

        st.divider()
        st.caption("Powered by WhisperX-ASR · yt-dlp · Streamlit")

        return {"engine": engine_label, "provider": provider}


def render_dashboard_tab() -> None:
    """대시보드 탭 — 통계 리포트 + 의미 검색 인덱스 빌드/상태."""
    st.subheader("대시보드")
    jobs = load_index()
    stats = compute_stats(jobs)
    st.code(render_report(stats), language="text")

    st.divider()
    st.markdown("#### 의미 검색 인덱스")

    if not semantic_search.is_available():
        st.warning(semantic_search.missing_packages_hint())
        return

    info = semantic_search.index_stats()
    if info.get("built"):
        st.success(
            f"빌드됨 · 모델 `{info.get('model', '?')}` · "
            f"청크 {info.get('num_chunks', 0):,} · "
            f"잡 {info.get('num_jobs', 0):,} · "
            f"빌드 시각 `{info.get('built_at', '')[:19]}`"
        )
    else:
        st.info("아직 빌드된 인덱스가 없습니다. 아래 버튼으로 처음 빌드하세요.")

    col_b, col_c = st.columns(2)
    if col_b.button("Rebuild Semantic Index", use_container_width=True):
        if not jobs:
            st.warning("인덱싱할 작업이 없습니다.")
        else:
            log_lines: list[str] = []
            with st.status("의미 검색 인덱스 빌드 중...", expanded=True) as st_status:
                try:
                    result = semantic_search.build_index(
                        jobs, log=lambda m: (log_lines.append(m), st.write(m))[1],
                    )
                    st_status.update(
                        label=(
                            f"빌드 완료 · 잡 {result.get('num_jobs', 0)} · "
                            f"청크 {result.get('num_chunks', 0)} · "
                            f"스킵 {result.get('skipped', 0)}"
                        ),
                        state="complete",
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"인덱스 빌드 실패: {exc}")

    if col_c.button("Clear Index", use_container_width=True):
        semantic_search.clear_index()
        st.success("인덱스를 삭제했습니다. 새로 빌드하려면 위 버튼을 누르세요.")


def render_search_tab() -> None:
    """의미 검색 탭 — 질의 입력 → 유사 노트 매칭 + 다운로드."""
    st.subheader("의미 검색")

    if not semantic_search.is_available():
        st.warning(semantic_search.missing_packages_hint())
        return
    if not semantic_search.is_index_built():
        st.info(
            "아직 인덱스가 빌드되지 않았습니다. **대시보드** 탭에서 "
            "'Rebuild Semantic Index' 를 먼저 실행하세요."
        )
        return

    with st.form("semantic_search_form"):
        query = st.text_input(
            "질의 (의미/문맥 기반)",
            placeholder="예: AI 가 일자리를 대체할 가능성",
        )
        c1, c2 = st.columns(2)
        top_k = c1.slider("Top-K (잡 단위)", min_value=1, max_value=30, value=10)
        min_score = c2.slider("최소 유사도", min_value=0.0, max_value=1.0, value=0.25, step=0.05)
        submitted = st.form_submit_button("검색", type="primary")

    if not submitted:
        return
    if not query.strip():
        st.warning("질의를 입력하세요.")
        return

    try:
        results = semantic_search.search(query, top_k=top_k, min_score=min_score)
    except Exception as exc:  # noqa: BLE001
        st.error(f"검색 실패: {exc}")
        return

    if not results:
        st.info(f"매칭 결과가 없습니다. (최소 유사도 {min_score:.2f} 이상)")
        return

    st.caption(f"{len(results)} 개 잡 매칭 · 점수 내림차순")
    for r in results:
        score = r.get("score", 0.0)
        title = r.get("title") or "제목 없음"
        job_id = r.get("job_id", "")
        preview = r.get("preview", "")
        with st.expander(f"[{score:.3f}]  {title}", expanded=False):
            st.markdown(f"**Preview (chunk {r.get('chunk_idx', 0)}):**")
            st.write(preview)
            md = get_job_markdown(job_id)
            if md:
                st.download_button(
                    "마크다운 다운로드",
                    data=md.encode("utf-8"),
                    file_name=f"GuruNote_{sanitize_filename(title)}.md",
                    mime="text/markdown",
                    key=f"sem_dl_{job_id}",
                )


_FACET_LABELS = [
    ("field", "주제 (분야)"),
    ("person", "인물 (업로더)"),
    ("title", "제목 (첫글자)"),
    ("tag", "태그"),
]


def _render_nav_tree(jobs: list[dict]) -> None:
    """좌측 트리 내비 — 4 facet 을 st.expander 로 펼침. 클릭 시 필터 session_state."""
    facets = compute_facets(jobs)
    current = st.session_state.get("nav_filter")

    if st.button("× 필터 해제", use_container_width=True, disabled=current is None):
        st.session_state.pop("nav_filter", None)
        st.rerun()

    for key, title in _FACET_LABELS:
        nodes = facets.get(key, [])
        total = sum(n.count for n in nodes)
        with st.expander(f"{title}  ·  {total}", expanded=True):
            if not nodes:
                st.caption("(비어 있음)")
                continue
            for node in nodes:
                is_active = bool(
                    current and current.get("facet") == key and current.get("label") == node.label
                )
                label_txt = node.label if len(node.label) <= 22 else node.label[:21] + "…"
                btn_label = f"{'▸ ' if is_active else ''}{label_txt}  ({node.count})"
                if st.button(
                    btn_label, key=f"nav_{key}_{node.label}",
                    use_container_width=True,
                    type="primary" if is_active else "secondary",
                ):
                    if is_active:
                        st.session_state.pop("nav_filter", None)
                    else:
                        st.session_state["nav_filter"] = {
                            "facet": key,
                            "label": node.label,
                            "job_ids": list(node.job_ids),
                        }
                    st.rerun()


def render_history_tab() -> None:
    """📂 히스토리 탭 — 좌측 트리 내비 + 우측 잡 목록."""
    st.subheader("📂 작업 히스토리")
    jobs = load_index()
    if not jobs:
        st.info("아직 작업 기록이 없습니다. GuruNote 를 생성하면 여기에 자동 저장됩니다.")
        return

    nav_col, list_col = st.columns([1, 3])

    with nav_col:
        _render_nav_tree(jobs)

    with list_col:
        nav = st.session_state.get("nav_filter")
        if nav:
            # 삭제된 잡 id 정합 체크
            valid_ids = {j.get("job_id") for j in jobs}
            active_ids = set(nav.get("job_ids") or []) & valid_ids
            if not active_ids:
                st.session_state.pop("nav_filter", None)
                st.rerun()
            facet_title = dict(_FACET_LABELS).get(nav["facet"], "")
            st.caption(f"활성 필터  ·  {facet_title}  ›  **{nav['label']}**  ({len(active_ids)} 건)")
            filtered_jobs = [j for j in jobs if j.get("job_id") in active_ids]
        else:
            st.caption(f"전체 {len(jobs)} 건")
            filtered_jobs = jobs

        if not filtered_jobs:
            st.info("조건에 맞는 작업이 없습니다.")
            return

        for job in filtered_jobs:
            status = job.get("status", "unknown")
            icon = "✅" if status == "completed" else "❌"
            title = job.get("title", "제목 없음")
            created = (job.get("created_at") or "")[:16].replace("T", " ")
            engine = job.get("stt_engine", "")
            job_id = job.get("job_id", "")
            err = job.get("error_message", "")

            with st.expander(f"{icon} {title}  —  {created}  ·  {engine}", expanded=False):
                if err:
                    st.error(f"오류: {err}")

                col1, col2 = st.columns(2)
                if job.get("has_markdown"):
                    md = get_job_markdown(job_id)
                    if md:
                        col1.download_button(
                            "📥 마크다운 다운로드",
                            data=md.encode("utf-8"),
                            file_name=f"GuruNote_{sanitize_filename(title)}.md",
                            mime="text/markdown",
                            key=f"dl_{job_id}",
                        )

                log_text = get_job_log(job_id)
                if log_text:
                    if col2.button("📋 로그 보기", key=f"log_{job_id}"):
                        st.code(log_text, language="bash")


def render_settings_tab(default_provider: str) -> None:
    st.subheader("⚙️ Settings")
    st.caption("`.env` 를 직접 열지 않아도 이 탭에서 LLM 설정을 저장/테스트할 수 있습니다.")

    with st.form("settings_form"):
        provider = st.selectbox(
            "LLM Provider",
            options=list(LLM_PROVIDERS),
            index=0 if default_provider == "openai" else (2 if default_provider == "anthropic" else 1),
            help="openai_compatible: oMLX / vLLM / Ollama / LM Studio / llama.cpp 서버 등",
        )
        openai_key = st.text_input(
            "OpenAI API Key",
            value=os.environ.get("OPENAI_API_KEY", ""),
            type="password",
        )
        openai_base_url = st.text_input(
            "OpenAI Base URL (Local/Compatible)",
            value=os.environ.get("OPENAI_BASE_URL", ""),
            disabled=provider == "anthropic",
            placeholder="예: http://127.0.0.1:8000/v1",
        )
        openai_model = st.text_input(
            "OpenAI/Compatible Model",
            value=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        )
        anthropic_key = st.text_input(
            "Anthropic API Key",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            type="password",
        )
        anthropic_model = st.text_input(
            "Anthropic Model",
            value=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
        c1, c2, _ = st.columns([1, 1, 2])
        temperature = c1.number_input(
            "Temperature", min_value=0.0, max_value=2.0, step=0.1,
            value=float(os.environ.get("LLM_TEMPERATURE", "0.2") or 0.2),
        )
        tr_max = c2.number_input(
            "번역 Max Tokens", min_value=256, max_value=32768, step=256,
            value=int(os.environ.get("LLM_TRANSLATION_MAX_TOKENS", "8192") or 8192),
        )
        sum_max = st.number_input(
            "요약 Max Tokens", min_value=128, max_value=16384, step=128,
            value=int(os.environ.get("LLM_SUMMARY_MAX_TOKENS", "4096") or 4096),
        )

        save = st.form_submit_button("💾 Save Settings", type="primary")
        test = st.form_submit_button("🧪 Test Connection")

    settings_payload = {
        "LLM_PROVIDER": provider,
        "OPENAI_API_KEY": openai_key,
        "OPENAI_BASE_URL": openai_base_url,
        "OPENAI_MODEL": openai_model,
        "ANTHROPIC_API_KEY": anthropic_key,
        "ANTHROPIC_MODEL": anthropic_model,
        "LLM_TEMPERATURE": str(temperature),
        "LLM_TRANSLATION_MAX_TOKENS": str(int(tr_max)),
        "LLM_SUMMARY_MAX_TOKENS": str(int(sum_max)),
    }

    if save:
        changed, backup = save_settings(settings_payload, create_backup=True)
        st.success(
            f"설정 저장 완료 (변경 {changed}개)"
            + (f" · 백업: `{backup.name}`" if backup else "")
        )

    if test:
        try:
            # 저장하지 않아도 현재 폼 값으로 즉시 테스트
            tmp_cfg = LLMConfig.from_env(provider=provider)
            tmp_cfg.api_key = (openai_key if provider != "anthropic" else anthropic_key).strip()
            tmp_cfg.base_url = openai_base_url.strip()
            tmp_cfg.model = openai_model.strip() if provider != "anthropic" else anthropic_model.strip()
            tmp_cfg.temperature = float(temperature)
            resp = test_connection(tmp_cfg)
            st.success(f"연결 성공: {resp}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"연결 실패: {exc}")

    st.divider()
    st.markdown("#### 🔄 업데이트")
    u1, u2 = st.columns(2)
    if u1.button("업데이트 상태 확인", use_container_width=True):
        try:
            lines: list[str] = []
            status = check_updates(lines.append)
            st.code("\n".join(lines + [status]) if lines else status, language="bash")
        except Exception as exc:  # noqa: BLE001
            st.error(f"업데이트 확인 실패: {exc}")
    if u2.button("업데이트 실행", use_container_width=True):
        try:
            lines: list[str] = []
            with st.status("업데이트 실행 중...", expanded=True):
                update_project(lines.append, upgrade_deps=True)
                for line in lines:
                    st.write(line)
            st.success("업데이트 완료. 앱을 재실행하면 최신 버전이 반영됩니다.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"업데이트 실패: {exc}")


# -----------------------------------------------------------------------------
# 파이프라인 실행
# -----------------------------------------------------------------------------
def run_pipeline(
    engine: str,
    provider: str,
    *,
    youtube_url: str = "",
    local_file_path: str = "",
) -> None:
    """Step 1 → Step 5 실행 + 세션 상태 저장."""
    if not youtube_url and not local_file_path:
        st.error("유튜브 URL 또는 로컬 파일을 입력해주세요.")
        return

    tmp_dir = tempfile.mkdtemp(prefix="gurunote_")
    job_id = new_job_id()
    job_logger = JobLogger(job_id)

    try:
        import time as _time
        _pipeline_start = _time.monotonic()

        # stderr tee 는 Streamlit 에서는 사용하지 않음 — Streamlit 위젯 업데이트는
        # ScriptRunContext 가 바인딩된 메인 스레드에서만 안전하고, 백엔드 워커
        # 스레드(mlx-whisper 등)가 stderr 로 tqdm 을 찍으면 그 콜백이 워커
        # 스레드에서 실행돼 `MissingScriptRunContext` 경고 + 최악의 경우 tee 재귀.
        # 데스크톱 GUI 에만 적용 (gui.py). Streamlit 은 각 Step 완료 시 st.write
        # 로 진행 상황 확인 가능.
        with st.status("GuruNote 파이프라인 실행 중...", expanded=True) as status:
            progress_bar = st.progress(0, text="진행률 0%")

            def set_progress(pct: int, label: str) -> None:
                elapsed = _time.monotonic() - _pipeline_start
                em, es = divmod(int(elapsed), 60)
                eta_str = f"{em}m {es}s"
                if 2 < pct < 100:
                    remaining = max(0, (elapsed / pct * 100) - elapsed)
                    rm, rs = divmod(int(remaining), 60)
                    eta_str += f" | ~{rm}m {rs}s left"
                progress_bar.progress(
                    max(0, min(100, pct)),
                    text=f"{label} ({pct}%)  [{eta_str}]",
                )

            def log(msg: str) -> None:
                ts = _time.strftime("%H:%M:%S")
                st.write(f"[{ts}] {msg}")
                job_logger.write(msg)

            # ----- Step 1: 오디오 준비 -----
            set_progress(5, "Step 1 오디오 준비 중")
            st.write(f"📁 작업 폴더: `{tmp_dir}`")
            if youtube_url:
                st.write("⬇️ **Step 1.** yt-dlp 로 오디오 추출 중…")
                audio: AudioDownloadResult = download_audio(youtube_url, tmp_dir)
            else:
                st.write("🎵 **Step 1.** 로컬 파일에서 오디오 추출 중…")
                audio = extract_audio_from_file(local_file_path, tmp_dir)
            audio_size_mb = os.path.getsize(audio.audio_path) / (1024 * 1024)
            st.write(
                f"✅ `{audio.video_title}` ({audio_size_mb:.1f} MB, "
                f"{int(audio.duration_sec)}s)"
            )
            set_progress(20, "Step 1 완료")
            effective_engine = engine

            # 유튜브 메타데이터 로그 (로컬 파일에는 대부분 비어있음)
            if audio.upload_date:
                st.write(f"📅 게시일: `{audio.upload_date}`")
            if audio.chapters:
                st.write(f"⏱️ 공식 챕터 {len(audio.chapters)} 개 감지")
            if audio.subtitles_text:
                st.write(
                    f"💬 기존 자막 감지 ({len(audio.subtitles_text):,} chars) — "
                    "화자 이름 추론과 챕터 유지에 활용됩니다."
                )

            video_ctx = audio.to_context_dict()

            # ----- Step 2: STT + 화자 분리 -----
            set_progress(25, "Step 2 STT 진행 중")
            st.write("🎙️ **Step 2.** 화자 분리 STT (WhisperX-ASR) …")
            transcript: Transcript = transcribe(
                audio.audio_path, engine=effective_engine, progress=log
            )
            st.write(
                f"✅ {len(transcript.segments)} 세그먼트, "
                f"{len(transcript.speakers)} 화자, "
                f"엔진=`{transcript.engine}`"
            )
            set_progress(55, "Step 2 완료")

            # ----- Step 3: LLM 번역 -----
            set_progress(60, "Step 3 번역 진행 중")
            st.write("🌐 **Step 3.** LLM 한국어 번역 (청크 분할)…")
            # 사이드바 선택을 request-local 하게 주입 (process env 는 절대 건드리지
            # 않음 — Streamlit 동시 세션에서 race 가 나지 않도록).
            llm_cfg = LLMConfig.from_env(provider=provider)
            translated = translate_transcript(
                transcript, config=llm_cfg, progress=log, video_context=video_ctx
            )
            st.write(f"✅ 번역 완료 ({len(translated):,} chars)")
            set_progress(82, "Step 3 완료")

            # ----- Step 4: 요약본 생성 -----
            set_progress(86, "Step 4 요약 진행 중")
            st.write("📝 **Step 4.** GuruNote 스타일 요약본 생성…")
            summary_md = summarize_translation(
                translated,
                title=audio.video_title,
                config=llm_cfg,
                progress=log,
                video_context=video_ctx,
            )
            st.write("✅ 요약 완료")
            set_progress(91, "Step 4 완료")

            # ----- Step 4.5: 메타데이터 자동 추출 (제목/분야/태그) -----
            set_progress(93, "Step 4.5 분류 메타 추출 중")
            st.write("🏷️ **Step 4.5.** 분류 메타데이터(제목/분야/태그) 추출…")
            video_meta = {
                "title": audio.video_title,
                "uploader": audio.uploader,
                "tags": getattr(audio, "tags", None) or [],
            }
            metadata = extract_metadata(
                translated, video_meta=video_meta, config=llm_cfg, log=log,
            )
            if metadata:
                st.write(
                    f"✅ 분야: `{metadata.get('field', '')}` · "
                    f"태그: {metadata.get('tags', [])}"
                )
            set_progress(95, "Step 4.5 완료")

            # ----- Step 5: 마크다운 조립 -----
            set_progress(96, "Step 5 마크다운 조립 중")
            st.write("📦 **Step 5.** 마크다운 조립…")
            full_md = build_gurunote_markdown(
                title=audio.video_title,
                webpage_url=audio.webpage_url,
                summary_md=summary_md,
                translated_text=translated,
                transcript=transcript,
                uploader=audio.uploader,
                stt_engine=transcript.engine,
                upload_date=audio.upload_date,
                chapters=audio.chapters,
                subtitles_source=audio.subtitles_source,
                organized_title=metadata.get("organized_title", ""),
                field=metadata.get("field", ""),
                tags=metadata.get("tags", []),
            )
            st.write("✅ 완료")
            set_progress(100, "모든 단계 완료")

            status.update(label="GuruNote 생성 완료 🎉", state="complete", expanded=False)

        # 히스토리에 자동 저장 (분류 메타 포함)
        save_job(
            job_id,
            title=audio.video_title,
            source_url=audio.webpage_url,
            stt_engine=transcript.engine,
            llm_provider=provider,
            status="completed",
            duration_sec=audio.duration_sec,
            num_speakers=len(transcript.speakers),
            full_md=full_md,
            organized_title=metadata.get("organized_title", ""),
            field=metadata.get("field", ""),
            tags=metadata.get("tags", []),
            uploader=audio.uploader or "",
            upload_date=audio.upload_date or "",
        )
        log("💾 히스토리에 저장됨")

        # autosave
        try:
            saved = autosave_result(full_md, audio.video_title)
            log(f"💾 Autosave: {saved}")
        except Exception:  # noqa: BLE001
            pass

        # 세션 상태에 저장 → 탭 렌더링에서 사용
        st.session_state["result"] = {
            "audio": audio,
            "transcript": transcript,
            "translated": translated,
            "summary_md": summary_md,
            "full_md": full_md,
        }
    except Exception as exc:  # noqa: BLE001
        st.error(f"파이프라인 실행 중 오류: {exc}")
        st.exception(exc)
        # 실패도 히스토리에 기록
        save_job(
            job_id,
            title=youtube_url or local_file_path or "unknown",
            source_url=youtube_url or local_file_path,
            stt_engine=engine,
            llm_provider=provider,
            status="failed",
            error_message=str(exc),
        )
    finally:
        job_logger.close()
        cleanup_dir(tmp_dir)


# -----------------------------------------------------------------------------
# 결과 렌더링
# -----------------------------------------------------------------------------
def render_results() -> None:
    result = st.session_state.get("result")
    if not result:
        return

    audio: AudioDownloadResult = result["audio"]
    transcript: Transcript = result["transcript"]
    translated: str = result["translated"]
    summary_md: str = result["summary_md"]
    full_md: str = result["full_md"]

    st.divider()
    st.subheader(f"🎉 결과: {audio.video_title}")

    file_name = f"GuruNote_{sanitize_filename(audio.video_title)}.md"
    st.download_button(
        label="📥 GuruNote 마크다운 다운로드",
        data=full_md.encode("utf-8"),
        file_name=file_name,
        mime="text/markdown",
        type="primary",
    )

    tab_summary, tab_translation, tab_original = st.tabs(
        ["📌 GuruNote 요약본", "🇰🇷 전체 번역 스크립트", "🇺🇸 영어 원문"]
    )

    with tab_summary:
        st.markdown(summary_md)

    with tab_translation:
        st.markdown(translated)

    with tab_original:
        for seg in transcript.segments:
            ts = _format_ts(seg.start)
            st.markdown(f"**[{ts}] Speaker {seg.speaker}:** {seg.text}")


# -----------------------------------------------------------------------------
# 메인
# -----------------------------------------------------------------------------
def main() -> None:
    render_header()
    settings = render_sidebar()
    tab_run, tab_history, tab_dashboard, tab_search, tab_settings = st.tabs(
        ["🎧 GuruNote 생성", "📂 히스토리", "📊 대시보드", "🔎 의미 검색", "⚙️ Settings"]
    )

    with tab_run:
        st.subheader("🎧 오디오 소스 선택")
        input_tab_yt, input_tab_local = st.tabs(["🔗 유튜브 URL", "📁 로컬 파일"])

        with input_tab_yt:
            url = st.text_input(
                "유튜브 URL",
                placeholder="https://www.youtube.com/watch?v=...",
                label_visibility="collapsed",
            )
            yt_submitted = st.button(
                "GuruNote 생성하기", type="primary", key="btn_yt"
            )

        with input_tab_local:
            uploaded = st.file_uploader(
                "동영상 또는 오디오 파일을 업로드하세요",
                type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTS)],
                help=f"지원 형식: {', '.join(sorted(SUPPORTED_EXTS))}",
            )
            local_submitted = st.button(
                "GuruNote 생성하기", type="primary", key="btn_local"
            )

        # WhisperX 미설치 감지 + 안내
        # mlx 또는 Apple Silicon 의 auto 라우팅에서는 WhisperX 가 필요 없으므로 스킵
        engine_to_use = settings["engine"]
        if yt_submitted or local_submitted:
            needs_whisperx = (
                engine_to_use == "whisperx"
                or (engine_to_use == "auto" and not is_apple_silicon())
            )
            if needs_whisperx and not is_whisperx_installed():
                st.warning(
                    "WhisperX-ASR 패키지가 설치되어 있지 않습니다. "
                    "아래에서 설치하거나 AssemblyAI 로 전환하세요."
                )
                col_install, col_switch, _ = st.columns([1, 1, 2])
                if col_install.button("📦 WhisperX 설치", key="btn_install_vv"):
                    with st.status("WhisperX 설치 중…", expanded=True):
                        ok = install_whisperx(progress=lambda m: st.write(m))
                    if ok:
                        st.success("설치 완료! 다시 'GuruNote 생성하기' 를 눌러주세요.")
                    else:
                        st.error("설치 실패. AssemblyAI 로 전환하거나 수동 설치를 시도해주세요.")
                    st.stop()
                if col_switch.button("🔄 AssemblyAI 사용", key="btn_switch_aai"):
                    engine_to_use = "assemblyai"
                    st.info("STT 엔진을 AssemblyAI 로 전환합니다.")
                else:
                    st.stop()

        if yt_submitted:
            if not is_probably_youtube_url(url):
                st.error("올바른 유튜브 URL 을 입력해주세요.")
            else:
                run_pipeline(
                    engine=engine_to_use,
                    provider=settings["provider"],
                    youtube_url=url,
                )

        if local_submitted:
            if not uploaded:
                st.error("파일을 먼저 업로드해주세요.")
            else:
                tmp_upload = tempfile.mkdtemp(prefix="gurunote_upload_")
                local_path = os.path.join(tmp_upload, uploaded.name)
                with open(local_path, "wb") as f:
                    f.write(uploaded.getbuffer())
                run_pipeline(
                    engine=engine_to_use,
                    provider=settings["provider"],
                    local_file_path=local_path,
                )
                cleanup_dir(tmp_upload)

        render_results()

    with tab_history:
        render_history_tab()

    with tab_dashboard:
        render_dashboard_tab()

    with tab_search:
        render_search_tab()

    with tab_settings:
        render_settings_tab(settings["provider"])

    st.divider()
    st.caption(
        "Powered by **Microsoft WhisperX-ASR** · OpenAI / Anthropic · yt-dlp · Streamlit"
    )


if __name__ == "__main__":
    main()

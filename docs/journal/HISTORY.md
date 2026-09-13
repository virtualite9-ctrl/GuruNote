# GuruNote 역사 — 시간순

> 2026-04-11 첫 commit ~ 2026-05-24 v1.0.0.0 선언 + main 통합. 통합 main 트리 412 commit + archive/main-pre-cli 211 commit + 183 test 통과. 1차 사료는 `docs/wip/session_history_digest.md` (Claude Code 세션 18개, 4/19~5/24) + git log + README/CHANGELOG. **Phase 0 (4/11~18) 일부는 본인 기억 기반 2차 사료** — 본 문서에서 명시.

## 0. 시작 (2026-04-11, 2차 사료)

### PRD — 본인 메모

해외 IT/AI **구루(Guru)** 인사이트(Jensen Huang, Sam Altman 등)가 매일 쏟아지는데 한국어로 정리된 자료는 늦거나 부정확. 구루 영상/팟캐스트를 한국어 노트로 자동 정리하는 데스크톱 앱을 만든다.

- **이름 유래**: 구루들의 인사이트 노트
- **초기 스택**: Streamlit + yt-dlp + AssemblyAI + OpenAI/Anthropic
- **프롬프트 4원칙**:
  1. GuruNote 수석 에디터 페르소나
  2. 화자 실명 추론
  3. 전문 용어 영문 병기
  4. 구어체 다듬기
- **첫 commit 사고**: `1079431` push 시 GitHub 403 권한 catch — 본인 catch 후 해결

### 첫 commit 흐름

```
4bcbee6  04-11 07:42  Initial commit
1079431  04-11 22:55  Step 1 scaffolding: requirements, env, audio download UI
4ecbf77  04-11 23:10  full 5-step pipeline + VibeVoice-ASR
ab86b9e  04-12 08:46  Codex review (hotwords, token budget, env mutation)
30459d9  04-12        v0.1.0 README + CHANGELOG
5584096  04-12        Gemini review hardening
830cf90  04-12        CustomTkinter desktop GUI (Streamlit 대체)
```

## 1. STT 엔진 여정 (4/11~v0.6)

| 시기 | 엔진 | 사건 |
|------|-----|------|
| 4/11 v0.1.0 | **VibeVoice-ASR** | "적극 도입" — 5-step 파이프라인 primary STT |
| ~ v0.3 | VibeVoice + AssemblyAI fallback | RTX5090 32GB **OOM (32분 처리)** catch |
| **v0.4.0** | **WhisperX 전면교체** | NVIDIA GPU 정합 (faster-whisper + diarization) |
| **v0.6.0** | **mlx-whisper 합류** | Mac MLX (Apple Silicon GPU) 추가 |
| 5/24 (현재) | mlx-whisper (Mac) + WhisperX (NVIDIA) + pyannote community-1 | **AssemblyAI 완전 제거 = 완전 로컬** |
| 2026-10 재평가 후보 | **Apple SpeechAnalyzer** | 2026-05 발견(Kanary Voice 계기), on-device — 아래 평가 |

**VibeVoice / Nemotron Omni 통합 모델 평가** (시점 기록 부재 — 본인 기억 2차 사료):
- 한국어 ASR 정확도 / 로컬 실행 / 화자 분리 분리성 부족 → 기각
- 재평가 예정: **2026-10** (Appendix B)

**Apple SpeechAnalyzer 재평가 후보** (2026-05 발견, Kanary Voice 계기 — ADR 아님, 미결정 후보):
- on-device, macOS 26 Tahoe + Apple Silicon, MacWhisper large-v3-turbo 대비 **약 55% 빠름**, 한국어 `ko_KR` 지원.
- 단 **화자 분리는 별도**(SpeakerKit = pyannote v4 community-1 포팅이 따로 필요) + Swift 경계 + Phase 5 재검증 필요.
- VibeVoice 와 달리 **실용 후보**로 분류. 재평가 시점은 위 2026-10 라인과 같이 본다(Appendix B).

## 2. GUI 여정 (Streamlit → CustomTkinter → PySide6 폐기 → pywebview + React)

| 시기 | GUI | 사건 |
|------|-----|------|
| v0.1.0 | Streamlit | 초기 5-step UI |
| **v0.1.1** (PR #4) | **CustomTkinter** | "백엔드 직접 호출, Tauri는 오버엔지니어링" — PR #4 자료 |
| 4/19~20 | **PySide6 + PyWebView 시도** | `feat/webview-ui` 브랜치, "경로 C-1: PyWebView + HTML/CSS/JS + gurunote/* 로직 그대로 재사용" (4/19 16:05 본인 결정) |
| 4/20 14:43 | (계속) | "Phase 1-B MVP 완전 성공. end-to-end 검증 완료" |
| 4/20 15:11 | (계속) | PR #107 (PyWebView UI Phase 1-B) draft |
| 4/27 07:32 | **PySide6 폐기 → pywebview + React 신축** | "Phase 2B-0: 신축 baseline 준비 (미커밋 폐기 + Phase 1-C vanilla 폐기)" — vanilla→React 전환 동기 |
| 4/27 ~ 5/9 | Phase 2B-1 ~ 2B-6d | React 신축 시리즈 (Sidebar/MainScreen/HistoryScreen/EditorScreen/DashboardScreen/SettingsScreen) |
| 현재 | pywebview + React + Material 3 | gurunote/webui/ |

**GUI 기술 여러 번 재고** (Python GUI ↔ 웹 GUI 왕복) — 1년에 4번 전환 (Streamlit / CustomTkinter / PySide6 / pywebview+React).

## 3. 정체성 진화

| 시기 | 정체성 | 사료 |
|------|--------|-----|
| 4/11 PRD | **"IT/AI 구루 요약 앱"** | PRD 본인 메모 (2차) |
| 시점 부재 | **"24/7 지식 증류기 + Obsidian"** | WORK_ORDER (시점 기록 부재, 본인 기억 2차) |
| 5/24 (현재) | **"모델 비의존 한국어 지식 정리"** | Phase 5 통합 후 본인 결정 — STT 재분할 + char_limit이 모델 capability 의존 부재 path catch |

## 4. Phase 시간순 (UI Phase 0~2B + 백엔드 품질 Phase 1~5)

### Phase 0 — v0.1.0 ~ v0.8.0.6 (4/11~19, 2차 사료 일부)

| 시기 | 일/commit | 사건 |
|------|----------|------|
| 4/11 | 4bcbee6 | Initial commit |
| 4/11 22:55 | 1079431 | Step 1 scaffolding (yt-dlp + audio download UI) |
| 4/11 23:10 | 4ecbf77 | 5-step pipeline + VibeVoice-ASR |
| 4/12 | 830cf90 (PR #4) | CustomTkinter 추가 (Streamlit 대체) |
| 4/13~17 | 다수 PR | settings dialog (#5), local file (#6), openai_compatible LLM (#8), update workflow (#9), YouTube metadata (#11), 모델 갱신 (#12), GUI redesign (#14) |
| 4/19 | 9b6c621 | v0.8.0.6 macOS SSL 인증서 fix (certifi context) — **main 브랜치 마지막 v0.x** |

### Phase 1 (UI Phase 1-A/B/C) — feat/webview-ui (4/19~4/22)

| 시기 | commit/사건 | 사료 (1차 — session_history_digest) |
|------|------------|----------------------------------|
| 4/19 13:59 | 본인: "이 프로젝트를 https://github.com/avlp12/GuruNote 에 커밋/PR 할 예정" | 세션 1 첫 메시지 |
| 4/19 15:50 | 본인: "Phase 2 시작하기 전에 멈춰줘" | 본인 신중함 |
| 4/19 15:53 | 본인: "PyWebView 현실적 제약도 같이 조사" | webview 채택 동기 |
| 4/19 16:05 | 본인: **"경로 C-1 확정. PyWebView + HTML/CSS/JS + gurunote/* 로직 그대로 재사용"** | Phase 1 결정 |
| 4/20 11:03 | 본인: "Phase 1-B 진입 전 외부 11 commit 정체 확인 먼저" | 본인 신중함 |
| 4/20 14:43 | 본인: **"Phase 1-B MVP 완전 성공. end-to-end 검증 완료"** | Phase 1-B 완료 |
| 4/20 15:11 | 본인: PR #107 작성 (PyWebView UI Phase 1-B draft) | |
| 4/22 05:59 | 본인: "A. UI Commit 시작. 다만 Commit 2 (목록 view) 만. Commit 3 (detail) 은 오늘 안 함" | Phase 2A Commit 2 시작 (Tailwind redesign 첫 시도) |
| 4/23 02:33 | 본인: **"[Request interrupted by user for tool use] STOP. 진행 중단. 3번 (No) 선택"** | **Commit 2 aborted** ❗ |

### Phase 2A — Tailwind redesign 진입 (4/24~25)

| 시기 | commit/사건 | 사료 |
|------|------------|-----|
| 4/24 | `cedae0e` | chore: initialize Phase 2A (Tailwind redesign branch) |
| 4/24 | docs/legacy/design/KICKOFF_PHASE_2A.md | Decision 1: License 전환 (MIT → Elastic 2.0), Decision 2~4 디자인 자산 |
| 4/25 00:33 | 본인: "Commit 2 시작. 옵션 C (Tailwind CDN + 기본 layout + 생성 화면 idle)" | Commit 2 재시작 |
| 4/25 01:24 ~ 13:01 | Commit 2 — Step 1 자산 / Step 2 Material 3 CSS / Step 3a~3c | |
| 4/25 13:13 | `4d7222f` | Phase 2A Commit 2: Material 3 sidebar + frameless titlebar + MainScreen idle |
| 4/25 **13:49** | 본인: **"Phase 2A — Commit 2 Revert + Commit 3a 준비"** | **Commit 2 Revert 결정** |
| 4/25 13:58 | 본인: "Commit 2 Revert 후속: 자산 영구 보존 위치 이동 + README + **archive push**" | `archive/commit-2-aborted` 브랜치 작성 |
| 4/25 14:11 | `31f59e3` | Phase 2A Commit 3a Step 3a-1: 자산 복원 + Babel 검증 |
| 4/25 | `5f8f1da`, `b1cd138` | Step 3a-2, Step 0 (어제 누락분 보강) |

### Phase 2B — React 신축 (4/27~5/2, 514 commits 절정)

| 시기 | commit/사건 |
|------|------------|
| 4/27 07:32 | `2160a66` Phase 2B-0: 신축 baseline 준비 (vanilla 폐기 + clean React entry) |
| 4/27 07:47 | `6376385` Phase 2B-1: Sidebar + App + 5 화면 placeholder |
| 4/27 08:16 | 본인: "Phase 2B-1 재시작: Sidebar 우리 코드로 신축 (cp 폐기)" |
| 4/27 08:38 | `598ead0` Phase 2B-2: MainScreen — 생성 화면 + 파이프라인 + 결과 4탭 |
| 4/27 10:41~12:38 | `0158942` 2B-3a HistoryScreen 카드 그리드 / 2B-3b 검색·필터 |
| 4/28 | `ebb8f2f` 2B-3c HistoryScreen 정렬+카운트 / `dbe3c79` 2B-3d Facet tree + Detail |
| 4/29~5/2 | 2B-4a EditorScreen / 2B-4b DashboardScreen / 2B-4c SettingsScreen (LLM/STT, Obsidian/Notion, 고급) |
| 5/2 | 2B-5a 라이브러리 wiring / 2B-5b Stale 라벨 / 2B-5b-2 EditorScreen 에러 + 복구 |
| 5/2~ | 2B-6a TopBar + breadcrumb / 2B-6b EditorScreen split / 2B-6b-2 Sidebar appbar / 2B-6c DashboardScreen 재구성 / 2B-6d ⌘K SearchPalette |

### Phase 2B-3-backend Layer 1~15 (5/9~11) — UI/문구 표기 fix

> Layer = **frontend + LLM prompt + 화자 다듬기** (UI 정책 자료). 백엔드 번역 본체 Phase 1~5보다 **선행**.

| 시기 | commit | Layer 사건 |
|------|--------|----------|
| 5/8 15:43 | 본인 세션 | "Phase 2B-3-backend Step 3b-2 보류 + 본질 진단 진입" — Layer 작업 진입 |
| 5/8 16:09 | 본인 세션 | Layer 1 fix 진입 |
| 5/9 00:58 | 본인 세션 | "본질 catch 정정 — 라이브러리 vs 모델 영역 분리" |
| 5/9 16:30 | `d9c5f0b` | Layer 1: pyannote max_speakers + embedding clustering |
| 5/9 18:31 | `1846098` | Layer 5+6: LLM hallucination cascading + STT noise filter |
| 5/9 23:27 | `c7e9e1a` | Layer 7: ResultPanel 4 tab DetailPanel + EditorScreen 통합 |
| 5/9 23:30 | `cf4a7bd` | Layer 8: 고유명사 한국어 표기법 일관성 |
| 5/9 23:39 | `c2da2d3` | **Layer 8 fix-up: Tiffany Janzen 표준 표기 (잰슨→잔젠)** ⭐ |
| 5/9 14:35 (세션) | 본인 사료 | **"티파니 잰슨이 아니라 티파니 잔젠 (Tiffany Janzen). 외국인 인명 표준 표기법에 따를 것"** — Layer 8 사용자 catch 시점 |
| 5/10 00:09 | `a512b12` | Layer 9: markdown transcript 가독성 정합 |
| 5/10 00:58 | `027f243` | Layer 13: 화자 표기 한국어 번역 + entity 영문 병기 명확화 |
| 5/10 01:59 | `12e1868` | Layer 13 fix-up #2: 화자 라벨 첫 등장 영문 병기 누락 fix |
| 5/10 19:01 | `d30c782` | Layer 11: Rule 11 한자/일본어 차단 + _SHARED_LANG_RULES |
| 5/10 20:27 | `ee8b616` | Layer 14: transcript line break 정규화 |
| 5/11 00:34 | `ece961e` | Layer 15: METADATA prompt _SHARED_LANG_RULES inline + title 정합 |
| 5/11 21:41 | `d7a726b` | Layer 15 fix-up #1: title hallucination 가이드라인 강화 |

### 백엔드 품질 Phase 1~5 (5/16~24) — 번역 본체

> Layer 시리즈 후 일주일 gap (5/12~15 정전 대비 catch). Layer = UI 정책, **본 Phase = 번역 LLM 본체 품질**.

| 시기 | commit | 사건 |
|------|--------|-----|
| 5/14 09:36 | (HANDOFF) | `HANDOFF_POWER_OUTAGE_2026-05-14.md` 작성 (정전 대비, HEAD 3f3f04d, stash 보존) |
| 5/16 01:00 | `c68aab8` | **Phase 1 Redesign: Index Mapping + json_schema strict + segment cap 15 + post-process** |
| 5/17 20:08 | `b447a11` | **Phase 4a-1: xgrammar selective disable + A-3 timeout dead code revert** |
| 5/18 19:00 | `cdbdc67` | **Phase 3: 한자/일본어 0건 후처리 (Sub-path A+B+C)** |
| 5/18 21:25 | `47c3448` | Phase 3 마무리: unit tests + 의존성 등록 |
| 5/19 23:27 | `22927fc` | **Phase 2 (B01) Step B: entity cache helper + unit test** |
| 5/19 23:47 | `f9c2da2` | **Phase 2 (B01) Step C: translate_transcript 통합 + Rule 12** |
| 5/20 08:20 (세션) | 본인 사료 | **"판카지 샤르마 회귀 진단 우선"** — B06 동기 catch |
| 5/20 16:25 | `2ed4701` | **B02: slow chunk wall-clock timeout (ThreadPoolExecutor wrap)** |
| 5/21 21:03 | `4a8f281` | **B06 (Phase 2B-3): entity_cache 디스크 + 외래어 표기법 + 표기 통일** |
| 5/22 00:08 | `8fdc2a8` | B06 verify 통과: 판카지 회귀 차단 + 캐시 적중 |
| 5/22 17:23 | `9afcc93` | B06 한계 2: canonicalize 미세 본문 변경 차단 |
| 5/22 17:26 | `988b4c1` | B02 한계 1: R1 padding fallback |
| 5/22 20:57 | `f58d5f2` | B06 보완 verify 통과 |
| 5/23 12:07 | `f314d6e` | B02 wall-clock timeout 수정 (ThreadPoolExecutor with 결함 fix) |
| 5/23 13:11 | `97855bd` | B02 R2: 즉시 padding → strict retry → fallback |
| 5/23 14:11 | `39652c6` | (가) 옵션 A prototype: 2-pass 분리 (자유 번역 → 정렬) |
| 5/23 16:01 | `7a397fa` | **(가) 2-pass 보강: A1 rule 충돌 해소 + A5 prefix strip** |
| 5/23 (later) | `6b94a49` | **(가) 화자 라벨 코드 부착: 식별 1회 + 결정론 부착** |
| 5/23 (later) | `8ecd276` | pyannote diarization 모델 변경: 3.1 → community-1 (speaker confusion 감소) |
| 5/23 23:42 | `599c94b` | 2-pass 빈 output 복구 시퀀스 (3단계 안전망) |
| 5/24 12:28 | `527d2ea` | **Phase 5: STT 의미 단위 재분할 + chunk size 자동 (재분할 토글)** |

### docs 정리 (5/24)

| 시기 | commit | 사건 |
|------|--------|-----|
| 5/24 | `4f2db79` | docs: 옛 UI 작업 문서 legacy로 정리 이동 (37 rename) |
| 5/24 | `373d5db` | docs: Phase 5 검증 산출물 보존 (prototype + 보고서) |
| 5/24 | `5c3c240` | docs: 18개 세션 사료화 (역사 1차 자료) |
| 5/24 | `41745e6` | docs: GuruNote 역사 기록 (통합 일지 + HISTORY/DECISIONS/DEBUGGING/CHANGELOG 첫 작성) |

### Phase 5 마무리 + v1.0.0.0 선언 + main 통합 (5/24 저녁)

| 시기 | commit | 사건 |
|------|--------|-----|
| 5/24 | `6dc9934` | **Phase 5 default on**: `GURUNOTE_SEGMENT_RESPLIT` + `GURUNOTE_TWO_PASS` 기본값 off → on. daily 검증 영상 2개 통과 — xKK5ze3FukQ (Boston Dynamics, 5.7 분) 96→49 segments / zNuOOMM20Tk (NVIDIA Podcast, 33.4 분) 586→294 segments. timeout 0, CJK 0, 화자 이름 정상 부착. 토글 off 안전망 유지 (`=0` 명시 시 기존 동작). 신규 백로그 B07 (D 재평가) + B08 (화자 bootstrap 한계). |
| 5/24 | `2971939` | **release: v1.0.0.0** — 버전 0.8.0.6 → 1.0.0.0 (7 곳 갱신: `__init__.py`, `gui.py` 사이드바, `package_desktop.py` Inno Setup + pkgbuild, `SettingsScreen.jsx` fallback, README "현재 버전", CHANGELOG entry). CLAUDE.md 체크리스트 5-file → 6-file (React UI fallback 추가). 신규 `run_webview.command` (React/PyWebView 진입점 wrapper). README 약 60% 재작성 — 진입점 `app_webview.py` 권장 + 옛 진입점 호환 표기, React/Mac/MLX 위주. backlog B09 (PipelineWorker 분리) + B10 (setup 스크립트 echo 갱신) 신규. test 183 passed. |
| 5/24 | (브랜치 작업) | **main 통합 — unrelated histories 처리**. 옛 main 트리 (root `4bcbee6`, HEAD `9b6c621` v0.8.0.6) 와 redesign 트리 (root `af50c2e`, HEAD `2971939` v1.0.0.0) 가 공통 조상 부재 사실 확인 (4/19 직후 웹 Claude → 로컬 CLI Claude Code 전환 시 별도 init 한 결과). 옛 main 211 commit 을 `archive/main-pre-cli` 로 origin 보존 → `git push origin main --force-with-lease` 로 redesign 트리를 main 으로 통일. origin/main: `9b6c621` → `2971939`. |

### v1.0.0.1~0.7 — daily 사용성·인명 품질 개선 (5/25~26)

> v1.0.0.0 이후 본인 daily 사용에서 발견한 불편을 차례로 수정. 각 항목 read-only 진단 → 외과적 구현 → 검증 → commit 흐름. 모두 REVISION 단위 (CLAUDE.md 정책 — updater 감지).

| 버전 | commit | 내용 |
|------|--------|-----|
| v1.0.0.1 | `add66d2` | 노트 상세 **출처 링크**(클릭→시스템 브라우저 + URL 복사) + **HistoryScreen 다운로드 wiring** — 카드/상세 다운로드 버튼이 stub("Phase 2B-4 예정" toast)이던 것을 실저장(`save_result_as` 재사용) 연결. bridge `open_external`(http/https) 신규. (B11) |
| v1.0.0.2 | `4615843` | **RAG 의미 검색 React 재배선** — 기존 `semantic.py`(완성·옛 UI 동작)를 React bridge 에 연결. 대시보드 "의미 검색 인덱스" 카드 실데이터 + Semantic Rebuild, History "의미 검색" 칩(오버레이), 노트 상세 "연관 노트"(top-K). bridge `rebuild_index`/`semantic_index_stats`/`semantic_search`/`semantic_available`. 선택 의존성 미설치 시 안내. (B12) |
| (환경, commit 무) | — | **RAG 의존성 gesicht 설치 + 인덱스 빌드 + 검색 품질 검증**. `.venv` 에 sentence-transformers 5.5.1 추가(torch/numpy 불변), 모델 `paraphrase-multilingual-MiniLM-L12-v2`(~117MB). 28 노트 / 1698 chunk(`~/.gurunote/embeddings.npz`). 쿼리 검증 — 휴머노이드/AI 에너지/투자 주제가 관련 노트를 상위에. 연관 노트 자기 제외 동작 확인. |
| v1.0.0.3 | `8eaa538` | **Obsidian 내보내기 + RAG wikilink** — 카드 hub 아이콘을 vault 내보내기로 배선(`send_obsidian`, 기존 `obsidian.py` `save_to_vault` 재사용). 내보낼 때 RAG 유사 노트 top5(≥0.5)를 본문 "## 연관 노트" + frontmatter `related` 로 `[[stem\|제목]]` alias wikilink 삽입 → Obsidian 그래프 연결. (B13) |
| v1.0.0.4 | `ef4426d` | **라이브러리 삭제 ↔ Obsidian 사본 동기화** — 내보낼 때 frontmatter 에 `gurunote_job_id` 표식, 삭제 시 그 표식 일치 vault 파일만 제거(`delete_from_vault`). best-effort(라이브러리 삭제 우선), 사본 있을 때만 확인 문구. 표식 없는 기존 파일은 보존(설계 의도). (B14) |
| v1.0.0.5 | `8b2125e` | **Obsidian 파일명 접두사 제거** — `GuruNote_<제목>.md` → `<제목>.md`. 파일명·wikilink stem 을 단일 helper(`_obsidian_note_stem`)로 통합해 그래프 연결 유지. 출처 구분은 `gurunote_job_id` 표식 + `Gurunote/` 폴더가 담당. |
| v1.0.0.6 | `77dd6b0` | **인명 음차 통용 표기 우선 (A)** — 번역 프롬프트 Rule 10 우선순위 역전: 통용 표기(철자 아닌 발음 기준) > 통용 목록 > 외래어 규칙(fallback). "팰머 러커이/리크 리더" → 팔머 럭키/릭 리더. 로컬 모델이 통용 표기를 알고 있어 dict 일괄 보강 불필요로 확인. |
| v1.0.0.7 | `8f836a0` | **영문 병기 철자 소스 검증 (B)** — `_correct_english_annotations`: `한국어(English)` 병기 영문을 소스(transcript 전문 + 제목)로 결정론적 대조. 정확 시 케이싱 정규화 / 단일 토큰 오타는 보수적 최근접(difflib 0.84, 대소문자 무시) 교정 / 근거 없으면 병기 생략. "Anduril→Danduril" 류 차단. 본문 + organized_title 적용. tests 8건. |

### v1.0.0.8~26 — 처리 토글·인명 자동화·품질·사용성 (5/26~29)

> v1.0.0.8 처리 옵션 토글 이후, 인명 관리 자동화(A-2) → 한국어 출력 품질 2차(제목·본문·요약) → 뷰어 사용성 → 자동 내보내기 정책·토스트 시각까지. 모두 REVISION 단위, 본인 daily 사용에서 발견한 항목을 차례로 수정.

| 버전 | commit | 내용 | 결정/추적 |
|------|--------|-----|----------|
| v1.0.0.8 | `d6a5d12` | 설정 "고급" 처리 옵션 토글(2-pass `GURUNOTE_TWO_PASS` + STT 재분할 `GURUNOTE_SEGMENT_RESPLIT`, 둘 다 기본 켜짐) | ADR-016 |
| v1.0.0.9 | `83551bc` | **Obsidian 작업 완료 후 자동 내보내기 토글**(설정-Obsidian, 기본 꺼짐). `App.onResult` 에서 `send_obsidian`, best-effort, 결과 토스트. **B16-2 완료** | B16-2 |
| v1.0.0.10 | `9d342b6` | 인명 통용 표기 **결정론적 교정** — `~/.gurunote/canonical_names.json` + entity/speaker 캐시 강제 교정(디스크 캐시 self-heal) | ADR-017 |
| v1.0.0.11 | `d106430` | 통용 dict **auto/user 구조 + 자동 채움**(작업 중 raw 표기 auto 누적, user 우선) | ADR-017 |
| v1.0.0.12 | `c8311ae` | 통용 표기 **편집 UI**(설정 고급 `SettingsCanonicalNames`) | ADR-017 |
| v1.0.0.13 | `390d69b` (+`50d0140` 라벨) | 노트 **표기 새로고침**(`refresh_canonical_in_markdown`, 기존 노트 소급 치환) | ADR-017 |
| v1.0.0.14 | `2692cd0` | 제목·요약 **한자 혼입 차단**(CJK 후처리 segment 없는 경로 적용) | ADR-018 / B17 |
| v1.0.0.15 | `5ef0e2f` | 제목 원본 **직역 우선** + 인명 dict 교정 | ADR-018 / B18 |
| v1.0.0.16 | `01553af` | 제목 **구조 직역 강화**(게임 문답·말장난 형식 보존) | ADR-018 / B18 |
| v1.0.0.17 | `89f68ec` | 노트 frontmatter **생성 버전 표시**(`gurunote_version`, 추적성) | ADR-018 / B19 |
| v1.0.0.18 | `c372c72` | 본문 번역 **충실 의역 전환**(환각·누락·영어 비번역 금지 + 예시) | ADR-018 / B20 |
| v1.0.0.19 | `ab04856` | 본문 **반복 라인 축약**(`_collapse_repeated_lines`, 더듬거림 회귀 차단) | ADR-018 / B21 |
| v1.0.0.20 | `9aad35e` | 요약 **충실도 강화**(`SUMMARY_SYSTEM_PROMPT` + dict 인명 후처리) | ADR-018 / B22 |
| v1.0.0.21 | `9a12566`→`c3b58bb`(Revert)→`ca9ebf1`+`26b3f2a` | 뷰어 **타임스탬프 표시 토글**(보기 전용) + 본문 **드래그 복사**(`user-select:text`). exporter 적용판을 먼저 만들었다가 적용 지점 오판으로 revert 후 뷰어판 재구현 | DEBUGGING §7 |
| v1.0.0.22 | `b6a8f5a` | 뷰어 **생성일 KST 표시**(`historyFormatCreatedAt`, ISO UTC 원본 노출 수정, 저장 필드 불변) | |
| v1.0.0.23 | `8f09c91` | 통용 표기 **독립 화면 이동 + 검색**(검색 중에도 수정·삭제 원본 인덱스 보존) | |
| v1.0.0.24 | `b70379f` | 통용 표기 **추가 행을 목록 맨 위로** | |
| v1.0.0.25 | `86ce877` | 자동 내보내기 **중복 노트 스킵**(같은 `gurunote_job_id` 자동만 스킵·수동 보존, `find_vault_copies` 재사용) | ADR-021 |
| v1.0.0.26 | `a05925c` | 토스트 **타입별 좌측 보더 색**(배경 불투명 유지) + 자동 토스트 누락 "버그 아님" 규명 후 임시 계측 제거 | ADR-022 / DEBUGGING §8 |

**트랙 B 요약** (2차 사료): 2026-05-14~17 Phase 1 Redesign 기간, 트랙 A(구현)와 병행해 트랙 B(read-only 검증 보조)가 9개 항목 독립 검증 + Phase 2 entity cache spec(449 줄) 사전 작성. 주요 결정 — `json_object` → `json_schema` strict 전환, chunk_size 6000 가설 기각(근본 원인은 chunk 당 segment 수로 판명 → `MAX_SEGMENTS_PER_CHUNK=15` 정정), Index Mapping helper 5 개 + finish_reason continuation. 잔존 한계 — tail attention drop (B04). 통합 commit `c68aab8`. [원본 트랙 B 로그는 렌더링 깨짐·단어 stuffing 다수 — 추후 `docs/legacy` 보관 예정, 본인이 원본 텍스트 제공 시.]

## 5. 현재 (2026-05-29 22시 GMT+9 기준, HEAD a05925c, v1.0.0.26)

### 코드 상태
- gurunote/ ~9100 line (llm.py 2700+ / stt_mlx.py 517 / stt.py 455 / updater.py 534 / 등)
- webui/ React 신축 (Phase 2B, 컴포넌트 + `SettingsCanonicalNames`)
- tests/ 235 passed (slow 3 deselected)
- License: Elastic 2.0
- 통합 main 트리: 412 commit (root `af50c2e`)
- 보존: `archive/main-pre-cli` 211 commit (root `4bcbee6`, 옛 main v0.x 전체)

### 진입점 (v1.0.0.0)

| 진입점 | 위치 | 상태 |
|---|---|---|
| **React/PyWebView** (권장) | `app_webview.py`, `run_webview.command` | v1.0+ |
| **CustomTkinter** (호환 유지) | `gui.py`, `run_gui.command`, `run_desktop.{sh,bat}` | `PipelineWorker` 클래스 보유 — React UI 가 의존 (B09 분리 작업 백로그) |
| **Streamlit** (호환 유지) | `app.py`, `run_web.{sh,bat}` | 단독 사용 가능 |

### backlog 완료 (5/25~29)

B11 출처 링크+다운로드 wiring · B12 RAG 재배선 · B13 Obsidian 내보내기+wikilink · B14 삭제 동기화 · B15 인명 음차(A)+영문 병기(B) · B16-1단계 처리 옵션 토글 (v1.0.0.1~0.8).
**B16-2 자동 내보내기** (v1.0.0.9) · **B17 한자 차단** (v1.0.0.14) · **B18 제목 품질** (v1.0.0.15~16) · **B19 생성 버전 표시** (v1.0.0.17) · **B20 충실 의역** (v1.0.0.18) · **B21 반복 축약** (v1.0.0.19) · **B22 요약 충실도** (v1.0.0.20) · 인명 관리 자동화 A-2 (v1.0.0.10~13) · 뷰어 사용성 + 자동 내보내기 스킵 정책 (v1.0.0.21~26) — 모두 완료.

### backlog 미해결

| ID | 상태 | 내용 |
|----|------|-----|
| (신규) | not_started | **검색 그라운딩 AgentSearch** (ADR-020) — SearXNG 래핑 + entity 검증 패스, 착수 대기 |
| B03 | not_started | Phase 1 fix-up #3 schema text leak — xgrammar 외부 의존, 신 버전 대기 |
| B04 | blocked | Phase 1 fix-up #2 tail attention drop — 정황 확인 필요 |
| B05 | blocked | Phase 4 capability profile — 모델 교체 결정 후 진입 (5/24 "모델 비의존" 방향으로 본 전제 우회) |
| B07 | not_started | D segment 단독 번역 재평가 — Phase 5 후속, 정합 낮은 영상에서 SHIFT 재발 시 |
| B08 | not_started | 화자 bootstrap 식별 한계 후속 — 5/24 영상1 5명 중 3명만 식별, 메타데이터 한계 |
| B09 | not_started | PipelineWorker 를 gui.py 에서 별도 모듈로 분리 — React 가 옛 CustomTkinter UI 파일에 의존하는 기술 부채 |
| B10 | not_started | setup.sh / setup.bat echo 갱신 — README v1.0 진입점과 일관성 |

## 6. 다음 — 본 문서 작성 시점 기준 (5/29)

- **검색 그라운딩 AgentSearch** (ADR-020) — SearXNG + entity 검증 패스. 착수는 신선한 세션(Wash→Warsh 작은 검증부터).
- temperature·프롬프트 한계 후속 — 0.6 도 영어 누출·인명 환각 100% 차단 못 함(DEBUGGING §8) → 검색 그라운딩 + 요약 충실도 보완.
- 트랙 B 원본 raw → `docs/legacy` 보관 (본인이 원본 텍스트 제공 시).
- B07/B08/B09/B10 각 결정.
- B03/B04/B05 각 결정.

> 이미 처리됨: v1.0.0.1~26 daily 사용성·품질 (5/25~29) + 자동 내보내기(B16-2, v1.0.0.9) + 스킵 정책(v1.0.0.25). verify 산출물 commit(`208f18a`) + GitHub release 태그 `v1.0.0.0` (5/25).

---

**자료 한계 명시**:
- Phase 0 (4/11~18 첫 commit ~ v0.8.0.6) — 본인 메모/기억 2차 사료. session_history_digest 시작이 4/19.
- VibeVoice OOM 32분 / Nemotron Omni 평가 / 정체성 진화 시점 일부 — 본인 기억 2차 사료.
- License MIT → Elastic 전환 동기 — 본인 링크 대화 (DECISIONS.md 확장).
- main 트리 / redesign 트리 unrelated histories 사실 — 5/24 통합 시점에 사후 확인. 별도 init 가 정확히 어느 commit 인지는 기록 부재 (양쪽 모두 "Initial commit" 메시지, 4/11 같은 날, hash `4bcbee6` vs `af50c2e`). 본인 기억으로는 4/19 직후 로컬 CLI Claude Code 도입 시 환경 변경.

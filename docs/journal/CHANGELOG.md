# GuruNote 변경 기록 (저장소 CHANGELOG + 백엔드 Phase 연계)

> 저장소 `CHANGELOG.md` (Keep a Changelog 형식) 은 5/24 v1.0.0.0 entry 작성됨. 본 문서는 두 트리 (옛 main `4bcbee6` 트리 + redesign `af50c2e` 트리) 의 통합 view. 5/24 main 통합 완료 — 옛 main 은 `archive/main-pre-cli` 영구 보존.

## main 브랜치 v0.x (PRD ~ v0.8.0.6)

### [0.1.0] - 2026-04-12

- 5-step 파이프라인 + VibeVoice-ASR primary STT (`4ecbf77`)
- Streamlit UI
- yt-dlp + AssemblyAI fallback + OpenAI/Anthropic

### [PR #4] - 2026-04-12

- **CustomTkinter desktop GUI** 추가 (Streamlit 대체) — "Tauri는 오버엔지니어링" 본인 결정

### [PR #5] - 2026-04-13

- in-app settings dialog (API 키 catch)

### [PR #6] - 2026-04-13

- 로컬 video/audio 파일 입력 catch

### [PR #8] - 2026-04-14

- **OpenAI-compatible local LLM** (qwen3.6 등) + in-app settings UX

### [PR #9] - 2026-04-15

- in-app + CLI update workflow (Codex review 후속)

### [PR #11] - 2026-04-16

- **YouTube metadata catch** (date, chapters, captions) LLM 컨텍스트 catch

### [PR #12] - 2026-04-16

- 기본 LLM 모델 갱신 (gpt-5.4, claude-sonnet-4-6)

### [PR #14] - 2026-04-17

- GUI redesign (sidebar + card layout + step indicators)

### [Unknown] - v0.4.0

- **WhisperX 전면 교체** (NVIDIA GPU 정합, VibeVoice-ASR 폐기) — 시점 기록 부재 (본인 기억 2차 사료)

### [Unknown] - v0.6.0

- **mlx-whisper 합류** (Mac Apple Silicon) — 시점 기록 부재. AssemblyAI 완전 제거 → 완전 로컬 catch.

### [0.8.0.0~5] - 2026-04 후반

- v0.8.0.4 Provider 조건부 필드 + secret 지우기
- v0.8.0.5 History 카드 Del 버튼 잘림 fix (grid uniform 컬럼)

### [0.8.0.6] - 2026-04-19

**Fixed**: macOS python.org Python에서 YouTube 썸네일 + 업데이트 체크 실패 (SSL 인증서) — `gurunote/_net.py` 신규 (certifi 번들 기반 SSL context).

### [0.8.0.7] - 2026-04-20 (feat/webview-ui 분기, 폐기)

- PyWebView UI Phase 1-B MVP (PR #107 draft)
- 4/27 vanilla 폐기 + Phase 2B-0 React 신축 진입

---

## redesign/tailwind-v2 브랜치 (Phase 2A/2B/백엔드 Phase 1~5)

> main 미머지. 4/24 ~ 5/24 현재.

### Phase 2A — Tailwind redesign (4/24~25)

- `cedae0e` (4/24) chore: initialize Phase 2A
- `4d7222f` (4/25) Phase 2A Commit 2: Material 3 sidebar + frameless titlebar → **Revert (4/25 13:49)** → `archive/commit-2-aborted`
- `b1cd138` / `31f59e3` (4/25) Phase 2A Commit 3a: 자산 복원 + React + Babel 검증
- **License MIT → Elastic 2.0** (KICKOFF Decision 1)

### Phase 2B — React 신축 (4/27~5/2, 514 commits 절정)

- `2160a66` (4/27) **Phase 2B-0**: 신축 baseline (vanilla 폐기 + clean React entry)
- `6376385` Phase 2B-1: Sidebar + App + 5 화면 placeholder
- `598ead0` Phase 2B-2: MainScreen (생성 + 결과 4탭)
- 2B-3a~3d: HistoryScreen (카드 그리드, 검색·필터, 정렬, Facet tree + Detail)
- 2B-4a~4c: EditorScreen, DashboardScreen, SettingsScreen
- 2B-5a/5b: 라이브러리 wiring, 에러 + 복구
- 2B-6a~6d: 글로벌 TopBar, EditorScreen split, Dashboard 재구성, ⌘K SearchPalette

### Phase 2B-3-backend Step 시리즈 (4월 후반)

- `0cc5608` Step 3b-1: 한국어 skip + detected_language
- `38381db` Step 3b-prep: MainScreen state lifted
- `db98761` Step 3b-2: delete_history wiring
- `b1e288f` Step 3b-3: Title 동기화 frontmatter SSOT

### Phase 2B-3-backend Layer 1~15 (5/9~5/11)

- `d9c5f0b` (5/9) Layer 1: pyannote max_speakers + embedding clustering
- `1846098` (5/9) Layer 5+6: LLM hallucination cascading + STT noise filter
- `c7e9e1a` (5/9) Layer 7: ResultPanel 4 tab DetailPanel + EditorScreen 통합
- `cf4a7bd` (5/9) Layer 8: 고유명사 한국어 표기법 일관성
- `c2da2d3` (5/9) **Layer 8 fix-up**: Tiffany Janzen 표준 표기 (잰슨→잔젠)
- `a512b12` (5/10) Layer 9: markdown transcript 가독성
- `027f243` (5/10) Layer 13: 화자 표기 한국어 + entity 영문 병기
- `12e1868` (5/10) Layer 13 fix-up #2: 화자 라벨 첫 등장 영문 병기
- `d30c782` (5/10) Layer 11: Rule 11 한자/일본어 차단 + _SHARED_LANG_RULES
- `ee8b616` (5/10) Layer 14: transcript line break 정규화
- `ece961e` (5/11) Layer 15: METADATA prompt _SHARED_LANG_RULES inline
- `d7a726b` (5/11) Layer 15 fix-up #1: title hallucination 가이드라인

### 백엔드 품질 Phase 1~5 (5/16~5/24)

- `c68aab8` (5/16) **Phase 1 Redesign**: Index Mapping + json_schema strict + segment cap 15
- `b447a11` (5/17) **Phase 4a-1**: xgrammar selective disable + A-3 timeout dead code
- `cdbdc67` (5/18) **Phase 3**: 한자/일본어 0건 후처리 (Sub-path A+B+C)
- `47c3448` (5/18) Phase 3 마무리 unit tests
- `22927fc` (5/19) **Phase 2 (B01) Step B**: entity_cache helper + unit test
- `f9c2da2` (5/19) Phase 2 (B01) Step C: translate_transcript 통합 + Rule 12
- `2ed4701` (5/20) **B02**: slow chunk wall-clock timeout (ThreadPoolExecutor)
- `4a8f281` (5/21) **B06 (Phase 2B-3)**: entity_cache 디스크 + 외래어 표기법 + 표기 통일
- `8fdc2a8` (5/22) B06 verify: 판카지 회귀 차단
- `9afcc93` (5/22) B06 한계 2: canonicalize 미세 변경 차단
- `988b4c1` (5/22) B02 한계 1: R1 padding fallback
- `f58d5f2` (5/22) B06 보완 verify 통과
- `f314d6e` (5/23) B02 수정: ThreadPoolExecutor 결함 + 전 경로 통합
- `97855bd` (5/23) B02 R2: 즉시 padding → strict retry → fallback
- `39652c6` (5/23) **2-pass DCCD prototype**: 자유 번역 → 정렬 토글
- `7a397fa` (5/23) 2-pass 보강: A1 rule 충돌 + A5 prefix strip
- `6b94a49` (5/23) **화자 라벨 코드 부착**: 식별 1회 + 결정론
- `8ecd276` (5/23) **pyannote 3.1 → community-1**
- `599c94b` (5/23) 2-pass 빈 output 복구 시퀀스 (3단계 안전망)
- `2ed4701` (5/24 직전 보강 외) ...
- `527d2ea` (5/24) **Phase 5**: STT 의미 단위 재분할 + chunk_size 자동 (토글)

### docs 정리 (5/24)

- `4f2db79` docs: 옛 UI 작업 문서 legacy 정리 (37 rename)
- `373d5db` docs: Phase 5 검증 산출물 보존
- `5c3c240` docs: 18개 세션 사료화
- `41745e6` docs: GuruNote 역사 기록 (통합 일지 + HISTORY/DECISIONS/DEBUGGING/CHANGELOG 첫 작성)

### Phase 5 마무리 (5/24 저녁)

- `6dc9934` **Phase 5 default on**: `GURUNOTE_SEGMENT_RESPLIT` + `GURUNOTE_TWO_PASS` 기본값 off → on. daily 검증 영상 2 개 통과 (xKK5ze3FukQ 96→49 segments, zNuOOMM20Tk 586→294 segments, timeout 0, CJK 0). 토글 off 안전망 유지. 신규 백로그 B07 (D 재평가) + B08 (화자 bootstrap 한계).

### v1.0.0.0 선언 + main 통합 (5/24 저녁)

- `2971939` **release: v1.0.0.0**:
  - 버전 0.8.0.6 → 1.0.0.0 (7 곳 동시 갱신: `__init__.py`, `gui.py` 사이드바, `package_desktop.py` Inno Setup + pkgbuild, `SettingsScreen.jsx` fallback, `README.md`, `CHANGELOG.md`)
  - CLAUDE.md 체크리스트 5-file → 6-file
  - 신규 `run_webview.command` (React/PyWebView macOS 런처)
  - README 약 60 % 재작성 — 진입점 `app_webview.py` 권장, React/Mac/MLX 위주
  - 신규 백로그 B09 (PipelineWorker 분리, P3) + B10 (setup 스크립트 echo, P3)
  - 1.0 근거 (하위 호환 깸): License MIT → Elastic, UI CustomTkinter/Streamlit → React/Material 3/PyWebView, 번역 1-pass → 2-pass DCCD + entity_cache + CJK + STT 재분할
- (브랜치 작업, 5/24) **main 통합 — unrelated histories 처리**:
  - 옛 main 트리 (root `4bcbee6`, HEAD `9b6c621` v0.8.0.6, 211 commit) 와 redesign 트리 (root `af50c2e`, HEAD `2971939` v1.0.0.0) 가 공통 조상 부재 사실 확인
  - 옛 main 211 commit 전체를 `archive/main-pre-cli` 로 origin 영구 보존
  - `git push origin main --force-with-lease` 로 redesign 트리를 main 으로 통일
  - origin/main: `9b6c621` → `2971939`
  - test 183 passed (main 상태)

### daily 사용성·품질 v1.0.0.1~26 (5/25~29)

> v1.0.0.0 이후 본인 daily 사용에서 발견한 항목을 REVISION 단위로 수정. 상세 흐름은 HISTORY §4, 결정은 DECISIONS ADR-014~022.

- `add66d2` **v1.0.0.1**: 출처 링크 + 다운로드 wiring (B11)
- `4615843` **v1.0.0.2**: RAG 의미 검색 React 재배선 (B12) — 별도 환경 작업으로 의존성 설치 + 28노트 인덱스 빌드
- `8eaa538` **v1.0.0.3**: Obsidian 내보내기 + RAG wikilink (B13)
- `ef4426d` **v1.0.0.4**: 라이브러리 삭제 ↔ vault 사본 동기화, `gurunote_job_id` 표식 (B14, ADR-014)
- `8b2125e` **v1.0.0.5**: Obsidian 파일명 접두사 제거 (ADR-014)
- `77dd6b0` **v1.0.0.6**: 인명 음차 통용 표기 우선 (A, ADR-015)
- `8f836a0` **v1.0.0.7**: 영문 병기 철자 소스 검증 (B, ADR-015)
- `d6a5d12` **v1.0.0.8**: 처리 옵션 토글 (2-pass / STT 재분할, ADR-016)
- `83551bc` **v1.0.0.9**: Obsidian 작업 완료 후 자동 내보내기 토글 (B16-2)
- `9d342b6` **v1.0.0.10**: 인명 통용 표기 결정론적 교정 (ADR-017)
- `d106430` **v1.0.0.11**: 통용 dict auto/user 구조 + 자동 채움 (ADR-017)
- `c8311ae` **v1.0.0.12**: 통용 표기 편집 UI (ADR-017)
- `390d69b` (+`50d0140`) **v1.0.0.13**: 노트 표기 새로고침 (ADR-017)
- `2692cd0` **v1.0.0.14**: 제목·요약 한자 혼입 차단 (ADR-018, B17)
- `5ef0e2f` **v1.0.0.15**: 제목 원본 직역 우선 + 인명 dict 교정 (ADR-018, B18)
- `01553af` **v1.0.0.16**: 제목 구조 직역 강화 (ADR-018, B18)
- `89f68ec` **v1.0.0.17**: 노트 생성 버전 표시 (ADR-018, B19)
- `c372c72` **v1.0.0.18**: 본문 충실 의역 전환 (ADR-018, B20)
- `ab04856` **v1.0.0.19**: 본문 반복 라인 축약 (ADR-018, B21)
- `9aad35e` **v1.0.0.20**: 요약 충실도 강화 (ADR-018, B22)
- `9a12566`→`c3b58bb`(Revert)→`ca9ebf1`+`26b3f2a` **v1.0.0.21**: 뷰어 타임스탬프 토글 + 드래그 복사 (DEBUGGING §7)
- `b6a8f5a` **v1.0.0.22**: 뷰어 생성일 KST 표시
- `8f09c91` **v1.0.0.23**: 통용 표기 독립 화면 + 검색
- `b70379f` **v1.0.0.24**: 통용 표기 추가 행 맨 위
- `86ce877` **v1.0.0.25**: 자동 내보내기 중복 노트 스킵 (ADR-021)
- `a05925c` **v1.0.0.26**: 토스트 타입별 좌측 보더 색 (ADR-022)

> 저장소 루트 `CHANGELOG.md`(Keep a Changelog)는 별개 파일로 v1.0.0.26 까지 최신. 본 문서는 두 트리 통합 view.

---

## 통합 view — UI Phase vs 백엔드 품질 Phase

| 시기 | UI/frontend Phase | 백엔드 품질 Phase |
|------|------------------|---------------|
| 4/11~4/19 | v0.1.0 ~ v0.8.0.6 (Streamlit → CustomTkinter → 다수 PR) — **옛 main 트리** | — |
| 4/19~4/22 | UI Phase 1-B (PyWebView MVP) — feat/webview-ui, 폐기 | — |
| 4/24~4/25 | Phase 2A (Tailwind, Commit 2 Revert) — **redesign 트리 시작 (별도 init)** | — |
| 4/27~5/2 | Phase 2B (React 신축, 514 commit 절정) | — |
| 4/30~5/2 | Phase 2B-3-backend Step 3b-1~3b-3 | — |
| 5/9~5/11 | Phase 2B-3-backend Layer 1~15 (UI 정책 + LLM prompt) | — |
| 5/12~5/15 | (gap, 정전 대비) | — |
| 5/16~5/24 오후 | — | **Phase 1 → 4a-1 → 3 → 2(B01) → B02 → B06 → 2-pass DCCD → 화자 코드 → community-1 → 빈 복구 → Phase 5 재분할** |
| 5/24 저녁 | **v1.0.0.0 선언 + main 통합** (redesign 트리 → main, 옛 main → archive/main-pre-cli 보존) | Phase 5 default on (daily 검증 후) |
| 5/25~29 | daily 사용성 — 출처/RAG/Obsidian, 인명 자동화, 뷰어 토글/KST, 토스트 시각 (v1.0.0.1~26) | 인명 품질·충실 의역·요약 충실도 (ADR-015·017·018), temperature 0.6 (ADR-019), 검색 그라운딩 채택 (ADR-020, 대기) |

## 상호 관계

- **Layer = UI/frontend + LLM prompt** (출력 표기, 화자 라벨, 가독성, 한자 차단 등)
- **Phase 1~5 = 번역 본체** (LLM 호출 path, chunk 분할, entity_cache, 후처리, STT 재분할)
- Layer 시리즈 (5/9~11) 후 일주일 gap (5/14 정전 대비) → 5/16~ 백엔드 본체 진입.
- v1.0.0.0 (5/24) = 두 흐름의 통합 + 옛 main 트리 (v0.x Streamlit/CustomTkinter) 의 archive 보존.

## 브랜치 / 트리 구조 (5/24 통합 후)

| 브랜치 | HEAD | root | commit 수 | 의미 |
|---|---|---|---|---|
| `origin/main` | `2971939` (v1.0.0.0) | `af50c2e` | 412 | redesign 트리 — 통일된 main |
| `origin/redesign/tailwind-v2` | `2971939` | `af50c2e` | 412 | 작업 브랜치 (동일) |
| `origin/archive/main-pre-cli` | `9b6c621` (v0.8.0.6) | `4bcbee6` | 211 | 옛 main 트리 — 영구 보존 |
| `origin/archive/commit-2-aborted` | (4/25 작성) | (redesign 트리) | — | Phase 2A Commit 2 자산 보존 |

---

**참고**:
- 저장소 `CHANGELOG.md` 는 Keep a Changelog 형식 — 5/24 `[1.0.0.0]` entry 작성됨 + 옛 v0.x history 잔존.
- 본 문서는 두 트리 통합 view + 5/24 통합 사후 기록.
- v0.x 일부 (v0.4.0/0.6.0) 본인 기억 2차 사료.
- 두 트리가 별개 root 를 가진 정확한 원인 시점은 **기록 부재** — 본인 기억으로는 4/19 직후 환경 전환.

# GuruNote 개발 일지

> 유튜브 링크 한 줄로 해외 IT/AI **구루(Guru)** 영상을 **화자 분리 + 한국어 영문병기 마크다운 요약**으로 정리하는 데스크톱 앱.

## 한 문단

해외 IT/AI 인사이트(Jensen Huang, Sam Altman, Tiffany Janzen 등)가 매일 쏟아지는데, 한국어로 정리된 자료는 늦거나 부정확하다. GuruNote는 구루들의 유튜브/팟캐스트를 **완전 로컬**(mlx-whisper Mac / WhisperX NVIDIA)로 받아 화자 분리 + 한국어 번역 + 외래어 표기법 표준 + 영문병기 + Obsidian/Notion 출력까지 자동화한다. 2026-04-11 첫 commit, 2026-05-24 v1.0.0.0 선언 + main 통합 완료. 통합 main 트리 기준 412 commit + 183 test 통과.

**정체성 진화**: "IT/AI 구루 요약 앱"(PRD, 4/11) → "24/7 지식 증류기 + Obsidian"(WORK_ORDER) → "**모델 비의존 한국어 지식 정리**"(5/24).

## 현재 지점 (2026-05-29, HEAD a05925c, v1.0.0.26)

### 완료
- **Phase 0~1 (v0.1.0 ~ v0.8.0.6)**: 5-step 파이프라인 → CustomTkinter GUI → openai_compatible local LLM → YouTube metadata → 모델 갱신 → SSL 인증서 fix
- **Phase 2A**: Tailwind redesign 진입, License MIT → Elastic 2.0 전환
- **Phase 2B**: React 신축 (Sidebar/MainScreen/HistoryScreen/EditorScreen/DashboardScreen/SettingsScreen) — 4/27 baseline ~ 5/9 polish
- **Phase 2B-3-backend Layer 1~15**: pyannote drift fix → LLM cascading + STT noise → ResultPanel 통합 → Tiffany Janzen 표기 → markdown 가독성 → CJK 차단 → title 정합
- **백엔드 품질 Phase 1~5 (Mac/MLX)**:
  - Phase 1 Redesign (`c68aab8`): Index Mapping + json_schema strict + segment cap 15
  - Phase 2 entity_cache (`f9c2da2`, `4a8f281` B06): 판카지/샘 올트먼 hallucinate 0
  - Phase 3 CJK (`cdbdc67`): Sub-path A+B+C 한자 0
  - Phase 4a-1 (`b447a11`): xgrammar selective disable
  - B02 timeout (`2ed4701`): ThreadPoolExecutor wall-clock 안전망
  - 2-pass DCCD + 화자 코드 부착 + community-1 + 빈 복구 (`599c94b`)
  - Phase 5 (`527d2ea`, 5/24): STT 의미 단위 재분할 + char_limit 자동 조정
- **Phase 5 마무리 (`6dc9934`, 5/24)**: daily 검증 영상 2개 통과 (xKK5ze3FukQ 96→49 segments, zNuOOMM20Tk 586→294 segments, timeout 0, CJK 0, 화자 이름 정상 부착). `GURUNOTE_SEGMENT_RESPLIT` + `GURUNOTE_TWO_PASS` 기본값 on 전환. 토글 off 안전망 유지 (`=0` 명시 시 기존 동작).
- **v1.0.0.0 선언 + main 통합 (`2971939`, 5/24)**: 버전 0.8.0.6 → 1.0.0.0 (7 곳 일치). 1.0 근거 — License MIT → Elastic 2.0, UI CustomTkinter/Streamlit → React/Material 3/PyWebView (`app_webview.py`), 번역 1-pass → 2-pass DCCD + entity_cache + CJK + STT 재분할. README 약 60% 재작성, `run_webview.command` 신규. **main 통합 (force-with-lease)**: origin/main `9b6c621`(v0.8.0.6) → `2971939`(v1.0.0.0), 옛 main 211 commit (root `4bcbee6`) 은 `origin/archive/main-pre-cli` 에 영구 보존.
- **v1.0.0.1~0.8 daily 사용성·인명 품질 (5/25~26)**: 출처 링크+다운로드 wiring(`add66d2` B11) → RAG React 재배선(`4615843` B12, gesicht 의존성 설치+28노트 인덱스 검증) → Obsidian 내보내기+RAG wikilink(`8eaa538` B13) → 삭제↔사본 동기화(`ef4426d` B14, `gurunote_job_id` 표식) → 파일명 접두사 제거(`8b2125e`) → 인명 음차 통용 표기 우선(`77dd6b0` B15-A) → 영문 병기 철자 소스 검증(`8f836a0` B15-B, Danduril 차단) → 처리 옵션 토글(`d6a5d12` B16-1, 2-pass/재분할). 자세히 [HISTORY](./HISTORY.md) §4 + [DECISIONS](./DECISIONS.md) ADR-014~016.
- **v1.0.0.9~26 자동 내보내기·인명 자동화·품질·사용성 (5/26~29)**: 자동 내보내기 토글(`83551bc` B16-2 **완료**) → 인명 관리 자동화 A-2(`9d342b6`~`390d69b` v1.0.0.10~13, 결정론 교정+auto/user dict+편집 UI+노트 새로고침, ADR-017) → 한국어 출력 품질 2차(한자 차단·제목 직역·생성 버전·충실 의역·반복 축약·요약 충실도, v1.0.0.14~20, ADR-018, B17~B22) → 뷰어 사용성(타임스탬프 토글·드래그 복사·KST·통용 표기 화면, v1.0.0.21~24) → 자동 내보내기 중복 스킵 정책(`86ce877` v1.0.0.25, ADR-021) → 토스트 타입 시각(`a05925c` v1.0.0.26, ADR-022). temperature 0.6 확정(ADR-019) + 검색 그라운딩 채택(ADR-020, 구현 대기). 자세히 [HISTORY](./HISTORY.md) §4 + [DECISIONS](./DECISIONS.md) ADR-017~022 + [DEBUGGING](./DEBUGGING.md) §7~8.

### 진행 중 (없음 — WIP=1)

### Blocked / 대기
- **B03** Phase 1 fix-up #3 (schema text leak) — P2 not_started. xgrammar 외부 의존, 신 버전 대기.
- **B04** Phase 1 fix-up #2 (tail attention drop) — blocked, 정황 확인 필요 (backlog.md 그대로).
- **B05** Phase 4 capability profile — blocked, 모델 교체 결정 후 진입 예정. 2026-05-24 "모델 비의존" 방향 선회로 본 전제 우회.
- **B07** D segment 단독 번역 재평가 — not_started, 정합 낮은 영상에서 SHIFT 재발 시 재검토.
- **B08** 화자 bootstrap 식별 한계 후속 — not_started, 메타데이터 한계로 식별 이름 < 전체 화자 시 fallback 처리 (5/24 daily 영상1 5명 중 3명만 식별).
- **B09** PipelineWorker 를 gui.py 에서 별도 모듈로 분리 — not_started, React UI (`app_webview.py`) 가 `gui.py` 의 `PipelineWorker` 클래스를 import 하는 기술 부채. P3.
- **B10** setup.sh / setup.bat 안내 echo 갱신 — not_started, README 와 일관성. P3.

## 문서 안내

| 문서 | 무엇 | 언제 보나 |
|------|------|---------|
| [HISTORY.md](./HISTORY.md) | 시간순 — 시작부터 현재까지 무엇이 일어났나 | "이 프로젝트는 어떻게 발전했나" |
| [DECISIONS.md](./DECISIONS.md) | 결정 — 갈림길에서 무엇을 골랐고 왜 | "왜 PySide6 폐기? 왜 Elastic License?" |
| [DEBUGGING.md](./DEBUGGING.md) | 추적 사슬 — 27b 느림 → 환경 오염 → ... → Phase 5 재분할 | "특정 버그/현상 추적 흐름" |
| [CHANGELOG.md](./CHANGELOG.md) | 버전별 변경 (기존 `CHANGELOG.md` + 백엔드 Phase 연계) | "v0.x.x에 무엇이 바뀌었나" |

저장소 다른 핵심 자료:
- `docs/backlog.md` — WIP=1 운영, B01~B22 추적 (B11~B22 완료, 검색 그라운딩 신규 대기)
- `docs/quality.md` — 모듈별 등급 (STT A / LLM B+ / 후처리 A / 화자 B / UI 확인필요 / 검증 B)
- `docs/research/` — Phase 1~3 spec + 외래어 표기법 원본
- `docs/legacy/handoff/` — Phase 2A 사전 디자인 handoff
- `docs/legacy/webview-ui/{ARCHITECTURE,TECH_CHOICE}.md` — feat/webview-ui (4/20, 폐기) 결정
- `docs/wip/session_history_digest.md` — 18개 세션 사료 (4/19~5/24, 1차 자료)

## 핵심 결정 — 큰 줄기 8개 (전체 ADR-001~022, 자세히 [DECISIONS.md](./DECISIONS.md))

1. **STT 엔진 여정 (VibeVoice → WhisperX → mlx-whisper)**: 초기 VibeVoice-ASR 채택 → RTX5090 32GB **OOM 32분 처리 시간** → **v0.4.0 WhisperX 전면교체** → Mac 사용자 위해 **v0.6.0 mlx-whisper 합류** → **AssemblyAI 완전 제거 → 완전 로컬** 결정. (큰 줄기)
2. **PyWebView + React 채택, PySide6 폐기** (4/19~4/27): "경로 C-1: PyWebView + HTML/CSS/JS + gurunote/* 로직 그대로 재사용" → Phase 1-B MVP 성공 → "Phase 2B-0: 신축 baseline 준비 (vanilla 폐기)" — feat/webview-ui 폐기, Phase 2B 진입.
3. **License MIT → Elastic 2.0 전환** (Phase 2A KICKOFF Decision 1): "최초 프로젝트 목적 망각 말고, 내 시간·노력 인정. 남들에게 다 퍼주는 게 마냥 좋은 건 아니다" — 본인 링크 대화 사료.
4. **2-pass DCCD + 화자 코드 부착** (`7a397fa`, `6b94a49`, 5/23): 1단계 자유 번역 (schema 부재) → 2단계 strict 정렬, 화자 라벨은 LLM 식별 1회 + 결정론 부착 — rule 1 prompt 충돌 근본 해소.
5. **STT 직후 의미 단위 재분할 + char_limit=2000 자동** (`527d2ea`, 5/24): Whisper segment 잘림이 D leak + 2-pass SHIFT + 본문 가독성의 공통 원인 → word-level 끝 검사 + 화자 우선 병합. **모델 비의존 하네스** 방향. daily 검증 후 default on (`6dc9934`).
6. **Phase 4 capability profile 보류 → "모델 비의존" 우회**: B05 "모델 교체 결정 후 진입" 전제였으나, 5/24 재분할 + char_limit 통합으로 모델 capability 의존 부재 path 발견 → 본 전제 우회.
7. **v1.0.0.0 선언** (`2971939`, 5/24): CLAUDE.md "1.0 전 MINOR 대체" 정책의 의식적 예외. License 전환 + UI 전면 교체 + 백엔드 파이프라인 재구조가 동시에 하위 호환을 깨므로 1.0 선언이 정직하다고 판단. 옛 두 진입점 (`gui.py` / `app.py`) 은 호환 유지 (Path C — React 가 `gui.PipelineWorker` 의존, 분리는 B09 백로그).
8. **main 통합 — unrelated histories 처리** (5/24): main 트리 (root `4bcbee6`, 211 commit, v0.8.0.6) 와 redesign 트리 (root `af50c2e`, v1.0.0.0) 가 공통 조상 부재 (4/19 직후 웹 Claude 환경에서 로컬 CLI Claude Code 로 전환할 때 별도 init 한 결과). 안전망 먼저: 옛 main 을 `archive/main-pre-cli` 로 origin 보존 → `git push origin main --force-with-lease` 로 redesign 트리를 main 으로 통일.

## 다음 할 일

- 역사 문서 주기적 갱신 (본 commit = v1.0.0.9~26 + 5/26~29 결정/디버깅 반영, ADR-017~022 + DEBUGGING §7~8).
- **검색 그라운딩 AgentSearch** (ADR-020) — SearXNG + entity 검증 패스. 착수는 신선한 세션(Wash→Warsh 작은 검증부터).
- ~~**B16-2** Obsidian 자동 내보내기 토글~~ → **완료** (v1.0.0.9 `83551bc`, `App.onResult` 트리거, 기본 꺼짐). 중복 스킵 정책은 v1.0.0.25(ADR-021).
- 트랙 B 원본 raw → `docs/legacy` 보관 (본인이 원본 텍스트 제공 시).
- ~~`docs/wip/daily_verify_phase5.py` / `verify_results/daily_phase5/` 운명 결정~~ → **commit 완료** (`208f18a`, 5/25).
- ~~GitHub release 태그 `v1.0.0.0`~~ → **생성 완료** (5/25, `2971939` + GitHub release).
- **B07** D segment 단독 번역 재평가 — 정합 낮은 영상에서 SHIFT 재발 시.
- **B08** 화자 bootstrap 식별 한계 후속 — 영상 빈도 누적 후 B01 연계 검토.
- **B09** PipelineWorker 를 gui.py 에서 별도 모듈로 분리 — 옛 진입점 폐기 시점 또는 React 단일화 결정 시.
- **B10** setup.sh / setup.bat echo 갱신 — README 와 일관성.
- B03 schema text leak 후처리 (xgrammar 신 버전 도착 시).
- B04 tail attention drop 정황 확인 (backlog 미해결 항목).
- B05 capability profile — 모델 비의존 방향과 통합 결정.

---

**참고**: 본 일지는 2차 사료(요약·재구성)이다. 1차 자료는 `docs/wip/session_history_digest.md` (Claude Code 세션, 4/19~5/24) + git log (통합 main 트리 기준 412 commit + archive 211 commit) + README/CHANGELOG. Phase 0 (4/11~18) 일부는 본인 기억(2차)으로 보강. main 트리와 redesign 트리가 별개 root 를 가진 사실은 5/24 통합 시점에 사후 확인됨.

# GuruNote 결정 기록 (ADR — Architecture Decision Records)

> 갈림길에서 무엇을 골랐고 왜. 맥락(상황) / 결정 / 대안 / 이유 / 결과 구조. 채택된 결정 + 기각된 대안 둘 다 catch.

## 채택된 결정

### ADR-001. AssemblyAI 완전 제거 → 완전 로컬 STT (v0.4.0 ~ v0.6.0)

**맥락**: 초기 v0.1.0 — VibeVoice-ASR primary + AssemblyAI 클라우드 fallback. RTX5090 32GB에서 VibeVoice 처리 시 **OOM (32분 처리)** catch.

**결정**: AssemblyAI 완전 제거 → **완전 로컬 STT** (mlx-whisper Mac + WhisperX NVIDIA).

**대안**:
- A. VibeVoice 유지 + AssemblyAI fallback 적극 — 비용 + 클라우드 의존
- B. WhisperX 전면 교체 — Mac 사용자 부재
- C. (채택) v0.4.0 WhisperX 전면 + v0.6.0 mlx-whisper 합류 → AssemblyAI 제거

**이유**: 클라우드 의존 부재 + 사용자 데이터 외부 전송 부재 + 처리 시간 안정.

**결과**: 완전 로컬 catch. 2개 STT 백엔드 (Mac MLX / NVIDIA CUDA) 정합.

---

### ADR-002. PyWebView 채택, PySide6 폐기 (4/19~4/27)

**맥락**: v0.1.0 Streamlit → PR #4 CustomTkinter ("Tauri는 오버엔지니어링, 백엔드 직접 호출") → 4/19 다음 GUI 선택 시점.

**결정 (4/19 16:05, 본인 사료)**: **"경로 C-1 확정. PyWebView + HTML/CSS/JS + gurunote/* 로직 그대로 재사용"**.

**대안**:
- PySide6 — Python GUI 본격 (heavy)
- Tauri — 오버엔지니어링 catch (PR #4)
- Electron — 메모리/배포 큼
- (채택) PyWebView — Python ↔ JS bridge + 가벼움

**이유**: gurunote/* 로직 그대로 재사용, HTML/CSS/JS 자유, Python 단독 배포.

**결과**: 4/20 Phase 1-B MVP 성공 (PR #107). 단 **4/27 폐기** — ADR-003.

---

### ADR-003. PyWebView vanilla → React 신축 (4/27)

**맥락**: PyWebView Phase 1-B MVP 성공. 단 vanilla JS 신축 시 화면 신규 작업이 많아지고 catch 부족.

**결정 (4/27 07:32, 본인 사료)**: **"Phase 2B-0: 신축 baseline 준비 (미커밋 폐기 + Phase 1-C vanilla 폐기)"** — React 신축 진입.

**대안**:
- A. vanilla 유지 — 매 화면 직접 작성
- B. (채택) React + Material 3 + Babel — 컴포넌트 catch + 재사용
- C. Svelte / Vue — Material 3 catch 부족

**이유**: 5+ 화면 신축에 컴포넌트 catch 강력. React 생태계 자료 풍부.

**결과**: 4/27 ~ 5/2 Phase 2B-1 ~ 2B-6d 시리즈 514 commit + 5/9~11 Layer 1~15 정합.

---

### ADR-004. UI Commit 2 Revert + archive 작성 (4/25)

**맥락**: 4/22 Phase 2A Commit 2 (Material 3 sidebar) 시도. 4/23 02:33 본인 STOP. 4/25 Commit 2 재시도 → `4d7222f`. 단 본인이 검토 후 revert 결정.

**결정 (4/25 13:49, 본인 사료)**: **"Phase 2A — Commit 2 Revert + Commit 3a 준비"** + **"자산 영구 보존 위치 이동 + README + archive push"** (`archive/commit-2-aborted` 브랜치 작성).

**이유**: Commit 2 catch 후 본인이 결과 catch 부족 catch → 자산 보존 + 신축 path 진입.

**결과**: `archive/commit-2-aborted` 브랜치 catch. Commit 3a (자산 복원 + Babel 검증) 재시작.

---

### ADR-005. License MIT → Elastic 2.0 (4/24, Phase 2A KICKOFF Decision 1)

**맥락**: v0.x main MIT License catch. Phase 2A 진입 (Tailwind redesign).

**결정**: **MIT → Elastic License 2.0**.

**이유 (본인 링크 대화 사료)**: **"최초 프로젝트 목적 망각 말고, 내 시간·노력 인정. 남들에게 다 퍼주는 게 마냥 좋은 건 아니다."**

**결과**: LICENSE 파일 Elastic 2.0 catch. 사용자가 GuruNote 코드를 그대로 SaaS 호스팅 / 라이선스 우회 catch 부재.

---

### ADR-006. 2-pass DCCD + 화자 코드 부착 (5/23)

**맥락**: 1-pass에서 LLM이 segment N개를 다른 line 수로 출력 (drift). strict json_schema는 출력 강제 catch이지만 모델이 1줄 본문에 다음 segment 정보 합치는 catch (hallucinate). rule 1 prompt 추가 시 모델 충돌 catch.

**결정 (5/23, `39652c6` ~ `599c94b`)**: **DCCD (Draft-Conditioned Constrained Decoding)** — 1단계 자유 번역 (schema 부재) → 2단계 strict 정렬 (minItems=maxItems=N). 화자 라벨은 LLM 식별 1회 + 코드 결정론 부착 (rule 1 prompt 충돌 해소).

**대안**:
- A. rule 1 prompt 추가 (단일 통과) — 모델 충돌, 강한 모델만 catch
- B. (채택) 2-pass + 화자 코드 부착 — 모델 비의존 path
- C. 정렬을 코드로만 — 가능성 catch이지만 의미 단위 분할 catch 부족

**이유**: 모델 비의존 = 약한 모델에서도 SHIFT 차단. 화자 부착 = LLM 비결정성 catch 차단.

**결과**: 2-pass 1단계 정합 30% → 57~69% (3배). 빈 output 3단계 복구 시퀀스 추가.

---

### ADR-007. pyannote 3.1 → community-1 (5/23)

**맥락**: 화자 라벨 코드 부착 catch했지만 일부 영상에서 같은 화자가 chunk마다 다른 cluster catch (embedding drift). 3-speaker 영상에서 A 라벨에 두 화자 섞임 catch.

**결정 (`8ecd276`)**: pyannote 3.1 → **community-1** (pyannote.audio 4.0+ 정합).

**이유**: community 1 모델이 speaker confusion 마크 catch 감소 (pyannote 공식 catch).

**결과**: oE5lNDhz9oo 검증에서 A=Jensen / B=Michael / C=Ed Ludlow 3명 정확 catch.

---

### ADR-008. STT 직후 의미 단위 재분할 + char_limit=2000 자동 (5/24, Phase 5)

**맥락**: 5/23 화자 코드 + 2-pass catch했으나, 5/24 D segment 단독 번역 prototype catch에서 **context leak** 발견 ([365.7] "secure and" / [574.0] "during a meeting,"). 본질 진단: Whisper segment 잘림 = 음성 신호 기반 (의미 단위 부재). 같은 catch가 1-pass hallucinate + 2-pass SHIFT + 본문 가독성 + D leak 4개 단계 공통 catch.

**결정 (`527d2ea`)**: STT 직후 **word-level 의미 단위 재분할** + 재분할 적용 시 **chunk_size=12 + char_limit=2000** 자동.

**대안**:
- A. D 직전 합치기 (F) — 우회, 다른 단계 catch 부재
- B. (채택) STT 직후 1회 재분할 — 단일 진실 (단일 위치, 모든 단계 영향)
- C. context 모델 비의존 차단 (한국어 context 등) — 병렬 손실

**이유**: 모델 비의존 catch — Whisper segment 잘림 동기 (음성 기반)을 코드로 차단. 4개 단계 (D leak / 2-pass SHIFT / 1-pass hallucinate / 가독성) 동시 catch.

**결과**:
- D leak 해소 ([365.7] [574.0] 두 사례)
- 2-pass 1단계 합침 16 → 9 (44% 감소), 정합 30→57~69%
- 1-pass timeout 6 → 1 (긴 영상 catch)
- 다영상 6개 검증 + 통합 본체 검증 (HEAD 527d2ea catch)

**토글**: `GURUNOTE_SEGMENT_RESPLIT` 기본 off — daily 검증 후 default on 결정.

---

### ADR-009. Phase 4 capability profile 보류 → "모델 비의존" 우회 (5/24)

**맥락**: backlog B05 — Phase 4 capability profile (모델별 max_ctx, supports_tool_call, korean_quality 추적) — "모델 교체 결정 후 진입" blocked 상태. 현재 qwen3.6-35b-q5 고정.

**결정 (5/24)**: **B05 본 전제 (모델 교체) 우회** — Phase 5 (재분할 + char_limit)이 모델 capability 의존 부재 path catch. capability profile 본 시점 진입 부재.

**이유**: 모델별 catch (max_ctx, korean_quality 등)에 처리 결과를 맞추는 게 아닌, **입력(segment)을 정제해서 모델 편차를 줄이는** path catch. 약한 모델 (35b-A3B)에서도 catch.

**결과**: B05 blocked 유지. "모델 비의존" 방향과 통합 결정은 추후.

---

### ADR-010. Phase 5 default on — 재분할 + 2-pass 기본값 전환 (5/24)

**맥락**: ADR-008 STT 의미 단위 재분할 (`527d2ea`) 진입 시점에는 토글 기본값 off (daily 1-pass 동작 보존 의도). 다영상 6 개 검증 + 통합 본체 검증 통과했으나, daily 환경 (cache 격리 부재, qwen3.6-35b-q5) 에서 본인 평소 영상 토글 on 결과는 미측정.

**결정 (`6dc9934`, 5/24)**: daily 검증 영상 2 개 토글 on 결과 통과 후 **`GURUNOTE_SEGMENT_RESPLIT` + `GURUNOTE_TWO_PASS` 기본값 off → on** 전환. 토글 자체는 유지 — `GURUNOTE_*=0` 명시 시 기존 1-pass + 원본 segment 동작 보존 (안전망).

**검증 결과**:
- xKK5ze3FukQ (Boston Dynamics, 5.7 분): 96 → 49 segments (-49 %), timeout 0, CJK 0, 5 명 화자 중 3 명 bootstrap 식별 (메타데이터 한계 — B08 등록)
- zNuOOMM20Tk (NVIDIA Podcast, 33.4 분): 586 → 294 segments (-50 %), timeout 0, CJK 0, 2/2 화자 식별

**대안**:
- A. default off 유지 — 안전, 단 사용자가 토글 모를 시 개선 반영 부재
- B. (채택) default on, off 안전망 유지 — 새 사용자 자동 적용 + 익숙 사용자 우회 가능
- C. default on, 토글 제거 — 회귀 차단 path 부재 (기각)

**이유**: daily 검증 통과 = 권장 동작이 default. 토글 안전망 유지로 회귀 대비.

**결과**: test 2 건 수정 (`test_default_off_uses_one_pass` → `test_explicit_off_uses_one_pass`, `test_env_default_off` → `test_env_default_on`), 183 tests passed.

---

### ADR-011. v1.0.0.0 선언 — CLAUDE.md "1.0 전 MINOR 대체" 의식적 예외 (5/24)

**맥락**: CLAUDE.md 버전 정책 본문에 "1.0.0 전까지는 MINOR 로 대체" 명시. 단 redesign/tailwind-v2 누적 변경 = License MIT → Elastic, UI CustomTkinter/Streamlit → React/Material 3/PyWebView, 번역 1-pass → 2-pass DCCD + entity_cache + CJK 차단 + STT 재분할 — 셋 다 하위 호환을 동시에 깸.

**결정 (`2971939`, 5/24)**: **0.8.0.6 → 1.0.0.0**. CLAUDE.md 정책의 **의식적 예외**. 1.0 선언이 변경 규모를 정직하게 표기.

**대안**:
- A. 0.9.0.0 (표준 MINOR 1 회) — 변화 규모 과소 표현
- B. 0.10.0.0 (MINOR 2 회 분량) — 의미가 약함
- C. (채택) 1.0.0.0 — License + UI + 백엔드 셋 다 하위 호환 깸 = MAJOR 정직 표기
- D. 보류 — 변경 묶음 누적이 이미 큼

**이유**: 라이선스 (외부 사용자 영향) + 진입점 (사용자 명령 변경) + 파이프라인 동작 (출력 형식 영향) 셋이 한 묶음으로 통합되는 시점이 1.0 선언에 부합.

**결과**:
- 버전 6 곳 + pkgbuild 1 곳 = **7 곳 일치** (`__init__.py:9`, `gui.py:3341`, `package_desktop.py:113` Inno Setup, `package_desktop.py:231` pkgbuild, `SettingsScreen.jsx:721` fallback, `README.md:506`, `CHANGELOG.md` entry)
- CLAUDE.md 체크리스트 5-file → **6-file** (React fallback `SettingsScreen.jsx` 추가)
- 신규 `run_webview.command` (React/PyWebView macOS 런처)
- README 약 60 % 재작성
- 신규 백로그 B09 (PipelineWorker 분리) + B10 (setup 스크립트 echo 갱신)

---

### ADR-012. main 통합 — unrelated histories + force-with-lease (5/24)

**맥락**: 5/24 main 통합 시점에 두 브랜치가 **공통 조상 부재** 사실 사후 확인. `git merge-base origin/main redesign/tailwind-v2` 가 빈 결과 반환. main 트리 root `4bcbee6` (4/11 "Initial commit"), redesign 트리 root `af50c2e` (같은 메시지, 다른 hash). 4/19 직후 웹 Claude → 로컬 CLI Claude Code 전환 시 별도 `git init` 으로 시작한 결과로 추정 (본인 기억 — 정확한 시점/commit 기록 부재).

**결정 (5/24)**: 옛 main 영구 보존 후 redesign 트리를 main 으로 통일. **`git push origin main --force-with-lease`**.

**대안**:
- A. `--allow-unrelated-histories` 머지 — 파일 충돌 다수 예상 (같은 경로 다른 파일), 머지 commit 통합
- B. (채택) 옛 main archive 보존 + redesign 를 main 으로 force-with-lease — 안전망 먼저 + history 깔끔
- C. branch 자체 교체 (delete main + rename redesign) — GitHub default branch 재설정 필요
- D. 보류 — 두 브랜치 양립 운영 (운영 복잡)

**안전망 시퀀스**:
1. `git branch archive/main-pre-cli origin/main`
2. `git push origin archive/main-pre-cli` (확인: `9b6c62...`, 211 commit, root `4bcbee6` 도달)
3. `git checkout main && git reset --hard redesign/tailwind-v2`
4. `git push origin main --force-with-lease` (origin/main 예상 상태 검증 후 push, plain `--force` 부재)

**이유**: force push 는 본인 명시 허용 + archive 보존이 되돌릴 수 있는 안전망. force-with-lease 는 다른 사용자 push 보호. 단일 main 트리가 운영 복잡도를 낮춤.

**결과**:
- origin/main: `9b6c621` (v0.8.0.6) → `2971939` (v1.0.0.0)
- origin/archive/main-pre-cli: `9b6c621` 유지 (옛 main v0.x 전체 211 commit 영구 보존)
- test 183 passed (main 상태)

---

### ADR-013. gui/app legacy 처리 — Path C (파일 유지, 분리는 백로그) (5/24)

**맥락**: v1.0.0.0 준비 시 옛 진입점 `gui.py` (CustomTkinter) + `app.py` (Streamlit) 의 legacy 이동 검토. 의존성 사전 점검 시 **`gurunote/webui/session.py:67`** 에 `from gui import PipelineWorker` 발견. React UI (`app_webview.py`) 가 옛 CustomTkinter UI 파일에 들어있는 `PipelineWorker` 클래스를 그대로 import 함.

**결정 (5/24)**: **Path C** — gui.py / app.py 둘 다 루트 유지. README / 진입점 안내만 갱신. `PipelineWorker` 분리는 **B09 백로그**.

**대안**:
- A. gui.py 유지, app.py 만 legacy 이동 — 일부 정리
- B. PipelineWorker 를 `gurunote/pipeline_worker.py` 신규 모듈로 분리 후 gui.py legacy 이동 — 가장 깔끔하나 코드 로직 이동 (가드레일 "코드 로직 변경 부재" 위반)
- C. (채택) 양쪽 다 루트 유지, README/안내만 갱신 — 가장 안전, 외과적
- D. 보류 — v1.0 작업 범위 축소

**이유**: 본 세션 가드레일 "외과적, 코드 로직 변경 부재". PipelineWorker 분리는 별도 세션 작업으로 분리. 옛 진입점 호환 유지 = 옛 사용자 안전망.

**결과**:
- 파일 이동 0, 코드 로직 변경 0
- README 가 `app_webview.py` 권장 + 옛 진입점 호환 사실 + B09 백로그 안내 명시
- 백로그 B09 (PipelineWorker 분리, P3, 중간 비용) 등록
- 백로그 B10 (setup 스크립트 echo 갱신, P3, 작음) 등록

---

### ADR-014. Obsidian 출력 — 표식 기반 동기화 + 파일명 = 제목 (5/25)

**맥락**: v1.0.0.3~0.5 Obsidian 내보내기 배선. 라이브러리 삭제 시 vault 사본도 지울지, vault 파일을 job 과 어떻게 잇는지, 파일명 접두사를 둘지 결정 필요.

**결정**:
- 내보낼 때 frontmatter 에 `gurunote_job_id` **표식** 삽입. 삭제 시 그 표식이 일치하는 vault 파일만 제거 (`delete_from_vault`). 파일명은 충돌 시 timestamp suffix 가 붙어 역추적 불가하므로 표식이 유일한 정확 매칭 근거.
- **표식 없는 기존 내보낸 파일은 자동 삭제 대상 아님** (설계 의도) — 앞으로 내보내는 것만 동기화, 기존은 사용자 수동 정리. 의도치 않은 삭제 위험 차단.
- 삭제는 **best-effort** — 라이브러리 삭제는 무조건 성공, vault 삭제 실패는 결과만 알림.
- 파일명 `GuruNote_<제목>.md` → **`<제목>.md`** (접두사 제거, v1.0.0.5). 출처 구분은 접두사 대신 표식 + `Gurunote/` 하위 폴더가 담당. 파일명·wikilink stem 을 단일 helper(`_obsidian_note_stem`)로 통합해 그래프 연결 유지.

**이유**: 표식은 파일명 변경·중복에 영향받지 않는 안정적 식별자. best-effort 는 vault 미설정/네트워크 등으로 핵심 동작(삭제)이 막히지 않게. 접두사 제거는 daily 그래프 가독성.

**결과**: B13/B14 완료. wikilink alias `[[stem\|제목]]` 로 그래프 연결 + 제목 표시. 삭제 동기화는 표식 기반이라 파일명 변경(v1.0.0.5)에 영향 없음.

---

### ADR-015. 인명/고유명사 품질 — 음차는 프롬프트, 영문 철자는 결정론 검증 (5/26)

**맥락**: daily 노트에서 인명이 통용 표기와 어긋남 — "팰머 러커이"(Palmer Luckey), "리크 리더"(Rick Rieder). 별개로 영문 병기 철자 오염 — "안두릴(Danduril)"(원문 Anduril, 제목 포함). 진단 — (A) 음차는 통용 dict 미수록 인명을 LLM 이 외래어 규칙으로 철자 추정 + entity_cache 가 첫 표기 고정해 "일관되게 틀림". (B) 영문 병기는 LLM 이 영문 원어를 자유 생성하다 오염 (소스에 정답 있어도).

**결정**:
- **(A) 음차 — 프롬프트 강화** (v1.0.0.6): 번역 Rule 10 우선순위 역전 (통용 표기[발음 기준] > 통용 목록 > 외래어 규칙 fallback). 통용 dict 일괄 보강 대신 **모델이 아는 통용 표기를 끌어냄**. 짧은 테스트로 로컬 모델이 통용 표기를 안다고 확인 → dict 보강 불필요.
- **(B) 영문 병기 — 결정론적 소스 검증** (v1.0.0.7): `_correct_english_annotations` 가 `한국어(English)` 병기 영문을 소스(transcript 전문 + 제목)와 대조. 정확 시 케이싱 정규화 / 단일 토큰 오타는 보수적 최근접(difflib 0.84) 교정 / **근거 없으면 병기 생략** (틀린 철자 안 박음). LLM 무관 순수 함수.

**이유**: 음차(A)는 모델의 한국어 지식 영역이라 프롬프트가 적합 + dict 유지비 회피. 영문 철자(B)는 소스에 정답이 있는데도 LLM 수동 생성이 오염되므로, 프롬프트(수동)로는 부족하고 프로그램이 능동 검증해야 확실. "근거 없으면 생략"은 틀린 철자보다 누락이 낫다는 판단.

**결과**: B15 (A·B) 완료. end-to-end — 팔머 럭키/릭 리더(A) + Anduril 정확/Danduril 0(B) 동시 확인. 과교정·회귀 부재. tests 8건.

---

### ADR-016. 처리 옵션을 앱 토글로 — 환경변수에서 UI 로 (5/26)

**맥락**: 2-pass 번역(`GURUNOTE_TWO_PASS`) + STT 재분할(`GURUNOTE_SEGMENT_RESPLIT`) 이 환경변수로만 조절돼 앱에서 못 바꿈. 둘 다 기본 켜짐.

**결정 (v1.0.0.8, B16-1단계)**: 설정 "고급"에 토글 노출. `_KNOWN_SETTINGS` 에 두 키 추가 → `get_settings`/`save_settings`(.env + os.environ) 연동. **백엔드 읽기 로직(`llm.py`/`stt_mlx.py`)은 무변** — 키 추가 + UI 만. 자동 내보내기 토글은 2단계(B16-2)로 분리.

**핵심 함정 회피**: 백엔드가 정확히 `"1"`만 ON 으로 보고 `""`(빈 값)은 OFF 로 본다. `get_settings`는 미설정 키를 `""`로 반환하므로, 토글 표시 = `값 !== "0"` (빈 값·absent → ON), 저장은 **항상 `"1"`/`"0"` 만** 기록 (빈 값 저장 금지). patch 는 변경된 키만 보내므로 미조작 토글은 env 미설정 유지 → 기본 동작 불변.

**대안**: 백엔드 default 를 바꾸거나 별도 config 파일 — 기각 (env 인프라 재사용이 외과적).

**결과**: B16-1단계 완료. 격리 .env 라운드트립 검증 (미설정→ON, off→llm OFF, on→llm ON). 재사용 `SettingsSwitch` 컴포넌트 신규.

---

### ADR-017. 인명 관리 자동화 — auto/user dict + 편집 UI + 결정론 교정 (v1.0.0.10~13, 5/26~27)

**맥락**: ADR-015(A)에서 음차 통용 표기를 프롬프트(Rule 10)로 끌어내기로 했으나, 실제 daily 영상에서 "팰머 러커이"가 계속 굳었다. 재진단 결과 세 겹 원인 — bootstrap 의 first-seen 표기 고정 / bootstrap 프롬프트에 발음 우선 규칙 미반영 / **디스크 캐시가 옛 표기를 그대로 로드해 프롬프트를 우회**. 프롬프트만으로는 캐시에 굳은 표기를 못 바꾼다.

**결정**: 프롬프트(ADR-015) 위에 **결정론 교정 계층**을 얹는다. ADR-015 의 후속·확장이며, v1.0.0.6(프롬프트)과 별개의 문제(캐시 고정)를 다룬다.
- **v1.0.0.10** (`9d342b6`): 편집 가능 통용 dict `~/.gurunote/canonical_names.json` 신설. `entity_cache`·`speaker_cache` 의 한국어 표기를 dict 로 강제 교정(대소문자 무시, 미수록은 불변). bootstrap(디스크 캐시 적중 포함) 직후 + chunk loop 전에 적용 → 저장 시 디스크 캐시 self-heal. bootstrap 프롬프트에도 발음 우선 지시 추가.
- **v1.0.0.11** (`d106430`): dict 구조를 `{English:{auto,user}}` 로 확장(옛 flat → user 마이그레이션). 작업 중 raw 표기를 auto 로 자동 누적(user 불변), 교정은 user 우선. atomic 저장.
- **v1.0.0.12** (`c8311ae`): 설정 "고급"에 `SettingsCanonicalNames` 편집 UI(영문 | auto 읽기전용 | user 입력 | 삭제). bridge `get_canonical_names`/`save_canonical_names` 신규(llm `_load`/`_save` 호출만, .env 와 별개 state).
- **v1.0.0.13** (`390d69b`, +`50d0140` 라벨 보강): `refresh_canonical_in_markdown` + bridge `refresh_job_canonical` — 이미 저장된 노트의 옛 표기를 auto·user 둘 다 있는 항목만 단일 패스 정규식으로 치환(연쇄 치환 없음). HistoryScreen "표기 새로고침" 버튼.

**대안**: dict 일괄 보강(유지비 큼, 기각) / 캐시 비활성(일관성 손실, 기각) / 프롬프트만 더 강화(캐시 우회 못 함, 이미 실패).

**이유**: 음차 자체는 모델의 한국어 지식이라 프롬프트가 맞지만(ADR-015), 캐시에 굳은 표기는 프로그램이 결정론적으로 덮어써야 확실하다. user 우선 dict 로 사용자가 최종 통제권을 갖는다.

**결과**: B15 A-2 전체 완료. 인명 품질 자동화 완결(자동 누적 + 편집 + 기존 노트 소급). tests 7~8건 누적, 213 passed.

---

### ADR-018. 번역 충실도 방향 — 충실 의역 전환 + 환각·영어 차단 (v1.0.0.14~20, 5/27~28)

**맥락**: 본문·제목·요약이 각각 별도 LLM 경로라 품질 규칙이 고르게 적용되지 않았다. 직역이 모호해 형식(게임 문답·말장난)을 뭉개거나, 요약에 원문에 없는 인물이 섞이거나, 영어 단어가 한국어로 안 옮겨지는 사례가 daily 에서 누적.

**결정**: "직역 vs 의역" 을 **충실 의역**으로 정리하고, 각 경로에 환각·영어·인명 일관 규칙을 프롬프트 + 결정론 후처리로 일관 적용.
- **v1.0.0.14** (`2692cd0`): 제목·요약 한자 혼입 차단 — Phase 3 CJK 후처리를 segment 없는 경로(제목·요약)에도 적용(`post_process_cjk_text`).
- **v1.0.0.15·16** (`5ef0e2f`·`01553af`): 제목 원본 직역 우선 + 인명 dict 교정(15), 제목 구조·형식·문답·말장난 보존 규칙 구체화(16). "I Say Economy, You Say…" 게임 구조 보존 확인.
- **v1.0.0.17** (`89f68ec`): 노트 frontmatter 에 생성 GuruNote 버전 표시(추적성, B19).
- **v1.0.0.18** (`c372c72`): 본문 번역을 충실 의역으로 전환 — 환각·누락·영어 비번역 금지 + 예시(B20).
- **v1.0.0.19** (`ab04856`): 본문 연속 반복 라인 축약(`_collapse_repeated_lines`) — 더듬거림 구간을 2-pass 정렬이 같은 문장으로 채우던 회귀 차단(B21).
- **v1.0.0.20** (`9aad35e`): 요약 충실도 — `SUMMARY_SYSTEM_PROMPT` 환각·영어·인명 규칙 + 요약 결과 dict 인명 후처리(B22).

**이유**: 직역의 모호함을 "충실 의역(의미·형식 보존, 날조·생략 금지)"으로 못박고, 프롬프트로 부족한 부분(인명·CJK)은 결정론 후처리로 메운다. 본체·제목·요약 세 경로의 규칙을 정합시켜 편차를 줄인다.

**결과**: B17~B22 완료(v1.0.0.14~20). 단 프롬프트 레벨이라 완벽 통제는 아님 — 노트 편집·검색 그라운딩(ADR-020)으로 보완.

---

### ADR-019. LLM temperature 0.6 확정 (5/29)

**맥락**: 같은 영상(드러켄밀러)을 temperature 0.8 과 0.6 으로 대조 처리해 품질을 비교.

**결정**: **temperature 0.6 유지**(설정값, 코드 무관).

**대안**: 0.8(더 자유로운 표현, 단 누출·환각 증가) / 0.6(채택) / 더 낮춤(경직·반복 우려).

**이유**: 0.6 에서 제목의 "경제" 같은 핵심어가 살아남고, `formidable`·`things` 같은 영어 누출이 한국어로 더 옮겨지며, 전반적으로 더 충실했다. Besson/Wash 류 인명 오인식은 0.8·0.6 무승부 — 이는 temperature 가 아니라 검색 그라운딩(ADR-020)이 다룰 사안.

**결과 / 한계**: 0.6 확정. 단 **0.6 도 영어 누출·인명 환각을 100% 차단하지 못함** — 5/29 재처리에서 `formidable`/`brilliant`/`Rates` 누출 + 원문에 없는 "제롬 파월" 환각 재확인(DEBUGGING §8). 프롬프트·temperature 의 한계 → 검색 그라운딩(ADR-020) + 요약 충실도(B22) 대상.

---

### ADR-020. 검색 그라운딩 — AgentSearch(SearXNG) 채택 + entity-only 번역 검증 (5/29, 채택·구현 대기)

**맥락**: 프롬프트(ADR-018)·temperature(ADR-019) 로는 인명·회사명 오인식·환각을 못 막는다(Besson/Wash, "제롬 파월"). 모델 내부 지식만으로는 한계라 외부 근거가 필요.

**결정 (채택, 구현 대기)**: **AgentSearch** — SearXNG 를 FastAPI 로 래핑(gesicht 에 Docker)해 검색 그라운딩 계층을 만든다. 전체 번역이 아니라 **인명·회사명만 번역 후 entity 검증 패스**로 좁히고, 기존 `entity_cache`·통용 dict 를 재사용한다. 토글로 켜고, 오프라인이면 자동 스킵. Wash→Warsh 같은 작은 검증부터 착수.

**대안**: 더 큰 모델로 교체(모델 비의존 방향과 충돌) / 프롬프트 추가 강화(이미 한계) / dict 수동 확대(유지비·커버리지 한계).

**이유**: 오류가 좁은 영역(고유명사)에 몰려 있어 전면 검색이 아니라 entity 한정 검증이 비용 대비 효과가 크다. 토글·오프라인 스킵으로 완전 로컬 정체성을 깨지 않는다.

**결과**: 설계 확정. **착수는 신선한 세션**(현재 구현 0). 진행 시 entity 검증 패스 + 토글 + Wash→Warsh 검증 순.

---

### ADR-021. 자동 내보내기 중복 스킵 정책 — Q23=C (v1.0.0.25, 5/29)

**맥락**: 자동 내보내기 본체는 이미 v1.0.0.9(B16-2, `83551bc`)에 완료(작업 완료 시 `App.onResult` 에서 `send_obsidian`, 기본 꺼짐, best-effort). 단 `save_to_vault` 는 같은 파일명이면 timestamp 접미사로 새 파일을 만들어, 자동을 켠 채 같은 영상을 재처리하면 vault 사본이 쌓였다.

**결정 (Q23=C)**: **자동 호출일 때만**, 같은 `gurunote_job_id` 표식 노트가 vault 에 이미 있으면 내보내기를 건너뛴다. **수동 "Obsidian" 버튼은 종전대로 항상 새로 저장**(스킵 안 함). 기존 `obsidian.find_vault_copies`(읽기 전용) 재사용.

**대안**: 항상 덮어쓰기(수동 의도 훼손) / 항상 스킵(수동 재내보내기 불가) / 파일명 해시 비교(표식이 더 안정적, 기각).

**이유**: 자동은 "중복 누적 방지", 수동은 "사용자가 일부러 다시 내보냄" — 의도가 다르므로 자동에만 스킵. 표식 기반(ADR-014)이라 파일명 변경에 영향 없음.

**결과**: v1.0.0.25(`86ce877`). `bridge.send_obsidian` 에 `skip_if_exists` 인자(기본 꺼짐, 자동 호출만 켬), 스킵 시 안내 토스트. `save_to_vault`·`obsidian.py`·`semantic.py` 무변(재사용만).

---

### ADR-022. 토스트 타입 시각 재도입 — Phase 2B-6d 제약을 지킨 복원 (v1.0.0.26, 5/29)

**맥락**: Phase 2B-6d 에서 토스트의 타입별 시각(반투명 tint 배경·좌측 color strip)을 **의도적으로 제거**했다. 사유는 tint 배경이 TopBar 검색창 위에 겹칠 때 반투명하게 보여 가독성이 떨어졌기 때문(`main.css` 주석). 그 결과 성공·건너뜀·실패를 텍스트로만 구분해야 했다.

**결정**: 제거 결정의 **반전이 아니라, 그 제약(배경 불투명 유지)을 지킨 재도입**. 배경은 불투명 흰색 그대로 두고 **좌측 보더 색만** 부여(성공=`--gn-success`, 정보=`--gn-primary`, 경고=`--gn-warning`, 실패=`--gn-danger`). 기존 토큰 재사용, info 는 전용 토큰이 없어 primary 차용.

**대안**: tint 배경 복원(원래 가독성 문제 재발, 기각) / 텍스트만 유지(구분 약함, 현행) / 아이콘 추가(레이아웃 변경 큼).

**이유**: 원래 제거 사유는 "반투명 배경"이지 "타입 구분 자체"가 아니었다. 좌측 보더는 불투명 배경을 건드리지 않으면서 구분을 준다. 사용자 확인 후 진행한 선택.

**결과**: v1.0.0.26(`a05925c`). `main.css` 한 파일. 직전에 자동 내보내기 토스트 누락이 "버그 아님"으로 규명되며(DEBUGGING §8) 함께 정리.

---

## 기각된 대안

### REJ-001. VibeVoice / Nemotron Omni 통합 모델 (시점 기록 부재)

**평가**: 한국어 ASR 정확도 + 로컬 실행 + 화자 분리 분리성 catch.

**기각 이유**: 셋 다 catch 부족.

**재평가**: 2026-10 (Appendix B, 본인 기억).

---

### REJ-002. dense 모델 가설 (5/22 시점 추정)

**맥락**: MoE (qwen3.6-35b-A3B-oQ6) catch 부족 의심 — dense 모델 (qwen3.6-35b-q5)으로 fallback 평가.

**기각 이유**: 다영상 검증에서 둘 다 catch + 2-pass + 재분할 catch path가 모델 종류 비의존 catch. dense 가설 부재.

---

### REJ-003. rule 1 prompt 조정 (5/23 직전)

**맥락**: 2-pass 2단계 정렬 prompt에 rule 1 (drift 차단) 추가 시도.

**기각 이유**: 모델 충돌 catch — 강한 모델만 catch, 약한 모델 출력 부재 위험. **모델 비의존 path 부재** — 본인 결정 (5/23 보강 시리즈 catch).

**대체**: A1 (rule 1 강화) + A5 (prefix strip) 보강 (`7a397fa`).

---

### REJ-004. 모델 자동 감지 (5/24, Phase 5 진단)

**맥락**: 재분할 후 1-pass timeout 증가 catch (긴 영상). 토글 / 모델 capability 자동 감지 후보.

**기각 이유**: 모델 capability 자동 감지 = 추정 위험 + 복잡. **단일 진실 (재분할 + char_limit=2000 default on)** path 채택.

**대체**: char_limit=2000 자동 적용 (`527d2ea`).

---

### REJ-005. (시점 부재 - 본인 기억) Streamlit 유지

**기각 이유**: 데스크톱 앱 catch 부족 — 백엔드 직접 호출 path 부재. PR #4에서 CustomTkinter로 전환.

---

## 결정 영향 catch 표

| 결정 | 영향 모듈 | 시간 |
|------|---------|------|
| ADR-001 완전 로컬 | gurunote/stt.py, stt_mlx.py | v0.4.0 ~ v0.6.0 |
| ADR-002 PyWebView | gurunote/webui/ (신규) | 4/19~ |
| ADR-003 React 신축 | webui/components/* | 4/27~5/2 |
| ADR-004 Commit 2 Revert | archive/commit-2-aborted | 4/25 |
| ADR-005 Elastic 2.0 | LICENSE | 4/24 |
| ADR-006 2-pass DCCD | gurunote/llm.py | 5/23 |
| ADR-007 community-1 | gurunote/stt_mlx.py | 5/23 |
| ADR-008 STT 재분할 | gurunote/stt_mlx.py, llm.py, tests/test_segment_resplit.py | 5/24 |
| ADR-009 Phase 4 보류 | backlog.md (B05 blocked 유지) | 5/24 |
| ADR-010 Phase 5 default on | gurunote/stt_mlx.py, llm.py, tests 2 건 수정 | 5/24 (`6dc9934`) |
| ADR-011 v1.0.0.0 선언 | __init__.py, gui.py, package_desktop.py, SettingsScreen.jsx, README, CHANGELOG, CLAUDE.md, run_webview.command (신규), backlog.md | 5/24 (`2971939`) |
| ADR-012 main 통합 | origin/main (force-with-lease), origin/archive/main-pre-cli (신규 보존) | 5/24 |
| ADR-013 gui/app Path C | (파일 이동 부재) — README 진입점 안내, backlog B09/B10 | 5/24 |
| ADR-014 Obsidian 표식 동기화 | gurunote/obsidian.py, webui/bridge.py | 5/25 (v1.0.0.3~0.5) |
| ADR-015 인명 음차/영문 철자 | gurunote/llm.py | 5/26 (v1.0.0.6~0.7) |
| ADR-016 처리 옵션 토글 | webui/bridge.py, SettingsScreen.jsx | 5/26 (v1.0.0.8) |
| ADR-017 인명 관리 자동화 | gurunote/llm.py, webui/bridge.py, SettingsCanonicalNames.jsx, HistoryScreen.jsx | 5/26~27 (v1.0.0.10~13) |
| ADR-018 충실도 방향 | gurunote/llm.py, exporter.py | 5/27~28 (v1.0.0.14~20) |
| ADR-019 temperature 0.6 | (설정값, 코드 무관) | 5/29 |
| ADR-020 검색 그라운딩 AgentSearch | (구현 대기) | 5/29 |
| ADR-021 자동 내보내기 스킵 정책 | webui/bridge.py, webui/components/App.jsx | 5/29 (v1.0.0.25) |
| ADR-022 토스트 타입 시각 | webui/styles/main.css | 5/29 (v1.0.0.26) |

---

**자료 한계 명시**:
- REJ-001/REJ-002/REJ-005 시점 일부 본인 기억 2차 사료.
- ADR-001/004/006/007/008/010/011/012 는 commit hash + session_history_digest + git ref 1차 사료.
- ADR-014~022 는 commit hash 1차 사료(전부 redesign 트리 git log 로 확인). **ADR-020(검색 그라운딩)은 채택 결정만 기록 — 구현 0, 착수 대기.** ADR-019(temperature)는 설정값이라 코드 commit 없음.
- ADR-012 의 unrelated histories 발생 정확한 시점 (별도 init 한 commit) 은 **기록 부재** — 양쪽 root commit 메시지 동일 ("Initial commit"), 4/11 같은 날, hash `4bcbee6` vs `af50c2e`. 본인 기억으로는 4/19 직후 환경 전환.

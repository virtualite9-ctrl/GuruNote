# GuruNote Backlog

마지막 갱신: 2026-05-29 (v1.0.0.21~26 뷰어 사용성 + 자동 내보내기 스킵 정책 + 토스트 시각, 검색 그라운딩 신규 대기)
운영 규칙: WIP=1 (동시 active 작업 1개 제한)
상태 정의: not_started / active / blocked / passing

## 진행 중 (WIP=1)

없음

## 대기 중

### Phase 5: STT 의미 단위 재분할 + 2-pass default on

- 상태: **완료** (5/24, commit `527d2ea` + default on `feat: Phase 5 재분할 + 2-pass default on`)
- 요약: GURUNOTE_SEGMENT_RESPLIT + GURUNOTE_TWO_PASS 기본값을 on으로 전환. daily 검증 2개 영상 통과 (영상1 96→49 segments, 영상2 586→294 segments, timeout 0, CJK 0, 화자 이름 정상 부착).
- 토글 off 안전망 유지: GURUNOTE_SEGMENT_RESPLIT=0 / GURUNOTE_TWO_PASS=0 으로 기존 동작 복원 가능.

### 검색 그라운딩 — AgentSearch (SearXNG) + entity 검증 패스

- 배경: 프롬프트(ADR-018)·temperature 0.6(ADR-019)으로도 인명·회사명 오인식·환각을 못 막음(Besson/Wash, 원문에 없는 "제롬 파월" 환각 — 드러켄밀러 재처리 5/29). 모델 내부 지식 한계 → 외부 근거 필요.
- 설계 (ADR-020): SearXNG 를 FastAPI 로 래핑(gesicht Docker). 전체 번역이 아니라 **인명·회사명만 번역 후 entity 검증 패스**로 좁힘. 기존 `entity_cache`·통용 dict 재사용. 토글(오프라인 자동 스킵 — 완전 로컬 정체성 유지). Wash→Warsh 작은 검증부터.
- 상태: **채택, 구현 0 (착수 대기 — 신선한 세션)**
- 우선순위: P1 (인명 품질 마지막 한계)
- 비용: 큼 (Docker + 검증 패스 + 토글 + 검증)

### 뷰어 사용성 — v1.0.0.21~24 (완료, 5/28~29)

- **타임스탬프 토글 (v1.0.0.21, 완료)**: 뷰어 한·영 탭에서 `[MM:SS]` 표시 토글(보기 전용, 원본 불변). exporter 적용판을 먼저 만들었다가 적용 지점 오판으로 revert(`9a12566`→`c3b58bb`) 후 `ResultPanel` 뷰어판 재구현(`ca9ebf1`). 본문 드래그 복사도 함께 수정(`26b3f2a`, `user-select:text`). DEBUGGING §7.
- **생성일 KST 표시 (v1.0.0.22, 완료)**: `historyFormatCreatedAt` — ISO UTC 원본이 그대로 노출되던 것을 `Asia/Seoul` 변환 표시. 저장 필드 불변(정렬 무영향).
- **통용 표기 독립 화면 + 검색 (v1.0.0.23, 완료)**: 설정 "고급" 인라인에서 떼어 좌측 네비 독립 항목으로. 영문·표기 검색(검색 중에도 수정·삭제 원본 인덱스 보존).
- **통용 표기 추가 행 맨 위 (v1.0.0.24, 완료)**: "추가" 시 새 빈 행을 목록 맨 앞에(스크롤 없이 바로 입력, 검색어 해제).

### B01: Phase 2 — entity cache + 화자 cache

- 동작: 영상 단위 entity/speaker 정보 캐시로 외부 인물 hallucinate 차단
- path 결정: (e) Entity Cache + (b) Two-Stage 결합 (5/19)
- 검증:
  - `tests/test_phase2_entity_cache.py` 통과 (24/25, 1 slow integration) — 5/19 작성
  - real video verify 에서 5/18 샘 올트먼 사례 재현 부재 (구현 후)
- 상태: **passing** (Step B + Step C 모두 완료, verify 통과)
- 우선순위: P0 (사용자 경험 가장 큰 개선)
- spec: `docs/research/phase2_entity_cache_spec.md` (5/14 작성, 5/19 갱신)
- 진행 catch:
  - Step B 완료 (5/19): helper 함수 3개 (`_extract_entities`, `_build_entity_cache_block`, `_bootstrap_entity_cache_from_metadata`) + unit test 24건 통과
  - Step C 완료 (5/19): translate_transcript 통합 + Rule 12 추가 + verify 통과 (150.3초, 8/8, 5/13+5/18 사례 3건 모두 차단)
- 상태 갱신: active → passing
- 비용: 큼 (~2~3 세션)

### B02: slow chunk wall-clock timeout

- 동작: chunk 당 60초 hard limit 으로 grammar-recovery loop 진입 시 즉시 종료
- path 결정 (5/20): (f) ThreadPoolExecutor + future.result(timeout) wrap
- 검증:
  - `tests/test_phase2_slow_chunk_timeout.py` 9/9 통과 (5/20 작성)
  - 실측 verify (phase2_b02_run1): 8/8 통과, slow chunk 자연 발생 부재 (timeout 미발동)
- 상태: **passing** (코드 + unit test 정합, production slow chunk 발생 시 catch 가능 상태)
- 우선순위: P1 (간헐적 처리 시간 폭주 차단)
- 참고: 5/17 A-3 timeout 시도 실패 (httpx read timeout 이 wall-clock 강제 부재)
- 한계: production 에서 slow chunk 자연 발생 시까지 wall-clock timeout 발동 검증 부재
- 비용: 중간 (~1 세션)

### B07: D segment 단독 번역 재평가

- 동작: context leak 의 원인이 된 D segment를 청크에서 분리해 단독 번역하는 방안
- 배경: Phase 5 의미 단위 재분할이 D leak 동기(Whisper 경계 잘림)를 간접 차단함. 현재 D 단독 번역 경로는 별도로 만들지 않음.
- 재검토 조건: 정합이 낮은 영상에서 SHIFT 재발 시. 재분할만으로 해소 여부 영상 수 누적 후 판단.
- 상태: not_started
- 우선순위: P3 (Phase 5 이후 대기)

### B08: 화자 bootstrap 식별 한계 후속

- 동작: 메타데이터 기반 bootstrap 화자 식별이 영상 내 전체 화자를 커버하지 못하는 경우 처리
- 배경: Phase 5 daily 검증 영상1 (Boston Dynamics) — 5명 화자 중 3명만 bootstrap 식별. 나머지는 "화자 N" fallback. 메타데이터에 이름이 부재한 화자가 있는 구조적 한계.
- 재검토 조건: 식별 이름 수 < 전체 화자 수인 영상 빈도 증가 시. B01 entity cache 와 연계 가능성 검토.
- 상태: not_started
- 우선순위: P3

### B09: PipelineWorker 를 gui.py 에서 별도 모듈로 분리

- 동작: 파이프라인 워커 로직 (`PipelineWorker` 클래스) 을 CustomTkinter UI 파일 (`gui.py`) 에서 떼어내 `gurunote/pipeline_worker.py` 신규 모듈로 이동
- 배경: v1.0 React/PyWebView UI (`app_webview.py`) 가 `gurunote/webui/session.py:67` 에서 `from gui import PipelineWorker` 로 옛 CustomTkinter UI 파일에 의존. `gui.py` 를 legacy 로 정리 부재 — React 가 깨짐. 기술 부채.
- 작업 범위: `gui.py` 안 `PipelineWorker` 클래스 추출, import 갱신 (`webui/session.py`, `gui.py` 자체), test 통과 확인
- 상태: **완료** (9/13, v1.0.0.28)
- 결과: `gurunote/pipeline_worker.py` 신설 (클래스 본문 248행 바이트 동일 이전). `webui/session.py` 는
  모듈 레벨 import 로 전환, `gui.py` 는 하위 호환 re-export 유지 + 불필요해진 import 11개 정리
  (4348행 → 4098행). `tests/test_pipeline_worker_extraction.py` 6건이 워커/React 어댑터가 UI 툴킷을
  적재하지 않음을 별도 인터프리터에서 확인. `redesign/tailwind-v2` 통합 시 브랜치가 워커에 추가한
  화자 실명 조회(`load_speaker_names`) 4행도 새 모듈로 함께 옮겼다. 통합 후 전체 266건 통과.
- 남은 것: 옛 진입점 (`gui.py`/`app.py`) 자체의 폐기와 React 진입점 단일화는 별도 결정 사항.
- 우선순위: P3 (1.0 후 정리)
- 비용: 중간 (~1 세션, 코드 이동 + import 갱신 + 회귀 테스트)

### B10: setup.sh / setup.bat 안내 문구 갱신

- 동작: setup 스크립트 종료 시 echo 안내가 옛 진입점 (`gui.py`, `streamlit run app.py`) 만 가리킴. v1.0 React 진입점 (`app_webview.py`, `run_webview.command`) 우선 안내로 갱신
- 위치: `setup.sh:120~121`, `setup.bat:96~97`
- 상태: not_started
- 우선순위: P3 (사용자 경험 정합 — README 와 일관성)
- 비용: 작음 (~0.1 세션, echo 문구 갱신)

### B11: HistoryScreen 다운로드 wiring + 노트 상세 출처 링크

- 동작: 노트 상세 화면 두 가지 불편 해소 — (1) HistoryScreen 다운로드 버튼이 stub (`showToast('Phase 2B-4 다운로드 wiring 예정')`) 이라 동작 부재, (2) 출처 URL 이 텍스트만이라 클릭/복사 불가
- 배경: v1.0 daily 사용에서 발견. EditorScreen 다운로드는 `save_result_as` 로 이미 동작했으나 HistoryScreen (목록 카드 + 상세 패널) 다운로드 버튼 2개는 Phase 2B-4 화면 신축 때 stub 로 남았음 (조사 obs 817).
- 작업 범위:
  - `bridge.py` — `open_external(url)` 신규 (webbrowser.open, http(s) 만 허용). save_result_as 는 재사용 (로직 불변).
  - `HistoryScreen.jsx` — top-level helper 3개 (`historyOpenExternal`, `historyCopyText`, `historyDownloadJob`). 다운로드 stub 2곳 → 실저장 연결 (상세 패널은 로드된 `detail.markdown` 재사용, 목록 카드는 `get_history_detail` 로 본문 로드 후 저장). 출처 행 → 클릭(브라우저) + 복사 버튼.
- 검증: 전체 test 통과 (회귀 부재). 수동 확인은 본인 GUI.
- 상태: **완료** (5/25)
- 우선순위: P2 (v1.0 사용성 — 다운로드 미동작이 미완성으로 보임)

### B12: semantic.py React 재배선 (RAG / 의미 검색)

- 동작: 기존 `gurunote/semantic.py` (413행, sentence-transformers 임베딩 + 코사인 유사도 + 인덱스 빌드, 옛 gui.py/app.py 에서 동작) 을 React UI 에 재연결
- 배경: 백엔드는 완성돼 있으나 React 전환 (Phase 2B) 때 포팅 부재. 현재 비활성 — `bridge.py:995` `rebuild_index` → `NotImplementedError`, DashboardScreen "의미 검색 인덱스" 카드 placeholder, HistoryScreen "연관 노트" 버튼 toast.
- 작업 범위: `bridge.py` `rebuild_index` 구현 + 검색 메서드 노출 → DashboardScreen 카드 + "연관 노트" 연결. 선택 의존성 (`requirements-search.txt`) 미설치 시 `is_available()` False 안내. **신규 알고리즘 부재 — 배선 작업.**
- 상태: **완료** (5/25)
- 우선순위: P2
- 완료 내용:
  - bridge.py 4개 메서드 구현 (`rebuild_index` / `semantic_index_stats` / `semantic_search` / `semantic_available`) — semantic.py 호출만, 로직 불변
  - DashboardScreen "의미 검색 인덱스" 카드 실데이터 연결 + Semantic Rebuild 버튼
  - HistoryScreen "의미 검색" 칩 (쿼리 검색 오버레이) + 노트 상세 "연관 노트" (top-K 유사)
  - 의존성 미설치 시 카드 자체에 설치 안내, README 선택 의존성 안내 추가
- 검증 한계: sentence-transformers 가 개발 환경에 미설치 → 미설치 경로(에러 안내)만 검증. 실제 임베딩/검색 경로는 deps 설치 후 본인 GUI 확인 필요.
- 잔여(별도): History 툴바 "본문 포함" 칩은 substring full-text 검색으로 RAG 와 별개 — 미구현 유지 (이번 범위 밖).

### B13: Obsidian 내보내기 + RAG 유사 노트 wikilink (방향 3)

- 동작: 기존 `gurunote/obsidian.py` (`save_to_vault`, 옛 gui.py 에서 동작) 을 React 에 재연결 + 내보낼 때 RAG 유사 노트를 wikilink 로 삽입해 Obsidian 그래프 연결
- 배경: 카드 hub 아이콘이 B12 때 "상세 열기" 중복으로 잘못 배선됨. 본인 의도 = Obsidian 내보내기 (hub = Obsidian, 설정 화면 Obsidian 섹션 아이콘과 정합). `bridge.send_obsidian(1217)` 은 `NotImplementedError` stub 이었음.
- 설계 확정: 유사 노트 top5 + 유사도 ≥ 0.5 / 본문 "## 연관 노트" 섹션 + frontmatter `related` 둘 다 / 표시 `[[GuruNote_<제목>|제목]] (78%)` (alias 로 그래프 연결 + 제목 표시) / 미내보낸 노트는 미래 링크 허용
- 상태: **완료** (5/25)
- 우선순위: P2
- 완료 내용:
  - `bridge.send_obsidian` 구현 (obsidian.py `save_to_vault` + semantic.py `search` 호출만, 로직 불변). vault 미설정 시 `NO_VAULT` 안내.
  - module helper `_inject_related_notes` / `_obsidian_note_stem` — vault 사본에만 wikilink 삽입, 저장된 result.md 불변 (기존 frontmatter 필드 보존).
  - 카드 hub → Obsidian 내보내기 (중복 "열기" 제거). 노트 상세에 Obsidian 버튼 추가, RAG "연관 노트"는 `device_hub` 아이콘으로 유지.
- 검증: 임시 vault 로 end-to-end 확인 — 파일 생성 + ## 연관 노트 섹션 + frontmatter related + wikilink alias, related_count=5, 자기 제외. NO_VAULT 경로 확인. (사용자 vault 무관)
- 역할 구분: 다운로드(.md 로컬 저장) / Obsidian(vault 내보내기 + wikilink) / 연관 노트(앱 내 RAG 검색).
- 후속 (v1.0.0.5): vault 파일명 `GuruNote_` 접두사 제거 → 파일명 = `<sanitize(title)>.md`. `_obsidian_note_stem` 을 파일명·wikilink 단일 출처로 통합 (그래프 연결 유지). 출처 구분은 `gurunote_job_id` 표식 + `Gurunote/` 폴더가 담당. 기존 접두사 파일은 수동 정리.
- 잔여(별도): bridge `save_pdf` / `send_notion` 은 여전히 stub (이번 범위 밖). 사용자 vault 에 OBSIDIAN_VAULT_PATH 설정 시 실 그래프 검증은 본인 GUI.

### B14: 라이브러리 삭제 시 Obsidian 사본 자동 삭제 (표식 기반)

- 동작: History 에서 노트 삭제 시 내보냈던 Obsidian vault 사본도 함께 삭제. "라이브러리에서 지움 = 그 노트가 잘못됨 → vault 에서도 빠져야" 라는 논리.
- 설계 확정: `send_obsidian` 이 내보낼 때 frontmatter 에 `gurunote_job_id` 표식 삽입 → 삭제 시 vault 스캔해 표식 일치 파일만 삭제. 앞으로 내보내는 것만 동기화 (표식 없는 기존 파일은 사용자 수동 정리). best-effort (라이브러리 삭제는 무조건 진행). 사본 있을 때만 확인 문구.
- 상태: **완료** (5/25)
- 우선순위: P2
- 완료 내용:
  - `bridge.send_obsidian`: `_inject_frontmatter_field(md_out, "gurunote_job_id", job_id)` — vault 사본에만, result.md 불변.
  - `obsidian.py` 신규 `find_vault_copies` / `delete_from_vault` (표식 매칭 스캔/삭제, save_to_vault 로직 불변). `import re` 추가.
  - `bridge.delete_history`: `delete_job` 후 `delete_from_vault` best-effort 호출 (try/except, `vault_deleted` 반환). `has_vault_copy` 메서드 신규 (확인 문구용).
  - `HistoryScreen` DeleteConfirmDialog: 사본 있을 때만 안내, 완료 토스트에 삭제 수.
- 검증: 임시 vault end-to-end — 표식 삽입/매칭 삭제/표식 없는 파일 보존/무관 job_id 안전(0)/중복 방지. `delete_history` 직접 호출은 실제 job 삭제라 미실행(분류기 차단 정상) — vault 측 `delete_from_vault` 독립 검증으로 대체.
- 잔여(별도): 표식 없는 기존 vault 파일은 자동 삭제 대상 아님 (설계 의도). bridge `save_pdf` / `send_notion` 은 여전히 stub.

### B22: 요약 섹션 충실도 강화 — 환각·영어 leak·인명 일관 + dict 후처리 — 완료 (v1.0.0.20)

- 배경: 요약(`SUMMARY_SYSTEM_PROMPT`)이 본문(`translate_transcript`)과 별도 LLM 경로라 v1.0.0.18 충실도 룰(환각·영어 leak 금지) 미적용. 요약 입력은 dict 교정·반복 축약된 본문 한국어인데, 요약 LLM 이 압축하며 자율 변형·날조. 실측(v1.0.0.19 드러켄밀러 노트): 본문에 없는 'Janet Yellen'/'Jerome Powell' 환각, "formidable(강력한)" 영어 leak(본문은 "무서운 존재들"), 본문 "스탠 드러켄밀러"인데 요약 "스턴 드러켄밀러" 재음차.
- 해결: ① SUMMARY_SYSTEM_PROMPT 에 환각 금지·영어 단어 미번역 금지·인명 표기 일관 조항 + 실측 예시(Yellen/Powell·formidable·스턴) 추가 (확률적). ② `summarize_translation` 출력에 `_correct_korean_in_annotations` 적용 — `한국어(English)` 병기 영문 key 로 통용 dict 조회 → 한국어 강제 교정(스턴→스탠, 결정론). 제목(extract_metadata)과 같은 helper 재사용. 본문·제목·`_SHARED_LANG_RULES`·`post_process_cjk_text` 전부 무변(요약 경로만). tests 3건(`test_summary_fidelity.py`), 238 passed.
- 한계: 요약은 LLM 압축이라 환각 0 보장 불가(프롬프트로 줄임). 인명 일관은 결정론이나 영문 병기 있는 인명에만 적용(병기 없으면 매칭 불가). `_SHARED_LANG_RULES` 통합(세 경로 중복 룰 일원화)은 별도 리팩토링 세션으로 미룸.

### B21: 본문 연속 반복 라인 — 더듬거림 회귀 축약 — 완료 (v1.0.0.19)

- 배경: 충실도 강화(v1.0.0.18) 후 노출 — STT 가 더듬거림을 여러 segment 로 끊고 1단계 자유 번역이 1 line 압축 → 2-pass 2단계 strict N개 강제가 같은 문장 반복 채움 (실측 최대 16회). 진단: 2-pass 구조적 한계(1단계 line ≪ N), 후처리는 검출만. C 옵션 채택(B 옵션 — 함수 내 축약은 zip 1:1 제약으로 불가, STOP 후 재조정).
- 해결: `_collapse_repeated_lines` 신규 — 같은 화자+텍스트 3회+ 연속 & 10자+ 이면 첫 라인만. 짧은 발화/다른 화자/marker 보존. translate_transcript 본문 조립 직후(1-pass·2-pass 공통). 2-pass 로직·프롬프트·_post_process_two_pass_outputs·충실도 강화 전부 무변. 임계는 실데이터 분포 근거(긴 17건 vs 짧은 6건, 9자/10자 경계). tests 9건, 235 passed.

### B20: 본문 번역 충실도 — 충실 의역 전환 — 완료 (v1.0.0.18)

- 배경: Rule 5 "자연스럽게 다듬어"가 의역 유발 + 환각/누락/영어 leak 방지 규칙 부재. 실측(드러켄밀러) — 자조농담 정반대 해석 + 환각 "(而非 문화적 정체)" + "which is what I am" 누락 + "관세는acceptable하며" 영어 leak. 진단: 2-pass 1단계 "자유 번역"이 발원지, 2단계는 정렬만이라 오류 보존.
- 해결: TRANSLATION_SYSTEM_PROMPT Rule 5 재구성(충실+자연) + Rule 13(환각)·14(누락)·15(영어 미번역) 신규 + 충실 의역 예시(드러켄밀러·acceptable). 2-pass 1단계 "자유 번역"→"충실 번역" 문구. (기존 Rule 11·12 충돌로 신규는 13/14/15 번호.) 프롬프트만, 로직·후처리·_SHARED_LANG_RULES 무변.
- 검증: 실제 LLM 호출 — 자조농담 보존 + 而非 0 + acceptable→용인. 226 passed. 한계: 관용 이해는 모델 능력이라 완벽 통제 아님.

### B19: 노트에 생성 GuruNote 버전 표시 (추적성) — 완료 (v1.0.0.17)

- 배경: 노트가 어느 빌드로 생성됐는지 안 보여, 발견한 품질 문제가 수정 전/후 어느 버전 산출인지 혼동(실제 v1.0.0.14 빌드로 처리해 제목 수정 미적용 혼동).
- 해결: exporter.py `_build_frontmatter` 에 `gurunote_version: "..."` + `build_gurunote_markdown` 메타 블록에 `- **생성:** GuruNote v...`. `gurunote.__version__` 단일 출처 동적 주입(`from gurunote import __version__`, 순환 없음). 226 passed.

### B18: 제목 품질 — 원본 직역 우선 + 인명 통용 표기 — 완료 (v1.0.0.15)

- 배경: 원본 제목("Bonus: I Say Economy, You Say…with Stan Druckenmiller")이 있는데 내용 요약 제목("스타니슬라프 드루킨밀러: 금리·관세…") 생성 + 인명 오음차(Stan→스타니슬라프). 진단: ①METADATA 프롬프트가 "광고/불명확이면 새로 작성" 재량 → LLM 요약 ②제목은 extract_metadata 독립 LLM 출력이라 본문 entity dict 교정 우회.
- 해결: METADATA organized_title 규칙 강화(원본 있으면 직역, 요약 대체 금지, 접두사·형식 살림). extract_metadata 가 youtube_title 유무로 직역/요약 신호 분기. `_correct_korean_in_annotations` 신규 — 제목 `한국어(English)` 병기의 영문 key 로 통용 dict 조회 → 한국어 강제(user 우선). 영문 병기 없으면 매칭 불가(프롬프트가 병기 요구). dict 미수록 불변. tests 7건, 226 passed.
- 본문 translate_transcript/summarize 변경 없음.
- **B18 후속 (v1.0.0.16) — 제목 구조 직역 강화**: v1.0.0.15 "직역"이 모호해 형식 뭉갠 의역(게임 형식 손실) 지속 → organized_title 규칙에 "구조·형식·문답·말장난 살림, 형식 뭉개기·요약 금지" 명시 + 좋은/나쁜 예 교체(기존 ✓ 예가 의역이라 잘못 유도하던 것 수정). 실측 — "I Say Economy, You Say…" 게임 문답 구조 보존 확인. 프롬프트 레벨이라 완벽 통제 아님(노트 편집 보완).

### B17: 제목·요약 한자/일본어 혼입 (Phase 3 우회 경로) — 완료 (v1.0.0.14)

- 배경: 한자 후처리(`post_process_cjk`)가 본문(translate_transcript:1988)에만 적용, 제목(`extract_metadata`)·요약(`summarize_translation`)은 우회. 실측 4건 leak — 직격谈话(간체) 제목 2건 + 設計/評価 요약 2건. 프롬프트에 한자 금지 룰 있어도 확률적 누출, cjk_lookup.yaml 에 해당 글자 없었음.
- 해결: `post_process_cjk_text` 신규 (Sub-path A 사전 + B LLM 재매핑, **C 영문 fallback 제외** = segment-less). `summarize_translation` 반환 + `extract_metadata` organized_title/field/tags 에 배선. 본문 post_process_cjk 무변(회귀 방지). cjk_lookup.yaml 에 谈话→담화/設計→설계/評価→평가 보강. A·B 후 잔존 한자는 그대로(노트 편집 보정). tests 6건, 219 passed.

### B15: 인명/고유명사 번역 품질 — 통용 표기 + 영문 병기 오타

- 배경: 통용 표기 dict 미수록 인명을 LLM 이 외래어 규칙으로 철자 추정 → 통용과 어긋남 (팰머 러커이/리크 리더). entity_cache 가 첫 표기를 고정해 "일관되게 틀림". 별개로 영문 병기 철자 오염 (Anduril→Danduril, 제목 포함).
- **A (음차) — 완료 (v1.0.0.6 프롬프트 + v1.0.0.10 결정론적 교정)**: v1.0.0.6 번역 Rule 10 우선순위 역전(통용 발음기반 > 목록 > 외래어 fallback). **단 실제 영상은 여전히 "팰머 러커이" 굳음** — 재진단 3겹 원인: bootstrap first-seen 결정 / bootstrap 프롬프트에 A 미반영 / **디스크 캐시 hit 옛 표기 로드**(프롬프트 우회). 캐시 증거 `{"english":"Palmer Luckey","korean":"팰머 러커이","source":"bootstrap"}`, Palmer Luckey 가 speaker A 라 335회는 화자 라벨.
  - **A 보완 (v1.0.0.10)**: 편집 가능 통용 dict `~/.gurunote/canonical_names.json` 신설. `entity_cache` + `speaker_cache` 한국어 표기를 dict 로 결정론적 강제 교정 (대소문자 무시, 미수록 불변). bootstrap(디스크 캐시 hit 포함) 직후 + chunk loop 전 적용 → cache_block·화자 라벨 교정 + 저장 시 디스크 캐시 self-heal. bootstrap 프롬프트에도 발음-우선 지시 추가. tests 7건. 198 passed. 실제 영상 재처리 최종 확인은 본인 GUI.
  - **A-2 ①단계 (v1.0.0.11) — auto/user 구조 + 자동 채움**: dict 구조 `{English:{auto,user}}` 확장 (옛 flat → user 마이그레이션). 작업 중 raw 표기를 auto 로 자동 누적 (user 불변), 교정은 user 우선. atomic 저장. tests 7건, 205 passed.
  - **A-2 ②단계 (편집 UI) — 완료 (v1.0.0.12)**: 설정 "고급"에 "통용 표기" 그룹 — `SettingsCanonicalNames` 컴포넌트 (영문 | auto 읽기전용 | user 입력 | 삭제, 추가 버튼, 전용 저장). bridge `get_canonical_names`/`save_canonical_names` 신규 (llm `_load`/`_save` 호출만, .env 와 별개 state·저장). 빈 항목 제외, 전부 삭제 가능. per-job 로드라 저장 즉시 반영. 205 passed, 라운드트립 검증.
  - **A-2 ③단계 (노트 리프레시) — 완료 (v1.0.0.13)**: `refresh_canonical_in_markdown` (auto·user 둘 다 있는 항목만, 일반+태그 언더스코어 2형태, 단일 패스 정규식으로 연쇄 치환 없음, 영어 원문 자동 무영향). bridge `refresh_job_canonical(job_id)` (get_job_markdown → 치환 → update_job_markdown, 변경 0 시 저장 생략). HistoryScreen 노트 상세 "표기 새로고침" 버튼 + 본문 재로드. tests 8건, 213 passed.
  - **A-2 전체 완료** (①auto/user 구조+자동채움 v1.0.0.11 / ②편집 UI v1.0.0.12 / ③노트 리프레시 v1.0.0.13). 인명 품질 자동화 완결.
- **B (영문 병기 오타) — 완료 (v1.0.0.7)**: `_correct_english_annotations` — `한국어(English)` 병기 영문을 소스(transcript 전문 + 제목)로 결정론적 검증. 정확히 있으면 케이싱 정규화 / 단일 토큰 오타는 보수적 최근접(difflib cutoff 0.84, 대소문자 무시) 교정 / 근거 없으면 병기 생략. 적용: 번역 본문(translate_transcript) + organized_title(extract_metadata, entity_cache 미참조라 별도). LLM 무관 순수 함수, 한국어 음차·화자·timestamp 불변. tests 8건. end-to-end — 팔머 럭키/릭 리더(A) + Anduril 정확/Danduril 0(B) 동시 확인. 실제 영상 최종 확인은 본인 GUI.

### B16: 설정 화면 처리 옵션 + 자동 내보내기 토글

- 배경: 환경변수로만 조절하던 처리 옵션을 앱 UI 에서 켜고 끄기. 작업 완료 시 Obsidian 자동 내보내기.
- **1단계 (처리 옵션 토글) — 완료 (v1.0.0.8)**: 재사용 `SettingsSwitch` 컴포넌트 신규. 설정 "고급"에 2-pass 번역(`GURUNOTE_TWO_PASS`) + STT 재분할(`GURUNOTE_SEGMENT_RESPLIT`) 토글. `_KNOWN_SETTINGS` 두 키 추가 → get_settings/save_settings 연동. 백엔드 env 읽기 로직 무변. 기본값 보존 — 미설정(빈 값)은 ON 표시, 저장 시 "1"/"0" 만 기록 (빈 값 저장 함정 회피). 격리 .env 검증 + 전체 191 passed.
- **2단계 (자동 내보내기) — 완료 (v1.0.0.9)**: 설정-Obsidian 에 "작업 완료 후 자동 내보내기" 토글 (`GURUNOTE_OBSIDIAN_AUTOEXPORT`, 기본 꺼짐 — "1"만 on). 트리거 A 채택 — React `App.onResult`(작업 완료 이벤트)에서 토글 on 시 `api.send_obsidian(job_id)`. 백엔드 파이프라인·send_obsidian 무변(호출만). best-effort(작업 결과 이미 저장 → 내보내기 실패해도 완료 정상). 결과 toast(성공/NO_VAULT/실패). 격리 .env 검증 — 미설정→off, "1"→on. 191 passed. 1단계 자동 삭제 동기화(v1.0.0.4)와 함께 자동 동기화 완성. 실제 작업 자동 내보내기 최종 확인은 본인 GUI.
- **3단계 (중복 스킵 정책, Q23=C) — 완료 (v1.0.0.25, `86ce877`)**: 자동을 켠 채 같은 영상 재처리 시 `save_to_vault` 가 timestamp 접미사로 사본을 쌓던 문제. 자동 호출일 때만 같은 `gurunote_job_id` 표식 노트가 vault 에 있으면 스킵(`bridge.send_obsidian` 에 `skip_if_exists`, `obsidian.find_vault_copies` 재사용·읽기 전용). 수동 버튼은 항상 새로 저장(보존). `save_to_vault`·obsidian.py·semantic.py 무변. ADR-021. 235 passed.
- **참고 (v1.0.0.26)**: 자동 내보내기 "성공 토스트 누락" 보고는 계측 결과 버그 아님으로 규명(4초 표시 안에 놓친 인지 문제) — 토스트 타입별 좌측 보더 시각 구분으로 정리(ADR-022, DEBUGGING §8).

### B03: Phase 1 fix-up #3 — schema text leak

- 동작: xgrammar 0.2.0 description 누설 후처리 필터
- 검증:
  - `tests/test_schema_leak_filter.py` 통과 (작성 필요)
  - 5/18 verify 의 `outputs_count_mismatch_warning_detected_as_false_positive_due_to_json_formatting` 케이스 재현 부재
- 상태: not_started
- 우선순위: P2
- 비용: 작음 (~0.5 세션)

### B04: Phase 1 fix-up #2 — tail attention drop

- 동작: (메모리에 정황 부재 — 5/16~17 에 등록된 항목, 자세한 내용 catch 필요)
- 검증: 미정
- 상태: blocked (정황 확인 필요)
- 비용: 미정

### B05: Phase 4 — capability profile

- 동작: 모델별 (max_ctx, supports_tool_call, korean_quality_score) JSON 추적
- 검증: `jsonschema -i model_capability_profile.json schemas/mcp.schema.json`
- 상태: blocked (모델 교체 결정 후 진입)
- 우선순위: P3 (현재 qwen3.6-35b-q5 고정 사용 중)
- 비용: 큼

### B06: Phase 2B-3 — Canonical Translation (외래어 표기법 + entity_cache 디스크 저장)

- 동작: 외래어 표기법 (문화체육관광부고시 제2017-14호) LLM 참조 + entity_cache 영구 저장으로 인명·지명 표기 표준 강제
- spec: `docs/research/phase2b_canonical_translation_spec.md` (5/20 작성)
- 자료:
  - `gurunote/data/loanword_orthography.md` (외래어 표기법 본문, LLM 참조 정합)
  - `docs/research/외래어표기법.html` (원본 자료 영구 보존)
- 구현 commits:
  - `09bc6d0` (5/20) — spec 자료
  - `88ea485` (5/20) — 본인 결정 5가지 반영
  - `4a8f281` (5/21) — 코드 + tests (21건 신규 + 12건 리팩토링, 84 passed)
- 검증 결과 (5/22 real video verify 3회, NVIDIA GTC 288 segments):
  - Run 1: rc=1, 청크 5 B02 wall-clock timeout (B06 외부 원인, LLM grammar-recovery)
  - Run 2: 8/8 통과 (261s) — bootstrap 4건 → 5건, canonicalize 줄 수 582→582
  - Run 3: 8/8 통과 (291s, cache hit) — canonicalize 줄 수 576→576
  - **'판카지' count: 0건 (Run 2, Run 3 모두)** vs 5/20 baseline 191~192건 → 회귀 100% 차단
  - 판카즈 샤르마 (정 표기): 206~207건 / Run 2, 179~181건 / Run 3
  - cache 파일 `title_<hash>.json` 정합 (Pankaj Sharma → 판카즈 샤르마 source=bootstrap)
- 상태: **passing** (5/22 verify 통과, '판카지' 회귀 차단 확인 + 보완 verify 통과)
- 우선순위: P0 (5/20 발견의 본질 catch + 5/14 spec 의 본질 완성)
- 보완 commits (5/22):
  - `9afcc93` — 한계 2: canonicalize prompt 강화 + `_detect_unexpected_changes` (P-다 — 의심 변경 로그, canonical 채택)
  - `988b4c1` — B02 한계 1: `TIMEOUT_PADDING_MARKER = "[⚠ timeout]"` + retry loop R1 padding fallback
- 보완 verify 결과 (5/22 20:39~20:55, 3회):
  - Run 1: rc=0 / 280s / 8/8 / 판카지 0건 / 판카즈 샤르마 206건 / 줄 수 580→580 / 의심 1건 (젠슨→젠슨 황, 외래어 표기법 적용)
  - Run 2: rc=0 / 311s / 8/8 / 판카지 0건 / 판카즈 샤르마 204건 / 줄 수 592→592 / 의심 1건
  - Run 3: rc=0 / 327s / 8/8 / 판카지 0건 / 판카즈 샤르마 202건 / 줄 수 574→574 / 의심 5건
  - '소프트웤어' (5/22 baseline Run 3 변형): 3 run 모두 **0건** — prompt 강화 효과 catch
  - `[⚠ timeout]` 마커: 3 run 모두 0건 — timeout 자연 발생 부재, R1 효과는 production 대기 (unit test 검증 상태)
- 한계 (잔존):
  - canonicalize LLM 호출 1회 추가 — 처리 시간 +20~36s 보완 verify (5/22 baseline 261~291s → 5/22+ 280~327s)
  - `_detect_unexpected_changes` 한계: 한 줄에 entity 변경 + 일반 단어 변경 함께 있으면 의심 catch 부재 (P-다 정합, daily 빈도 수집 목적)
- 비용: 실제 ~5~6 시간 (5/20 spec, 5/21 구현+tests, 5/22 verify + 보완 commits + 보완 verify)

## 별도 추적

### Schema description leak (xgrammar 0.2.0 한계)

- xgrammar 외부 의존이라 본 저장소에서 본질 해결 부재
- B03 (Phase 1 fix-up #3) 에서 후처리로 부분 catch
- xgrammar 신 버전 대기 또는 omlx 측 변경 요청 별 trajectory

## 정리 기록 (2026-05-20)

- 샘 올트먼 hallucinate stochastic → B01 (Phase 2 entity cache) 통과로 5/17~5/20 verify run 4회 모두 0회. 별도 추적 제거.
- 판카지 회귀 stochastic → B06 (Phase 2B-3) 로 통합. 별도 추적 부재 (B06 spec 의 D 사례).

# Changelog

이 프로젝트의 주요 변경 사항은 이 파일에 기록됩니다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 를 따르며,
버전은 [Semantic Versioning](https://semver.org/lang/ko/) 을 따릅니다.

## [Unreleased]

## [1.0.0.32] - 2026-09-14

`gui.py` 와 `app_webview.py` 는 최근 네 번의 리팩터가 모두 건드렸는데, CI 에 tkinter 와
pywebview 가 없어 AST 로만 확인해 왔다. 정적 검사는 import 한 이름이 실제로 존재하는지
알려주지 못한다.

### Added

- `tests/test_entry_points_import.py` 8건 — UI 툴킷만 스텁으로 갈아끼우고 진입점을 실제로
  import 한다. `gui.py` 가 뜨는지, 선택지 목록이 `gurunote.options` 에서 오는지,
  `gui.PipelineWorker` 가 추출된 클래스와 같은 객체인지, 사이드바 버전 문자열이 패키지
  버전과 맞는지, `webui/session.py` 가 추출된 워커를 쓰는지, JSX 가 부르는
  `api.<method>` 22개가 실제로 노출되는지. pywebview 가 있으면 그 열거 방식
  (`dir()` + `inspect.ismethod`, webview/util.py)으로 서비스 메서드 노출까지 확인하고,
  없으면 해당 2건만 건너뛴다.
- `python-dotenv` 를 `dev` optional-dependency 로 선언. `gui.py` 가 모듈 레벨에서 쓴다.

### Notes

- 기능 변경 없음. 검사만 추가했다.
- 전체 372건 통과 + 2건 skip (pywebview 없는 환경). pywebview 가 있으면 374건.
- 창을 띄우지는 않는다. 위젯 렌더링과 사용자 상호작용은 여전히 사람이 확인해야 한다.

## [1.0.0.31] - 2026-09-14

모듈화 3단계 (backlog B13). `webui/bridge.py` 의 `Api` 는 pywebview 의 `js_api` 로 쓰이는
클래스라, 창을 띄우지 않는 호출자는 그 안의 동작에 접근할 방법이 없었다. 실제로 창이
필요한 것은 36개 중 4개뿐이었다.

### Added

- `gurunote/service.py` — `GuruNoteService`. `Api` 가 담고 있던 창 없는 동작 29개
  (설정, 통용 표기, 기록, 의미 검색, 노트 편집, Obsidian/Notion 내보내기, 하드웨어 탐지,
  연결 시험)를 옮겼다. 상태를 들지 않고 창 없이 인스턴스화된다.
- CLI 명령 3개 — `gurunote history`, `gurunote search`, `gurunote settings`. React UI 가
  쓰는 것과 **같은 함수 객체**를 호출한다 (`Api.list_history is
  GuruNoteService.list_history`). `--json` 으로 기계가 읽는 출력, 실패는 stderr + 종료코드 1.
- `tests/test_service_layer.py` 26건 — 서비스가 창·pywebview 없이 import·동작하는지,
  `Api` 표면이 줄지 않았는지, bridge 가 서비스 메서드를 다시 정의하지 않는지, CLI 렌더링과
  종료 코드.

### Changed

- `Api` 는 `GuruNoteService` 를 상속하고 window 배선(`__init__`, `bind_window`,
  `_require_window`)과 창이 있어야만 되는 4개(`pick_file`, `start_pipeline`,
  `select_obsidian_vault_dir`, `save_result_as`)만 갖는다. 위임 메서드를 나열하지 않으므로
  JS 에 노출되는 표면이 그대로고 드리프트가 생길 자리가 없다.
- 정의 본문은 옮기기만 했다. 원본 정의 줄 1335행이 생성물과 줄 단위로 일치한다.
- `bridge.py` 의 모듈 docstring 을 고쳤다. "Phase 1 MVP status: skeleton — 대부분
  NotImplementedError" 라고 적혀 있었으나 오래전에 구현이 끝난 상태였다.

### Notes

- 동작 변경 없음. JS 가 부르는 메서드 이름과 반환 형태 모두 그대로다.
- 전체 366건 통과 (1.0.0.30 의 340건 + 26건). 실패 0.
- 가드는 고의 위반으로 음성 검증했다 — `Api` 에 서비스 메서드를 다시 정의하면 실패하고,
  서비스가 창을 건드리면 실패한다.

## [1.0.0.30] - 2026-09-14

모듈화 2단계 (backlog B13). `gurunote/llm.py` 한 파일에 3447행, 함수 61개(public 12,
private 49), 모듈 상수 45개가 모여 있어 무엇이 무엇에 딸린 것인지 읽어내기 어려웠다.

### Changed

- `gurunote/llm.py` → `gurunote/llm/` 패키지 8개 모듈. 의존 방향이 한쪽으로만 흐른다:
  `client` → (`prompts`, `chunking`, `context`) → `entities` → `postprocess` →
  `translate` / `summarize`. 순환 없음.
  - `client` (513행) — provider 호출 경계. 재시도, 타임아웃, xgrammar 사전 점검.
    실제 네트워크 호출은 이 모듈만 한다.
  - `prompts` (329행) — system 프롬프트 본문.
  - `chunking` (75행), `context` (98행) — 요청 단위 분할, 영상 메타데이터 블록.
  - `entities` (947행) — entity/speaker 캐시, 통용 표기 dict, 검색 그라운딩.
  - `postprocess` (467행) — 한자 차단, 영문 병기 검증, 연속 반복 축약.
  - `translate` (824행), `summarize` (270행).
- 정의 본문은 옮기기만 했다. 원본 정의 줄 3070행이 생성물에서 그대로 일치하는 것을
  줄 단위로 대조해 확인했다 (의도한 2곳 제외).
- 모듈을 넘는 참조는 전부 모듈 경유로 부른다 (`client._call_llm(...)`). 이름을 직접
  import 하면 호출부에 별도 바인딩이 생겨 정의 모듈을 patch 해도 먹지 않는다. 그러면
  테스트가 실제 엔드포인트를 호출해 멈춘다 — 분할 도중 실제로 8개 파일이 그렇게 멈췄다.
- 테스트의 patch 표적을 정의 모듈로 맞췄다 (`gurunote.llm._call_llm` →
  `gurunote.llm.client._call_llm` 등 86곳, `patch.object`/`setattr` 형태 포함).

### Added

- `gurunote/llm/_data.py` — 패키지 안 데이터 파일 위치를 한 곳에서 해석한다.
- `tests/test_llm_package_surface.py` 41건 — 분할 중 실제로 밟은 함정 세 가지를 고정한다.
  데이터 경로 해석, `@dataclass` 보존, 모듈 경유 patch 계약, 하위 모듈 단독 import,
  의존 순환 부재, re-export 전량, entity 캐시 격리가 하위 모듈까지 먹는지.

### Fixed

- `_CJK_LOOKUP_PATH` / `_LOANWORD_FILE` 이 `Path(__file__).parent / "data"` 였다.
  패키지로 나누면 한 단계 깊어져 `gurunote/llm/data/` 를 찾게 되므로 `_data.DATA_DIR`
  기준으로 바꿨다. 분할하면서 생길 수 있었던 파일 부재를 테스트로 막았다.

### Notes

- 동작 변경 없음. `from gurunote.llm import X` 는 private 이름까지 그대로 동작한다
  (`__init__` 이 107개 전량 re-export).
- 전체 340건 통과 (1.0.0.29 의 299건 + 41건). 실패 0.
- `tests/test_phase2_slow_chunk_timeout.py` 를 단독 실행하면 테스트는 1.3초에 통과하지만
  프로세스가 바로 끝나지 않는다. `ThreadPoolExecutor` 의 긴 blocking 스레드 때문이며
  main 에서도 같다. 이번 변경과 무관하다.

## [1.0.0.29] - 2026-09-14

에이전트·스크립트가 쓸 수 있는 진입점을 만드는 모듈화 1단계. 그동안 파이프라인에
닿는 경로는 GUI 를 띄우는 것뿐이었다.

### Added

- `gurunote/pipeline.py` — 파이프라인 동기 실행 API. `run_pipeline(source, ...)` 가 끝까지
  기다렸다가 `PipelineResult`(ok / job_id / full_md / summary_md / error / logs) 를 돌려준다.
  `PipelineWorker` 의 스레드 + 3 큐 배선을 호출자가 다루지 않아도 된다. 파이프라인 로직은
  옮기지 않았고 큐를 비우고 스레드를 정리하는 층만 새로 넣었다. `resolve_source` 가 URL 인지
  파일인지 한 곳에서 판정한다.
- `gurunote/cli.py`, `gurunote/__main__.py`, pyproject 의 `[project.scripts]` — `gurunote note`
  / `engines` / `providers`. 노트와 `--json` 은 stdout, 진행 로그는 stderr 로 분리해
  `> note.md` 로 받아도 섞이지 않는다. 종료 코드는 성공 0, 파이프라인 실패 1, 입력·옵션
  오류 2, `--timeout` 초과 124.
- `gurunote/options.py` — STT 엔진과 LLM provider 목록의 단일 출처.
- `tests/test_pipeline_api.py` 26 건 — 가짜 워커를 주입해 큐 계약, 입력 판정, 타임아웃,
  결과 없이 죽은 스레드, CLI 출력 스트림과 종료 코드를 검사한다. 실제 STT·LLM 은 부르지 않는다.
- `tests/test_options_single_source.py` 7 건 — 진입점이 목록을 다시 하드코딩하면 실패한다.

### Changed

- `gui.py`, `app.py` 가 선택지 목록을 각자 하드코딩하던 것을 `gurunote.options` 참조로 바꿨다.
  같은 목록이 `gui.py`·`app.py`·`MainScreen.jsx` 3 곳에 복사돼 있었다. React 쪽은 리터럴로
  남겨두고 드리프트만 테스트로 잡는다.
- README 의 주요 기능·실행·프로젝트 구조·FAQ 에 CLI 사용법을 넣고, 구조도에 누락돼 있던
  `tests.yml` 을 추가했다.

### Fixed

- `[Unreleased]` 와 직전 릴리스 사이에 빈 줄이 두 개 들어가 있던 것을 하나로 고쳤다
  (1.0.0.28 을 넣을 때 생긴 것).

### Notes

- 파이프라인 동작 변경 없음. STT / 번역 / 요약 / 내보내기 경로는 손대지 않았다.
- `--provider` 를 주지 않으면 종전처럼 `LLM_PROVIDER` 환경변수를 따른다. 그 fallback 이
  `openai` 라는 것을 `LLMConfig.from_env` 를 실제로 실행해 확인한 뒤 상수로 적었다.
- 전체 299 건 통과 (1.0.0.28 의 266 건 + 33 건).

## [1.0.0.28] - 2026-09-13

`redesign/tailwind-v2` 통합 릴리스. 5/24~5/30 에 브랜치에 쌓인 41 커밋(v1.0.0.1~27)과,
그 사이 main 에 들어간 CI·패키징·구조 작업을 하나의 버전으로 합쳤다.

### Merged

- 브랜치의 v1.0.0.1~v1.0.0.27 항목은 아래에 그대로 보존한다. 통용 표기 dict(auto/user,
  편집 UI, 독립 화면, 새로고침), Obsidian 내보내기 통합(자동 토글, 삭제 동기화, wikilink,
  중복 건너뛰기), 번역·요약·제목 충실도, RAG React 재배선, 뷰어 UX, 영어 원문 화자 실명.

### Added

- 단위 테스트 CI (`.github/workflows/tests.yml`) — Python 3.10 / 3.11 / 3.12 에서
  `pytest -m "not slow"` 실행.
- `openai`, `yt-dlp` 를 `dev` optional-dependency 로 선언.
- `tests/test_pipeline_worker_extraction.py` — 워커와 React 어댑터가 UI 툴킷을 적재하지
  않는지 검사.

### Changed

- `PipelineWorker` 를 `gui.py` 에서 `gurunote/pipeline_worker.py` 로 분리 (backlog B09).
  이 통합에서 브랜치가 워커에 추가한 화자 실명 조회(`load_speaker_names`) 4 행도 새 모듈로
  함께 옮겼다.
- `gurunote/webui/session.py` 의 워커 import 를 모듈 레벨로 올렸다.

### Fixed

- `pip install -e .` 이 "Multiple top-level packages discovered in a flat-layout"
  으로 실패하던 문제. `[tool.setuptools.packages.find] include = ["gurunote*"]` 로
  배포 대상을 한정했다.

### Notes

- **버전 번호 충돌 정리.** main 에 9/13 자로 `1.0.0.1` 과 `1.0.0.2` 를 붙였는데, 같은 번호가
  이미 브랜치에서 다른 내용으로 쓰이고 있었다. 브랜치 쪽 번호 체계가 먼저이므로 그쪽을
  정본으로 남기고, main 에 있던 두 항목의 내용은 이 `1.0.0.28` 안으로 옮겼다. 태그를
  붙이지 않은 상태였으므로 공개된 릴리스가 바뀐 것은 없다.
- `CLAUDE.md` 는 저장소에서 계속 추적한다. 브랜치가 `.gitignore` 에 넣어 추적 해제했으나,
  버전 정책과 CHANGELOG 규칙의 출처라 통합하면서 되돌렸다.

## [1.0.0.27] - 2026-05-30

### Added
- **영어 원문 스크립트 화자 표기를 라벨에서 실제 이름으로** — 한국어 번역본은 번역 중
  화자 실명이 본문에 들어가는데 영어 원문 섹션은 `Speaker A/B` 라벨뿐이라 비대칭이었다.
  같은 화자 매핑(`speaker_cache`)을 영어 원문 섹션에도 적용해 라벨을 English 실명으로
  표기. 매핑 없는 라벨(화자분리 미식별·캐시 miss)은 기존 `Speaker X` 로 fallback. 디스크
  entity cache 의 `speakers` 필드를 재사용(`load_speaker_names`), 저장 게이트를 entity 0건
  영상도 화자 매핑이 남도록 보완(`entity_cache or speaker_cache`). 한국어 번역본·STT·화자
  식별 로직 무변, 표시 + 전달 경로만.

## [1.0.0.26] - 2026-05-29

### Added
- **토스트 알림 타입별 좌측 보더 색 구분** — 성공(초록)·정보(파랑)·경고(주황)·실패(빨강)를
  좌측 3px 보더 색으로 구분(기존 `--gn-*` 토큰 재사용, info 는 primary 차용). 배경은 불투명
  흰색을 그대로 유지해 Phase 2B-6d 의 가독성 결정(반투명 tint 제거)을 존중 — tint 배경은
  재도입하지 않음. 기존엔 타입별 시각 차이가 없어 성공·건너뜀·실패를 텍스트로만 구분해야
  했음. `main.css` 한 파일, 백엔드 무변.

## [1.0.0.25] - 2026-05-29

### Changed
- **자동 Obsidian 내보내기 중복 건너뛰기** — 자동 내보내기 토글
  (`GURUNOTE_OBSIDIAN_AUTOEXPORT="1"`) 이 켜진 상태에서 같은 영상을 다시 처리하면 vault 에
  같은 노트 사본이 타임스탬프 접미사로 계속 쌓이던 문제. 자동 호출에 한해 같은
  `gurunote_job_id` 표식 노트가 vault 에 이미 있으면(`obsidian.find_vault_copies` 재사용,
  읽기 전용) 내보내기를 건너뛰고 "이미 내보낸 노트 — 건너뜀" 토스트로 안내. 수동 "Obsidian"
  버튼은 종전대로 항상 새로 저장(건너뛰지 않음). `bridge.send_obsidian` 에 `skip_if_exists`
  인자 추가(기본 꺼짐, 자동 호출만 켬), `App.jsx` 자동 호출만 플래그 전달.
  `save_to_vault`·`obsidian.py`·`semantic.py` 는 호출만 — 변경 없음.

## [1.0.0.24] - 2026-05-29

### Changed
- **통용 표기 "추가" 행을 목록 맨 위로** — 통용 표기 화면에서 "추가"를 누르면 새 빈 행이 목록
  끝에 붙어 한참 스크롤해야 보이던 문제. 새 빈 행을 맨 앞에 넣어 추가 직후 스크롤 없이 바로
  입력하게 함(검색어도 함께 해제 — 빈 행이 필터에 안 걸려 안 보이는 문제 방지). 렌더는 rows
  배열 순서 그대로라 맨 앞 추가가 즉시 반영되고, 알파벳 정렬은 저장 시 다시 적용됨. 검색 중
  수정·삭제의 원본 인덱스 보존은 그대로 유지. `SettingsScreen.jsx` 한 파일, 백엔드 무변.

## [1.0.0.23] - 2026-05-29

### Changed
- **통용 표기 독립 화면 이동 + 검색** — 통용 표기 편집(`SettingsCanonicalNames`)을 설정 "고급"
  인라인에서 떼어 좌측 설정 네비의 독립 항목("통용 표기", Notion 다음·고급 앞)으로 이동.
  auto 자동 채움으로 항목이 늘어 고급 화면을 뒤덮던 문제 해소. 우측 전체 화면 + 섹션 헤더.
  - **검색 추가** — 영문·auto·user 셋 다 대소문자 무시 부분 일치 필터. 검색 시에도 원본 인덱스를
    보존해 수정·삭제가 맞는 행에만 적용(필터된 목록 인덱스로 다른 행을 망가뜨리지 않음).
    빈 행 추가 시 검색어 자동 해제.
  - 고급에는 처리 옵션·다른 LLM provider 키·WhisperX 등 본래 항목만 남김.
  - `SettingsScreen.jsx` 한 파일. bridge(`get/save_canonical_names`)·백엔드 무변.

## [1.0.0.22] - 2026-05-29

### Fixed
- **뷰어 "생성일" KST 표시** — 노트 상세 패널·삭제 확인 대화상자의 "생성일"이 저장 원본인
  ISO UTC 문자열(`2026-05-28T15:11:40.942242+00:00`)로 그대로 노출되던 문제. 표시 단계에서
  `Asia/Seoul` 고정으로 변환해 `2026-05-29 00:11` (`YYYY-MM-DD HH:mm`, 업로드일과 같은 결)로
  표시. 저장 필드(`created_at`, ISO)는 불변 — 정렬(`localeCompare`/`Date.parse`)이 ISO 에
  의존하므로 표시만 변환. 파싱 실패·빈 값이면 원본 그대로 반환. `HistoryScreen.jsx` 한 파일.

## [1.0.0.21] - 2026-05-28

### Added
- **뷰어 타임스탬프 표시 토글** — 노트 뷰어(`ResultPanel`)의 한국어·영어 원문 탭에 "타임스탬프"
  인라인 토글 추가. 끄면 전체 스크립트 라인의 `[MM:SS]` 가 화면에서만 사라지고 화자명은 유지.
  보기 전용 클라이언트 상태(기본 켜짐, 영속화 부재) — 원본 `result.md`·job 데이터 불변,
  백엔드/exporter/환경변수 미경유. 요약 탭(타임라인 타임스탬프)은 무변. 라이브·히스토리 상세·
  편집기 미리보기 세 곳 공통 적용. ※ 9a12566(exporter 판) revert 후 뷰어 표시 방식으로 재구현.

### Fixed
- **뷰어 본문 드래그 선택·복사 불가** — 노트 뷰어의 한국어·영어 원문 탭(`.result-transcript`)과
  요약 탭(`.result-rendered`) 본문을 마우스로 드래그 선택해 복사할 수 없던 문제. 이 webview
  환경은 콘텐츠가 기본적으로 선택되지 않아 `user-select: text` 명시가 필요한데, Log 탭
  (`.log-pane`)에만 있고 본문·요약 셀렉터엔 빠져 있었음. 두 셀렉터에 `.log-pane` 과 동일하게
  `user-select: text; -webkit-user-select: text; cursor: text;` 추가 (`main.css` 한 파일).

## [1.0.0.20] - 2026-05-28

### Added
- **요약 섹션 충실도 강화** — 요약(`SUMMARY_SYSTEM_PROMPT`)이 본문(`translate_transcript`)과
  별도 LLM 경로라 v1.0.0.18 충실도 강화(환각·영어 leak 금지 룰)가 미적용이던 문제. 요약 LLM 이
  본문(이미 dict 교정된 한국어)을 압축하며 자율 변형·날조하던 실측 사례를 차단.
  - **프롬프트 조항 추가** (확률적):
    - 환각 금지 — 입력 번역본에 실제로 있는 내용·인물만. 입력에 없는 인물(실측: 본문에 없는
      'Janet Yellen', 'Jerome Powell')을 요약에 등장시키지 않음.
    - 영어 단어 미번역 금지 — 일반 영단어 한국어화 (실측: 'formidable(강력한) 존재감' →
      '강력한 존재감'). 병기/약어/모델·제품명/회사명은 예외.
    - 인명 표기 일관 — 입력 번역본 표기를 그대로 (실측: 본문 '스탠 드러켄밀러' 인데 요약이
      '스턴 드러켄밀러' 로 재음차). 첫 등장 영문 병기는 유지.
  - **dict 인명 후처리** (결정론): `summarize_translation` 출력에 `_correct_korean_in_annotations`
    적용 — `한국어(English)` 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정(스턴→스탠).
    제목(`extract_metadata`)과 같은 helper 재사용. 영문 병기 있는 인명에만 적용.
  - 본문 `translate_transcript`/`TRANSLATION_SYSTEM_PROMPT`·제목 `extract_metadata`·
    `_SHARED_LANG_RULES`·`post_process_cjk_text` 전부 무변 (요약 경로만 변경).
  - `tests/test_summary_fidelity.py` 3건.

## [1.0.0.19] - 2026-05-28

### Fixed
- **본문 연속 반복 라인 축약** — 충실도 강화(v1.0.0.18) 후 노출된 회귀 차단. 더듬거림
  구간(예: "I'm not I'm not…")을 STT 가 여러 짧은 segment 로 끊고, 1단계 자유 번역이 한
  문장으로 압축하면, 2-pass 2단계가 segment 수(strict schema)에 맞춰 **같은 문장을 반복으로
  채우던** 문제 (실측 — 같은 화자가 동일 긴 문장 최대 16회 연속).
  - `_collapse_repeated_lines` 신규 — 같은 화자 + 같은 텍스트가 **3회 이상 연속**이고
    텍스트가 **10자 이상**이면 첫 라인만 남기고 제거 (timestamp 는 첫 라인 것).
  - **보존**: 짧은 발화(네./맞습니다. < 10자, 횟수 무관)·다른 화자 동일 발화·marker
    ([번역 누락]/[⚠ timeout]/음성 인식 오류). 임계는 실데이터(노트 반복 분포) 근거.
  - 적용: `translate_transcript` 본문 조립 직후 (1-pass·2-pass 공통). 2-pass 로직·정렬/
    freeform 프롬프트·`_post_process_two_pass_outputs`·충실도 강화 프롬프트 전부 무변.
  - `tests/test_collapse_repeated_lines.py` 9건.

## [1.0.0.18] - 2026-05-28

### Changed
- **본문 번역 — 충실 의역 전환** (환각·누락·영어 leak 차단). 기존 Rule 5 "자연스럽게
  다듬어" 가 의역을 유발하고 환각/누락 방지 규칙이 없어, 실측에서 자조 농담의 정반대
  해석 + 원문에 없는 한자 대조구 "(而非 문화적 정체)" 환각 + "which is what I am" 절 누락 +
  "관세는acceptable하며" 영어 leak 발생:
  - `TRANSLATION_SYSTEM_PROMPT` Rule 5 재구성 — "원문의 모든 절·정보를 빠짐없이 옮기고,
    추임새·군더더기만 정리, 자연스럽게 재구성하되 추가·축약 금지".
  - Rule 13(환각 금지)·14(누락 금지 — 자조·삽입절)·15(일반 영어 단어 미번역 금지, 병기/
    약어/모델명 예외) 신규. 충실 의역 좋은 예/나쁜 예(드러켄밀러·acceptable 실측) 추가.
  - 2-pass 1단계 자유 번역 문구를 "충실 번역(환각·누락·영어 leak 금지)" 으로 교체.
  - 프롬프트 문구만 — 본문/2-pass 로직·후처리·요약/제목 프롬프트 무변. 실측 확인 —
    자조 농담 보존 + 而非 0 + acceptable→"용인할 수 있다".
  - 한계: 관용표현 이해는 모델 능력이라 새 패턴은 또 빠질 수 있음 (큰 방향 개선, 완벽 통제 아님).

## [1.0.0.17] - 2026-05-28

### Added
- **노트에 생성 GuruNote 버전 표시 (추적성)** — 어느 빌드로 만든 노트인지 식별해, 발견한
  품질 문제가 어느 버전 산출인지 추적:
  - frontmatter `gurunote_version: "1.0.0.x"` (Obsidian 메타/검색·필터용).
  - 본문 메타 블록에 `- **생성:** GuruNote v1.0.0.x` 한 줄 (재생 시간 아래).
  - 버전은 `gurunote.__version__` 단일 출처에서 **동적 주입** (하드코딩 아님 — 버전 업 시 자동 반영).
  - `exporter.py` `_build_frontmatter` + `build_gurunote_markdown` 메타 블록만 추가. 다른 로직 무변.

## [1.0.0.16] - 2026-05-27

### Changed
- **제목 — 구조 직역 강화**. v1.0.0.15 의 "직역 우선" 이 모호해 LLM 이 형식을 뭉갠 의역
  (예: "I Say Economy, You Say…" → "경제 단어 연상")을 내던 것을 교정:
  - `METADATA_SYSTEM_PROMPT` organized_title 규칙에 **원문의 구조·형식·문답·말장난을 살려
    직역** (형식 뭉개기·내용 요약 금지) 명시 + 좋은/나쁜 예 보강. (기존 "✓ 좋은 예" 가
    오히려 형식 뭉갠 의역이라 LLM 을 잘못 유도하던 것을 구조 보존형으로 교체.)
  - 실측 확인: "Bonus: I Say Economy, You Say…with Stan Druckenmiller" →
    "보너스: 내가 '경제'라고 하면 당신은? — 스탠 드러켄밀러(Stan Druckenmiller)" (게임 문답 구조 보존).
  - 인명 dict 교정·영문 병기·한자 후처리·youtube_title 유무 분기는 변경 없음. 프롬프트
    레벨이라 완벽 통제는 아님 (가끔 노트 편집 보완).

## [1.0.0.15] - 2026-05-27

### Changed
- **제목 — 원본 영상 제목이 있으면 직역 우선** (내용 요약 제목 생성 금지). 그동안 프롬프트가
  "광고/불명확이면 새로 작성" 재량을 줘 원본이 있어도 내용 요약 제목(예: "스타니슬라프
  드루킨밀러: 금리·관세…")이 나오던 것을 교정:
  - `METADATA_SYSTEM_PROMPT` organized_title 규칙 강화 — 원본 제목 있으면 접두사("Bonus:")·
    게임/코너 형식까지 살려 직역, **요약 제목 대체 금지**. 원본 부재 시에만 인물·주제 요약.
  - `extract_metadata` 가 `youtube_title` 유무로 user 프롬프트에 직역/요약 신호를 명시 분기.

### Fixed
- **제목 인명 통용 표기 불일치** (예: Stan → "스타니슬라프 드루킨밀러"). 제목은
  `extract_metadata` 의 독립 LLM 출력이라 본문 entity dict 교정을 안 거쳐 인명이 매 작업
  달랐음. `_correct_korean_in_annotations` 신규 — `한국어(English)` 병기의 **영문 key 로
  통용 dict 조회 → 한국어를 통용 표기로 강제** (user 우선). LLM 오음차여도 영문 원어로 복원,
  dict 미수록·병기 없는 인명은 불변. `tests/test_title_korean_correction.py` 7건.

## [1.0.0.14] - 2026-05-27

### Fixed
- **제목·요약 한자/일본어 혼입 차단 (Phase 3 보완)**. 한자 후처리가 본문(전체
  스크립트)에만 적용되고 제목(`extract_metadata`)·요약(`summarize_translation`,
  인사이트/타임라인)은 우회해, 실측에서 `직격谈话`(간체)·`設計`·`評価`(요약) 4건 leak.
  - `post_process_cjk_text` 신규 — 본문 후처리의 Sub-path A(사전)+B(LLM 재매핑) 골격
    재사용, **Sub-path C(영문 fallback, segment 의존)는 제외**한 segment-less 변형.
    A·B 후에도 남는 한자는 그대로 둠 (드묾 — 노트 편집으로 보정).
  - `summarize_translation` 반환 + `extract_metadata` 의 organized_title/field/tags 에 배선.
    본문 `post_process_cjk`(translate_transcript)는 변경 없음 (회귀 방지).
  - `cjk_lookup.yaml` 보강: 谈话→담화, 設計→설계, 評価→평가 등 (Sub-path A 결정론 적중).
  - `tests/test_cjk_text_postprocess.py` 6건. 한자 없는 정상 텍스트는 무동작(과처리 부재).

## [1.0.0.13] - 2026-05-27

### Added
- **노트 통용 표기 새로고침 (A-2 ③단계)** — 노트 상세의 "표기 새로고침" 버튼으로
  이미 만든 노트의 옛 인명 표기(auto)를 수정 표기(user)로 **텍스트 치환**. 번역 LLM
  재실행 없이 완성된 `result.md` 의 문자열만 교체:
  - `refresh_canonical_in_markdown` — auto·user 둘 다 있는 항목만 대상. 일반형 +
    태그 언더스코어형(`팰머_러커이`) 둘 다. **단일 패스 정규식**(긴 패턴 우선)이라 연쇄
    치환 없음. auto 가 한국어라 **영어 원문 섹션·영문 병기는 자동 무영향**.
  - bridge `refresh_job_canonical(job_id)` — `get_job_markdown` → 치환 →
    `update_job_markdown`. 변경 0 이면 저장 생략. 갱신 markdown 반환(UI 재렌더).
  - HistoryScreen 노트 상세에 버튼 + 갱신 후 본문 자동 재로드. `tests/test_canonical_refresh.py` 8건.
  - 이로써 인명 품질 자동화(A-2: auto/user 구조 → 자동 채움 → 편집 UI → 노트 리프레시) 완결.

## [1.0.0.12] - 2026-05-27

### Added
- **통용 표기 편집 UI (A-2 ②단계)** — 설정 → 고급에 "통용 표기" 그룹. GuruNote 가
  자동으로 채운 표기(auto, 읽기 전용 회색)를 확인하고 틀린 것만 수정 표기(user)에
  입력. 행 추가/삭제 + 전용 저장 버튼. user 가 있으면 user 우선 적용 (다음 작업부터,
  재시작 불필요 — dict 는 작업마다 로드).
  - bridge `get_canonical_names` / `save_canonical_names` 신규 — `llm.py` 의
    `_load`/`_save_canonical_names` 호출만 (파일 I/O 단일 출처). `.env`
    `get_settings`/`save_settings` 와 완전 별개 (별도 메서드·별도 state·별도 저장 버튼).
  - 빈 영문/빈 항목은 저장 시 제외. 초기값 포함 전부 삭제 가능 (dict 비어도 정상).
  - 노트 리프레시(③)는 다음 단계.

## [1.0.0.11] - 2026-05-26

### Added
- **통용 표기 dict auto/user 구조 + 자동 채움 (A-2 ①단계, 백엔드 토대)**. 인명 통용
  표기를 GuruNote 가 채우고 사용자는 틀린 것만 고치는 방식의 토대:
  - dict 구조 `{English: {"auto": GuruNote 자동 표기, "user": 사용자 수정}}` 로 확장.
    옛 flat `{English: "한국어"}` 는 값을 **user 로 자동 마이그레이션** (사용자 초기값으로 간주).
  - **자동 채움**: 작업 중 본 고유명사의 **교정 전 raw 표기**를 `auto` 로 누적 저장
    (`~/.gurunote/canonical_names.json`). `user` 는 절대 덮지 않음.
  - **교정은 user 우선** (`user` 있으면 user, 없으면 auto) — entity/speaker 캐시 모두.
  - atomic 저장(`tmp → os.replace`). 기존 교정 동작·하위 호환(flat dict 전달) 보존.
  - 편집 UI(②)·노트 리프레시(③)는 다음 단계. `tests/test_canonical_auto_user.py` 7건.

## [1.0.0.10] - 2026-05-26

### Fixed
- **인명 통용 표기 — 실제 영상에서 굳던 오표기 결정론적 교정 (A 보완)**. v1.0.0.6
  프롬프트 강화 후에도 실제 영상은 "팰머 러커이"(Palmer Luckey) 가 굳던 문제. 재진단으로
  3겹 원인 확정 — bootstrap 이 first-seen 표기 결정 / bootstrap 프롬프트에 발음-우선
  지시 미반영 / **디스크 캐시 hit 시 옛 표기 로드(프롬프트 우회)**.
  - 편집 가능한 통용 표기 dict `~/.gurunote/canonical_names.json` (English→한국어,
    초기값 Palmer Luckey→팔머 럭키 / Rick Rieder→릭 리더) 신설. 2단계에서 설정 UI 편집 예정.
  - `entity_cache` + `speaker_cache`(화자 라벨 — 본문 prefix 지배) 의 한국어 표기를 dict 로
    **강제 교정** (대소문자 무시). dict 미수록 인명은 불변 (과교정 부재).
  - 적용: bootstrap(디스크 캐시 hit 포함) 직후 + chunk 신규 entity — chunk loop 전 적용으로
    프롬프트 context·화자 라벨이 교정된 표기 사용, 저장 시 디스크 캐시도 self-heal(재처리 시
    옛 표기 교정).
  - bootstrap LLM 프롬프트에도 발음-우선 지시·예시 추가 (dict 미수록 신규 인명용).
  - `tests/test_canonical_name_correction.py` 7건. (B 영문 철자·화자·timestamp 회귀 부재.)

## [1.0.0.9] - 2026-05-26

### Added
- **Obsidian 작업 완료 후 자동 내보내기** (설정 → Obsidian 토글, 기본 꺼짐) — 켜면
  노트 생성이 끝날 때마다 자동으로 vault 에 내보낸다 (RAG 인덱스 있으면 연관 노트
  wikilink 포함). 1단계 자동 삭제 동기화(v1.0.0.4)와 함께 자동 동기화 완성.
  - `GURUNOTE_OBSIDIAN_AUTOEXPORT` 키 (`_KNOWN_SETTINGS`), **"1" 일 때만 on** (기본
    꺼짐 — 미설정/"0" 은 off). 1단계 `SettingsSwitch` 재사용.
  - 트리거 = React `App.onResult` (작업 완료 이벤트) 에서 토글 on 시
    `api.send_obsidian(job_id)` 호출. **백엔드 파이프라인·`send_obsidian` 무변** (호출만).
  - best-effort: 자동 내보내기 실패(또는 Vault 미설정)해도 작업 결과는 이미 저장돼
    완료 흐름은 정상. 결과는 토스트로 알림.

## [1.0.0.8] - 2026-05-26

### Added
- **설정 "고급"에 처리 옵션 토글** — 그동안 환경변수로만 조절하던 처리 옵션 2개를
  앱에서 켜고 끌 수 있다:
  - **2-pass 번역** (`GURUNOTE_TWO_PASS`) — 자유 번역 후 정렬하는 2단계 (정확도↑ 시간↑).
  - **STT 의미 단위 재분할** (`GURUNOTE_SEGMENT_RESPLIT`) — 가독성·화자 정합↑.
  - 재사용 `SettingsSwitch` 컴포넌트 신규. 두 키를 `_KNOWN_SETTINGS` 에 추가 →
    `get_settings`/`save_settings`(.env + os.environ) 로 저장/로드. 백엔드 읽기 로직
    (`llm.py` / `stt_mlx.py`) 은 그대로 — 키 추가 + UI 만.
  - **기본값 보존**: 둘 다 기본 켜짐. 미설정(빈 값)은 ON 으로 표시하고 저장 시 항상
    `"1"`/`"0"` 만 기록해, 기존 동작이 바뀌지 않는다.

## [1.0.0.7] - 2026-05-26

### Fixed
- **영문 병기 철자 오염 차단 (Anduril → Danduril 류)**. LLM 이 `한국어(English)`
  병기의 영문 원어를 자유 생성하다 철자를 틀리던 문제 (제목 포함) 를 소스에 실재하는
  철자로 결정론적 검증:
  - `_correct_english_annotations` — 소스(transcript 전문 + 제목)에 정확히 있으면 케이싱
    정규화, 단일 토큰 오타는 보수적 최근접(difflib, cutoff 0.84, 대소문자 무시)으로 교정,
    근거 없으면 **병기 생략** (틀린 철자를 박지 않음). LLM 무관 순수 함수.
  - 적용: 번역 본문 (`translate_transcript` 최종), organized_title (`extract_metadata`
    — entity_cache 미참조라 별도 검증).
  - 한국어 음차·화자 라벨·timestamp 는 건드리지 않음. `tests/test_english_annotation_source_check.py` 8건 추가.

## [1.0.0.6] - 2026-05-25

### Changed
- **인명 음차 — 통용 표기 우선 (번역 프롬프트 강화)**. 통용 표기 dict 에 없는 유명
  인물·기업을 LLM 이 외래어 표기법 규칙으로 **철자 기반** 추정해 통용과 어긋나던 문제
  (예: Palmer Luckey→"팰머 러커이", Rick Rieder→"리크 리더") 개선:
  - Rule 10 머리에 표기 결정 우선순위 명시 — ① 통용 표기(철자 아닌 **발음** 기준 음차)
    ② 통용 표기 목록 ③ 외래어 표기법 규칙은 모르는 이름의 fallback (통용을 덮어쓰지 않음).
  - 공통 룰의 통용 표기 dict 에도 발음 우선 안내 미러링.
  - 짧은 테스트 확인: Palmer Luckey→**팔머 럭키**, Rick Rieder→**릭 리더** (오표기 0).
  - dict 수정·외래어 규칙·entity_cache 로직 변경 없음 (프롬프트 지시만).

## [1.0.0.5] - 2026-05-25

### Changed
- **Obsidian 내보내기 파일명에서 `GuruNote_` 접두사 제거** — 파일명이 작업물 제목
  (`<sanitize(title)>.md`) 으로만 구성돼 Vault 그래프에서 제목 가독성이 좋아진다.
  출처 구분은 frontmatter `gurunote_job_id` 표식 + `Gurunote/` 하위 폴더가 담당하므로
  접두사가 불필요. 파일명과 `## 연관 노트` wikilink stem 이 같은 helper
  (`_obsidian_note_stem`) 를 거쳐 항상 일치 — 그래프 연결 유지.
  - 삭제 동기화는 frontmatter 표식 기반이라 영향 없음.
  - **이미 내보낸 `GuruNote_` 접두사 파일은 그대로** (앞으로 내보내는 노트부터 적용) —
    필요 시 사용자가 수동 정리.

## [1.0.0.4] - 2026-05-25

### Added
- **라이브러리 삭제 ↔ Obsidian vault 동기화** — History 에서 노트를 삭제하면
  내보냈던 Obsidian 사본도 함께 삭제된다. `send_obsidian` 이 내보낼 때 frontmatter 에
  남기는 `gurunote_job_id` 표식으로 정확히 그 파일만 매칭 (`obsidian.delete_from_vault`).
  - 표식이 없는 (이번 버전 이전에 내보낸) vault 파일은 매칭되지 않아 **삭제되지 않는다**
    — 사용자가 수동 정리. 앞으로 내보내는 노트부터 동기화.
  - best-effort: vault 삭제가 실패해도 라이브러리 삭제는 진행되고 결과만 알린다.
  - 삭제 확인 다이얼로그는 vault 에 표식 사본이 실제 있을 때만 "Obsidian 사본도 함께
    삭제됩니다" 안내 (`has_vault_copy`). 완료 토스트에 삭제한 사본 수 표시.

## [1.0.0.3] - 2026-05-25

### Added
- **Obsidian 내보내기 활성화** — History 카드 hub 아이콘과 노트 상세 "Obsidian"
  버튼이 저장된 노트를 Obsidian Vault 로 내보낸다 (`bridge.send_obsidian`,
  기존 `gurunote/obsidian.py` `save_to_vault` 재사용). Vault 경로는 설정 → Obsidian
  에서 지정 (`OBSIDIAN_VAULT_PATH`), 미설정 시 안내.
- **RAG 유사 노트 wikilink** — 내보낼 때 의미 검색으로 유사 노트 top 5 (유사도 ≥ 0.5)
  를 본문 끝 `## 연관 노트` 섹션 (`- [[GuruNote_<제목>|제목]] (78%)`) + frontmatter
  `related` 로 삽입. Obsidian 그래프에서 노트끼리 연결된다 (상대 노트도 내보내면
  링크 연결; 미내보낸 노트는 미래 링크로 허용). RAG 미설치/인덱스 없으면 연관 노트
  없이 내보낸다. 저장된 `result.md` 는 손대지 않고 Vault 사본에만 삽입.

### Changed
- History 카드 hub 아이콘이 "상세 열기" 중복 동작이던 것을 "Obsidian 으로 내보내기"
  로 교체 (hub = Obsidian, 설정 화면 Obsidian 섹션 아이콘과 정합). 노트 상세의
  RAG "연관 노트" (앱 내 검색) 는 별도 아이콘 (`device_hub`) 으로 유지.

## [1.0.0.2] - 2026-05-25

### Added
- **의미 검색 (RAG) React UI 재배선** (백로그 B12) — 기존 `gurunote/semantic.py`
  (sentence-transformers 임베딩 + 코사인 유사도) 를 React UI 에 연결:
  - 대시보드 "의미 검색 인덱스" 카드 — 모델 / chunk 수 / 작업 수 / 빌드 시각 실데이터
    표시 + "Semantic Rebuild" 버튼으로 인덱스 빌드.
  - History "의미 검색" 칩 — 검색어로 의미 유사 노트를 찾아 결과 오버레이 표시.
  - 노트 상세 "연관 노트" 버튼 — 현재 노트와 의미가 유사한 노트 top-K 표시.
  - 선택 의존성 (`requirements-search.txt`) 미설치 시 대시보드 카드에 설치 안내.
  - bridge: `rebuild_index` / `semantic_index_stats` / `semantic_search` /
    `semantic_available` 구현 (semantic.py 호출만, 로직 변경 없음).

## [1.0.0.1] - 2026-05-25

### Added
- 노트 상세 화면 "출처" URL 을 클릭 가능한 링크로 변경 — 클릭 시 시스템 브라우저로 열림
  (`bridge.open_external`, http/https 만 허용). 옆에 URL 복사 버튼 추가.

### Fixed
- HistoryScreen (라이브러리) 다운로드 버튼이 동작하지 않던 문제 — 목록 카드·상세 패널
  양쪽 모두 실제 마크다운 저장(`save_result_as`, 네이티브 저장 다이얼로그)에 연결.
  기존에는 "Phase 2B-4 다운로드 wiring 예정" 안내만 표시됨 (백로그 B11).

## [1.0.0.0] - 2026-05-24

> **1.0 선언 릴리스.** `redesign/tailwind-v2` 브랜치에서 누적된 4월 24일 이후의
> 모든 변경을 묶어 1.0 으로 승격. CLAUDE.md "1.0 전 MINOR 대체" 정책의
> 의식적 예외 — 라이선스 전환 + UI 전면 교체 + 백엔드 파이프라인 재구조가
> 동시에 하위 호환성을 깨므로 1.0 선언이 정직한 표기라고 판단.

### Changed
- **UI 전면 교체 (BREAKING)**: CustomTkinter (`gui.py`) / Streamlit (`app.py`)
  양립 구조에서 **React + Material 3 + PyWebView** 신축 (`gurunote/webui/`)
  으로 권장 진입점 이동. 새 진입점: `app_webview.py` (모든 OS), macOS 는
  `run_webview.command` 더블 클릭 가능. 사이드바 + 5 화면 (Main / History /
  Editor / Dashboard / Settings) + ⌘K SearchPalette. 옛 두 진입점은 호환
  유지 — `gui.py` 는 React UI 가 `PipelineWorker` 클래스로 의존하기 때문
  (분리 작업은 백로그 B09).
- **License (BREAKING)**: MIT → **Elastic License 2.0** (4/24). SaaS 호스팅 /
  라이선스 키 우회 부재 조항. 4/24 이전 main 브랜치 커밋은 MIT 유지.
- **STT 파이프라인**:
  - pyannote `3.1` → `community-1` (speaker confusion 마킹 감소, pyannote.audio 4.0+ 정합).
  - STT 직후 word-level **의미 단위 재분할** 도입 (`gurunote/stt_mlx.py`).
    Whisper segment 경계는 음성 신호 기반이라 의미 단위 부재 — 끝 검사 +
    화자 우선 합침으로 D context leak, 2-pass 정렬 drift, 가독성, 1-pass
    hallucinate 4 단계 공통 동기 차단. 모델 비의존 방식.
  - 환경변수 `PYANNOTE_DIARIZATION_MODEL` 토글 추가 (기본 `community-1`).
- **번역 파이프라인**:
  - 1-pass → **2-pass DCCD** (Draft-Conditioned Constrained Decoding)
    기본값 on. 1단계 자유 번역 + 2단계 strict 정렬 (minItems=maxItems=N).
    약한 로컬 모델에서도 segment 수 정합 보장. 환경변수
    `GURUNOTE_TWO_PASS` 토글 (기본 on, off 강제: `=0`).
  - **entity_cache 디스크 영속** + 외래어 표기법 (문화체육관광부고시
    제2017-14호) LLM 참조 → 인명·지명 표기 일관성. bootstrap 단계에서
    영상 메타데이터로 1 회 식별 + 캐시.
  - 화자 라벨 코드 부착 (LLM 식별 1 회 + 코드 결정론 부착) — Rule 충돌
    해소.
  - 한자 / 일본어 / 중국어 문자 차단 후처리 (3 단계 sub-path).
  - chunk 당 wall-clock timeout (B02) — slow chunk grammar-recovery 루프
    즉시 종료.
  - 환경변수 `GURUNOTE_SEGMENT_RESPLIT` 토글 (기본 on, off 강제: `=0`).
- **버전**: `0.8.0.6` → `1.0.0.0`. 6 곳 동시 갱신 (`gurunote/__init__.py`,
  `gui.py` 사이드바, `scripts/package_desktop.py` Inno Setup,
  `gurunote/webui/components/SettingsScreen.jsx` fallback, `README.md`,
  본 파일). CLAUDE.md 버전 체크리스트 5-file → 6-file 로 갱신 (React UI
  fallback 추가).

### Added
- `app_webview.py` 신규 진입점 (PyWebView 기반 React UI).
- `run_webview.command` macOS 런처.
- `gurunote/webui/` — React 컴포넌트 10 개, CSS, vendor (Babel standalone /
  React / Tailwind utility), `bridge.py` (Api 클래스 — Python ↔ JS bridge),
  `session.py` (PipelineSession 어댑터).
- `gurunote/data/loanword_orthography.md` — 외래어 표기법 본문 (LLM 참조).
- `gurunote/_net.py` — certifi 번들 기반 SSL context (`v0.8.0.6` 에서 도입,
  1.0 으로 승격).
- 백엔드 품질 Phase 1~5 (`docs/journal/CHANGELOG.md` 통합 일지 참고).

### Fixed
- 다수 — `docs/journal/HISTORY.md` / `docs/journal/DEBUGGING.md` 의 통합
  기록 참고.

## [0.8.0.6] - 2026-04-19

### Fixed
- **macOS python.org Python 에서 YouTube 썸네일 / 업데이트 체크 실패**
  (`gurunote/thumbnails.py`, `gurunote/updater.py`, 신규
  `gurunote/_net.py`).
  - **원인**: macOS 에 `https://python.org` installer 로 설치한 Python
    3.13 은 기본적으로 시스템 루트 CA 에 접근하지 못해 `urlopen
    ("https://...")` 이 `SSL: CERTIFICATE_VERIFY_FAILED — unable to get
    local issuer certificate` 로 실패. 사용자가 수동으로 `Install
    Certificates.command` 를 실행하기 전까지 `i.ytimg.com` / `raw.
    githubusercontent.com` / GitHub API 호출이 모두 silent None 으로
    떨어져 History 썸네일이 🎬 fallback 으로 뜨고 업데이트 체크/tarball
    fallback 이 동작 안 함.
  - **수정**: 신규 `gurunote._net.default_ssl_context()` — `certifi`
    번들(`certifi.where()`) 기반 `ssl.SSLContext` 를 `@lru_cache` 로
    제공. `certifi` 미설치 환경은 system default 로 폴백.
    `thumbnails.py` 의 1개 + `updater.py` 의 3개 `urlopen` 호출에 모두
    `context=default_ssl_context()` 추가.
  - **의존성**: `certifi>=2024.2.2` 를 `requirements.txt` 에 명시
    (yt-dlp/requests 등의 전이적 의존성으로 거의 모든 환경에 이미
    설치돼 있으나 명시로 안정성 확보).
  - **사용자 workaround (코드 fix 와 별도)**: 터미널에서
    `/Applications/Python\ 3.13/Install\ Certificates.command` 실행
    시 즉시 해결 — 이 커밋 적용 전에도 동작.

## [0.8.0.5] - 2026-04-18

### Fixed
- **History 카드 Del 버튼 잘림** (`gui.py:HistoryDialog._render_card`) —
  사용자 스크린샷에서 `Log` 버튼 옆 버튼이 일부만 보이고 잘려 보이던 버그.
  - **원인**: 기존 버튼 행은 `.md · Edit · PDF · Obs · Ntn · Log` 6개를
    `pack(side="left")` 로, `Del` 하나만 `pack(side="right")` 로 배치.
    카드 폭 280px → 내부 btn_row 268px 인데, 좌측 6개 버튼이 실제 렌더 폭
    합계 242px 를 차지해 Del 이 26px 로 squeeze 되며 "Del" 텍스트가 clip.
  - **수정**: `grid_columnconfigure(..., weight=1, uniform="hist_btn")` 로
    7개 컬럼 균등 배치. 각 버튼은 `grid(column=i, sticky="ew", padx=1)` —
    모든 버튼이 ~36px 동일 폭으로 렌더되며 누구도 clip 되지 않음.
  - Phase 3 (히스토리 카드 전면 재설계, 2버튼 + 더보기) 전까지 임시 유지.

## [0.8.0.4] - 2026-04-18

### Changed
- **UI 리프레시 Phase 2a-ii — Provider 조건부 필드 노출** (`gui.py:
  SettingsDialog`). LLM Provider 선택에 따라 AI Provider 섹션 내
  관련 API 키·모델 필드만 grid 되고 나머지는 `grid_forget` 으로 숨김.
  화면 밀도 감소 → 사용자가 "내가 쓰는 provider 의 키는 어디에 넣지?"
  고민하지 않아도 됨.
  - `openai` / `openai_compatible` → `OPENAI_API_KEY` ·
    `OPENAI_BASE_URL` · `OPENAI_MODEL`
  - `anthropic` → `ANTHROPIC_API_KEY` · `ANTHROPIC_MODEL`
  - `gemini` → `GOOGLE_API_KEY` · `GEMINI_MODEL`
  - 구현: `_field_widgets[env_key]` 에 필드별 위젯 리스트(label, input,
    aux 버튼 등) 저장 → `_apply_provider_visibility(provider)` 가 show/
    hide 일괄 적용. 위젯의 원본 grid 정보는 `_saved_grid_info` 속성에
    백업해 restore 가능.
  - 다이얼로그 초기 오픈 시 + Provider dropdown 변경 시 모두 트리거.

### Added
- **Secret 필드 "지우기" 버튼** — API Key 필드 옆 `보기` 버튼 옆에
  `지우기` 추가. 클릭 시 entry 내용 즉시 clear. 저장 시 `.env` 에서
  해당 항목이 제거됨 (또는 빈 값으로 기록).
  - 기존 secret 필드 레이아웃: `[entry]  [보기]`
  - 변경 후: `[entry]  [보기] [지우기]` — transparent frame 하나로 묶어
    column 2 에 배치.

## [0.8.0.3] - 2026-04-18

### Changed
- **업데이트 완료 후 앱 자동 재시작** (`gui.py:UpdateProgressDialog._poll`,
  신규 `_restart_app`). 기존에는 "앱을 재시작하세요" messagebox 만 띄우고
  사용자가 수동으로 앱을 껐다 켜야 했음. 이제 업데이트 성공 시
  `_status_label` 에 `"업데이트 완료! · 재시작 중…"` 을 0.7초간 표시한 뒤
  자동으로 프로세스를 교체.
  - **전략**: PyInstaller 번들은 `sys.executable` 자체를 재실행. 일반
    `python gui.py` 실행은 `[sys.executable, *sys.argv]` 로 재실행.
  - **1차**: `os.execv` 로 현재 프로세스 in-place 교체 — 가장 깔끔.
  - **2차 폴백**: 일부 macOS .app 번들에서 execv 가 launchd 와 충돌하는
    케이스를 대비해 `subprocess.Popen(start_new_session=True)` + Tk root
    destroy + `sys.exit(0)`.
  - **3차 폴백**: 두 방법 모두 실패 시 "재시작 실패" 경고 dialog 후 종료
    (사용자가 수동 재실행).
  - 업데이트 실행 중인 파이프라인 worker 는 강제 종료됨 (업데이트 시작
    시점에 사용자가 작업 중단을 이미 수락한 것으로 간주).

## [0.8.0.2] - 2026-04-18

### Fixed
- **결과 카드 empty state 잘림** (`gui.py:_build_result_meta_header`) — 사용자
  스크린샷에서 🎙️ 아이콘 외 empty state 텍스트(`아직 결과가 없습니다` /
  3단계 흐름 / 지원 파일) 가 보이지 않던 버그.
  - **원인**: `self._meta_row = ctk.CTkFrame(...)` 를 빈 상태로 생성 시
    CustomTkinter 의 CTkFrame 기본 크기(200×200) 가 적용돼 메타 헤더 row 0
    이 232px 로 부풀었고, 결과 카드 row 1 (weight=1) 에 할당된 공간이
    58px 로 찌그러지면서 empty state 의 4개 라벨 중 🎙️ 만 보이고 나머지
    3개가 clip 됨.
  - **수정**: `_meta_row` 생성 시 `height=1` 명시. `grid_propagate(True,
    기본값)` 가 children(labels/chips) 추가 시 자연스럽게 expand.
    populated 후 433×28, clear 후 children 없음 확인.

## [0.8.0.1] - 2026-04-18

### Changed
- **UI 리프레시 Phase 2a-i — 설정 화면 섹션화** (`gui.py:SettingsDialog`).
  긴 단일 폼을 5개 섹션 구조로 재배치해 "어디에 무엇이 있는지" 인지 부담
  감소. 필드 자체·저장 로직·프리셋 연동은 전부 그대로 — `self._entries`
  dict 에 widget 참조를 보관하므로 `_on_save` / `_on_test_connection` /
  `_apply_preset` 가 unchanged.
  - **5개 섹션**: `일반` (LLM Provider) / `AI Provider` (OpenAI / Anthropic
    / Gemini 키·모델) / `STT · 하드웨어` (하드웨어 프리셋 + WhisperX / MLX
    / AssemblyAI / HuggingFace) / `연동` (Obsidian / Notion) / `고급` (LLM
    temperature / max_tokens).
  - **헤더**: 페이지 제목 "설정" (FONT_HEADING) + 서브타이틀 + 하드웨어
    자동 감지 결과 표시.
  - **섹션 구분**: 섹션 간 얇은 divider (`uc.divider`).
  - **하단 sticky footer**: 좌측 `연결 테스트` (ghost) / 우측 `취소` +
    `저장` (primary). 스크롤되지 않음.
  - **다이얼로그 크기**: 620×640 → 680×760.
  - **디자인 토큰 이관**: 모든 패딩/색/폰트를 `ui_theme` 토큰 + `uc.*`
    factory 로 통일 (기존 하드코딩 색상 `"gray55"`, `"#22C55E"` 등 제거).

### Removed
- **`SettingsDialog._on_update`** + **Update 버튼** — 사이드바에 이미
  Update 메뉴가 있어 중복. 사이드바 진입점으로 단일화.

## [0.8.0.0] - 2026-04-18

### Changed
- **UI 리프레시 Phase 1 완결 — 결과 카드 재설계** (`gui.py`
  `_build_result_card` + 신규 `_build_result_meta_header` /
  `_build_result_empty_state` / `_show_empty_state` / `_show_result_tabs` /
  `_update_result_meta`). Phase 1a/1b/1c 에서 준비한 디자인 시스템과
  재구조화가 메인 화면의 마지막 카드에 적용되며, 이번 minor bump 로
  전체 Phase 1 (메인 화면 + 디자인 시스템 기반) 이 마무리됨.

  - **메타 헤더 추가** — 결과 카드 상단에 영상 제목(크게) + 업로더 ·
    게시일 · 길이 · 화자 수 + `STT 엔진` / `LLM provider` chip 을
    한 줄로 배치. 길이는 `6150초 → 1시간 42분` / `125초 → 2분 5초`
    로 한국어 포맷. `_format_duration_meta` 헬퍼 신규.

  - **내보내기 dropdown** (`_show_export_menu` + `_on_copy_markdown` +
    `_on_open_saved_folder`) — 기존 4개 Save 버튼(`Save .md` / `Save PDF`
    / `→ Obsidian` / `→ Notion`) 을 단일 Primary 버튼 `내보내기 ▾` 로
    통합. 클릭 시 `tk.Menu` popup 으로 다음 항목 표시:
    - 복사 (결과 마크다운 전체 → 클립보드)
    - Markdown 저장  ·  PDF 저장
    - Obsidian 으로 보내기  ·  Notion 으로 보내기
    - 폴더 열기 (가장 최근 저장 경로의 부모 폴더; 저장 전 비활성)
    OS 별 폴더 열기: macOS `open` / Windows `explorer` / Linux `xdg-open`.

  - **Empty state** — 파이프라인 실행 전 결과 카드 본문에 안내 프레임
    (🎙️ 아이콘 + "아직 결과가 없습니다" + 3단계 흐름 + 지원 파일 힌트).
    Empty state ↔ tabview 전환은 `grid()` / `grid_forget()` 토글.

  - **탭 한국어화** — `Summary` → `요약`, `Korean` → `한국어 전문`,
    `English` → `원문`, `Log` → `처리 로그`. `_on_pipeline_done` 의
    기본 탭 선택도 `"요약"` 으로 갱신.

### Added
- **Non-blocking 토스트 알림** — `GuruNoteApp.__init__` 에서
  `ToastManager(self)` 초기화 (1a 에서 모듈만 만들었던 것을 실제 사용).
  저장/복사/Notion 전송 상태를 `messagebox.showinfo` blocking modal 대신
  우측 하단 토스트로 표시. 에러는 계속 modal (사용자 acknowledgment 필요).
  적용 지점:
  - Markdown 저장 성공: `저장됨  ·  <파일명>` (success)
  - PDF 저장 성공: `PDF 저장됨  ·  <파일명>` (success)
  - 복사: `클립보드에 복사됨` (success)
  - Notion 전송 시작: `Notion 으로 전송 중…` (info, 4s duration)
  - 복사 실패: `복사 실패: <err>` (error)

### Removed
- `GuruNoteApp._save_btn` / `_save_pdf_btn` / `_save_obsidian_btn` /
  `_save_notion_btn` — 내보내기 dropdown 으로 통합됨. 관련 disable/enable
  로직(`_on_run`, `_on_pipeline_done`, `_poll_notion_result`) 은 모두
  `self._export_btn` 하나로 단일화.

### Changed (세부)
- 실행 중 title 라벨: `"파이프라인 실행 중…"` → `"처리 중…"`
- `_on_pipeline_done` 에러 title: `"[Error] 오류 발생"` →
  `"[오류] 파이프라인 실패"`
- `_on_run` 에서 empty state → tabview 로 자동 전환 (로그 탭에서 라이브
  진행 확인 가능).

### 버전 정책
Phase 1 전체 완결 (사용자 체감 UI 리디자인 4개 sub-phase 누적) 이므로
CLAUDE.md 의 MINOR 기준 (`새 기능 추가, UI 변경, 신규 모듈, 엔진 교체`)
에 따라 `0.7.2.5` → `0.8.0.0` 상승. PATCH/REVISION 은 0 으로 리셋.

## [0.7.2.5] - 2026-04-18

### Changed
- **UI 리프레시 Phase 1c — 진행 카드 재설계** (`gui.py` `_build_progress_card`
  + `_refresh_eta_label`).
  - **상태 라인 한국어화** — 기존 `"45%  |  2m 15s elapsed  |  ~3m left"`
    → `"번역 중  ·  2m 15s 경과  ·  ~3m 25s 남음"` (현재 단계명 + 경과 +
    ETA). 완료 시 `"완료  ·  총 {elapsed}"`, 30s 동안 진행률 변화 없으면
    `"... 진행 대기 중…"` 표시.
  - **현재 단계 자동 도출** (`_current_step_name(pct)`) — progress 퍼센트
    에서 STEP_LABELS (오디오/STT/번역/요약/조립) 중 현재 단계를 도출.
    임계값 (`_STEP_THRESHOLDS = 0.18/0.55/0.78/0.90/1.0`) 은 기존
    `_update_steps` 와 동일해 pill 과 라벨이 항상 일관됨.
  - **처리 로그 드로어** — 카드 하단에 `▸ 처리 로그 보기` ghost 토글
    추가. 열면 전체 파이프라인 로그가 카드 내에 160px 높이
    `CTkTextbox` 로 표시됨. 결과 카드의 `처리 로그` 탭과 **동일한
    내용을 미러** — `_append_log` / `_clear_log` 가 두 textbox 에 동시
    write. 기본 접힘.
  - **진행률 bar 색상** — `C_ACCENT` (soft lavender) → `C_PRIMARY_BRIGHT`
    (tone 80) 로 변경해 대비 향상.
  - 모든 패딩/폰트/반경을 `ui_theme` 토큰 사용 (`uc.card`,
    `ut.SPACE_*`, `ut.RADIUS_SM`, `ut.FONT_META` 등).

### Changed (리팩터링)
- **`GuruNoteApp._preset_var` → `_processing_preset_var`**, **`_on_preset_change`
  → `_on_processing_preset_change`**, **`_preset_segment` →
  `_processing_preset_segment`**. `SettingsDialog` 의 **하드웨어 프리셋**
  과 이름이 겹쳐 향후 panel 구조 전환 시 혼동 위험이 있어 처리 모드
  프리셋(Phase 1b 도입)에 명시적 prefix 추가. 서로 다른 클래스의
  같은 속성명이라 파이썬 레벨 버그는 아니었음 — 선제적 정리.

## [0.7.2.4] - 2026-04-18

### Changed
- **UI 리프레시 Phase 1b — 메인 입력 카드 3행 재배치** (`gui.py`
  `_build_input_card`). 기존 1~2행 혼재 구조를 명확한 3행 위계로 분리해
  "어디를 눌러야 하는지" 인지 부담을 줄임.
  - **행 1 — 소스 입력**: 좌측 `파일 선택` 버튼 + 우측 URL Entry
    (hero-size `HEIGHT_LG=40`). placeholder 를 예시 URL 포함 형태로 확장.
  - **행 2 — 처리 모드 + Primary CTA**: 좌측 프리셋 세그먼트 (아래 항목
    참조) + 우측 유일한 Primary 버튼 `▶  GuruNote 생성` + `⏹` stop.
    세그먼트는 `CTkSegmentedButton` 기반, selected 색은 `C_PRIMARY`.
  - **행 3 — 고급 설정 토글**: `▸ 고급 설정` ghost 버튼 한 개. 클릭 시
    행 4 에 STT 엔진 / LLM provider 드롭다운이 접혀 있다 펼쳐짐
    (`grid()` / `grid_forget()` 토글). 기본 접힘 — 사용자가 구체 엔진
    이름을 볼 필요 없음.

- **처리 모드 프리셋(빠름/균형/품질/직접)** (`gui.py` `_preset_to_stt` /
  `_stt_to_preset` / `_on_preset_change` / `_on_stt_manual_change`). 초보자가
  엔진 이름(whisperx/mlx/assemblyai) 대신 속도/품질 트레이드오프로 선택.
  - **빠름** → `assemblyai` (클라우드, GPU 불필요, 빠른 시동)
  - **균형** → `auto` (기존 기본, 플랫폼별 자동 선택)
  - **품질** → `mlx` (Apple Silicon) / `whisperx` (그 외 — NVIDIA 가정)
  - **직접** → 고급 영역 자동 확장, 사용자가 STT/LLM 수동 선택
  - 초기 preset 은 `GURUNOTE_STT_ENGINE` 환경변수값에서 역추론 —
    env=assemblyai → "빠름", env=mlx/whisperx → "품질", env=auto → "균형",
    그 외 → "직접".
  - 사용자가 고급 영역에서 STT 드롭다운을 **수동으로** 변경하면 preset
    이 자동으로 "직접" 으로 전환 (UI 일관성 유지).
  - WhisperX 미설치 / API 키 없음은 기존 `_check_whisperx_available()` /
    `_check_api_keys()` 가 그대로 처리 — preset 은 표시용 레이어.

### Changed (세부)
- 한국어 라벨 통일: `File` → `파일 선택`, `▶  GuruNote 생성하기` →
  `▶  GuruNote 생성` (CTA/reset/empty state 텍스트 모두).
- `gui.py` 가 `gurunote.ui_theme` / `gurunote.ui_components` 를 import
  하기 시작 — Phase 1a 에서 준비한 디자인 토큰/factory 를 메인 입력
  카드부터 실제 사용. 진행/결과 카드는 1c/1d 에서 이관.

### Fixed
- `CHANGELOG.md` v0.7.2.3 항목의 "자동 자동 dismiss" 오타 수정 (편집용).

## [0.7.2.3] - 2026-04-18

### Added
- **UI 리프레시 Phase 1a — 디자인 시스템 / 컴포넌트 라이브러리 기반 구축**
  (`gurunote/ui_theme.py`, `gurunote/ui_components.py`, `gurunote/ui_toast.py`
  신규). Phase 1 UI 리프레시의 **첫 번째 단계** — 후속 Phase (1b/1c/1d) 에서
  실제 화면에 적용할 재료를 준비한다. `gui.py` 는 이번 PR 에서 **건드리지
  않아** 동작 회귀 위험이 0 이다.
  - **`ui_theme.py`** — 분산돼 있던 색상/간격/반경/폰트/높이 상수를 단일
    출처로 통합. Material 3 다크 팔레트(purple tonal)는 기존 `gui.py` 의
    `C_*` 값을 그대로 이관해 시각적 변화 없음. 추가 토큰:
    `SPACE_XXS~XXXL` (2·4·8·12·16·24·32·48), `RADIUS_SM/MD/LG` (8/12/16),
    `HEIGHT_SM/MD/LG/XL` (28/32/40/48), `FONT_PAGE_TITLE~META` (27/21/16/14/13/11),
    `BTN_PRIMARY/SECONDARY/GHOST/DANGER` 변형 상수, `STATUS_COLORS` 맵
    (완료/실패/처리 중/대기).
  - **`ui_components.py`** — factory 함수 6종:
    - `button(...)` — 변형 기반 CTkButton (primary/secondary/ghost/danger)
    - `card(...)` — RADIUS_MD + border 로 표준 카드 frame
    - `section_header(...)` — title + optional subtitle
    - `status_pill(...)` — 작업 상태 표시용 pill
    - `tag_chip(...)` — 태그/분류용 chip (default/accent)
    - `divider(...)` — 수평/수직 분리선
  - **`ui_toast.py`** — `ToastManager` 클래스. `messagebox` 의 blocking
    modal 대신 우측 하단에 non-blocking 토스트 표시. 여러 개 스택 가능,
    레벨(info/success/warning/error) 별 색상, 클릭 시 즉시 dismiss,
    `after()` 로 자동 dismiss (기본 2.5초).

## [0.7.2.2] - 2026-04-18

### Fixed
- **macOS 오디오 소스 입력창 붙여넣기 안정화** (`gui.py` —
  `_install_clipboard_shortcuts`) — 사용자가 "오디오 소스 URL 입력창에
  붙여넣기가 동작하지 않는다" 고 보고. 이전 v0.6.0.2 의 fix 가
  `event_generate("<<Paste>>")` 로 가상 이벤트를 dispatch 했지만 두 가지
  실패 경로가 남아 있었음:
  1. `focus_get()` 가 CTkEntry 의 wrapper Frame 을 돌려주는 케이스 —
     Frame 에는 `<<Paste>>` 바인딩이 없어 가상 이벤트가 무시됨.
  2. macOS Aqua + 한국어 IME 조합에서 Tk 의 가상 이벤트 tail 큐
     dispatch 가 누락되는 케이스.
  - 이번 fix 는 가상 이벤트를 거치지 않고 `clipboard_get()` 으로 직접
    텍스트를 읽어 포커스 위젯에 `insert()` 한다. CTkEntry/CTkTextbox
    wrapper 가 포커스 대상이면 내부 `_entry`/`_textbox` 로 자동 위임.
  - 복사/잘라내기/전체선택도 동일한 직접 호출 방식으로 통일 (선택 영역
    없으면 silent no-op).

### Added
- **우클릭 컨텍스트 메뉴 (macOS)** — Cmd+V 가 어떤 이유로든 실패해도
  마우스로 잘라내기/복사/붙여넣기/전체 선택 가능. Button-2 (한 손가락
  우클릭), Button-3 (두 손가락 클릭), Ctrl+클릭 모두 지원. 클립보드/선택
  상태에 따라 메뉴 항목이 자동 활성/비활성.

## [0.7.2.1] - 2026-04-17

### Fixed
- **업데이트 시 GitHub `Username/Password` 프롬프트 문제** (`gurunote/updater.py`,
  `gui.py`) — Google OAuth 로만 GitHub 에 로그인한 사용자처럼 password 가
  없는 계정에서 `git pull` 이 credential 입력을 요구하며 멈추던 문제 해결.
  - 모든 `git` 서브프로세스가 이제 **완전 non-interactive** 로 실행:
    `GIT_TERMINAL_PROMPT=0` + `GIT_ASKPASS=/bin/echo` +
    `-c credential.helper=""` 로 credential helper 비활성화 +
    `stdin=subprocess.DEVNULL` 로 TTY 접근 차단.
  - 공개 저장소라면 이 조합만으로 인증 없이 fetch/pull 이 정상 동작.
  - auth 관련 실패(`Authentication failed`, `could not read Username`,
    `HTTP 401/403` 등) 감지 시 `GitAuthError` 를 raise.

### Added
- **저장소 공개/비공개 자동 감지 + 분기 업데이트** (`detect_repo_visibility()`,
  `update_project()`) — 사용자가 저장소 공개/비공개를 왔다갔다 해도 항상
  현재 상태에 맞게 동작:
  - GitHub REST API `GET /repos/{owner}/{repo}` 를 unauth 로 호출해 `private`
    필드 확인 (200/404/403 각각 처리).
  - **공개 저장소** + git 인증 실패 → `update_via_tarball()` 로 자동 폴백
    (사용자 개입 없이 성공).
  - **비공개 저장소** (또는 감지 실패) + git 인증 실패 → `GitAuthError` 즉시
    raise → GUI 가 `GitAuthErrorDialog` 로 `gh auth login` / PAT 옵션 안내.
  - 업데이트 로그 상단에 `[감지] 공개 저장소 — ...` / `[감지] 비공개 저장소 — ...`
    를 표시해 사용자가 현재 모드 확인 가능.

### Added
- **`GitAuthErrorDialog`** (`gui.py`) — 비공개 저장소 등으로 인증이 필요한
  상황에서 사용자가 해결 옵션을 한눈에 볼 수 있는 다이얼로그. 사용자가
  OAuth 로만 GitHub 에 가입해 password 가 없는 케이스를 주 대상으로 설계.
  - **방법 1 · GitHub CLI (권장)** — `gh auth login --web` 을 별도
    Terminal 창(macOS AppleScript / Windows cmd `/K` / Linux
    xdg terminal) 으로 띄워 브라우저 OAuth 플로우로 로그인. 로그인 후
    git 이 자동으로 gh 의 credential helper 를 통해 토큰 사용. 미설치 시
    OS 별 설치 명령(`brew install gh` / `winget install GitHub.cli` 등)
    안내.
  - **방법 2 · Personal Access Token** — `github.com/settings/tokens/new`
    (repo scope 사전 선택) 을 기본 브라우저로 열어 토큰 생성 유도.
  - **"다시 시도"** 버튼으로 로그인 완료 후 업데이트 재실행 원클릭.
- **`update_via_tarball()`** (`gurunote/updater.py`) — 공개 저장소에서만
  유효한 tarball 기반 업데이트 헬퍼 (현재는 공개 저장소 전용 옵션으로
  보관. 향후 public repo 감지 시 자동 제안용).
- **remote 버전 확인 3차 fallback** — git fetch 가 완전히 막힌 환경에서도
  `raw.githubusercontent.com` 에서 직접 `__init__.py` 를 가져와 버전
  비교가 동작하도록 추가 (공개 저장소 한정).

## [0.7.2.0] - 2026-04-17

### Fixed
- **터미널 앞으로 튀어오르는 문제** (`gurunote/log_redirect.py` 신규,
  `gui.py` 모듈 초기화) — `python gui.py` 직접 실행 시 WeasyPrint /
  pyannote / mlx-whisper 의 native 라이브러리가 C 레벨에서 stderr 로
  찍는 경고 ("WeasyPrint could not import some external libraries")
  가 macOS Terminal 을 반복적으로 포그라운드로 끌어올리던 문제 해결.
  - `os.dup2` 로 FD 1, 2 자체를 `~/.gurunote/gui.log` 로 리다이렉트
    해서 `fprintf(stderr, ...)` 직접 호출까지 커버.
  - Tkinter 메인 루프 및 heavy import 전에 실행 (gui.py 상단).
  - `GURUNOTE_NO_REDIRECT=1` 환경변수로 비활성화 (디버깅용).
- **PDF availability 판정 오탐** (`gurunote/pdf_export.py`) — 기존
  `is_pdf_export_available()` 는 `import weasyprint` 만 확인해서
  cairo/pango native 라이브러리가 없어 WeasyPrint 가 실제로는 동작
  불가인 상태에서도 True 를 반환. `Save PDF` 클릭 → 저장 시도 →
  OSError 크래시 + stderr 경고 폭주로 이어지던 문제 수정.
  - 이제 minimal `HTML(string="<p>_</p>")` 객체를 실제 생성해서
    cffi 네이티브 바인딩까지 통과하는지 확인.
  - 결과는 프로세스 수명 동안 캐시되며 `force_recheck=True` 로 갱신
    가능 — `pdf_installer.run_plan` 이 설치 성공 후 이를 호출.

### Changed
- **Obsidian 저장 성공 다이얼로그 재설계** (`gui.py` `ObsidianSaveDialog`
  신규) — 이전의 `messagebox.showinfo("Obsidian 저장 완료", 전체경로)`
  "성의없는 팝업" 교체.
  - 파일명 + vault/하위폴더 요약 표시 (긴 절대경로 대신).
  - **`Obsidian 에서 열기`** 버튼 — `obsidian://open?path=...` URL 스킴
    으로 Obsidian 앱에서 해당 노트 즉시 열기.
  - **`폴더 보기`** 버튼 — macOS `open -R` / Windows `explorer /select`
    / Linux `xdg-open` 로 파일 위치 공개.
  - `닫기` 버튼.
  - 히스토리 카드의 `→ Obsidian` 과 결과 카드의 `→ Obsidian` 양쪽
    모두 이 다이얼로그를 사용.

## [0.7.1.1] - 2026-04-17

### Changed
- **README 갱신** — v0.7.0.4 ~ v0.7.1.0 까지의 신규 기능을 본문 (빠른 시작,
  주요 기능, 실행 섹션, 프로젝트 구조, Uninstall, FAQ) 에 모두 반영.
  - 빠른 시작 / 실행 섹션: macOS 백그라운드 런처 (`./run_gui.command`) 안내
    + venv 자동 감지 + `~/.gurunote/gui.log` 진단법
  - 주요 기능: PDF 자동 설치 다이얼로그, Obsidian vault 자동 감지, 4-facet
    트리 내비, 노트 인-앱 편집, 의미 검색, 대시보드, Material 3 다크 UI
  - 프로젝트 구조: 신규 모듈 11종 (`thumbnails.py`, `pdf_export.py`,
    `pdf_installer.py`, `obsidian.py`, `notion_sync.py`, `search.py`,
    `semantic.py`, `stats.py`, `nav_tree.py`, `ui_state.py`, `app_icon.py`)
    + `run_gui.command` 추가 표기
  - Uninstall: `~/.gurunote` 하위 신규 산출물 (썸네일 캐시, 의미 검색
    인덱스, UI 상태, 앱 아이콘, 백그라운드 로그) 명시
  - FAQ 5건 신규: PDF 자동 설치 / Obsidian 자동 감지 / macOS 터미널
    분리 런처 / 앱 아이콘 / 트리 내비

## [0.7.1.0] - 2026-04-17

### Added
- **전용 앱 아이콘** (`gurunote/app_icon.py` 신규) — 이전엔 macOS
  messagebox 가 Python 기본 "로켓" 아이콘을 썼던 문제 해결. 첫 실행 시 PIL
  로 `G` 모노그램 아이콘을 `~/.gurunote/app_icon.png` 에 생성 (Material 3
  Primary 컨테이너 보라 + 흰 글자, 둥근 사각). 메인 윈도우 및 모든
  `CTkToplevel` (History/Dashboard/Settings/NoteEditor/Obsidian/PDF
  Install/Update) 에 `iconphoto` 로 적용.
- **macOS 백그라운드 런처** (`run_gui.command`) — 소스에서 실행할 때 터미널
  에 pyannote/mlx-whisper 의 진행 로그가 쏟아지던 문제 해결.
  - `nohup ... &` + `disown` + stdin `/dev/null` 로 완전 분리.
  - 모든 stdout/stderr 를 `~/.gurunote/gui.log` 로 리다이렉트 (진단 시
    `tail -f` 로 접근 가능).
  - 런치 후 Terminal.app 의 해당 창을 AppleScript 로 자동 닫음.
  - venv 자동 감지 (`./.venv/bin/python` → `./venv/bin/python` → 시스템
    `python3`).
- **`Pillow>=10.0` 의존성 명시** — 지금까지 `customtkinter` 의 전이
  의존으로만 들어오던 것을 명시 선언.

### Changed
- **Material 3 다크 팔레트 적용** (`gui.py`) — 기존 indigo/navy 톤을 구글
  Material 3 다크 테마 기준 톤으로 재조정.
  - Background: `#141218` (base surface) / Sidebar: `#1D1B20` (+1dp)
  - Surface: `#211F26` / Surface HI: `#2B2930` (hover)
  - Primary: `#4F378B` (primary container, purple 30) / Hover: `#5D43A8`
  - Text: `#E6E0E9` (on-surface) / Dim: `#938F99` (on-surface-variant)
  - Success: `#81C995` / Danger: `#F2B8B5`
  - 새 `C_PRIMARY_BRIGHT (#D0BCFF)` 는 Material Primary(purple 80) 로
    아이콘/하이라이트 전용.
- **다이얼로그 타이틀 정돈**: `📊 GuruNote Dashboard` 등 이모지 프리픽스
  제거 → `GuruNote · 대시보드` 형태 중점 구분자 사용.
- **필터바 이모지 제거**: `📄 본문 포함` → `본문 포함`, `🔮 의미 검색` →
  `의미 검색` (Windows 렌더링 호환성 개선; CLAUDE.md UI 규칙 준수).

## [0.7.0.5] - 2026-04-17

### Added
- **Obsidian 연동 간편 설정** (`gurunote/obsidian.py`, `gui.py`
  `ObsidianSetupDialog`) — 이전엔 Settings 로 가서 vault 경로를 **직접 입력**
  해야 했던 플로우를 대폭 개선.
  - `find_vault_candidates(max_depth=2)` — macOS/Windows/Linux 공통 경로
    (`~/Documents`, iCloud Obsidian Sync, `~/OneDrive/Documents` 등) 를
    최대 2단계까지 스캔해 `.obsidian/` 폴더가 있는 vault 자동 감지. 최근
    수정일 내림차순 정렬.
  - **`ObsidianSetupDialog`**: 자동 감지된 vault 를 한 번의 클릭으로 선택,
    또는 `폴더 찾아보기...` 버튼으로 `askdirectory` 피커. 선택 시 `.env`
    자동 저장 + `os.environ` 즉시 반영 + 원래 저장 플로우 자동 이어감.
  - Vault 미설정 상태에서 `→ Obsidian` 클릭 시 **경고창 대신** 이
    다이얼로그가 열림. 경로 직접 타이핑 없음.
  - `.obsidian/` 없는 폴더 선택 시 경고 + "그래도 사용" 확인 (Obsidian 이
    처음 열면 자동 생성됨을 안내).

### Changed
- **Settings 다이얼로그의 Obsidian Vault 경로 필드**: `찾아보기` 버튼 추가
  (`CTkButton` 3번째 열) + 실시간 유효성 chip (`✓ vault` / `폴더 있음
  (.obsidian/ 없음)` / `경로 없음`). 타이핑 중에도 `<KeyRelease>` 로 즉시
  재검증.

## [0.7.0.4] - 2026-04-17

### Changed
- **PDF 출력 패키지 기본 설치 포함** (`requirements.txt`) — `markdown` +
  `weasyprint` 를 기본 요구 패키지로 승격. 신규 설치 시 `bash setup.sh` /
  `pip install -r requirements.txt` 한 번이면 PDF 출력 준비 완료.
  `requirements-pdf.txt` 는 레거시 호환용으로 유지.

### Added
- **PDF 미설치 시 자동 설치 다이얼로그** (`gurunote/pdf_installer.py` 신규,
  `gui.py` `PDFInstallDialog`) — 이전엔 `Save PDF` 클릭 시 경고문만 띄우고
  사용자가 수동 설치를 해야 했던 플로우를 대폭 개선.
  - `is_python_deps_ok()` / `plan_installation()` 로 현재 상태 감지 후
    OS 별 설치 플랜 (pip / brew / sudo-apt) 생성.
  - macOS + Homebrew 환경: `brew install cairo pango gdk-pixbuf libffi` +
    `pip install` 자동 실행 (사용자 yes/no 확인 후).
  - Linux (sudo 필요) / Homebrew 미설치 macOS: 수동 명령을 다이얼로그에
    안내만 하고 자동 실행 스킵.
  - Windows: pip 만 자동 실행 (weasyprint wheel 에 DLL 포함).
  - 설치 성공 시 원래 "Save PDF" 플로우를 자동으로 이어 실행해, 다시 클릭할
    필요 없음.
  - 진행 로그 스트리밍 (CTkTextbox), 실패 시 에러 표시.

## [0.7.0.3] - 2026-04-17

### Fixed
- **유튜브 썸네일 다운로드 안정화** (`gurunote/thumbnails.py`, `gui.py`) —
  일부 영상 (라이브 replay, 오래된 업로드, shorts 등) 의 `mqdefault.jpg` 가
  404 / 1-2KB placeholder 를 반환해 히스토리 카드에 ⏳ 아이콘이 영구 고착되던
  문제 해결.
  - **해상도 폴백 체인**: `mqdefault` → `hqdefault` → `sddefault` → `default`.
    첫 유효 응답 (>=2KB) 에서 중단. 모든 variant 실패 시 None.
  - **Referer + User-Agent 정규화**: 일부 CDN 경로에서 빈 Referer 요청에
    투명 PNG 를 반환해서 실패하던 케이스 예방.
  - **실패 피드백 UX**: 다운로드 최종 실패 시 `_mark_thumbnail_failed` 가
    ⏳ 플레이스홀더를 🎬 로 즉시 교체 (스틱 상태 방지).
  - **Atomic write**: 썸네일 JPEG 를 `tmp → replace` 로 저장해 앱 크래시 시
    반쪽 파일이 캐시에 남지 않음.
  - **디버그 로그**: `GURUNOTE_THUMB_DEBUG=1` 환경변수로 variant 별 시도
    결과 추적 가능.

## [0.7.0.2] - 2026-04-17

### Added
- **Streamlit 히스토리 탭 트리 내비 포팅** (`app.py`) — Phase 3 "지식 증류기
  UI" 마지막. 데스크톱 GUI 의 4-facet 트리를 웹 앱에도 동등 기능으로 제공.
  - 히스토리 탭을 `st.columns([1, 3])` 으로 분할 — 좌: 트리 내비 / 우: 잡 목록.
  - `gurunote.nav_tree.compute_facets(jobs)` 재사용 → 주제/인물/제목/태그
    각각 `st.expander` 로 펼침.
  - 노드 버튼 클릭 → `st.session_state["nav_filter"]` 설정 → `st.rerun()`.
    활성 노드는 `type="primary"` 로 강조.
  - `× 필터 해제` 버튼 (상단) + 우측 패널 상단 활성 필터 chip.
  - 삭제된 잡의 stale id 자동 정합 — `valid_ids` 교집합 후 0 이면 필터 해제.

## [0.7.0.1] - 2026-04-17

### Added
- **트리 내비게이션 Phase 2** (`gurunote/nav_tree.py`, `gurunote/ui_state.py` 신규,
  `gui.py` HistoryDialog) — Phase 1 의 3-facet 에 확장 3종.
  - **Tag facet** 추가 (`태그`) — 한 잡이 여러 태그에 속할 수 있으므로
    각 태그 버킷에 중복 append. count 내림차순 정렬.
  - **트리 내 노드 검색 박스** — 패널 상단 `트리 내 검색…` Entry.
    입력 시 모든 facet 의 노드를 라벨 서브스트링으로 실시간 필터.
    세션 단위 (영속 X).
  - **Expand 상태 영속** (`~/.gurunote/ui_state.json`) — 헤더 ▾/▸ 토글
    상태를 atomic write 로 저장. HistoryDialog 열 때 로드, 닫을 때 저장
    (`WM_DELETE_WINDOW` protocol). 파싱/쓰기 실패는 silent fallback.

## [0.7.0.0] - 2026-04-17

### Added
- **히스토리 우측 트리 내비게이션 패널** (`gurunote/nav_tree.py` 신규,
  `gui.py` HistoryDialog) — Phase 1 "지식 증류기 UI" 개선안 Option A.
  3-facet 고정 분류: **주제(분야)** / **인물(업로더)** / **제목(첫글자 버킷)**.
  - 노드 클릭 → 해당 facet 의 `job_ids` 집합을 `_nav_filter` 로 설정 →
    기존 검색/분야/정렬 필터와 AND 결합 (직교 필터링)
  - 동일 노드 재클릭 / `× 필터 해제` chip / `필터 초기화` 버튼 → 해제
  - Facet 헤더 ▾/▸ 토글 (기본 전부 펼침)
  - 제목 버킷: A-G / H-N / O-T / U-Z / 가-마 / 바-아 / 자-하 / 기타
    (한영 혼합 대응)
  - 빈 인덱스 안내: "노트를 만들면 자동 분류됩니다"
  - HistoryDialog 폭 960 → 1240px 확장 (트리 280px 추가)
  - 노트 삭제 시 nav 필터의 job_ids 자동 정합 (stale 필터 방지)

## [0.6.0.19] - 2026-04-17

### Added
- **Streamlit 앱 대시보드 / 의미 검색 탭 포팅** (`app.py`) — 데스크톱 GUI
  와 같은 두 기능을 웹 앱에서도 사용 가능하게 추가.
  - `📊 대시보드` 탭: `gurunote.stats.compute_stats` + `render_report` 결과를
    `st.code` 로 표시 (전체 통계 + 분야/업로더/태그/월별 차트). 의미 검색
    인덱스 상태 패널 + `Rebuild Semantic Index` / `Clear Index` 버튼.
  - `🔎 의미 검색` 탭: 질의 입력 → `gurunote.semantic.search()` → 잡 단위
    매칭 카드 표시 (점수 / 제목 / preview / 마크다운 다운로드). Top-K
    슬라이더 (1~30) + 최소 유사도 슬라이더 (0~1).
  - 가용성 체크: `sentence-transformers` 미설치 / 인덱스 미빌드 시 친절한
    안내 메시지로 graceful fallback.

## [0.6.0.18] - 2026-04-17

### Added
- **Semantic 인덱스 incremental 갱신** (`gurunote/semantic.py::update_job_in_index`,
  `gui.py` 파이프라인 + NoteEditorDialog 저장 hook) — 인덱스가 이미 빌드된
  상태에서 새 작업을 저장하거나 기존 노트를 편집하면 백그라운드에서 해당
  job 의 chunk 만 재계산해 인덱스에 incremental append. 사용자가 Dashboard
  의 "Semantic Rebuild" 를 매번 눌러야 하던 부담 제거.
  - 인덱스 미빌드 / `sentence-transformers` 미설치 시 silent no-op
  - 같은 `job_id` 의 기존 chunk 모두 제거 후 새 본문으로 교체 (편집/재저장 대응)
  - 본문이 비면 cleanup 만 수행 (vectors 에서 해당 잡 제거)
  - 모든 예외 swallow — 파이프라인/저장 흐름을 절대 막지 않음
- **NoteEditorDialog 마크다운 분할 프리뷰** (`gui.py`) — 좌: raw textbox,
  우: 렌더링된 preview (`👁 Preview` 토글로 우측 숨김 가능, 숨기면 textbox
  가 전체 폭 차지). 250ms debounce 로 키 입력 후 자동 갱신.
  - YAML frontmatter 자동 제외 (preview 노이즈 방지)
  - Block: H1/H2/H3, 인용 (│ ...), 불릿 (• ...), 번호 리스트, 수평선, 코드블록
  - Inline: `**bold**` / `*italic*` / `` `code` `` / `[link](url)` 모두 Tk Text
    `tag_config` 로 스타일링 (markdown 라이브러리 의존성 없음)
  - 다이얼로그 폭 900 → 1200px 로 확장

## [0.6.0.17] - 2026-04-17

### Added
- **의미 검색 (Semantic Search)** (`gurunote/semantic.py` 신규,
  `requirements-search.txt` 신규) — 로드맵 "지식 증류기 확장" 의 마지막
  단계 완성. Phase F 의 키워드 substring 검색을 embedding 기반 cosine
  similarity 로 보완.
  - 모델: `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~117MB,
    한국어 지원). 환경변수 `GURUNOTE_SEMANTIC_MODEL` 로 오버라이드 가능.
  - Chunk 분할: 1000자 + 100자 overlap (frontmatter 는 제외)
  - 인덱스 저장: `~/.gurunote/embeddings.npz` (vectors) +
    `embeddings_meta.json` (job_id / chunk_idx / title / preview)
  - `build_index(jobs)` / `search(query, top_k=10, min_score=0.25)` /
    `clear_index()` / `index_stats()` API
  - `search()` 는 동일 잡의 중복 chunk 제거하여 job 당 최고 점수 chunk
    1개씩만 반환 → 히스토리 그리드에 중복 카드 없이 표시
- **HistoryDialog `🔮 의미 검색` 토글** (`gui.py`) — 기존 `📄 본문 포함`
  옆에 체크박스 추가. 켜지면 query 로 embedding 검색 → cosine 유사도
  0.25 이상 상위 20 잡을 결과에 포함. 매칭 잡 카드에
  `[유사도 0.73] ...preview...` 스니펫 표시. 최초 쿼리 실패 시 한 번만
  경고 대화상자 (반복 경고 방지).
- **Dashboard `🔮 Semantic Rebuild` 버튼** — 모든 저장된 잡 본문을
  재인덱싱. 백그라운드 worker thread + `after()` polling 으로 UI
  freeze 방지. 완료 시 다이얼로그에 `{num_jobs, num_chunks, skipped}`
  카운트. Dashboard 본문에도 "의미 검색 인덱스" 상태 블록 추가
  (모델 / chunks / 작업 수 / 빌드 시각).
- **`requirements-search.txt`** — `sentence-transformers>=2.5` 선택 설치.
  미설치 시 친절한 설치 안내 (`is_available()` False + 117MB 모델 다운로드
  알림).

### Roadmap 완성 (Step 3)
- ✅ 3.1 리인덱싱 (PR #80)
- ✅ 3.2 노트 편집 (PR #81)
- ✅ 3.3 대시보드 (PR #82)
- ✅ **3.4 의미 검색** ← 이번 PR

## [0.6.0.16] - 2026-04-17

### Added
- **거시적 통계 대시보드** (`gurunote/stats.py` 신규,
  `gui.py::DashboardDialog`, 사이드바 **Dashboard** 네비 버튼) — 저장된
  노트 전체에 대해 한눈에 보이는 지표. matplotlib / chart lib 의존성
  없이 Unicode block (█) 바 차트로 CTkTextbox 에 직접 렌더링.
  - **전체 통계**: 총 작업 수 (완료/실패 분리), 총·평균·최장 녹취 시간,
    누적 화자 수, 최초/최근 작업 날짜
  - **분야별 분포** (상위 10, 퍼센트 표시)
  - **상위 업로더** (상위 10)
  - **상위 태그** (상위 20)
  - **월별 작업 추이** (시간 순 정렬, 라이브러리 성장 시각화)
  - Refresh 버튼으로 재집계; 비어 있으면 "아직 저장된 작업이 없습니다" 안내
  - 모든 지표는 `~/.gurunote/history.json` 메타만 읽음 — Phase A 메타
    (organized_title/field/tags/uploader/upload_date/num_speakers) 가
    없는 과거 잡은 해당 항목에서만 집계 제외되고 전체 카운트엔 포함.
- **사이드바 네비 4개로 확장** — Settings / **Dashboard** / History /
  Update. grid row 재배치 (spacer row 6, version row 7).

## [0.6.0.15] - 2026-04-17

### Added
- **저장된 노트 인라인 편집기** (`gui.py::NoteEditorDialog`,
  `gurunote/history.py::update_job_markdown`) — LLM 요약/번역의 교정이
  자주 필요한데 그동안은 외부 에디터로 `~/.gurunote/jobs/<id>/result.md`
  를 열어야 했다. 이제 HistoryDialog 카드의 **Edit** 버튼 한 번으로
  CTkToplevel 편집기가 열린다.
  - YAML frontmatter 포함 전체 마크다운을 단일 textbox 로 표시 (monospace
    Menlo, wrap=word)
  - 저장: `update_job_markdown` 이 `result.md` 만 덮어씀 (metadata 불변),
    필요시 인덱스의 stale `has_markdown=False` 를 True 로 보정
  - dirty 체크: 닫기/취소 시 저장 안 된 변경 있으면 확인 대화상자
  - Cmd/Ctrl+S 로 저장 단축키
  - 저장 후 `search_clear_cache()` 호출 + 히스토리 그리드 재로드 →
    Phase F 본문 검색 스니펫이 수정된 내용으로 즉시 갱신

### Changed
- **HistoryDialog 카드 버튼 레이아웃** — 6 → 7 버튼으로 확장
  (`.md` / **Edit** / `PDF` / `Obs` / `Ntn` / `Log` / `Del`).
  `Edit` 은 `.md` 바로 옆에 배치 (둘 다 원본 마크다운 대상). 버튼 너비를
  34 → 32px 로 조정해 카드 inner ~264px 에 7×32 + 6×gap = 236px 로 여유
  있게 맞춤. Edit 은 gray-dark-hover-primary 스타일로 시각적 구분.

## [0.6.0.14] - 2026-04-17

### Added
- **히스토리 인덱스 재생성** (`gurunote/history.py::rebuild_index`,
  `gui.py` HistoryDialog "Rebuild" 버튼) — `~/.gurunote/jobs/` 폴더 전체를
  스캔해 `history.json` 을 재작성한다. 용도:
  - `history.json` 삭제/손상 시 복구 (각 `jobs/<id>/metadata.json` 에서 재수집)
  - 다른 머신에서 `jobs/` 폴더만 복사해 왔을 때 히스토리 마이그레이션
  - metadata 엔 `has_markdown=true` 인데 실제 `result.md` 가 사라진 stale
    엔트리 자동 교정

  안전 보장:
  - 잡 파일들 자체는 절대 건드리지 않음 (read-only 스캔)
  - 손상된 JSON / 누락된 metadata.json 은 건너뛰고 결과 리포트에 기록
  - 결과: `{total_scanned, indexed, errors, missing_md}` 카운트 다이얼로그
  - atomic rename (v0.6.0.13) 으로 write 도중 crash 방지
  - 검색 본문 캐시도 함께 클리어해 stale 결과 방지

## [0.6.0.13] - 2026-04-17

### Fixed
- **YouTube `/live/` URL 썸네일 지원** (`gurunote/thumbnails.py`) —
  라이브 스트림 replay 영상 (`https://www.youtube.com/live/<id>`) 이
  `extract_youtube_id` 정규식에서 매치되지 않아 History 카드에 🎙️ placeholder
  아이콘만 뜨던 문제. `_YT_ID_RE` 에 `/live/` 패턴 추가.
- **`history.json` 원자적 write** (`gurunote/history.py::_write_index_atomic`) —
  `save_job` 이 인덱스를 쓰는 도중 `HistoryDialog.load_index()` 가 동시 실행
  되면 partial file 을 읽어 `JSONDecodeError` 로 떨어지던 race window 제거.
  임시 파일에 쓰고 `os.replace` 로 대체하는 atomic rename 패턴. POSIX 는
  커널 단 원자성, Windows 는 sector-level 원자성 보장. `save_job` + `delete_job`
  양쪽 호출 경로에서 같은 헬퍼 사용.
- **썸네일/Notion poll 의 TclError 방어** (`gui.py`) — `HistoryDialog` 가
  destroyed 된 뒤에도 pending `after()` 콜백이 한 번 더 실행되며
  `winfo_children` / `configure` 가 `_tkinter.TclError` 를 던지던 엣지케이스.
  `_poll_thumb_queue` 와 `_poll_notion_from_history` 본문을 try/except 로
  감싸 조용히 종료.

### Verified (no fix needed)
- **pyannote.audio 4.x API 호환성** — 릴리스 노트 조사 결과 우리가 쓰는
  API (`Pipeline.from_pretrained(..., token=...)`, `.to(torch.device("mps"))`,
  `pipeline(audio_path)` string input, `itertracks(yield_label=True)` 3-tuple)
  모두 4.0 에서 breaking change 없음. `DEFAULT_DIARIZATION_MODEL` 은 기존
  `pyannote/speaker-diarization-3.1` 유지 (사용자가 이미 terms 동의). 4.x 의
  새 권장 모델 `pyannote/speaker-diarization-community-1` (VBx clustering)
  은 `PYANNOTE_DIARIZATION_MODEL` 환경변수로 선택 가능.

## [0.6.0.12] - 2026-04-17

### Fixed
- **pyannote.audio ↔ 신버전 torchaudio 호환성** (`requirements-mac.txt`,
  `gurunote/stt_mlx.py`) — 화자 분리 단계에서
  `AttributeError: module 'torchaudio' has no attribute 'AudioMetaData'`
  에러가 나고 단일 화자(A) 로 fallback 되던 문제. torchaudio 2.8+ 에서
  `AudioMetaData` 가 제거되면서 pyannote.audio 3.x 의 audio I/O 경로가
  깨졌다. pyannote.audio **4.0.0** 이 이미 `torchaudio` → `torchcodec`
  마이그레이션으로 해결한 상태였으나, 본 프로젝트의 `requirements-mac.txt`
  가 `<4` 로 상한을 걸어 사용자가 fix 를 받지 못함. 상한을 `<5` 로 완화해
  기본 설치가 최신 4.x 를 가져오도록 수정.
- **`stt_mlx.py` 에 AudioMetaData 전용 에러 메시지** — 업그레이드 명령
  (`.venv/bin/pip install --upgrade 'pyannote.audio>=4.0'`) 을 포함한
  구체적 안내가 GUI 로그에 표시되도록 분기 추가. 이미 설치된 기존 사용자가
  setup 을 재실행하지 않아도 에러 메시지만 보고 바로 해결 가능.

### 기존 사용자 즉시 업그레이드
```bash
cd ~/GuruNote
.venv/bin/pip install --upgrade 'pyannote.audio>=4.0'
bash run_desktop.sh
```

## [0.6.0.11] - 2026-04-17

> "지식 증류기" 로드맵 **Phase F — 저장된 노트 검색** (키워드 단계).
> 의미(임베딩) 검색은 추후 phase.

### Added
- **`gurunote/search.py` 신규** — `match_body(job_id, query)` 가 저장된
  `result.md` 본문 (frontmatter 제외) 에서 query 의 첫 매칭 위치를 찾아
  ±80자 스니펫을 반환. `functools.lru_cache(maxsize=128)` 로 본문을 지연
  로드 + 캐시해 재검색 시 I/O 반복을 피함. `clear_cache()` 는 삭제/리프레시
  시 호출해 stale 캐시 무효화. Case-insensitive 매칭, 빈 query 는 None 가드.
- **HistoryDialog 에 "📄 본문 포함" 토글** (`gui.py`) — 검색창 옆
  체크박스. 꺼져 있으면 기존처럼 제목/업로더/태그/분야 만 매칭 (빠름).
  켜지면 메타 불일치 잡도 본문에서 찾아보고, 매칭된 카드에는 `🔍 ±80자
  스니펫` 미리보기를 italic 으로 표시. 본문 로드는 on-demand + LRU 캐시.
- **`_reload_and_refresh` 가 본문 캐시 클리어** — 삭제/새 작업 반영 시 stale
  스니펫 방지.

## [0.6.0.10] - 2026-04-17

> "지식 증류기" 로드맵 **Phase E — Notion API 연동**.
>
> Phase D (Obsidian vault, 로컬) 에 이어 Notion workspace (클라우드) 로도
> 결과 마크다운을 바로 전송할 수 있게 한다.

### Added
- **`gurunote/notion_sync.py` 신규** — `save_to_notion()` 이 Notion
  Integration Token 과 parent database/page ID 를 받아 공식 `notion-client`
  SDK 로 페이지를 생성. 주요 기능:
  - **Markdown → Notion blocks 변환기** (내장, 의존성 없음) — heading_1/2/3,
    paragraph, bulleted/numbered_list_item, quote, code (language 지원),
    divider. Inline `**bold**` / `*italic*` / `` `code` `` 도 Notion rich_text
    annotations 로 매핑. Table 은 v0.6.0.10 에선 paragraph 로 polyfill.
  - **Frontmatter → DB properties 매핑** (parent 가 database 일 때) —
    title / Field (select) / Tags (multi_select) / Uploader (rich_text) /
    Upload Date (date) / Source (url). DB 스키마에 해당 property 가 없으면
    Notion API 가 400 으로 거부하므로 사용자가 스키마를 미리 맞춰야 함.
  - Notion 의 "한 번에 100 블록" 제한 자동 핸들링 — 초과분은
    `blocks.children.append` 로 이어 붙임.
- **`requirements-notion.txt` 신설 (선택 설치)** — `notion-client>=2.0`.
  Integration 생성 + target 공유 가이드 헤더 코멘트 포함.
- **Settings 다이얼로그 필드 3개 추가** — `NOTION_TOKEN` (secret, 마스킹),
  `NOTION_PARENT_ID` (UUID), `NOTION_PARENT_TYPE` (database/page).
- **GUI 버튼 추가** —
  - 결과 카드: Save .md / Save PDF / → Obsidian 옆에 **→ Notion** 버튼
  - HistoryDialog 카드: `.md` / `PDF` / `Obs` / **Ntn** / `Log` / `Del`
    (6개 버튼, 너비 34px 로 재조정). Notion 버튼은 primary color 강조.
  - 성공 시 생성된 Notion URL 을 다이얼로그에 표시 + "브라우저에서 열까요?"
    확인 후 `webbrowser.open`.
  - 실패 시 (401 Unauthorized / 404 parent not shared / 스키마 불일치)
    구체적 에러 메시지 노출.

## [0.6.0.9] - 2026-04-17

> 다른 채널 PR #73 의 Windows PowerShell 5.1 호환 + 선행 조건 docs 를
> salvage 해 현재 main 위에 적용 (원 PR 은 0.6.0.7 로 bump 했으나 Phase
> C/D 와 충돌해 머지 불가).


### Added
- **README 선행 조건(Prerequisites) 섹션** (`README.md`) — `setup.sh` /
  `setup.bat` 실행 전에 OS 에 설치돼 있어야 하는 3가지 도구 (Git, Python 3.10+,
  ffmpeg) 를 Windows / macOS / Linux 별 설치 명령 + 공식 다운로드 링크와 함께
  표로 제공. 신규 Windows PC 에서 README 첫 단계인 `git clone` 자체가
  `'git' 용어가 인식되지 않습니다` 로 실패하던 상황을 예방.
- **FAQ 신규 3항목** (`README.md`) —
  - `'git' 용어가 ... 인식되지 않습니다` (Windows Git 미설치)
  - `'&&' 토큰은 이 버전에서 올바른 문 구분 기호가 아닙니다`
    (PowerShell 5.1 의 `&&` 미지원 — 명령 분리 또는 PowerShell 7+ 안내)
  - `python: command not found` (Python 미설치 / PATH 누락)

### Changed
- **빠른 시작 3단계의 `git clone && cd` 분리** (`README.md`) — Windows PowerShell
  5.1 은 유닉스식 `&&` 를 파서 에러로 거부하므로 `git clone ...` 과 `cd GuruNote`
  를 별도 줄로 분리. 단계 번호도 1→2 분리로 재조정 (clone / setup / API 키 /
  실행 4단계). `.env.example` 복사는 PowerShell 용 `Copy-Item` 대안도 명시.
- **요구사항 섹션 설치 링크 보강** (`README.md`) — Git (git-scm.com),
  Python (python.org), ffmpeg (ffmpeg.org) 공식 링크와 winget ID 명시
  (`Git.Git`, `Python.Python.3.12`, `Gyan.FFmpeg`).
## [0.6.0.8] - 2026-04-17

> "지식 증류기" 로드맵 **Phase D — Obsidian vault 연동**.
>
> Phase A 의 YAML frontmatter 가 이미 Obsidian 호환 형식이라, 파일만 vault
> 폴더에 두면 Obsidian 이 즉시 인식해 태그 검색/Dataview 쿼리가 가능하다.
> 이 PR 은 "수동으로 vault 에 복사" 단계를 GUI 버튼 한 번으로 자동화.

### Added
- **`gurunote/obsidian.py` 신규** — `save_to_vault()` 가 지정된 vault 하위
  폴더에 결과 마크다운을 저장. 주요 기능:
  - `is_obsidian_vault(path)` — `.obsidian/` 하위 디렉토리 존재로 유효한
    vault 인지 판별
  - `resolve_vault_path()` / `resolve_subfolder()` — `OBSIDIAN_VAULT_PATH`
    (`~` 확장 + 심볼릭 링크 해결) / `OBSIDIAN_SUBFOLDER` (기본 `"GuruNote"`)
    환경변수 읽기
  - 파일명 충돌 시 `_YYYYMMDD_HHMMSS` 접미사 자동 부여
  - Path traversal 방지 — filename / subfolder 에 `..`, `/`, `\` 금지
- **Settings 다이얼로그 필드 2개 추가** (`gui.py`) —
  `OBSIDIAN_VAULT_PATH`, `OBSIDIAN_SUBFOLDER`. 다른 설정과 동일하게 `.env`
  에 저장.
- **GUI 버튼 추가** —
  - 결과 카드: Save .md / Save PDF 옆에 `→ Obsidian` 버튼
  - HistoryDialog 카드: `.md` / `PDF` / **Obs** / `Log` / `Del` (5개 버튼,
    너비 38px 로 재조정)
  - 버튼 클릭 시 `OBSIDIAN_VAULT_PATH` 미설정이면 Settings 열도록 안내,
    `.obsidian/` 폴더가 없으면 "그래도 저장할까요?" 확인 대화상자 표시.

## [0.6.0.7] - 2026-04-17

> "지식 증류기" 로드맵 **Phase C — 깔끔한 PDF 출력**.

### Added
- **결과 마크다운 → 렌더링된 PDF 변환** (`gurunote/pdf_export.py` 신규,
  `requirements-pdf.txt` 신규) — `markdown` (pure Python) 으로 MD → HTML,
  `weasyprint` 로 HTML → PDF. YAML frontmatter 를 자체 파서로 추출해 PDF 첫
  페이지 메타 테이블 (업로더/게시일/원본 URL/분야/STT 엔진/태그 pill) 로
  렌더링. 본문은 A4 페이지에 한국어 친화 폰트 스택 (Noto Sans KR → Apple SD
  Gothic Neo → 맑은 고딕 → Pretendard → system-ui) 으로 출력. 페이지 하단
  `N / M` 페이지 번호, 블록쿼트/코드블록/테이블/수평선 스타일 포함.
- **GUI "Save PDF" 버튼** (`gui.py`) — 결과 카드 우상단에 `.md` 옆에 추가,
  HistoryDialog 의 각 카드에도 `.md` / **PDF** 버튼 병치. weasyprint 미설치
  시 OS 별 시스템 의존성 (macOS: `brew install cairo pango gdk-pixbuf libffi`
  / Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0`) + `pip install
  -r requirements-pdf.txt` 명령을 담은 친절한 안내 다이얼로그 표시.
- **선택 설치 의존성 분리** — `requirements-pdf.txt` 신설. 기본 `.md` 저장은
  이 패키지 없이도 동작하므로 PDF 가 필요한 사용자만 설치.

### Fixed
- **Settings 연결 테스트에서 Gemini 분기 누락** (`gui.py::_on_test_connection`)
  — 이전에는 `anthropic` 외의 모든 provider 가 `else` 분기로 빠져 OPENAI_*
  키를 사용했기 때문에 `gemini` 를 선택한 사용자의 "Test" 버튼이 항상 실패.
  `elif provider == "gemini"` 분기 추가 (`GOOGLE_API_KEY` + `GEMINI_MODEL`).
  PR #65 에서 도입된 드롭다운 선택지가 실제 동작과 정합되도록 수정.

## [0.6.0.6] - 2026-04-17

> "지식 증류기" 로드맵 **Phase B — History 일괄 뷰**.
> Phase A 에서 저장한 분류 메타데이터(제목/분야/태그) 를 실제 UI 에서 활용.

### Added
- **History 카드 그리드 뷰** (`gui.py::HistoryDialog`) — 기존 단순 세로 리스트
  를 3열 카드 그리드로 재구성. 각 카드는 YouTube 썸네일 (mqdefault 320x180) +
  정리된 제목 + 업로더/게시일 + 길이/엔진/화자수 + 분야 + 태그 + 상태/에러를
  한눈에 보여준다. 카드 하단에 Save .md / Log / Del 액션 버튼.
- **필터 바** — 검색창 (제목/업로더/태그 실시간 fuzzy), 분야 드롭다운
  (히스토리의 실제 분야 목록에서 자동 생성), 정렬 드롭다운 (최신순 / 오래된순 /
  길이 긴 순 / 길이 짧은 순 / 제목 A-Z), 필터 초기화 버튼. 필터 상태는
  다이얼로그가 살아있는 동안 유지.
- **YouTube 썸네일 캐시** (`gurunote/thumbnails.py` 신규) — 표준 YouTube URL
  패턴 5종 (watch?v= / youtu.be/ / embed/ / v/ / shorts/) 에서 11자리 비디오
  ID 추출. `~/.gurunote/thumbnails/<id>.jpg` 에 1회만 다운로드 후 캐시.
  `download_thumbnail_async()` 로 첫 그리드 렌더링을 차단하지 않음 —
  플레이스홀더 (⏳) 표시 후 완료 시 메인 스레드 `after()` 폴링으로 교체.
  YouTube 가 "영상 없음" placeholder 를 반환하는 경우 (&lt; 2KB) 를 실패로 간주.
- **썸네일 폴백 아이콘** — 로컬 파일 소스는 🎵, URL 없음 / YouTube 아님은 🎙️,
  다운로드 실패는 🎬 로 시각적으로 구분.

## [0.6.0.5] - 2026-04-17

### Added
- **GUI 실시간 백엔드 진행률** (`gurunote/progress_tee.py` 신규, `gui.py`,
  `app.py`) — HuggingFace 모델 다운로드 / mlx-whisper / whisperx 의 tqdm
  진행률이 이전에는 CLI stderr 에만 찍혀 GUI 로그 패널에서는 보이지 않았다.
  새 `install_tee()` 컨텍스트 매니저가 파이프라인 실행 동안 `sys.stderr` 를
  tee 로 감싸 원본에는 그대로 쓰면서, 한 줄 단위로 파싱해 압축된 요약을
  GUI 로그 콜백에 전달한다.

  감지 + 압축 패턴:
  - `39%|...| 239370/619235 [05:14<09:37, 657.42frames/s]`
    → `[STT] 39% (239370/619235) · 05:14 경과 · ~09:37 남음 · 657.42 frames/s`
  - `Fetching 4 files: 100%|...| 4/4 [00:44<00:00, 11.06s/it]`
    → `[모델] Fetching 4 files — 4/4 (100%) · 남음 ~00:00`
  - `Download complete: : 3.08GB [00:44, 255MB/s]`
    → `[모델] 다운로드 완료 (3.08GB, 00:44 · 255 MB/s)`
  - `Detected language: English` → `[언어] English 감지`
  - HF 토큰 미설정 경고는 1회만 표시 (중복 억제)
  - ANSI 컬러 escape 제거, 500ms 스로틀링으로 GUI 로그 flood 방지

  **Streamlit(`app.py`) 에는 적용하지 않음** — `st.empty()` 등 Streamlit
  위젯은 `ScriptRunContext` 가 바인딩된 메인 스레드에서만 안전하게 업데이트
  가능하고, 백엔드 워커(mlx-whisper, whisperx)가 stderr 로 tqdm 을 찍는
  스레드에서 위젯 업데이트 콜백이 호출되면 `MissingScriptRunContext` 경고가
  발생하며 최악의 경우 경고 메시지 자체가 tee 로 재유입되는 재귀 위험이
  있어서. Streamlit 은 Step 완료마다 `st.write` 로 표시되므로 실용상 충분.
  데스크톱 GUI 에만 tee 적용.

  **방어적 restore** — `install_tee` 종료 시 `sys.stderr is tee_err` 인 경우
  에만 원본 복원해서, nested 컨텍스트 엣지케이스에서 stderr 가 영구 오염되는
  footgun 방지.

## [0.6.0.4] - 2026-04-17

### Fixed
- **메타 추출 품질 이슈 2건** (`gurunote/llm.py`) — PR #68 코드 리뷰 후속:
  - `_parse_metadata_json` 의 태그 필터를 `isinstance(t, str)` 기반으로 강화.
    이전: `str(t).strip()` 이 `None`/`{}` 등을 `"None"`/`"{}"` 문자열로 저장해
    쓰레기 태그가 영속화될 가능성. 이후: 문자열만 통과, 나머지 드롭.
    `organized_title` / `field` 도 동일하게 `isinstance(str)` 가드 추가.
  - `extract_metadata` 의 하드코딩된 `max_tokens=512` 를 `max(1024,
    config.summary_max_tokens // 4)` 로 변경. 긴 한국어 제목/태그 조합에서
    응답이 잘려 빈 결과가 반환되는 경우 방지.

## [0.6.0.3] - 2026-04-17

> "지식 증류기" 로드맵 **Phase A — 메타데이터 자동 추출**.
> 이후 Phase B (History 일괄 뷰) / C (PDF 출력) / D (Obsidian) / E (Notion) /
> F (검색) 의 기반.

### Added
- **분류용 메타데이터 자동 추출** (`gurunote/llm.py::extract_metadata`) —
  파이프라인에 새 Step 4.5 단계 삽입. 번역된 한국어 스크립트 + YouTube 메타
  (제목/업로더/태그) 를 LLM 으로 보내 다음 3개를 JSON 으로 추출:
  - `organized_title` — 사람이 보기 쉬운 한국어 제목 (60자 이내, [화자]: [핵심 주제] 패턴)
  - `field` — 분야 분류 (예: "AI/ML", "AI 하드웨어", "스타트업", "철학")
  - `tags` — 정확히 5개 키워드 (YouTube 원본 태그 우선 활용 + 본문 보완)
  실패 시 빈 dict 반환하여 파이프라인 진행 방해 안 함. JSON 파싱은 코드블록
  래핑 / 앞뒤 텍스트 모두 허용.
- **`gurunote/history.py::save_job` 스키마 확장** — `organized_title`, `field`,
  `tags`, `uploader`, `upload_date` 5개 필드 추가. `~/.gurunote/history.json`
  인덱스에 누적되어 향후 Phase B (필터/검색) 에서 활용.
- **Obsidian / Notion 호환 YAML frontmatter** (`gurunote/exporter.py`) —
  결과 마크다운 최상단에 frontmatter 자동 삽입:
  - `title`, `original_title`, `uploader`, `upload_date`, `source_url`
  - `field`, `tags` (Obsidian 태그 시스템 호환 — 공백→`_`, `#` prefix 제거)
  - `stt_engine`, `duration_sec`, `num_speakers`, `created`
  Obsidian vault 또는 Notion import 에 그대로 사용 가능.
- **마크다운 헤더 강화** (`gurunote/exporter.py`) — 제목을 `organized_title`
  로 표시, 원본 제목과 다르면 `원본 제목:` 라인 추가, `분야:` / `태그:` (인라인
  `#tag` 표시) 항목 표시.

### Changed
- **파이프라인 진행률 재배분** (`gui.py`, `app.py`) — Step 4 88% → Step 4.5
  92% → Step 5 100% 로 새 단계 반영.

## [0.6.0.2] - 2026-04-17

### Fixed
- **macOS 입력창에서 Cmd+C/V/X/A 미동작** (`gui.py`) — macOS 의 CTkEntry /
  CTkTextbox 에서 `Cmd+V` 로 붙여넣기가 되지 않던 문제 (Settings, 오디오 URL
  입력 등 모든 입력창). Tkinter 기본 바인딩이 Linux/Windows 의 `Ctrl+V` 는
  `<<Paste>>` 가상 이벤트로 매핑하지만 일부 Tcl/Tk 빌드에서 macOS 의 `Command`
  키 누락. 루트 윈도우에 `_install_clipboard_shortcuts()` 를 통해 `bind_all`
  로 `<Command-c/v/x/a>` (대소문자 모두) 를 명시 바인딩 → 포커스된 위젯에
  `<<Copy>>` / `<<Paste>>` / `<<Cut>>` / `<<SelectAll>>` 가상 이벤트를
  전파하도록 수정. `Toplevel` (SettingsDialog, HistoryDialog 등) 도 같은
  Tk 인터프리터를 공유하므로 한 번의 `bind_all` 로 전역 적용.
  Linux/Windows 는 no-op (기본 바인딩이 이미 Ctrl+V 처리).

## [0.6.0.1] - 2026-04-17

> v0.6.0 이후 머지된 UX/버그 수정 PR (#59~#66) 을 REVISION 단위로 묶은 릴리스.
> 앱 내장 업데이트 체크가 이 변경들을 감지할 수 있도록 `X.Y.Z.W` 4자리 버전
> 정책을 신규 도입 (`CLAUDE.md`). 이후 모든 코드 변경 PR 은 REVISION (`W`) 자리를
> +1 로 올린다.

### Added
- **4자리 버전 정책 `MAJOR.MINOR.PATCH.REVISION`** (`CLAUDE.md`) — 모든 코드
  변경 PR 마다 REVISION (`W`) 자리를 +1. `gurunote/updater.py` 의 업데이트 체크
  (`local == remote` 문자열 비교) 가 매 PR 의 변경을 감지 가능하도록 하는 목적.
  PEP 440 `N.N.N.N` 호환. 상위 자리 변경 시 하위는 0 리셋.
- **하드웨어 프리셋 자동 감지** (`gurunote/hardware.py` 신규) —
  NVIDIA GPU VRAM (`torch.cuda.get_device_properties`) 와 Apple Silicon
  Unified Memory (`sysctl hw.memsize`) 를 감지해 8개 프리셋 중 가장 적합한
  것을 추천 (NVIDIA 24/12/8/6GB · Apple Silicon Ultra/Pro-Max/base · Cloud only).
  각 프리셋이 WhisperX 모델/배치 크기, MLX 모델, LLM Temperature, 번역/요약
  Max Tokens 를 권장값으로 묶어 제공.
- **Settings 다이얼로그 하드웨어 프리셋 드롭다운** (`gui.py`) — 상단에 "하드웨어
  프리셋" 드롭다운 추가. 선택 시 STT/LLM 필드 일괄 자동 채움. "자동 감지 (권장)"
  또는 "직접 입력 (custom)" 옵션 지원. 현재 환경 감지 결과를 드롭다운 옆
  라벨에 표시 (예: "Apple Silicon 감지됨 (Unified Memory ~128GB)"). 개별 필드는
  드롭다운 이후에도 수동 override 가능.
- **MLX Whisper 모델 설정 필드** (`gui.py`) — Apple Silicon 사용자를 위한
  `MLX_WHISPER_MODEL` 환경변수를 Settings 다이얼로그에 추가. 기본값
  `mlx-community/whisper-large-v3-mlx`.
- **실행 래퍼 스크립트** — `run_desktop.sh` / `run_web.sh` (macOS/Linux) +
  `run_desktop.bat` / `run_web.bat` (Windows). `.venv` 를 activate 없이 직접
  호출해 macOS 의 `command not found: python` / `streamlit` 문제를 근본 차단.
  `.venv` 미존재 시 친절한 에러 메시지로 `setup.sh` 실행 안내. setup.sh/bat
  의 최종 메시지도 래퍼 스크립트를 1순위로 안내하도록 갱신.
- **README "🗑️ 제거" 섹션** — 프로젝트 폴더 / `~/.gurunote/` / HuggingFace
  모델 캐시의 OS 별 삭제 명령과 경로별 용량 요약. `.env` API 키 백업/폐기
  보안 안내, 공유 HuggingFace 캐시 조심 경고, 임시 파일 정책 설명 포함.
- **README Troubleshooting FAQ** — macOS 에서 `python` / `streamlit` 명령을
  찾지 못하는 상황과 해결법 명시. "▶️ 실행" 섹션에 래퍼 스크립트 + venv
  activate 대안을 모두 제시.

### Changed
- **Settings 다이얼로그 LLM Provider 드롭다운화** (`gui.py`) — 이전엔 자유
  텍스트 입력이었던 "LLM Provider" 를 CTkOptionMenu 로 변경해 오타/오설정을
  방지. 선택지: `openai` / `anthropic` / `gemini` / `openai_compatible`.
  `_entries` 딕셔너리가 CTkEntry 와 CTkOptionMenu(StringVar) 를 혼재하여 보관
  하도록 타입 확장 (`.get()` 인터페이스 통일).
- **데스크톱 배포 패키지 OS별 분리 + CI 의존성 정합성 수정**
  (`.github/workflows/release-desktop.yml`, `scripts/package_desktop.py`,
  `README.md`) — Release 아티팩트 이름에 플랫폼 suffix 추가
  (`GuruNote-Windows.exe`, `GuruNote-Windows-Installer.exe`,
  `GuruNote-macOS.dmg`, `GuruNote-macOS.pkg`). CI 의 hardcoded pip 리스트를
  `pip install -r requirements.txt` 로 교체해 v0.5.0 추가된 `google-genai`
  누락 문제 해결 (Gemini 선택 시 ImportError 방지). README 에 "데스크톱 패키지
  vs 소스 실행" 비교 표 추가 — 번들 패키지는 UI + 클라우드 STT(AssemblyAI)
  전용, 로컬 GPU STT(WhisperX/MLX) 가 필요하면 소스 실행 안내.

### Fixed
- **ffmpeg/ffprobe 누락 감지 + 친절한 에러** (`gurunote/audio.py`,
  `setup.sh`, `setup.bat`) — yt-dlp 오디오 추출에 ffmpeg 가 필요하지만 macOS 기본
  환경엔 없어 Step 1 에서 `ERROR: Postprocessing: ffprobe and ffmpeg not found`
  (ANSI 컬러 escape 포함) 로 파이프라인이 실패. 새 `ensure_ffmpeg_available()`
  pre-flight 가 `download_audio()` / `extract_audio_from_file()` 시작부에서
  `shutil.which` 로 감지 → 누락 시 OS 별 설치 명령 (`brew install ffmpeg` /
  `winget install ffmpeg` / `apt install ffmpeg`) 을 포함한 한국어 RuntimeError
  발생. setup.sh / setup.bat 에도 같은 감지 단계(`[0/4]`)를 추가해 setup 단계에서
  자동 설치 제안(brew/winget 감지 시) 또는 명확한 실패 메시지 출력.
- **Apple Silicon 세대 표기 M5 반영** — README / `requirements-mac.txt` / `stt.py`
  / `stt_mlx.py` 의 "M1/M2/M3/M4", "M1~M4" 표기 9곳을 M5 포함으로 갱신. 실제
  코드는 `platform.machine() == "arm64"` 로 세대 무관 동작하나 문서 표기는
  최신 세대 반영이 맞음.
- **README "🚀 설치" 모순 제거** — "빠른 시작" 은 `bash setup.sh` 바로 실행을
  안내하는데 "🚀 설치" 는 `python -m venv .venv && source .venv/bin/activate`
  수동 단계를 추가로 요구해 모순됐고, macOS 의 `python` 명령 부재로 이 수동
  단계가 실제로 실패하는 원인이 됨. setup.sh 가 이미 `.venv` 를 자체 생성하므로
  "🚀 설치" 섹션에서 수동 venv 단계를 제거하고, 대신 setup 스크립트가 자동
  수행하는 5단계 (venv 생성 → 플랫폼 감지 → 공통 의존성 → 플랫폼별 STT → 검증)
  를 명시적으로 문서화.
- **업데이트 다이얼로그 NameError** (`gui.py`) — `SettingsDialog._on_update` 가
  import 되지 않은 `check_updates(...)` 를 호출해 NameError 발생. 다른 위치
  (`_on_update_sb`) 와 동일하게 `check_for_update()` 호출 후 `info["message"]`
  사용하도록 수정. 사이드바 ⚙️ 설정 다이얼로그에서 "업데이트 확인" 버튼이 정상
  동작.
- **README VibeVoice 잔재 정리** — STT 섹션, 파이프라인 다이어그램, 60분 제한
  안내, GPU/VRAM 요구사항 표, 환경변수 예시, 사용 흐름, 최초 실행 안내, 프로젝트
  구조, FAQ 4개 항목 등 ~15곳을 현재 코드 (WhisperX + MLX + AssemblyAI 라우터)
  와 일치시킴. v0.4.x 의 WhisperX 전환 + v0.6.0 의 MLX 추가가 README 에 누락돼
  있던 부분을 일괄 갱신.

## [0.6.0] - 2026-04-16

### Added
- **macOS Apple Silicon 로컬 GPU STT** (`gurunote/stt_mlx.py`) — `mlx-whisper` 로
  Whisper 추론을 Apple GPU/Neural Engine 에서 native 실행, `pyannote.audio` 화자
  분리를 MPS 디바이스에서 수행. 단어 레벨 타임스탬프, IT/AI 핫워드 `initial_prompt`
  주입, SPEAKER_NN→A/B/C 오버랩 기반 화자 할당. `engine="mlx"` 로 명시 선택 또는
  `auto` 라우팅에서 자동 선택. `HUGGINGFACE_TOKEN` 미설정 시 단일 화자(A) 폴백.
  `MLX_WHISPER_MODEL` / `PYANNOTE_DIARIZATION_MODEL` 환경변수로 모델 오버라이드.
- **STT `auto` 라우팅 확장** (`gurunote/stt.py`) — 우선순위:
  CUDA WhisperX → Apple Silicon MLX → AssemblyAI Cloud. Apple Silicon 인데
  mlx-whisper 미설치 시 안내 메시지 (`pip install -r requirements-mac.txt`).
- **GUI / Streamlit STT 엔진 선택지에 `mlx` 추가** (`gui.py`, `app.py`) —
  드롭다운에 노출, help 텍스트 갱신. macOS arm64 + `auto` 또는 `mlx` 선택 시
  WhisperX 설치 강요 다이얼로그 우회.
- **플랫폼별 의존성 분리** — `requirements.txt` 는 공통 의존성만 유지,
  `requirements-mac.txt` (mlx-whisper, pyannote.audio, onnxruntime) 와
  `requirements-gpu.txt` (whisperx) 신설. `setup.sh` 가 `uname -s/-m` 으로
  Darwin arm64 를 감지해 MLX 스택을 자동 설치, `setup.bat` 는 NVIDIA 감지 시에만
  `requirements-gpu.txt` 추가 설치. 검증 단계가 MPS 가용성도 함께 출력.
- **README** — 빠른 시작에 `bash setup.sh` 안내, Apple Silicon FAQ 항목,
  기술 스택 표에 mlx-whisper + pyannote.audio 명시.

## [0.5.0] - 2026-04-16

### Added
- **Google Gemini API 지원** (`gurunote/llm.py`) — `LLM_PROVIDER=gemini` 으로
  Google Gemini 모델 사용 가능. `GOOGLE_API_KEY`, `GEMINI_MODEL` 환경변수 추가.
  `google-genai>=1.0` 의존성 추가. GUI/Streamlit Settings 에 Gemini 옵션 반영.

### Fixed
- **업데이트 체크 원격 버전 감지 실패 수정** (`gurunote/updater.py`) — remote 이름과
  기본 브랜치를 자동 감지(`_detect_remote_and_branch`)하여 `origin/main` 이 아닌
  환경에서도 동작. `git ls-remote` 폴백 추가. 실패 시 네트워크/remote 설정 안내 메시지.

## [0.4.1] - 2026-04-16

### Fixed
- WhisperX `DiarizationPipeline` API 변경 대응 (v3.8.5+: `whisperx.diarize.DiarizationPipeline`)
- AssemblyAI `speech_model` → `speech_models` (복수형 리스트) API 변경
- Windows symlink 없이 모델 다운로드 (`~/.gurunote/models/`)
- WhisperX `initial_prompt` → `load_model(asr_options=)` 로 이동
- setup.bat CUDA torch 버전 핀 (`torch==2.8.0+cu128`, whisperx 호환)
- GPU 미감지 시 CPU whisperx 거부 → AssemblyAI 직행
- 경고 억제 확대 (torchcodec, pyannote, huggingface_hub)

### Added
- 버전 비교 기반 업데이트 체크 (local vs remote `__version__` 비교)
- 업데이트 진행 다이얼로그 (백그라운드 스레드 + 실시간 로그)
- Semantic Versioning 정책 (`CLAUDE.md`)

### Changed
- STT 엔진: VibeVoice-ASR → **WhisperX** (Distil-Whisper + pyannote)
- setup.bat/sh: CUDA torch 먼저 설치 → whisperx "already satisfied"

## [0.4.0] - 2026-04-16

### Added
- **작업 히스토리** (`gurunote/history.py`) — 완료/실패 작업이 `~/.gurunote/jobs/`
  에 자동 저장. 마크다운 재다운로드, 파이프라인 로그 확인, 에러 진단 가능.
  데스크톱 History 다이얼로그 + Streamlit 히스토리 탭.
- **영속 파이프라인 로그** — 모든 `_log()` 호출이 `pipeline.log` 파일에 타임스탬프와
  함께 기록되어 실패 원인을 사후 분석 가능.
- **로그 타임스탬프** — `[HH:MM:SS]` prefix 자동 추가.
- **진행 바 ETA** — 경과 시간 + 남은 예상 시간 계산 표시.
- **4-bit/8-bit 자동 양자화** — VRAM 기반 자동 선택 (48GB+→bf16, 24GB+→8bit,
  기타→4bit NF4). `VIBEVOICE_QUANTIZATION` 환경변수로 오버라이드 가능.
- **CUDA OOM 방어** — 토큰 축소 재시도 (32768→16384→8192), 실패 시 모델 자동
  언로드 + GPU 메모리 반환.
- **VibeVoice 미설치 안내** — 설치/AssemblyAI 전환 선택 다이얼로그.

### Changed
- **GUI 텍스트 라벨 정비** — 이모지 → 텍스트 (Windows 렌더링 호환), 사이드바
  브랜드 잘림 수정 (200→220px, 세로 배치).
- **Windows 경고 억제** — `expandable_segments` 미지원 경고 + 무해한 토크나이저/
  preprocessor 경고를 `warnings.filterwarnings` 로 억제.

## [0.2.0] - 2026-04-16

### Added
- **유튜브 메타데이터 컨텍스트 주입** (`gurunote/audio.py`, `llm.py`, `exporter.py`)
  - `yt-dlp` 호출 시 수동/자동 자막(VTT)까지 함께 다운로드
  - `AudioDownloadResult` 에 `upload_date`, `description`, `chapters`,
    `subtitles_text`, `subtitles_source`, `tags` 필드 추가
  - 설명에 챕터가 없어도 `"MM:SS 제목"` 패턴을 정규식으로 파싱해 자동 추출
  - 새 헬퍼 `build_video_context_block()` 가 영상 제목/채널/게시일/챕터/
    자막 발췌를 `"### 영상 컨텍스트"` 블록으로 조립해 LLM user 메시지에 주입
  - 번역/요약 시스템 프롬프트가 컨텍스트를 활용하도록 규칙 추가
    (화자 이름 추론, 공식 챕터를 타임라인 뼈대로 사용)
  - `build_gurunote_markdown()` 이 게시일을 헤더에, 챕터를 새 `⏱️ 원본
    영상 챕터` 섹션으로 렌더링
  - Streamlit / CustomTkinter UI 가 게시일·챕터·자막 감지 결과를 진행
    로그에 표시
- **로컬 LLM(OpenAI-compatible) 지원 강화** (`gurunote/llm.py`)
  - `LLM_PROVIDER=openai_compatible` 추가
  - `OPENAI_BASE_URL` 지원으로 로컬/사설 OpenAI-compatible 엔드포인트 사용 가능
  - Temperature / 번역·요약 Max Tokens 환경변수(`LLM_TEMPERATURE`,
    `LLM_TRANSLATION_MAX_TOKENS`, `LLM_SUMMARY_MAX_TOKENS`) 반영
- **앱 내 Settings UX 확장**
  - Streamlit: 별도 `⚙️ Settings` 탭 추가 (`app.py`)
  - Desktop GUI: 설정 다이얼로그에 LLM Provider, Base URL, 고급 옵션,
    연결 테스트 버튼 추가 (`gui.py`)
  - 저장 시 `.env` 자동 백업 + 즉시 적용 (`gurunote/settings.py`)
- **실행 진행률 UX 개선** (`app.py`, `gui.py`)
  - Streamlit 파이프라인 단계별 퍼센트 진행률 바 추가
  - Desktop GUI에 진행률 바(%) 및 `⏹ 중지` 버튼 추가
- **업데이트 UX 추가** (`gurunote/updater.py`, `scripts/update_gurunote.py`, `app.py`, `gui.py`)
  - 재설치 없이 `git pull + requirements 업그레이드`를 수행하는 업데이트 유틸 추가
  - Streamlit/GUI 설정 화면에 업데이트 확인·실행 버튼 추가
- **CustomTkinter 데스크톱 GUI** (`gui.py`) — 브라우저 없이 네이티브 창으로
  GuruNote 파이프라인(Step 1~5) 실행. 백그라운드 스레드 + Queue 기반 비동기
  처리로 UI 블로킹 없음. 탭뷰(요약/번역/원문), 실시간 로그 패널, 네이티브
  파일 저장 대화상자 제공. `pyinstaller --windowed --onefile gui.py` 로
  `.app` / `.exe` 패키징 가능.
- **GUI 설정 다이얼로그** — 헤더의 ⚙️ 버튼으로 모달 창 오픈. OpenAI /
  Anthropic / AssemblyAI API 키와 모델명을 앱 안에서 입력·저장. 비밀번호
  마스킹(•) + 👁 토글, `dotenv.set_key()` 로 `.env` 에 영속 + `os.environ`
  즉시 반영. 파이프라인 실행 전 API 키 미설정 시 설정 화면으로 안내.
- **로컬 동영상/오디오 파일 지원** — 유튜브 URL 외에 로컬 미디어 파일
  (mp4/mkv/avi/mov/webm + mp3/wav/flac/m4a 등 17종)을 직접 입력 소스로
  사용 가능. `extract_audio_from_file()` 이 ffmpeg subprocess 로 mp3 변환
  수행, ffprobe 로 정확한 길이 취득.
  - Streamlit: 탭 UI 로 "🔗 유튜브 URL" / "📁 로컬 파일" 전환 + `st.file_uploader`
  - CustomTkinter: 📁 버튼으로 OS 네이티브 파일 대화상자, 자동 모드 감지
- **데스크톱 배포 패키징 스크립트** (`scripts/package_desktop.py`)
  - Windows: `dist/GuruNote.exe` (단일 실행 파일) 생성 자동화
  - Windows(선택): Inno Setup(ISCC) 감지 시 `dist/GuruNote-Installer.exe` 생성
  - macOS: `dist/GuruNote.app` 생성 + 옵션으로 `dist/GuruNote.dmg` /
    `dist/GuruNote.pkg` 생성 자동화
- **GitHub Actions 릴리스 워크플로우** (`.github/workflows/release-desktop.yml`)
  - `v*` 태그 푸시 시 Windows/macOS 패키지를 CI에서 자동 빌드
  - 생성물(`.exe`, 설치형 `.exe`, `.dmg`, `.pkg`)을 GitHub Release assets로 자동 업로드
- **태그 릴리스 리허설 체크 스크립트** (`scripts/release_rehearsal_check.py`)
  - 태그 형식, 워크플로우 핵심 항목, 필수 파일, 패키징 스크립트 스모크 테스트를
    릴리스 전 자동 점검
  - 실패 시 즉시 원인 출력 + 종료 코드 1 반환 (fail-fast)

- **GUI 전면 리디자인** (`gui.py`) — Clova Note 등 SaaS 도구를 참고.
  좌측 사이드바(브랜드 로고 + 설정/업데이트 네비게이션) + 메인 영역을
  입력 카드 → 진행 카드 → 결과 카드 3단 구조로 재편. 커스텀 브랜드 팔레트
  (네이비 `#1A1B2E`, 보라 CTA `#6C63FF`, 시안 진행바 `#22D3EE`), 5단계
  뱃지 인디케이터(dim→보라→초록), 로그를 결과 탭 안 📋 로그 탭으로 이동.

### Changed
- **LLM 기본 모델 최신화** — OpenAI `gpt-4o` → `gpt-5.4`, Anthropic
  `claude-3-5-sonnet-latest` → `claude-sonnet-4-6`. 코드 기본값(`llm.py` 의
  `openai`/`openai_compatible`/`anthropic` 3개 분기 모두), `.env.example`,
  Streamlit Settings 탭 placeholder, README, app.py 사이드바 텍스트 일괄 변경.
  기존 `.env` 에 `OPENAI_MODEL` / `ANTHROPIC_MODEL` 을 직접 설정한 사용자는
  영향 없음.
- **README 대폭 보강** — Gemini 리뷰 반영
  - GPU VRAM 요구사항 구체화 (최소 16GB VRAM / Apple Silicon 32GB+)
  - OS 별 ffmpeg 설치 명령어 (Mac/Windows/Ubuntu)
  - 60 분 초과 팟캐스트 Edge Case 처리 방식 안내 (v0.1.0 제한 및 AssemblyAI 대안)
  - 최초 실행 시 모델 다운로드 시간(14GB) 경고
  - Windows 설치형 exe / macOS dmg·pkg 배포 워크플로우 추가
  - 태그 기반 GitHub Actions 릴리스 자동화 안내 추가
  - 태그 릴리스 리허설 체크 스크립트 사용법 추가
- **긴 영상 STT 라우팅 보강** (`app.py`, `gui.py`) — 입력 오디오가 60분을
  넘고 STT 엔진이 `auto` 인 경우 AssemblyAI 로 자동 전환해 장편 콘텐츠의
  전사 누락 가능성을 기본 설정에서 완화.

### Fixed
- **LLM Rate Limit 방어** (`llm.py`) — `_call_llm` 에 지수 백오프(2s→4s→8s→16s)
  재시도 로직 추가, 청크 번역 사이 1초 쿨다운 삽입으로 분당 요청 제한 회피
- **VRAM 메모리 누수 방지** (`stt.py`) — VibeVoice 추론 완료 후 GPU 텐서 삭제
  (`del inputs, output_ids`) + `torch.cuda.empty_cache()` 호출
- **빈 전사 결과 조기 차단** (`stt.py`) — 세그먼트/텍스트가 비어 있으면 즉시
  예외를 발생시켜 후속 LLM 호출 낭비와 품질 저하를 방지.

## [0.1.0] - 2026-04-11

초판. Step 1~5 의 전체 파이프라인이 한 번의 버튼 클릭으로 동작합니다.

### Added
- **Step 1 — 오디오 추출** (`gurunote/audio.py`)
  - `yt-dlp` 로 유튜브 URL → mp3 다운로드
  - 영상 메타데이터(제목, 채널, 길이, URL) 수집
  - 임시 작업 폴더 자동 생성/정리 헬퍼
- **Step 2 — STT + 화자 분리** (`gurunote/stt.py`)
  - **Microsoft VibeVoice-ASR** (오픈소스, MIT) 을 기본 엔진으로 채택
  - 60 분 장편 오디오를 단일 패스로 처리, 화자/타임스탬프/내용 동시 추출
  - CUDA / MPS / CPU 자동 디바이스 감지, `flash_attention_2` 자동 활성화
  - 모델 싱글톤 lazy-load 로 연속 요청 시 재로딩 비용 제거
  - **IT/AI 도메인 핫워드 64 개** (Sam Altman, Lex Fridman, RLHF,
    Mixture of Experts 등) 를 VibeVoice 프로세서의 `context_info` 로 주입
  - VibeVoice 로딩 실패 시 **AssemblyAI Cloud API** 로 자동 폴백
  - 두 엔진 결과를 공통 `Transcript` 데이터클래스로 정규화
- **Step 3 — 한국어 번역** (`gurunote/llm.py`)
  - OpenAI (`gpt-4o`) / Anthropic (`claude-3-5-sonnet-latest`) 지원
  - "GuruNote 수석 에디터" 페르소나, 화자 실명 추론, 영문 병기, 구어체 정리
  - **청크 분할 번역** (`DEFAULT_CHUNK_CHAR_LIMIT=12_000`,
    `TRANSLATION_MAX_TOKENS=8192`) 으로 장편 영상 토큰 한도 초과 및 mid-script
    truncation 방지
  - 화자 라벨 + 타임스탬프 보존
- **Step 4 — GuruNote 스타일 요약본 생성** (`gurunote/llm.py`)
  - 📌 영상 제목 및 핵심 주제 요약 / 💡 Guru's Insights / ⏱️ 타임라인 구조 강제
  - 본문이 길 경우 부분 요약 → 통합 요약 2 단계 파이프라인
- **Step 5 — 마크다운 조립 + 내보내기** (`gurunote/exporter.py` · `app.py`)
  - 헤더(영상 메타) / 요약 / 전체 번역 / 영어 원문 섹션 조립
  - `GuruNote_<영상제목>.md` 다운로드 버튼
  - 작업 종료 후 임시 오디오 폴더 자동 정리
- **Streamlit UI** (`app.py`)
  - 헤더 `GuruNote 🎙️: 글로벌 IT/AI 구루들의 인사이트`
  - 사이드바에서 STT 엔진 (`auto` / `vibevoice` / `assemblyai`) 과 LLM provider
    (`openai` / `anthropic`) 를 런타임에 선택
  - `st.status` 로 단계별 진행 상황 스트리밍
  - 결과 탭: 📌 GuruNote 요약본 / 🇰🇷 전체 번역 스크립트 / 🇺🇸 영어 원문

### Fixed
- **VibeVoice 핫워드가 전달되지 않던 문제** — `transcribe()` 가 받은
  `hotwords` 인자를 VibeVoice 프로세서의 `context_info` 로 실제 주입하도록 수정.
  (이전에는 선언만 있고 실효 없음)
- **긴 청크에서 한국어 번역이 중간에 잘리던 문제** — 청크 입력 한도를
  24,000 → 12,000 chars 로 축소하고 `max_tokens` 을 4096 → 8192 로 확대.
- **Streamlit 동시 세션에서 LLM provider race condition** — 사이드바 선택을
  `os.environ` 에 쓰던 로직을 제거하고 `LLMConfig.from_env(provider=...)`
  override 로 request-local 하게 주입.

[Unreleased]: https://github.com/avlp12/GuruNote/compare/v1.0.0.32...HEAD
[1.0.0.32]: https://github.com/avlp12/GuruNote/compare/v1.0.0.31...v1.0.0.32
[1.0.0.31]: https://github.com/avlp12/GuruNote/compare/v1.0.0.30...v1.0.0.31
[1.0.0.30]: https://github.com/avlp12/GuruNote/compare/v1.0.0.29...v1.0.0.30
[1.0.0.29]: https://github.com/avlp12/GuruNote/compare/v1.0.0.28...v1.0.0.29
[1.0.0.28]: https://github.com/avlp12/GuruNote/compare/v1.0.0.27...v1.0.0.28
[1.0.0.27]: https://github.com/avlp12/GuruNote/compare/v1.0.0.26...v1.0.0.27
[1.0.0.26]: https://github.com/avlp12/GuruNote/compare/v1.0.0.25...v1.0.0.26
[1.0.0.25]: https://github.com/avlp12/GuruNote/compare/v1.0.0.24...v1.0.0.25
[1.0.0.24]: https://github.com/avlp12/GuruNote/compare/v1.0.0.23...v1.0.0.24
[1.0.0.23]: https://github.com/avlp12/GuruNote/compare/v1.0.0.22...v1.0.0.23
[1.0.0.22]: https://github.com/avlp12/GuruNote/compare/v1.0.0.21...v1.0.0.22
[1.0.0.21]: https://github.com/avlp12/GuruNote/compare/v1.0.0.20...v1.0.0.21
[1.0.0.20]: https://github.com/avlp12/GuruNote/compare/v1.0.0.19...v1.0.0.20
[1.0.0.19]: https://github.com/avlp12/GuruNote/compare/v1.0.0.18...v1.0.0.19
[1.0.0.18]: https://github.com/avlp12/GuruNote/compare/v1.0.0.17...v1.0.0.18
[1.0.0.17]: https://github.com/avlp12/GuruNote/compare/v1.0.0.16...v1.0.0.17
[1.0.0.16]: https://github.com/avlp12/GuruNote/compare/v1.0.0.15...v1.0.0.16
[1.0.0.15]: https://github.com/avlp12/GuruNote/compare/v1.0.0.14...v1.0.0.15
[1.0.0.14]: https://github.com/avlp12/GuruNote/compare/v1.0.0.13...v1.0.0.14
[1.0.0.13]: https://github.com/avlp12/GuruNote/compare/v1.0.0.12...v1.0.0.13
[1.0.0.12]: https://github.com/avlp12/GuruNote/compare/v1.0.0.11...v1.0.0.12
[1.0.0.11]: https://github.com/avlp12/GuruNote/compare/v1.0.0.10...v1.0.0.11
[1.0.0.10]: https://github.com/avlp12/GuruNote/compare/v1.0.0.9...v1.0.0.10
[1.0.0.9]: https://github.com/avlp12/GuruNote/compare/v1.0.0.8...v1.0.0.9
[1.0.0.8]: https://github.com/avlp12/GuruNote/compare/v1.0.0.7...v1.0.0.8
[1.0.0.7]: https://github.com/avlp12/GuruNote/compare/v1.0.0.6...v1.0.0.7
[1.0.0.6]: https://github.com/avlp12/GuruNote/compare/v1.0.0.5...v1.0.0.6
[1.0.0.5]: https://github.com/avlp12/GuruNote/compare/v1.0.0.4...v1.0.0.5
[1.0.0.4]: https://github.com/avlp12/GuruNote/compare/v1.0.0.3...v1.0.0.4
[1.0.0.3]: https://github.com/avlp12/GuruNote/compare/v1.0.0.2...v1.0.0.3
[1.0.0.2]: https://github.com/avlp12/GuruNote/compare/v1.0.0.1...v1.0.0.2
[1.0.0.1]: https://github.com/avlp12/GuruNote/compare/v1.0.0.0...v1.0.0.1
[1.0.0.0]: https://github.com/avlp12/GuruNote/compare/v0.8.0.6...v1.0.0.0
[0.8.0.6]: https://github.com/avlp12/GuruNote/compare/v0.8.0.5...v0.8.0.6
[0.8.0.5]: https://github.com/avlp12/GuruNote/compare/v0.8.0.4...v0.8.0.5
[0.8.0.4]: https://github.com/avlp12/GuruNote/compare/v0.8.0.3...v0.8.0.4
[0.8.0.3]: https://github.com/avlp12/GuruNote/compare/v0.8.0.2...v0.8.0.3
[0.8.0.2]: https://github.com/avlp12/GuruNote/compare/v0.8.0.1...v0.8.0.2
[0.8.0.1]: https://github.com/avlp12/GuruNote/compare/v0.8.0.0...v0.8.0.1
[0.8.0.0]: https://github.com/avlp12/GuruNote/compare/v0.7.2.5...v0.8.0.0
[0.7.2.5]: https://github.com/avlp12/GuruNote/compare/v0.7.2.4...v0.7.2.5
[0.7.2.4]: https://github.com/avlp12/GuruNote/compare/v0.7.2.3...v0.7.2.4
[0.7.2.3]: https://github.com/avlp12/GuruNote/compare/v0.7.2.2...v0.7.2.3
[0.7.2.2]: https://github.com/avlp12/GuruNote/compare/v0.7.2.1...v0.7.2.2
[0.7.2.1]: https://github.com/avlp12/GuruNote/compare/v0.7.2.0...v0.7.2.1
[0.7.2.0]: https://github.com/avlp12/GuruNote/compare/v0.7.1.1...v0.7.2.0
[0.7.1.1]: https://github.com/avlp12/GuruNote/compare/v0.7.1.0...v0.7.1.1
[0.7.1.0]: https://github.com/avlp12/GuruNote/compare/v0.7.0.5...v0.7.1.0
[0.7.0.5]: https://github.com/avlp12/GuruNote/compare/v0.7.0.4...v0.7.0.5
[0.7.0.4]: https://github.com/avlp12/GuruNote/compare/v0.7.0.3...v0.7.0.4
[0.7.0.3]: https://github.com/avlp12/GuruNote/compare/v0.7.0.2...v0.7.0.3
[0.7.0.2]: https://github.com/avlp12/GuruNote/compare/v0.7.0.1...v0.7.0.2
[0.7.0.1]: https://github.com/avlp12/GuruNote/compare/v0.7.0.0...v0.7.0.1
[0.7.0.0]: https://github.com/avlp12/GuruNote/compare/v0.6.0.19...v0.7.0.0
[0.6.0.19]: https://github.com/avlp12/GuruNote/compare/v0.6.0.18...v0.6.0.19
[0.6.0.18]: https://github.com/avlp12/GuruNote/compare/v0.6.0.17...v0.6.0.18
[0.6.0.17]: https://github.com/avlp12/GuruNote/compare/v0.6.0.16...v0.6.0.17
[0.6.0.16]: https://github.com/avlp12/GuruNote/compare/v0.6.0.15...v0.6.0.16
[0.6.0.15]: https://github.com/avlp12/GuruNote/compare/v0.6.0.14...v0.6.0.15
[0.6.0.14]: https://github.com/avlp12/GuruNote/compare/v0.6.0.13...v0.6.0.14
[0.6.0.13]: https://github.com/avlp12/GuruNote/compare/v0.6.0.12...v0.6.0.13
[0.6.0.12]: https://github.com/avlp12/GuruNote/compare/v0.6.0.11...v0.6.0.12
[0.6.0.11]: https://github.com/avlp12/GuruNote/compare/v0.6.0.10...v0.6.0.11
[0.6.0.10]: https://github.com/avlp12/GuruNote/compare/v0.6.0.9...v0.6.0.10
[0.6.0.9]: https://github.com/avlp12/GuruNote/compare/v0.6.0.8...v0.6.0.9
[0.6.0.8]: https://github.com/avlp12/GuruNote/compare/v0.6.0.7...v0.6.0.8
[0.6.0.7]: https://github.com/avlp12/GuruNote/compare/v0.6.0.6...v0.6.0.7
[0.6.0.6]: https://github.com/avlp12/GuruNote/compare/v0.6.0.5...v0.6.0.6
[0.6.0.5]: https://github.com/avlp12/GuruNote/compare/v0.6.0.4...v0.6.0.5
[0.6.0.4]: https://github.com/avlp12/GuruNote/compare/v0.6.0.3...v0.6.0.4
[0.6.0.3]: https://github.com/avlp12/GuruNote/compare/v0.6.0.2...v0.6.0.3
[0.6.0.2]: https://github.com/avlp12/GuruNote/compare/v0.6.0.1...v0.6.0.2
[0.6.0.1]: https://github.com/avlp12/GuruNote/compare/v0.6.0...v0.6.0.1
[0.6.0]: https://github.com/avlp12/GuruNote/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/avlp12/GuruNote/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/avlp12/GuruNote/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/avlp12/GuruNote/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/avlp12/GuruNote/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/avlp12/GuruNote/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/avlp12/GuruNote/releases/tag/v0.1.0

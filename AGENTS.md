# 코딩 에이전트 작업 규칙 (AGENTS.md)

이 파일은 Claude Code 를 포함한 모든 코딩 에이전트(opencode, Codex, Cursor 등)가
따르는 저장소 공용 규칙이다. [agents.md](https://agents.md) 표준을 따른다.

## 버전 정책 (Semantic Versioning + Revision)

[Semantic Versioning 2.0.0](https://semver.org/) 의 `MAJOR.MINOR.PATCH` 에
**REVISION** 자리를 추가한 `MAJOR.MINOR.PATCH.REVISION` 구조.

4자리 버전은 [PEP 440](https://peps.python.org/pep-0440/) 의 `N.N.N.N` 세그먼트
규칙과 호환되며, `packaging.version.Version` 으로 정상 파싱된다.

### 왜 REVISION 이 필요한가?

앱 내장 업데이트 체크(`gurunote/updater.py`)가 `__version__` 문자열 비교로
동작한다. MAJOR/MINOR/PATCH 만 쓰면 여러 코드 변경 PR 이 머지돼도 버전이 같아
"최신 버전입니다" 로 오판되는 문제가 있었다. REVISION 은 **모든 코드 변경 PR
마다 +1** 하여 업데이트 감지를 확실하게 한다.

### 언제 올리나?

| 변경 종류 | 버전 | 예시 |
|---|---|---|
| **REVISION** (0.6.0.**1**) | 모든 코드 변경 PR, 사소한 버그 수정, 경고 제거, 문서 정비 | ffmpeg pre-flight, README 문구 수정, hardware.py 프리셋 추가 |
| **PATCH** (0.6.**1**.0) | 2+ 개 누적 버그 수정의 릴리스, API 호환성 수정 | WhisperX diarize API 수정 묶음, AssemblyAI 파라미터 변경 |
| **MINOR** (0.**7**.0.0) | 새 기능 추가, UI 변경, 신규 모듈, 엔진 교체 | WhisperX 전환, GUI 리디자인, MLX STT 추가 |
| **MAJOR** (**1**.0.0.0) | 하위 호환성이 깨지는 변경, 대규모 아키텍처 변경 | 1.0.0 전까지는 MINOR 로 대체 |

상위 자리가 올라가면 하위 자리들은 **모두 0 으로 리셋**.
예: `0.6.0.5` + 새 기능 → `0.7.0.0`, `0.7.0.0` + REVISION → `0.7.0.1`.

### 판단 기준

- **REVISION 만 올리는 경우 (기본값, 거의 모든 PR):**
  - 코드 내부 리팩토링, 버그 수정, 문서 수정, CI/CD 설정, 의존성 pin
  - 사용자 체감이 크지 않아도 `__version__` 이 바뀌어 업데이트 감지 가능

- **PATCH 이상으로 올리는 경우:**
  - 2+ 개 누적 버그 수정을 한번에 묶을 때 → PATCH
  - 사용자가 즉시 체감할 새 기능 / UI → MINOR

- **버전을 전혀 올리지 않는 경우:**
  - `AGENTS.md` / `.github/` 워크플로우 단독 수정
  - 공백/포매팅만 변경 (내용 불변)
  - 이 경우에도 명시적 판단이 필요; 애매하면 REVISION 올림.

### 커밋 메시지 접두사

| 접두사 | 의미 | 버전 영향 (기본) |
|---|---|---|
| `feat:` | 새 기능 | MINOR (사용자 체감) 또는 REVISION |
| `fix:` | 버그 수정 | REVISION (1건) / PATCH (2건+ 묶음) |
| `docs:` | 문서만 | REVISION |
| `chore:` | 의존성, 빌드, 설정 | REVISION |
| `refactor:` | 리팩토링 (동작 불변) | REVISION |
| `style:` | UI/스타일 변경 | MINOR 또는 REVISION |

### 버전 업데이트 체크리스트

버전을 올릴 때 **반드시** 다음 5곳을 동시에 갱신:

1. `gurunote/__init__.py` → `__version__`
2. `gui.py` → 사이드바 버전 라벨 (CustomTkinter 진입점, v0.8 호환 유지)
3. `scripts/package_desktop.py` → Inno Setup + pkgbuild 버전
4. `gurunote/webui/components/SettingsScreen.jsx` → fallback 문자열 (`v{appInfo?.version || '...'}`) — bridge `get_app_info()` 실패 시에만 표시되지만 표기 일치 유지
5. `README.md` → "현재 버전" 문구
6. `CHANGELOG.md`:
   - `[Unreleased]` 내용을 `[X.Y.Z.W] - YYYY-MM-DD` 로 승격
   - 새 `[Unreleased]` 섹션 생성
   - 하단 비교 링크 갱신 (`[X.Y.Z.W]: .../compare/v<prev>...v<new>`)

> Inno Setup 과 `pkgbuild --version` 은 4자리 버전을 지원한다. Windows MSI
> 변환이 필요할 경우에만 `X.Y.Z` 로 축약하도록 별도 매핑을 고려.

## README 유지 규칙

- 새 기능이 추가되면 README 의 **주요 기능** / **FAQ** / **프로젝트 구조** 를 함께 갱신
- CLI 데모 로그 예시는 실제 출력 포맷과 일치하게 유지
- 이모지 사용 금지 (GUI 텍스트) — Windows 렌더링 호환성 위해 텍스트 라벨 사용

## CHANGELOG 규칙

- [Keep a Changelog](https://keepachangelog.com/) 형식 준수
- 모든 PR 의 변경 사항을 `[Unreleased]` 에 누적 (Added / Changed / Fixed / Removed)
- 릴리스 시 날짜와 함께 `[X.Y.Z.W] - YYYY-MM-DD` 로 승격
- REVISION 단위 릴리스는 엔트리가 작아도 CHANGELOG 에 기록 (업데이트 감지
  사용자가 실제 무엇이 바뀌었는지 볼 수 있어야 함)

# GuruNote 🎙️

> 유튜브 링크 한 줄로 해외 IT/AI 팟캐스트를 **화자 분리된 한국어 마크다운 요약본**으로.

```bash
$ ./run_webview.command            # macOS — React/PyWebView UI (v1.0+ 권장 진입점)
$ python3 app_webview.py           # 모든 OS — 동일 진입점, 터미널 출력 보임

# (v0.8 호환 — 옛 UI 진입점, 유지)
$ ./run_gui.command                # CustomTkinter 데스크톱 (백그라운드, 로그는 ~/.gurunote/gui.log)
$ streamlit run app.py             # Streamlit 웹 앱

# 실행 결과 (파이프라인 로그 — 타임스탬프 + ETA 포함):
[14:23:05] [Step 1] 유튜브 오디오 추출 중...
[14:23:18] [Step 1] OK: GPT-5 and the Future of AI (42.3 MB, 6150s)
[14:23:18]   > 게시일: 2025-09-15
[14:23:18]   > 공식 챕터 8개 감지
[14:23:20] [Step 2] 화자 분리 STT 중...             # 18%  |  0m 15s elapsed
[14:25:41] [Step 2] OK: 847 세그먼트, 2 화자        # 55%  |  2m 36s  |  ~2m left
[14:25:42] [Step 3] LLM 한국어 번역 중...
[14:27:10] [Step 3] OK: 번역 완료 (18,420 chars)    # 78%
[14:27:30] [Step 4] OK: 요약 완료                    # 90%
[14:27:32] [Step 5] OK: 마크다운 조립                # 100%
[14:27:32] [Done] GuruNote 생성 완료
[14:27:32] [Save] 히스토리에 저장됨
```

---

## 📦 선행 조건 (필수 사전 설치)

`setup.sh` / `setup.bat` 를 돌리기 **전에** 다음 3가지가 OS 에 설치돼 있어야
합니다. 하나라도 빠지면 첫 단계에서 `'git' 용어가 ... 인식되지 않습니다` /
`python: command not found` 같은 에러가 발생합니다.

| 도구 | 용도 | Windows | macOS | Linux (Debian/Ubuntu) |
|---|---|---|---|---|
| **Git** | 저장소 clone · 앱 내 업데이트 (`git pull`) | `winget install --id Git.Git -e` · [공식 다운로드](https://git-scm.com/download/win) | `brew install git` (또는 Xcode CLT 자동 설치) | `sudo apt install -y git` |
| **Python 3.10+** | GuruNote 런타임 | `winget install --id Python.Python.3.12 -e` · [python.org](https://www.python.org/downloads/windows/) | `brew install python@3.12` · [python.org](https://www.python.org/downloads/macos/) | `sudo apt install -y python3 python3-venv python3-pip` |
| **ffmpeg** | `yt-dlp` 오디오 추출 (Step 1) | `winget install --id Gyan.FFmpeg -e` · [공식 사이트](https://ffmpeg.org/download.html) | `brew install ffmpeg` · [Homebrew](https://brew.sh/) | `sudo apt install -y ffmpeg` |

> ⚠️ **Windows 사용자**: `winget` 으로 Git / Python 을 설치한 뒤에는 **PowerShell 창을
> 새로 열어야** `PATH` 가 갱신됩니다. 또한 Python 설치 시 "Add python.exe to PATH"
> 체크박스를 반드시 켜두세요 (설치 마법사 첫 화면).
>
> ⚠️ **Windows PowerShell 5.1 주의**: 기본 탑재된 PowerShell 5.1 은 유닉스식 명령
> 연결자 `&&` 를 지원하지 않습니다 (`'&&' 토큰은 이 버전에서 올바른 문 구분 기호가
> 아닙니다`). 아래 빠른 시작은 이를 피해 **한 줄에 하나씩** 실행하는 형태로
> 기술돼 있습니다. PowerShell 7+ (`winget install Microsoft.PowerShell`) 에서는
> `&&` 가 정상 동작합니다.

설치 확인 (버전이 표시되면 OK):

```bash
# Windows (PowerShell / cmd) · macOS · Linux 공통
git --version
python --version      # macOS 는 python3 --version
ffmpeg -version
```

---

## ⚡ 빠른 시작 (3단계)

```bash
# 1. 저장소 clone & 이동 (PowerShell 5.1 호환: && 를 쓰지 않고 한 줄씩)
git clone https://github.com/avlp12/GuruNote.git
cd GuruNote

# 2. 설치 (플랫폼 자동 감지 + STT 엔진 자동 설치 + .venv 자동 생성)
bash setup.sh        # macOS / Linux  (Windows 는 setup.bat)
# 자동 감지 + 설치:
#   - Apple Silicon Mac (M1~M5)  → MLX Whisper + pyannote (Metal/MPS GPU 가속, 권장)
#   - NVIDIA GPU (Linux/Windows) → CUDA PyTorch + WhisperX
#   - 그 외                       → AssemblyAI Cloud API 만 사용 가능

# 3. API 키 설정 (OpenAI / Anthropic / Google Gemini 중 하나)
cp .env.example .env
# .env 를 열어 OPENAI_API_KEY=sk-... 입력
# (Windows PowerShell 은 cp 대신 Copy-Item .env.example .env)

# 4. 실행 — v1.0+ React/PyWebView UI (권장)
bash run_webview.command     # macOS (더블 클릭도 가능)
python3 app_webview.py       # 모든 OS

# (v0.8 호환 — 옛 진입점, 유지)
bash run_desktop.sh          # CustomTkinter (macOS/Linux), Windows 는 run_desktop.bat
bash run_web.sh              # Streamlit (macOS/Linux), Windows 는 run_web.bat
```

> 💡 **macOS 주의**: macOS 12+ 는 `python` 명령이 없고 `python3` 만 있습니다.
> 또한 venv 를 activate 하지 않으면 `streamlit` 같은 venv 전용 명령은
> `command not found` 로 실패합니다. 위 래퍼 스크립트를 쓰면 이런 문제가
> 발생하지 않습니다.

> 앱 안의 **⚙️ 설정** 에서도 API 키를 입력할 수 있어 `.env` 를 직접 편집하지 않아도 됩니다.

---

## ✨ 주요 기능

- ⌨️ **UI 없는 실행 (CLI)** — `gurunote note <URL|파일>` 로 창을 띄우지 않고 파이프라인 실행.
  `--json` 은 결과를 기계가 읽는 형태로 내보내므로 스크립트나 에이전트가 그대로 쓸 수 있음.
  파이썬에서는 `from gurunote.pipeline import run_pipeline` 으로 호출.
- 🎧 **오디오 자동 추출** — `yt-dlp` 로 유튜브 영상의 오디오만 mp3 로 로컬 임시 폴더에 다운로드
- 📅 **유튜브 메타데이터 활용** — 영상 게시일, 채널, 설명, **공식 챕터**,
  **기존 자막**(수동/자동) 을 함께 수집해 LLM 번역·요약 단계에 컨텍스트로 주입.
  화자 실명 추론과 챕터 경계 유지 정확도가 향상되고, 최종 마크다운에는
  게시일/챕터 섹션이 자동으로 삽입됨.
- 🗣️ **화자 분리 STT** — 플랫폼별 로컬 GPU 엔진 + 클라우드 폴백
  - **NVIDIA GPU** (Linux/Windows): **WhisperX** (Distil-Whisper + pyannote, 청크 분할 처리, VRAM ~6GB)
  - **Apple Silicon Mac** (M1~M5): **MLX Whisper** + pyannote (Metal/MPS GPU 가속)
  - **GPU 없음**: **AssemblyAI Cloud API** 자동 폴백
  - 화자(Who) + 타임스탬프(When) + 내용(What) 을 동시 추출
  - IT/AI 도메인 핫워드 64 개 (Sam Altman, RLHF, Mixture of Experts …) 를 `initial_prompt` 로 주입해 고유명사/약어 인식률 향상
  - **의미 단위 재분할** — STT 직후 word-level 끝 검사로 Whisper 음성 경계 잘림을 보완. context leak 해소, 번역 정렬 drift 감소, 가독성 향상. 모델 비의존 방식으로 약한 로컬 LLM에서도 동일하게 작동.
- 🌐 **IT/AI 전문 톤 한국어 번역** — OpenAI `gpt-5.4` / Anthropic `claude-sonnet-4-6` / Google Gemini `gemini-2.5-flash`
  - 화자 실명(진행자/게스트) 자동 추론 + **bootstrap entity cache** 로 인명·지명 표기 일관성 유지
  - LLM / RAG / Fine-tuning 등 전문 용어 영문 병기
  - 구어체 추임새 정리, 가독성 높은 인터뷰 톤
  - **청크 분할 번역**으로 장편(1 시간+) 영상의 토큰 한도 초과 방지
  - **2-pass DCCD** (Draft-Conditioned Constrained Decoding) — 1단계 자유 번역 + 2단계 정렬. 약한 로컬 모델에서도 segment 수 정합 보장.
- 📝 **GuruNote 스타일 마크다운 요약**
  - 📌 영상 제목 및 핵심 주제 요약
  - 💡 Guru's Insights (3~5 개)
  - ⏱️ 타임라인별 주요 내용 요약
  - 📝 전체 스크립트 번역본 + 🇺🇸 영어 원문
- 📥 **다양한 출력** — `.md` / **PDF** (weasyprint) / **Obsidian vault** 직접 저장 / **Notion** 페이지 자동 작성
  - PDF 패키지 미설치 시 **자동 설치 다이얼로그** — `brew` + `pip` 자동 실행 (macOS)
  - Obsidian vault 미설정 시 **공통 경로 자동 감지** — `~/Documents`, iCloud Obsidian Sync 등 한 클릭 선택
- 📂 **작업 히스토리 + 4-facet 트리 내비** — 그리드 우측 패널에서 주제(분야)/인물(업로더)/
  제목(첫글자)/태그로 노트 자동 분류. 클릭 한 번에 직교 필터링.
- 📝 **노트 인-앱 편집** — 마크다운 분할 프리뷰 (좌: raw 편집, 우: 실시간 렌더링).
  저장 시 의미 검색 인덱스 자동 갱신.
- 🔍 **검색** — 키워드 substring + **의미 기반 (sentence-transformers, Korean 지원)**.
  의미 검색은 선택 의존성 — `pip install -r requirements-search.txt` 설치 후
  대시보드 "의미 검색 인덱스" 패널의 빌드 버튼으로 인덱스를 만들면, History 의
  "의미 검색" 칩과 노트 상세의 "연관 노트" 가 활성화된다. 미설치 시 패널에 설치 안내 표시.
- 📊 **대시보드** — 분야/업로더/태그/월별 통계 + 의미 검색 인덱스 빌드 패널
- ⏱ **실시간 진행 표시** — 5단계 뱃지 인디케이터 + ETA (경과 시간 + 남은 예상 시간)
- 🎨 **Material 3 React UI** (v1.0+) — `gurunote/webui/` 의 React + Tailwind CSS 구성. PyWebView 가 네이티브 윈도우 (macOS WKWebView / Windows WebView2 / Linux WebKitGTK) 를 띄움. 사이드바 + 5개 화면 (Main / History / Editor / Dashboard / Settings).
- 📦 **WhisperX 미설치 시 안내** (NVIDIA 환경) — 설치 또는 AssemblyAI 전환 선택 다이얼로그.
  Apple Silicon 환경에서는 `setup.sh` 가 MLX 스택을 자동 설치.
- 🧹 **임시 파일 자동 정리**

---

## 📋 출력 예시

GuruNote 가 생성하는 마크다운 요약본의 실제 모습:

```markdown
# 🎙️ GuruNote — Sam Altman: GPT-5 and the Future of AI

- **채널:** Lex Fridman
- **게시일:** 2025-09-15
- **STT 엔진:** `whisperx`
- **화자 수:** 2
- **재생 시간:** 01:42:30

# 📌 영상 제목 및 핵심 주제 요약
OpenAI CEO Sam Altman 이 Lex Fridman 팟캐스트에 출연해
GPT-5 의 아키텍처, AGI 로드맵, AI 안전성 연구 방향을 심층 논의.

# 💡 Guru's Insights (핵심 인사이트)
- **스케일링 법칙은 아직 유효하다** — ...
- **멀티모달 통합이 다음 도약의 열쇠** — ...
- **AI Alignment 연구에 수익의 20% 를 투자** — ...

# ⏱️ 타임라인별 주요 내용 요약
- [00:00] 인사 및 GPT-5 발표 배경
- [12:30] 아키텍처 변화 — Transformer 를 넘어서
- [35:00] AGI 정의와 실현 시점에 대한 견해
- ...

# 📝 전체 스크립트 번역본
[00:00] Speaker A (Lex Fridman): 오늘 특별한 게스트를 모셨습니다...
[00:15] Speaker B (Sam Altman): 초대해주셔서 감사합니다...
```

---

## 🧱 파이프라인

```
유튜브 URL
   │
   ▼  [Step 1] yt-dlp — 오디오 추출 (mp3)
   │
   ▼  [Step 2] WhisperX (NVIDIA) / MLX (Apple Silicon) / AssemblyAI — 화자 분리 전사
   │          └ IT/AI 핫워드를 initial_prompt 로 주입
   │          └ 청크 분할 처리 (영상 길이 제한 없음)
   │
   ▼  [Step 3] LLM 청크 분할 번역 (gpt-5.4 / claude-sonnet-4-6)
   │          └ 화자 라벨 + 타임스탬프 보존
   │
   ▼  [Step 4] LLM 요약본 생성 (GuruNote 스타일)
   │
   ▼  [Step 5] 마크다운 조립 + 다운로드 + 임시 폴더 정리
   │
   ▼
GuruNote_<영상제목>.md
```

---

## ⚙️ 요구사항

상세 설치 명령은 위 [📦 선행 조건](#-선행-조건-필수-사전-설치) 섹션 참고.

- **Git** ([git-scm.com](https://git-scm.com/downloads)) — 저장소 clone + 앱 내 업데이트
- **Python** 3.10 이상 ([python.org](https://www.python.org/downloads/))
- **ffmpeg** ([ffmpeg.org](https://ffmpeg.org/download.html)) — 오디오 추출에 필수적인 시스템 패키지
  - Mac: `brew install ffmpeg`
  - Windows: `winget install --id Gyan.FFmpeg -e` (또는 공식 사이트 다운로드)
  - Ubuntu/Debian: `sudo apt install ffmpeg`
- **로컬 STT GPU (선택)** — `setup.sh` 가 자동 감지/설치
  - **NVIDIA (Linux/Windows)** — WhisperX, VRAM ~6GB 권장 (Distil-Whisper + 청크 분할)
  - **Apple Silicon (M1~M5)** — MLX Whisper, 16GB+ Unified Memory 권장
  - **GPU 없음** — `GURUNOTE_STT_ENGINE=assemblyai` 로 클라우드 API 사용
- **API Key** (최소 하나씩)
  - LLM: `OPENAI_API_KEY` **또는** `ANTHROPIC_API_KEY`
  - STT 폴백용(선택): `ASSEMBLYAI_API_KEY`

---

## 🚀 설치

`bash setup.sh` (macOS/Linux) 또는 `setup.bat` (Windows) 단일 명령으로
가상환경 생성부터 플랫폼별 STT 엔진 설치까지 모두 자동 처리됩니다.

```bash
git clone https://github.com/avlp12/GuruNote.git
cd GuruNote

# macOS / Linux
bash setup.sh

# Windows
setup.bat
```

setup 스크립트가 순서대로 수행하는 작업:

1. `.venv/` 가상환경 생성 (이미 있으면 재사용) — `python3 -m venv .venv`
2. 플랫폼 감지: `nvidia-smi` 존재 여부 + `uname -s/-m`
3. 공통 의존성(`requirements.txt`) 설치 (UI / audio / LLM / AssemblyAI 폴백)
4. 플랫폼별 STT 엔진 추가 설치:
   - **NVIDIA GPU** → CUDA PyTorch 2.8.0 + `requirements-gpu.txt` (WhisperX)
   - **Apple Silicon** → `requirements-mac.txt` (MLX Whisper + pyannote + onnxruntime)
   - **감지 실패** → 추가 설치 없음 (AssemblyAI Cloud API 만 사용 가능)
5. 환경 검증 — PyTorch 버전, CUDA/MPS 가용성, 핵심 라이브러리 import 확인

> 💡 **venv 를 수동으로 만들 필요 없음** — setup 스크립트가 이미 `.venv` 를
> 만들고 그 안에 모든 의존성을 설치합니다. 실행은 `bash run_desktop.sh` /
> `run_web.sh` 래퍼가 `.venv/bin/python` 을 직접 호출하므로 `source activate`
> 없이 동작합니다 (macOS 의 `command not found: python` / `streamlit` 문제 회피).

### 📦 데스크톱 패키지 vs 소스 실행

| | 데스크톱 패키지 (.exe / .dmg / .pkg) | 소스 실행 (`bash setup.sh`) |
|---|---|---|
| **포함 STT 엔진** | AssemblyAI (클라우드만) | WhisperX (NVIDIA) / MLX (Apple Silicon) / AssemblyAI |
| **로컬 GPU 가속** | ❌ (PyInstaller 번들 한계) | ✅ |
| **인터넷 필요** | STT 마다 필요 | 로컬 STT 는 최초 모델 다운로드만 |
| **설치 난이도** | 더블클릭 | 가상환경 + setup 스크립트 |
| **추천 대상** | 클라우드 STT 만 쓰는 사용자 | 로컬 GPU 보유 사용자, 개발자 |

> 🔍 **왜 번들에 로컬 STT 가 빠지나요?**
> WhisperX(+CUDA PyTorch) ~3GB, MLX(+pyannote+torch) ~2GB 의 native binary 가
> 필요하고, CUDA 빌드는 GPU 러너가 있어야 합니다. 단일 실행 파일로 묶으면
> 다운로드 크기가 비현실적이고 시작 시간도 길어집니다. 번들된 venv 는
> 사후 `pip install` 도 불가능하므로, 로컬 GPU STT 가 필요하면 소스에서
> 실행하는 것이 현실적인 유일한 선택지입니다.

---

## 🔑 환경변수 설정

```bash
cp .env.example .env
```

그 뒤 `.env` 를 열어 필요한 값을 채웁니다. 최소 설정 예:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
# 로컬 OpenAI-compatible 서버 (선택)
# 예: oMLX / vLLM / Ollama / LM Studio / llama.cpp server
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
# STT 엔진 기본값 auto: NVIDIA → WhisperX, Apple Silicon → MLX, 그 외 → AssemblyAI
GURUNOTE_STT_ENGINE=auto
```

> `.env` 는 `.gitignore` 에 의해 절대 커밋되지 않습니다.

### 파이프라인 동작 제어 (선택 환경변수)

아래 변수는 `.env` 에 추가하거나 실행 전 셸에서 설정합니다. 미설정 시 괄호 안 값이 기본값입니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GURUNOTE_SEGMENT_RESPLIT` | `1` (on) | STT 직후 word-level 의미 단위 재분할. Whisper 음성 경계 잘림을 보완해 번역 정합·가독성 향상. `0` 으로 끄면 기존 Whisper segment 그대로 사용. |
| `GURUNOTE_TWO_PASS` | `1` (on) | 2-pass DCCD 번역. 1단계 자유 번역 → 2단계 정렬로 segment 수 정합 보장. `0` 으로 끄면 기존 1-pass. |
| `PYANNOTE_DIARIZATION_MODEL` | `pyannote/speaker-diarization-community-1` | 화자 분리 모델 (Apple Silicon). community-1 은 speaker confusion 마킹이 3.1 대비 감소. |

### Hugging Face 토큰 + pyannote community-1 권한 설정

pyannote 모델은 Hugging Face 계정 동의 후 비공개 접근이 가능합니다.

1. [huggingface.co](https://huggingface.co/) 계정 생성
2. 아래 두 모델 페이지에서 각각 **"Agree and access repository"** 클릭
   - `pyannote/speaker-diarization-community-1`
   - `pyannote/segmentation-3.0`
3. Hugging Face → Settings → Access Tokens 에서 `read` 권한 토큰 발급
4. `.env` 에 추가:

```env
HUGGINGFACE_TOKEN=hf_...
```

> `HF_TOKEN` 변수명도 동일하게 인식됩니다. 토큰은 최초 모델 다운로드 시 1회만 필요하며 이후는 로컬 캐시를 사용합니다.

---

## ▶️ 실행

### React/PyWebView UI (v1.0+ 권장 진입점)

**macOS**
```bash
./run_webview.command
```
- Finder 에서 더블 클릭 또는 터미널에서 실행.
- stdout/stderr 가 콘솔에 그대로 남아 pywebview + 파이프라인 디버깅이 쉽습니다 (CustomTkinter `run_gui.command` 와 달리 `~/.gurunote/gui.log` 로 리다이렉트하지 않음).
- venv 자동 감지 (`./.venv` → `./venv` → 시스템 `python3`).

**모든 OS 공통**
```bash
# macOS / Linux / Windows
python3 app_webview.py
```

- pywebview 가 네이티브 윈도우를 띄우고 `gurunote/webui/index.html` 의 React 앱을 로드합니다.
- 화면 구성: Main (생성 + 결과 4탭) / History (4-facet 트리 + 그리드) / Editor (마크다운 분할 프리뷰) / Dashboard (통계 + 의미 검색) / Settings (API 키 + STT/LLM 엔진 + Provider 조건부 필드).
- ⌘K (또는 Ctrl+K) 로 SearchPalette 호출.

### 명령줄 (CLI) — UI 없이 실행

창을 띄우지 않고 같은 파이프라인을 돌립니다. `pip install -e .` (또는 `setup.sh`) 이후 사용합니다.

```bash
gurunote note "https://www.youtube.com/watch?v=..." --out note.md
gurunote note ./talk.mp3 --engine mlx
gurunote note "https://youtu.be/..." --json          # 기계가 읽는 결과
gurunote history --limit 10                           # 저장된 작업 기록
gurunote search "확산 모델" --json                      # 의미 검색 (인덱스 필요)
gurunote settings                                     # 현재 설정 (비밀값은 설정 여부만)
gurunote engines                                      # 선택 가능한 STT 엔진
gurunote providers                                    # 선택 가능한 LLM provider
python -m gurunote --version                          # 설치 스크립트 없이도 동작
```

노트 본문(또는 `--json`)은 stdout 으로, 진행 로그는 stderr 로 나갑니다. 그래서
`gurunote note ... > note.md` 로 받아도 로그가 섞이지 않습니다. 로그를 아예 끄려면
`--quiet` 을 씁니다.

종료 코드: 성공 `0`, 파이프라인 실패 `1`, 입력·옵션 오류 `2`, `--timeout` 초과 `124`.

파이썬에서 직접 부를 때는 동기 API 를 씁니다.

```python
from gurunote.pipeline import run_pipeline

result = run_pipeline("https://youtu.be/...", engine="auto")
if result.ok:
    print(result.full_md)
else:
    print(result.error, result.job_id)   # 로그는 ~/.gurunote/jobs/<job_id>/
```

`--provider` 를 주지 않으면 `LLM_PROVIDER` 환경변수를 따릅니다. 선택지 정본은
`gurunote/options.py` 이며 GUI·CLI·React 가 같은 목록을 참조합니다.

`history` / `search` / `settings` 는 React UI 가 쓰는 것과 **같은 `GuruNoteService`** 를 호출합니다. 창이 필요한 것(파일 선택 대화상자, 진행 이벤트 전달)만 `webui/bridge.py` 에 남아 있고, 나머지 29개 동작은 창 없이 파이썬에서도 부를 수 있습니다.

```python
from gurunote.service import GuruNoteService

svc = GuruNoteService()          # 창 불필요
print(svc.list_history(limit=5))
print(svc.get_settings())        # 비밀값은 평문으로 반환하지 않음
```

### 옛 진입점 — v0.8 호환 (유지)

새 UI 가 동작하지 않거나 옛 인터페이스가 필요한 경우 아래 진입점이 그대로 동작합니다. 파이프라인 코어 (`gurunote/`) 는 셋 다 공유합니다.

**CustomTkinter 데스크톱** (`gui.py` — React UI 가 `PipelineWorker` 클래스로 의존하는 코어 파일)
```bash
# macOS — 백그라운드 실행, 로그는 ~/.gurunote/gui.log
./run_gui.command

# macOS / Linux / Windows — 터미널 출력 보면서
bash run_desktop.sh           # Windows: run_desktop.bat
# 또는: .venv/bin/python gui.py
```

**Streamlit 웹** (`app.py`)
```bash
bash run_web.sh               # macOS / Linux  (Windows: run_web.bat)
# 또는: .venv/bin/streamlit run app.py
```

### 사용 흐름

```
1. 유튜브 URL 입력 (또는 📁 로컬 파일 선택)
       ↓
2. STT 엔진 (auto / whisperx / mlx / assemblyai)
   LLM 제공자 (openai / anthropic / gemini / openai_compatible) 선택
       ↓
3. "▶ GuruNote 생성하기" 클릭
       ↓
4. 진행 상황을 5단계 인디케이터 + 로그로 실시간 확인
       ↓
5. 📌 요약본 / 🇰🇷 번역 / 🇺🇸 원문 탭에서 결과 확인
       ↓
6. 📥 마크다운 저장 → GuruNote_<영상제목>.md 다운로드
```

> **최초 실행 안내:**
> WhisperX (Distil-Whisper large-v3, ~1.5GB) 또는 MLX Whisper (large-v3, ~3GB)
> 모델 가중치를 Hugging Face Hub 에서 다운로드합니다. 네트워크 속도에 따라
> **수 분이 소요**될 수 있으며, 터미널에 진행 상황이 표시됩니다. 이후 실행부터는
> 로컬 캐시(`~/.gurunote/models/` 또는 `~/.cache/huggingface/`)를 사용합니다.

<details>
<summary><strong>🔧 고급: 패키징 / CI / 업데이트</strong></summary>

### 독립 실행 파일 패키징

```bash
pip install pyinstaller
pyinstaller --windowed --onefile gui.py
# dist/gui.app (Mac) 또는 dist/gui.exe (Windows)
```

또는 `scripts/package_desktop.py` 로 Windows `.exe`/설치형, macOS `.app`/`.dmg`/`.pkg` 를 자동 생성:

```bash
python scripts/package_desktop.py --target windows              # .exe
python scripts/package_desktop.py --target windows --formats installer  # 설치형
python scripts/package_desktop.py --target macos                # .app
python scripts/package_desktop.py --target macos --formats dmg  # .dmg
```

### GitHub Actions 릴리스 자동화

`.github/workflows/release-desktop.yml` — `v*` 태그 푸시 시 Windows/macOS 패키지를
CI 에서 자동 빌드하고 GitHub Release 에 업로드합니다.

### 업데이트 (재설치 없이)

```bash
python scripts/update_gurunote.py --check   # 상태 확인
python scripts/update_gurunote.py --update  # git pull + pip upgrade
```

앱 내 ⚙️ 설정에도 동일한 업데이트 버튼이 있습니다.

### 릴리스 리허설 체크

```bash
python scripts/release_rehearsal_check.py --tag v0.1.1
python scripts/release_rehearsal_check.py --tag v0.1.1 --local-tools  # 로컬 도구까지 검사
```

</details>

---

## 🗂️ 프로젝트 구조

```
GuruNote/
├── app.py                      # Streamlit 웹 UI (대시보드 + 의미 검색 + 트리 내비 포함)
├── gui.py                      # CustomTkinter 데스크톱 GUI
├── run_gui.command             # macOS 백그라운드 런처 (터미널 분리)
├── requirements.txt            # Pillow + markdown + weasyprint 기본 포함
├── .env.example
├── README.md
├── CHANGELOG.md
├── app_webview.py              # v1.0+ React/PyWebView 진입점 (권장)
├── run_webview.command         # macOS React UI 런처
├── docs/                       # 설계 참조, 연구 노트, 작업 일지 (legacy/journal/research/wip)
├── gurunote/
│   ├── __init__.py
│   ├── __main__.py             # `python -m gurunote` 진입점
│   ├── cli.py                  # 명령줄 인터페이스 (note / history / search / settings / engines / providers)
│   ├── service.py              # 창 없는 조작 표면 — bridge 와 CLI 가 공유
│   ├── pipeline.py             # 파이프라인 동기 실행 API (run_pipeline)
│   ├── options.py              # STT 엔진 / LLM provider 목록의 단일 출처
│   ├── types.py                # Segment / Transcript 공통 데이터클래스
│   ├── audio.py                # Step 1 — yt-dlp + 로컬 파일 오디오 추출
│   ├── stt.py                  # Step 2 — WhisperX (NVIDIA) + AssemblyAI 폴백 라우터
│   ├── stt_mlx.py              # Step 2 — MLX Whisper + pyannote (Apple Silicon) + 의미 단위 재분할 (v1.0+)
│   ├── llm/                    # Step 3~4 — LLM 번역·요약 (8개 모듈)
│   │   ├── client.py           #   provider 호출 경계 (재시도·타임아웃·xgrammar)
│   │   ├── prompts.py          #   system 프롬프트 본문
│   │   ├── chunking.py         #   요청 단위 분할 규칙
│   │   ├── context.py          #   영상 메타데이터 컨텍스트 블록
│   │   ├── entities.py         #   entity/speaker 캐시·통용 표기·검색 그라운딩
│   │   ├── postprocess.py      #   한자 차단·영문 병기 검증·반복 축약
│   │   ├── translate.py        #   2-pass DCCD·index mapping
│   │   └── summarize.py        #   요약·메타데이터 추출
│   ├── exporter.py             # Step 4~5 — GuruNote 마크다운 조립
│   ├── history.py              # 작업 히스토리 + 영속 로그 (~/.gurunote/)
│   ├── settings.py             # `.env` 저장/로드 + 백업 유틸
│   ├── updater.py              # git pull + pip upgrade 자동 업데이트 유틸
│   ├── thumbnails.py           # YouTube 썸네일 다운로드 + 캐시 (해상도 폴백 체인)
│   ├── pdf_export.py           # 마크다운 → PDF (weasyprint)
│   ├── pdf_installer.py        # PDF 의존성 자동 설치 다이얼로그 (brew + pip)
│   ├── obsidian.py             # Obsidian vault 저장 + find_vault_candidates()
│   ├── notion_sync.py          # Notion API 페이지 자동 작성
│   ├── search.py               # 키워드 substring 검색 + 본문 캐시
│   ├── semantic.py             # sentence-transformers 의미 검색 (한국어 지원)
│   ├── stats.py                # 대시보드 통계 (분야/업로더/태그/월별)
│   ├── nav_tree.py             # 4-facet 트리 내비 (주제/인물/제목/태그)
│   ├── ui_state.py             # UI 영속 상태 (트리 expand 등)
│   ├── app_icon.py             # 앱 아이콘 런타임 생성 (PIL "G" 모노그램)
│   ├── data/
│   │   └── loanword_orthography.md  # 외래어 표기법 (문화체육관광부고시 제2017-14호) — LLM 참조
│   └── webui/                  # v1.0+ React/PyWebView UI
│       ├── bridge.py           # PyWebView ↔ Python 브릿지 (Api 클래스)
│       ├── session.py          # PipelineSession (gui.PipelineWorker 어댑터)
│       ├── index.html          # React 진입 HTML (Babel standalone)
│       ├── components/         # JSX 컴포넌트 (App / Sidebar / TopBar / 5 화면 + ResultPanel + SearchPalette)
│       ├── styles/             # CSS (Material 3 톤 + Tailwind utility 일부)
│       └── vendor/             # 번들 React/Babel/Tailwind (오프라인 로딩)
├── gui.py                      # v0.8 호환 — CustomTkinter 진입점 (PipelineWorker 클래스 보유, React 가 의존)
├── app.py                      # v0.8 호환 — Streamlit 웹 앱
├── scripts/
│   ├── package_desktop.py      # Windows/macOS 배포 패키지 자동 생성
│   ├── update_gurunote.py      # CLI 업데이트 진입점
│   └── release_rehearsal_check.py  # 태그 푸시 전 릴리스 준비 체크
└── .github/workflows/
    ├── tests.yml               # push / PR 마다 단위 테스트 (Python 3.10 / 3.11 / 3.12)
    └── release-desktop.yml     # 태그 푸시 시 데스크톱 패키지 자동 빌드
```

---

## 🛠️ 기술 스택

| 영역 | 사용 기술 |
|---|---|
| UI (v1.0+ 권장) | [React](https://react.dev/) (Babel standalone) + Material 3 톤 CSS + [Tailwind CSS](https://tailwindcss.com/) utility + [PyWebView](https://pywebview.flowrl.com/) 4.x (macOS WKWebView / Windows WebView2 / Linux WebKitGTK) |
| UI (v0.8 호환) | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) 데스크톱 (`gui.py`) · [Streamlit](https://streamlit.io/) 웹 (`app.py`) |
| 오디오 추출 | [yt-dlp](https://github.com/yt-dlp/yt-dlp) · ffmpeg |
| STT + 화자 분리 | [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) + [pyannote.audio](https://github.com/pyannote/pyannote-audio) `community-1` (Apple Silicon, Metal/MPS) · [WhisperX](https://github.com/m-bain/whisperX) (NVIDIA CUDA) · [AssemblyAI](https://www.assemblyai.com/) (Cloud fallback) · 의미 단위 재분할 (v1.0+) |
| 번역 / 요약 | [OpenAI](https://platform.openai.com/) `gpt-5.4` · [Anthropic](https://docs.anthropic.com/) `claude-sonnet-4-6` · [Google Gemini](https://aistudio.google.com/) `gemini-2.5-flash` · OpenAI-compatible (로컬 LLM, oMLX / vLLM / LM Studio / llama.cpp 등) · 2-pass DCCD + entity_cache + 외래어 표기법 |
| 환경 설정 | [python-dotenv](https://pypi.org/project/python-dotenv/) · 앱 내 Settings 화면 |

---

## 📜 버전 기록

주요 변경 사항은 [CHANGELOG.md](./CHANGELOG.md) 에 [Keep a Changelog](https://keepachangelog.com/)
형식으로 기록되며 버전은 [Semantic Versioning](https://semver.org/) 을 따릅니다.

현재 버전: **v1.0.0.31** — `Api` 의 창 없는 동작 29개를 `gurunote/service.py` 로 분리했습니다. React UI 와 CLI 가 같은 코드를 씁니다(`gurunote history` / `search` / `settings` 추가). 동작 변경은 없습니다.

### v1.0.0.0 주요 변경 (요약)

- **UI**: CustomTkinter / Streamlit 양립 구조 → React + Material 3 + PyWebView 신축 (`gurunote/webui/`). 사이드바 + 5 화면 (Main / History / Editor / Dashboard / Settings) + ⌘K SearchPalette. 옛 진입점 (`gui.py` / `app.py`) 은 호환 유지.
- **STT**: mlx-whisper + pyannote `community-1` (3.1 대비 speaker confusion 감소) + STT 직후 word-level **의미 단위 재분할** (Whisper 음성 경계 잘림 보완).
- **번역**: 1-pass → **2-pass DCCD** (Draft-Conditioned Constrained Decoding), **entity_cache** 디스크 영속 (인명·지명 표기 일관성), 외래어 표기법 (문화체육관광부고시 제2017-14호) LLM 참조, 한자/일본어 차단 후처리.
- **License**: MIT → **Elastic License 2.0**.
- **환경변수 토글**: `GURUNOTE_SEGMENT_RESPLIT` / `GURUNOTE_TWO_PASS` / `PYANNOTE_DIARIZATION_MODEL` (기본 on, 자세한 내용은 위 🔑 환경변수 설정 참고).

---

## ❓ 자주 묻는 질문 (FAQ)

**Q. 창을 띄우지 않고 자동화하거나 에이전트에 연결할 수 있나요?**
네. `gurunote note <URL|파일>` 이 같은 파이프라인을 UI 없이 실행합니다. `--json` 을 주면
`ok` / `job_id` / `full_md` / `summary_md` / `error` 를 담은 JSON 이 stdout 으로 나오고,
진행 로그는 stderr 로 분리되므로 그대로 파이프에 넘길 수 있습니다. 파이썬에서는
`from gurunote.pipeline import run_pipeline` 을 씁니다. 종료 코드는 성공 `0`,
파이프라인 실패 `1`, 입력 오류 `2`, `--timeout` 초과 `124` 입니다.

| 질문 | 답변 |
|---|---|
| **`'git' 용어가 ... 인식되지 않습니다` (Windows)** | Git 이 설치되지 않았습니다. `winget install --id Git.Git -e` 실행 후 **새 PowerShell 창**을 열어 재시도하세요. winget 이 없는 구형 Windows 는 [git-scm.com/download/win](https://git-scm.com/download/win) 에서 인스톨러를 받아 설치. 자세한 내용은 위 [📦 선행 조건](#-선행-조건-필수-사전-설치) 참고. |
| **`'&&' 토큰은 이 버전에서 올바른 문 구분 기호가 아닙니다` (Windows PowerShell)** | Windows 기본 탑재된 PowerShell 5.1 은 `&&` 를 지원하지 않습니다. 명령을 **한 줄에 하나씩** 실행하거나 (`git clone ...` 한 줄 → `cd GuruNote` 한 줄), PowerShell 7+ 로 업그레이드(`winget install Microsoft.PowerShell`) 또는 `cmd.exe` 를 사용하세요. |
| **`python: command not found` / `'python' 용어가 인식되지 않습니다`** | Python 3.10+ 이 설치되지 않았거나 PATH 에 없습니다. Windows: `winget install --id Python.Python.3.12 -e` (설치 마법사의 "Add python.exe to PATH" 체크 필수). macOS 는 `python3` 명령을 사용하세요. Linux: `sudo apt install python3 python3-venv`. |
| **`command not found: python` (macOS)** | macOS 12+ 는 `python` 명령이 없고 `python3` 만 있습니다. `bash run_webview.command` 를 쓰면 venv 자동 감지로 동작합니다. 직접 실행하려면 `source .venv/bin/activate` 후 `python3 app_webview.py`. |
| **`gui.py` 를 지워도 되나요?** | 부재 — React UI (`app_webview.py`) 가 `gui.py` 의 `PipelineWorker` 클래스를 import 합니다 (`gurunote/webui/session.py`). 옛 CustomTkinter UI 코드와 파이프라인 워커 로직이 같은 파일에 들어있어 분리 부재 상태입니다 (백로그 등록 — `docs/backlog.md` B09). 이 분리 작업 전까지는 `gui.py` 유지 필요. |
| **GPU 없이 쓸 수 있나요?** | `.env` 에서 `GURUNOTE_STT_ENGINE=assemblyai` 로 설정하면 클라우드 API 로 동작합니다 (AssemblyAI 키 필요). |
| **Apple Silicon Mac (M1~M5) 에서 GPU 로컬 STT 가 되나요?** | 네. v0.6.0 부터 `setup.sh` 가 Apple Silicon 을 자동 감지해 `mlx-whisper` + `pyannote.audio` 를 설치합니다. STT 엔진을 `auto` 로 두면 Metal/MPS GPU 가속으로 로컬 전사 + 화자 분리가 동작합니다. 화자 분리에는 `HUGGINGFACE_TOKEN` + [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 및 [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) 모델 동의가 필요합니다. 위 🔑 환경변수 설정 섹션의 안내를 참고하세요. |
| **1시간 넘는 영상은?** | WhisperX / MLX 모두 청크 분할 처리라 길이 제한이 없습니다. AssemblyAI 도 길이 제한 없음. |
| **로컬 LLM 을 쓰고 싶어요** | `.env` 에서 `LLM_PROVIDER=openai_compatible` + `OPENAI_BASE_URL=http://127.0.0.1:8000/v1` 설정. Ollama, vLLM, LM Studio 등 OpenAI-compatible 서버라면 모두 가능합니다. |
| **"ffmpeg not found" 에러** | Mac: `brew install ffmpeg` / Windows: `winget install ffmpeg` / Ubuntu: `sudo apt install ffmpeg` |
| **모델 가중치 다운로드가 오래 걸려요** | MLX Whisper large-v3 (~3GB) / WhisperX Distil-Whisper (~1.5GB) / pyannote community-1 (~수십 MB) 는 최초 1회만 다운로드됩니다. 이후는 로컬 캐시 (`~/.cache/huggingface/` 또는 `~/.gurunote/models/`) 를 사용합니다. |
| **API 키를 어디에 넣나요?** | 앱 실행 후 Settings → 입력 → Save. `.env` 파일에 자동 기록됩니다. |
| **CUDA Out of Memory 에러** | v0.3.0 부터 자동으로 토큰 수를 줄여 재시도합니다 (32768→16384→8192). 그래도 실패하면 모델을 자동 언로드하고 에러 메시지에 해결 방법을 안내합니다. |
| **WhisperX 가 설치 안 됐다고 떠요** (NVIDIA) | "GuruNote 생성하기" 클릭 시 설치/AssemblyAI 전환 선택 다이얼로그가 뜹니다. Apple Silicon 에선 MLX 자동 사용. |
| **PDF 출력 패키지가 없다고 떠요** | v0.7.0.4 부터 `Save PDF` 클릭 시 "지금 자동 설치할까요?" 확인 → 승인 시 `brew install cairo pango gdk-pixbuf libffi` + `pip install` 자동 실행 (macOS+Homebrew). Linux 는 sudo 가 필요해서 명령만 안내됨. Windows 는 pip 만 자동. |
| **Obsidian vault 경로를 어떻게 설정하나요?** | v0.7.0.5 부터 `→ Obsidian` 클릭 시 자동 감지된 vault 후보 + "폴더 찾아보기" 다이얼로그가 뜹니다. Settings 다이얼로그에서도 "찾아보기" 버튼 + 실시간 유효성 chip (`✓ vault` 등) 으로 한 클릭 설정 가능. |
| **터미널에 pyannote 다운로드 로그가 자꾸 뜹니다** (macOS) | React UI (`run_webview.command`) 는 콘솔에 그대로 출력합니다 (디버깅 편의). 백그라운드 분리가 필요하면 옛 `./run_gui.command` 로 실행 — `nohup` + `disown` 으로 터미널과 분리되고 로그는 `~/.gurunote/gui.log` 로만 갑니다. `tail -f ~/.gurunote/gui.log` 로 진단. |
| **React UI 가 뜨지 않습니다 (빈 창)** | `gurunote/webui/index.html` 누락 또는 `pywebview` 미설치일 가능성. `bash setup.sh` 재실행으로 의존성 재설치 후 `python3 app_webview.py`. macOS 에서 WebKit 자체 문제일 경우 옛 `gui.py` 진입점으로 일시 우회 가능. |
| **앱 아이콘이 로켓 모양** | v0.7.1.0 부터 자체 "G" 모노그램 아이콘이 자동 생성됩니다. 캐시 위치: `~/.gurunote/app_icon.png`. |
| **과거 작업을 다시 보고 싶어요** | 사이드바 History → 우측 트리 내비 (주제/인물/제목/태그) 로 필터, 카드에서 Save (마크다운 재다운로드) / PDF / Obsidian / Notion / Log. |

---

## 🗑️ 제거 (Uninstall)

GuruNote 는 시스템 레벨 설치를 하지 않고 `.venv` + 프로젝트 폴더 + 홈의 데이터
폴더에만 파일을 남깁니다. 단계별로 지우면 깔끔하게 제거됩니다.

### macOS / Linux

```bash
# 1. ⚠️ API 키 백업 또는 완전 삭제 (.env 에 저장됨)
cat GuruNote/.env                 # 필요하면 내용 복사 후 보관
# (따로 보관할 필요 없으면 다음 단계에서 함께 삭제됨)

# 2. 프로젝트 폴더 통째로 삭제 (.venv/ + autosave/ + .env 모두 포함)
rm -rf GuruNote

# 3. 사용자 홈의 GuruNote 데이터 삭제
#    - ~/.gurunote/jobs/         작업 히스토리 (메타 + 결과 마크다운 + pipeline.log)
#    - ~/.gurunote/history.json  히스토리 인덱스
#    - ~/.gurunote/models/       WhisperX 모델 (NVIDIA 로 썼던 경우, ~1.5GB)
#    - ~/.gurunote/thumbnails/   YouTube 썸네일 캐시
#    - ~/.gurunote/embeddings.npz + embeddings_meta.json  의미 검색 인덱스
#    - ~/.gurunote/ui_state.json  GUI 영속 상태 (트리 expand 등)
#    - ~/.gurunote/app_icon.png  생성된 앱 아이콘
#    - ~/.gurunote/gui.log       run_gui.command 백그라운드 로그
rm -rf ~/.gurunote

# 4. (선택) HuggingFace 모델 캐시 — MLX / pyannote 가 다운받은 모델
#    ⚠️ 이 폴더는 다른 프로젝트 (transformers 직접 사용, ComfyUI 등) 도
#       공유하므로, GuruNote 전용이었던 경우에만 삭제.
ls ~/.cache/huggingface/hub/      # 먼저 확인
rm -rf ~/.cache/huggingface/hub/models--mlx-community--whisper-*
rm -rf ~/.cache/huggingface/hub/models--pyannote--*
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-*
# 또는 HuggingFace 캐시 자체를 통째로:
# rm -rf ~/.cache/huggingface
```

### Windows (PowerShell)

```powershell
# 1. ⚠️ API 키 백업 (GuruNote\.env)
Get-Content GuruNote\.env         # 내용 확인

# 2. 프로젝트 폴더 통째로 삭제
Remove-Item -Recurse -Force GuruNote

# 3. 사용자 홈의 GuruNote 데이터 삭제
Remove-Item -Recurse -Force "$env:USERPROFILE\.gurunote"

# 4. (선택) HuggingFace 모델 캐시
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface\hub\models--mlx-community--whisper-*"
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface\hub\models--pyannote--*"
Remove-Item -Recurse -Force "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-*"
```

### 삭제 대상 요약

| 경로 | 내용 | 크기 (대략) |
|---|---|---|
| `GuruNote/` (프로젝트 폴더) | 소스 + `.venv/` + `autosave/` + `.env` | **2~5 GB** (의존성 포함) |
| `~/.gurunote/jobs/` | 작업 히스토리 메타 + 결과 마크다운 + 로그 | 수 MB (작업 수에 따라) |
| `~/.gurunote/models/` | WhisperX 모델 (NVIDIA 로 사용 시) | **~1.5 GB** |
| `~/.gurunote/history.json` | 히스토리 인덱스 | 수 KB |
| `~/.cache/huggingface/hub/` (일부) | MLX Whisper, pyannote diarization 모델 | **~3~4 GB** |

> 🔒 **보안 주의**: `.env` 에는 OpenAI / Anthropic / Gemini / AssemblyAI API 키
> 가 평문 저장됩니다. 프로젝트 폴더 삭제 전에 안전한 위치로 백업하거나,
> API 제공자 대시보드에서 키를 폐기(revoke) 하세요.

> 📁 **임시 파일**: 파이프라인 실행 중 `/tmp/gurunote_*` (Windows: `%TEMP%\gurunote_*`)
> 에 임시 오디오 파일이 생성되며 작업 완료 시 자동 정리됩니다. 비정상 종료로
> 남아있다면 OS 재부팅 또는 수동 삭제로 제거됩니다.

---

## 📄 License

**Elastic License 2.0** (2026-04-24~ for commits on `redesign/tailwind-v2` and subsequent branches).

- ✅ View and study the source code
- ✅ Internal use within your organization
- ✅ Modify for personal/internal use
- ❌ Provide as a managed service (SaaS, hosting)
- ❌ Circumvent license key functionality (if any)

자세한 내용은 [LICENSE](./LICENSE) 참고.

> **Note on license history:** Commits before 2026-04-24 (on `main` branch)
> remain under MIT License (see git history). The license transitions to
> Elastic 2.0 starting with the `redesign/tailwind-v2` branch and all
> future work.

Copyright © 2026 Alis Volat Propriis ([@alis_volat_propriis](https://x.com/alis_volat_propriis)).

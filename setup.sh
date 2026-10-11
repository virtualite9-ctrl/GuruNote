#!/bin/bash
echo ""
echo "================================================"
echo "    GuruNote 환경 설정"
echo "================================================"
echo ""

# 0. 시스템 의존성: ffmpeg / ffprobe
#    yt-dlp 오디오 추출에 필수. 없으면 파이프라인 Step 1 에서 즉시 실패.
#    macOS 에서 brew 가 있으면 자동 설치 제안 (여전히 사용자 확인 필요).
if ! command -v ffmpeg &> /dev/null || ! command -v ffprobe &> /dev/null; then
    echo "[0/4] ⚠️  ffmpeg / ffprobe 미설치 — yt-dlp 오디오 추출에 필수입니다."
    case "$(uname -s)" in
        Darwin*)
            if command -v brew &> /dev/null; then
                echo "      Homebrew 감지됨. 다음 명령으로 설치:"
                echo "        brew install ffmpeg"
                read -p "      지금 설치할까요? [y/N] " yn
                case "$yn" in
                    [Yy]*)
                        brew install ffmpeg || {
                            echo "      ffmpeg 설치 실패. 수동 설치 후 setup.sh 를 재실행하세요."
                            exit 1
                        }
                        ;;
                    *)
                        echo "      설치 건너뜀. 수동 설치 후 setup.sh 를 재실행하세요:"
                        echo "        brew install ffmpeg"
                        exit 1
                        ;;
                esac
            else
                echo "      Homebrew 가 없습니다. 먼저 Homebrew 설치 후 재실행:"
                echo "        /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                echo "        brew install ffmpeg"
                exit 1
            fi
            ;;
        Linux*)
            echo "      다음 명령으로 설치 (sudo 필요):"
            echo "        sudo apt update && sudo apt install -y ffmpeg   # Debian/Ubuntu"
            echo "        sudo dnf install -y ffmpeg                       # Fedora/RHEL"
            exit 1
            ;;
        *)
            echo "      수동 설치 후 재실행하세요: https://ffmpeg.org/download.html"
            exit 1
            ;;
    esac
else
    echo "[0/4] ffmpeg / ffprobe 확인 OK"
fi
echo ""

# 1. venv
if [ ! -f ".venv/bin/python" ]; then
    echo "[1/4] 가상환경 생성 중..."
    python3 -m venv .venv
else
    echo "[1/4] 가상환경 확인 OK"
fi

PIP=".venv/bin/pip"
PYTHON=".venv/bin/python"

# 2. 플랫폼 감지 → STT 엔진 선택
#    우선순위: NVIDIA GPU (CUDA WhisperX) > Apple Silicon (MLX Whisper) > CPU/AssemblyAI
echo ""
OS="$(uname -s)"
ARCH="$(uname -m)"
STT_PROFILE="cpu"

if command -v nvidia-smi &> /dev/null; then
    echo "[2/4] NVIDIA GPU 감지됨 — CUDA PyTorch + WhisperX 설치"
    $PIP install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
    STT_PROFILE="gpu"
elif [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
    echo "[2/4] Apple Silicon 감지됨 — MLX Whisper 설치 (Metal/MPS GPU 가속)"
    STT_PROFILE="mac"
else
    echo "[2/4] GPU 미감지 — CPU 모드 (STT 는 AssemblyAI Cloud API 사용)"
fi

# 3. 공통 패키지 설치
echo ""
echo "[3/4] GuruNote 공통 패키지 설치 중..."
$PIP install -r requirements.txt

# 3-bis. 플랫폼별 STT 패키지 설치
if [ "$STT_PROFILE" = "gpu" ]; then
    echo ""
    echo "[3/4+] WhisperX (CUDA) 설치 중..."
    $PIP install -r requirements-gpu.txt
elif [ "$STT_PROFILE" = "mac" ]; then
    echo ""
    echo "[3/4+] MLX Whisper (Apple Silicon) 설치 중..."
    $PIP install -r requirements-mac.txt
fi

# 3-ter. Linux GUI 백엔드 (PyWebView GTK/WebKit2)
#        권장 진입점 app_webview.py 는 Linux 에서 WebKitGTK 백엔드가 있어야 창이
#        뜬다. PyGObject 는 시스템 gobject-introspection / cairo / 컴파일러에
#        의존하므로, pip 설치 전에 시스템 패키지를 먼저 점검한다 (sudo 필요 →
#        명령만 안내하고 자동 설치는 하지 않음). STT_PROFILE 과 무관하게 수행.
if [ "$OS" = "Linux" ]; then
    echo ""

    _have_webkit_typelib() {
        local d
        for d in /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu /usr/lib/aarch64-linux-gnu; do
            ls "$d"/girepository-1.0/WebKit2-4.*.typelib >/dev/null 2>&1 && return 0
        done
        return 1
    }

    GUI_SYSDEPS_OK=1
    command -v pkg-config >/dev/null 2>&1 || GUI_SYSDEPS_OK=0
    { command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1; } || GUI_SYSDEPS_OK=0
    pkg-config --exists girepository-1.0 2>/dev/null || GUI_SYSDEPS_OK=0
    pkg-config --exists cairo 2>/dev/null || GUI_SYSDEPS_OK=0
    _have_webkit_typelib || GUI_SYSDEPS_OK=0

    if [ "$GUI_SYSDEPS_OK" = "1" ]; then
        echo "[3/4+] Linux GUI 백엔드 (WebKitGTK) 설치 중..."
        $PIP install -r requirements-linux.txt
    else
        echo "[3/4+] ⚠️  Linux GUI 백엔드(WebKitGTK) 시스템 패키지가 없습니다."
        echo "       권장 진입점 app_webview.py 는 이 백엔드가 있어야 창이 뜹니다."
        echo "       배포판에 맞는 명령으로 설치 후 setup.sh 를 재실행하세요 (sudo 필요):"
        echo ""
        echo "         # Debian/Ubuntu (구형 배포판은 gir1.2-webkit2-4.0)"
        echo "         sudo apt update && sudo apt install -y \\"
        echo "           gir1.2-webkit2-4.1 libgirepository1.0-dev libcairo2-dev \\"
        echo "           pkg-config python3-dev gcc"
        echo ""
        echo "         # Fedora/RHEL"
        echo "         sudo dnf install -y webkit2gtk4.1 gobject-introspection-devel \\"
        echo "           cairo-gobject-devel pkgconf-pkg-config python3-devel gcc"
        echo ""
        echo "       (GUI 없이 CLI / Streamlit 만 쓰면 이 단계는 건너뛰어도 됩니다.)"
    fi
fi

# 4. 검증
echo ""
echo "[4/4] 환경 검증..."
$PYTHON -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}, MPS: {getattr(torch.backends, \"mps\", None) and torch.backends.mps.is_available()}')"
if [ "$STT_PROFILE" = "gpu" ]; then
    $PYTHON -c "import whisperx; print('WhisperX OK')" 2>/dev/null || echo "WhisperX: 설치 필요"
elif [ "$STT_PROFILE" = "mac" ]; then
    $PYTHON -c "import mlx_whisper; print('mlx-whisper OK')" 2>/dev/null || echo "mlx-whisper: 설치 필요"
    $PYTHON -c "import pyannote.audio; print('pyannote.audio OK')" 2>/dev/null || echo "pyannote.audio: 설치 필요"
fi

if [ "$OS" = "Linux" ]; then
    if $PYTHON -c "import gi; gi.require_version('WebKit2','4.1')" 2>/dev/null \
       || $PYTHON -c "import gi; gi.require_version('WebKit2','4.0')" 2>/dev/null; then
        echo "WebKitGTK 백엔드 OK"
    else
        echo "WebKitGTK 백엔드: 미설치 — app_webview.py 창이 안 뜰 수 있습니다 (위 안내 참고. CLI / Streamlit 는 무관)."
    fi
fi

echo ""
echo "================================================"
echo "    설정 완료!"
echo ""
echo "    실행 (권장 — venv activate 불필요):"
echo "      .venv/bin/python app_webview.py   # 권장 UI (React/PyWebView)"
echo "      bash run_desktop.sh               # 데스크톱 앱 (CustomTkinter, v0.8 호환)"
echo "      bash run_web.sh                   # 웹 앱 (Streamlit, v0.8 호환)"
echo ""
echo "    직접 실행:"
echo "      .venv/bin/python gui.py"
echo "      .venv/bin/streamlit run app.py"
echo "================================================"

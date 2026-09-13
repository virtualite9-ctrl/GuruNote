"""
GuruNote 데스크톱 배포 패키징 도우미.

목표:
- Windows: 단일 실행 파일(.exe) + (선택) Inno Setup 설치 프로그램(.exe)
- macOS: GuruNote.app + (선택) DMG / PKG

사용 예시:
    python scripts/package_desktop.py --target windows
    python scripts/package_desktop.py --target macos --formats dmg pkg

⚠️ 번들 STT 엔진 정책:
  PyInstaller 번들에는 **공통 의존성(requirements.txt) 만** 포함되며 로컬 GPU
  STT 엔진(WhisperX / mlx-whisper / pyannote) 은 의도적으로 제외된다. 사유:
    - WhisperX(+CUDA PyTorch) ~3GB / MLX+pyannote+torch ~2GB 의 native binary
    - CUDA 빌드는 GPU 러너 필요 (GitHub Actions 표준 러너 미제공)
    - PyInstaller --onefile 로 묶으면 다운로드/시동 비용 비현실적
  → 번들 패키지는 UI + AssemblyAI Cloud STT 만 동작. 로컬 GPU STT 가 필요한
    사용자는 README 의 "🚀 설치" 섹션을 따라 소스에서 `bash setup.sh` 후
    `python gui.py` 로 실행해야 한다.

CI 아티팩트 명명:
  로컬 빌드는 `dist/GuruNote.exe` / `dist/GuruNote.dmg` 등 generic 이름을 쓰고,
  GitHub Actions(`.github/workflows/release-desktop.yml`) 가 Release 업로드 시
  `GuruNote-Windows.exe` / `GuruNote-macOS.dmg` 등 플랫폼 suffix 를 추가한다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI_ENTRY = ROOT / "gui.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
APP_NAME = "GuruNote"


def _run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _require_gui_entry() -> None:
    if not GUI_ENTRY.exists():
        raise FileNotFoundError(f"gui.py 를 찾을 수 없습니다: {GUI_ENTRY}")


def _clean_previous() -> None:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    # dist 는 결과물을 확인할 수 있게 남긴다.


def build_windows() -> Path:
    """Windows용 단일 실행 파일 빌드."""
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onefile",
            "--name",
            APP_NAME,
            str(GUI_ENTRY),
        ]
    )
    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    if not exe_path.exists():
        raise RuntimeError(f"빌드 결과물(.exe)을 찾을 수 없습니다: {exe_path}")
    print(f"\n✅ Windows 실행 파일 생성 완료: {exe_path}")
    return exe_path


def _find_iscc() -> str | None:
    # Inno Setup command line compiler
    candidates = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def build_windows_installer(exe_path: Path) -> Path | None:
    """
    Inno Setup 이 설치된 경우 설치형 exe 생성.
    미설치 시 안내 메시지만 출력하고 None 반환.
    """
    iscc = _find_iscc()
    if not iscc:
        print(
            "\n⚠️ Inno Setup(ISCC)을 찾지 못해 설치형 exe 생성은 건너뜁니다.\n"
            "   설치: https://jrsoftware.org/isdl.php"
        )
        return None

    iss_path = BUILD_DIR / "gurunote_installer.iss"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    dist_dir_escaped = str(DIST_DIR).replace("\\", "\\\\")
    exe_path_escaped = str(exe_path).replace("\\", "\\\\")
    script = f"""
#define MyAppName "{APP_NAME}"
#define MyAppVersion "1.0.0.2"
#define MyAppPublisher "GuruNote"
#define MyAppExeName "{exe_path.name}"

[Setup]
AppId={{{{{APP_NAME}}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DisableProgramGroupPage=yes
OutputDir={dist_dir_escaped}
OutputBaseFilename=GuruNote-Installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 아이콘 생성"; GroupDescription: "추가 작업:"

[Files]
Source: "{exe_path_escaped}"; DestDir: "{{app}}"; Flags: ignoreversion

[Icons]
Name: "{{autoprograms}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "GuruNote 실행"; Flags: nowait postinstall skipifsilent
"""
    iss_path.write_text(script.strip() + "\n", encoding="utf-8")
    _run([iscc, str(iss_path)])
    installer = DIST_DIR / "GuruNote-Installer.exe"
    if installer.exists():
        print(f"\n✅ Windows 설치 프로그램 생성 완료: {installer}")
        return installer
    print("\n⚠️ ISCC 실행은 성공했지만 예상 출력 파일을 찾지 못했습니다.")
    return None


def build_macos_app() -> Path:
    """macOS용 app bundle 빌드."""
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name",
            APP_NAME,
            str(GUI_ENTRY),
        ]
    )
    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        raise RuntimeError(f"빌드 결과물(.app)을 찾을 수 없습니다: {app_path}")
    print(f"\n✅ macOS 앱 번들 생성 완료: {app_path}")
    return app_path


def build_macos_dmg(app_path: Path) -> Path | None:
    create_dmg = shutil.which("create-dmg")
    if not create_dmg:
        print(
            "\n⚠️ create-dmg 를 찾지 못해 DMG 생성은 건너뜁니다.\n"
            "   설치: brew install create-dmg"
        )
        return None

    dmg_path = DIST_DIR / f"{APP_NAME}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    _run(
        [
            create_dmg,
            "--overwrite",
            "--dmg-title",
            APP_NAME,
            str(dmg_path),
            str(app_path.parent),
        ]
    )
    print(f"\n✅ DMG 생성 완료: {dmg_path}")
    return dmg_path


def build_macos_pkg(app_path: Path) -> Path | None:
    pkgbuild = shutil.which("pkgbuild")
    if not pkgbuild:
        print("\n⚠️ pkgbuild 를 찾지 못해 PKG 생성은 건너뜁니다.")
        return None

    staging = BUILD_DIR / "pkg-root"
    app_dst = staging / "Applications" / f"{APP_NAME}.app"
    shutil.rmtree(staging, ignore_errors=True)
    app_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_path, app_dst)

    pkg_path = DIST_DIR / f"{APP_NAME}.pkg"
    if pkg_path.exists():
        pkg_path.unlink()

    _run(
        [
            pkgbuild,
            "--root",
            str(staging),
            "--identifier",
            "com.gurunote.desktop",
            "--version",
            "1.0.0.2",
            str(pkg_path),
        ]
    )
    print(f"\n✅ PKG 생성 완료: {pkg_path}")
    return pkg_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GuruNote 데스크톱 패키징 스크립트")
    parser.add_argument(
        "--target",
        choices=["windows", "macos"],
        required=True,
        help="패키징 대상 OS",
    )
    parser.add_argument(
        "--formats",
        nargs="*",
        default=[],
        help=(
            "추가 패키지 포맷. windows: installer / macos: dmg pkg "
            "(예: --formats dmg pkg)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _require_gui_entry()
    _clean_previous()
    os.chdir(ROOT)

    if args.target == "windows":
        exe_path = build_windows()
        if "installer" in args.formats:
            build_windows_installer(exe_path)
        return

    app_path = build_macos_app()
    if "dmg" in args.formats:
        build_macos_dmg(app_path)
    if "pkg" in args.formats:
        build_macos_pkg(app_path)


if __name__ == "__main__":
    main()

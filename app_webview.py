"""GuruNote WebView UI — entrypoint.

Coexists with the existing CTk entrypoint (``app.py``). Run either::

    python3 app.py            # legacy CustomTkinter UI
    python3 app_webview.py    # new PyWebView UI (this file)

This is the Phase 1 MVP skeleton. The pipeline wiring is intentionally not
hooked up yet — clicking '생성하기' shows a stub alert. Phase 1-B will wire
``Api.start_pipeline`` to the existing ``PipelineWorker``.

See:
- ``docs/webview-ui/TECH_CHOICE.md`` — why PyWebView
- ``docs/webview-ui/ARCHITECTURE.md`` — process model, bridge, event bus
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The WebView UI has its own window chrome — we do not need the "redirect stdout
# to ~/.gurunote/gui.log" behavior that prevents Terminal foregrounding in the
# CTk app. Keeping stderr on the console makes pywebview + pipeline debugging
# much easier. setdefault respects an explicit user override.
os.environ.setdefault("GURUNOTE_NO_REDIRECT", "1")


def _install_hint() -> str:
    """OS 별 PyWebView 백엔드 설치 안내 문구.

    pywebview 는 플랫폼 네이티브 웹뷰(WKWebView / WebView2 / WebKitGTK)에 의존한다.
    특히 Linux 는 pip 패키지만으로 부족하고 시스템 WebKitGTK typelib 이 있어야 한다.
    """
    if sys.platform == "darwin":
        return (
            "Install with:  pip install 'pywebview>=4.4,<5.0'\n"
            "(Or run setup.sh to install all GuruNote deps.)\n"
        )
    if sys.platform == "win32":
        return (
            "Install with:  pip install 'pywebview>=4.4,<5.0'\n"
            "Windows 는 Edge WebView2 런타임이 필요할 수 있습니다:\n"
            "  https://developer.microsoft.com/microsoft-edge/webview2/\n"
            "(Or run setup.bat to install all GuruNote deps.)\n"
        )
    # Linux (및 기타 Unix) — WebKitGTK 백엔드
    return (
        "Linux 는 PyWebView 의 GTK/WebKit2 백엔드가 필요합니다.\n"
        "  1) 시스템 패키지 (sudo):\n"
        "       Debian/Ubuntu (구형은 gir1.2-webkit2-4.0):\n"
        "         sudo apt install -y gir1.2-webkit2-4.1 libgirepository1.0-dev \\\n"
        "                             libcairo2-dev pkg-config python3-dev gcc\n"
        "       Fedora/RHEL:\n"
        "         sudo dnf install -y webkit2gtk4.1 gobject-introspection-devel \\\n"
        "                             cairo-gobject-devel pkgconf-pkg-config python3-devel gcc\n"
        "  2) pip install 'pywebview[gtk]>=4.4,<5.0'\n"
        "(Or run setup.sh to install all GuruNote deps — 위 과정을 점검/안내합니다.)\n"
    )


def main() -> int:
    try:
        import webview
    except ImportError:
        sys.stderr.write("pywebview is not installed.\n" + _install_hint())
        return 1

    # Linux: pywebview 자체는 import 되어도 GTK/WebKit2 백엔드가 없으면 창 생성
    # 시점에 불분명한 예외로 죽는다. 백엔드 존재 여부를 먼저 확인해 명확한 설치
    # 안내로 실패시킨다. (macOS/Windows 는 네이티브 웹뷰가 OS 에 내장되어 생략.)
    if sys.platform.startswith("linux"):
        try:
            import gi  # noqa: PLC0415

            try:
                gi.require_version("WebKit2", "4.1")
            except ValueError:
                gi.require_version("WebKit2", "4.0")
        except Exception:  # noqa: BLE001 — gi 미설치(ImportError)·버전 부재(ValueError) 모두
            sys.stderr.write(
                "PyWebView 의 GTK/WebKit2 백엔드를 불러오지 못했습니다.\n"
                + _install_hint()
            )
            return 1

    # Load .env before any bridge method reads os.environ. start_pipeline's
    # preflight checks (OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY /
    # OPENAI_BASE_URL) run before PipelineSession triggers the gui import
    # whose module-level load_dotenv() would otherwise fire. Mirrors app.py:56.
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv()

    from gurunote.webui.bridge import Api

    # Resolve index.html relative to this file so it works both in dev
    # (running from source) and once packaged by PyInstaller (where __file__
    # is inside the bundle).
    here = Path(__file__).resolve().parent
    index_path = here / "gurunote" / "webui" / "index.html"
    if not index_path.exists():
        sys.stderr.write(f"index.html not found at {index_path}\n")
        return 2

    api = Api()
    window = webview.create_window(
        title="GuruNote",
        url=str(index_path),
        js_api=api,
        width=1280,
        height=820,
        min_size=(960, 600),
        # frameless=False, easy_drag=False — keep native window chrome on macOS
    )
    api.bind_window(window)

    # webview.start() blocks the main thread until the window is closed.
    # All long-running work (PipelineWorker etc.) must be spawned on
    # background threads from within Bridge methods.
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

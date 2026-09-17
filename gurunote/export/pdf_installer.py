"""
PDF 출력 의존성 자동 설치 도우미.

사용자가 "Save PDF" 를 눌렀을 때 패키지가 없으면 (이전엔 경고만 띄웠던 곳을)
**설치 여부를 묻는 다이얼로그** 로 전환하고, 사용자가 승인하면 이 모듈이
실제 설치 커맨드를 실행한다.

설치 대상 2종:
  1) Python 패키지 (`markdown`, `weasyprint`) — `pip install` 로 항상 자동 처리.
  2) 시스템 라이브러리 (cairo/pango/gdk-pixbuf/libffi) — macOS + brew 환경에서
     자동 실행 가능. Linux/Windows 는 OS 패키지 관리자가 sudo 를 요구하거나
     이미 포함돼 있어 수동 처리. 미지원 환경에서는 사용자에게 수동 명령을
     보여주고 자동 실행은 스킵.

진행 상황은 `ProgressFn` 콜백으로 한 줄씩 보고된다 — GUI 는 이걸 CTkTextbox
로 스트리밍한다.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

ProgressFn = Callable[[str], None]


# =============================================================================
# 상태 감지
# =============================================================================
def is_python_deps_ok() -> bool:
    """markdown + weasyprint import 가능 여부 (시스템 라이브러리 포함)."""
    try:
        import markdown  # type: ignore  # noqa: F401
        import weasyprint  # type: ignore  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _is_pip_only_missing() -> bool:
    """Python 레벨 import 만 실패하는지 (= pip install 만 하면 됨)."""
    try:
        import markdown  # type: ignore  # noqa: F401
    except Exception:  # noqa: BLE001
        return True
    try:
        import weasyprint  # type: ignore
    except ImportError:
        return True
    except Exception:  # noqa: BLE001
        # OSError / cffi.VerificationError 등 — 시스템 라이브러리 문제
        return False
    return False


def has_brew() -> bool:
    return shutil.which("brew") is not None


# =============================================================================
# 설치 플랜
# =============================================================================
@dataclass
class InstallStep:
    label: str  # 사용자에게 보일 설명
    cmd: List[str]  # 실제 실행할 커맨드
    requires_sudo: bool = False  # True 면 자동 실행하지 않고 안내만


@dataclass
class InstallPlan:
    steps: List[InstallStep]
    manual_instructions: Optional[str] = None  # 자동 실행 불가 환경 안내
    can_run_automatically: bool = True

    @property
    def is_empty(self) -> bool:
        return not self.steps and not self.manual_instructions


def _pip_install_cmd() -> List[str]:
    return [
        sys.executable, "-m", "pip", "install", "--upgrade",
        "markdown>=3.5", "weasyprint>=60",
    ]


def plan_installation() -> InstallPlan:
    """현재 OS + 환경을 감지해 설치 플랜 반환."""
    system = platform.system()

    # 이미 모든 게 OK 면 빈 플랜
    if is_python_deps_ok():
        return InstallPlan(steps=[], can_run_automatically=True)

    # Python 패키지만 빠진 경우 — 어느 OS든 pip 로 해결
    if _is_pip_only_missing():
        return InstallPlan(
            steps=[InstallStep(
                label="Python 패키지 설치 (markdown + weasyprint)",
                cmd=_pip_install_cmd(),
            )],
            can_run_automatically=True,
        )

    # 시스템 라이브러리 부재 — OS 별 분기
    if system == "Darwin":
        if has_brew():
            return InstallPlan(
                steps=[
                    InstallStep(
                        label="Homebrew 로 cairo / pango / gdk-pixbuf / libffi 설치",
                        cmd=["brew", "install", "cairo", "pango", "gdk-pixbuf", "libffi"],
                    ),
                    InstallStep(
                        label="Python 패키지 설치 (markdown + weasyprint)",
                        cmd=_pip_install_cmd(),
                    ),
                ],
                can_run_automatically=True,
            )
        return InstallPlan(
            steps=[],
            manual_instructions=(
                "Homebrew 가 감지되지 않았습니다.\n\n"
                "다음 명령을 터미널에서 실행한 뒤 앱을 재시작하세요:\n\n"
                "  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/"
                "Homebrew/install/HEAD/install.sh)\"\n"
                "  brew install cairo pango gdk-pixbuf libffi\n"
                f"  {' '.join(_pip_install_cmd())}"
            ),
            can_run_automatically=False,
        )

    if system == "Linux":
        # sudo 가 필요한 apt / dnf 등은 GUI 에서 비밀번호 입력을 받기 어려워
        # 자동 실행 대신 명령을 보여준다.
        return InstallPlan(
            steps=[],
            manual_instructions=(
                "시스템 라이브러리 설치에 sudo 권한이 필요합니다.\n\n"
                "터미널에서 실행한 뒤 앱을 재시작하세요:\n\n"
                "  sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk\n"
                f"  {' '.join(_pip_install_cmd())}"
            ),
            can_run_automatically=False,
        )

    # Windows — weasyprint wheel 에 DLL 포함이므로 pip 만으로 충분한 게 정상.
    # 여기 도달했다는 건 pip 단계 실패 또는 특수한 경우. pip 재시도를 제안.
    return InstallPlan(
        steps=[InstallStep(
            label="Python 패키지 설치 (markdown + weasyprint)",
            cmd=_pip_install_cmd(),
        )],
        can_run_automatically=True,
    )


# =============================================================================
# 실행
# =============================================================================
def _stream_cmd(cmd: List[str], log: ProgressFn) -> int:
    """서브프로세스 실행, stdout/stderr 한 줄씩 `log` 로 방출, 종료 코드 반환."""
    log(f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        log(f"[오류] 커맨드를 찾을 수 없습니다: {cmd[0]}")
        return 127
    except Exception as exc:  # noqa: BLE001
        log(f"[오류] 실행 실패: {exc}")
        return 1

    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    return proc.wait()


def run_plan(plan: InstallPlan, log: ProgressFn) -> bool:
    """플랜의 모든 스텝을 순서대로 실행. 한 스텝이라도 실패하면 False."""
    if not plan.can_run_automatically:
        if plan.manual_instructions:
            log(plan.manual_instructions)
        return False
    if not plan.steps:
        log("설치할 것이 없습니다 (이미 준비됨).")
        return True

    for i, step in enumerate(plan.steps, start=1):
        log(f"\n[{i}/{len(plan.steps)}] {step.label}")
        rc = _stream_cmd(step.cmd, log)
        if rc != 0:
            log(f"\n[실패] 종료 코드 {rc} — 설치를 중단합니다.")
            return False

    # 검증 — import 뿐 아니라 실제 cffi native 로드까지 smoke-test
    from gurunote.export.pdf_export import is_pdf_export_available
    if not is_pdf_export_available(force_recheck=True):
        log(
            "\n[경고] 설치 커맨드는 성공했지만 weasyprint 가 여전히 동작하지 않습니다.\n"
            "cairo/pango 등 native 라이브러리 경로 문제일 수 있습니다. 앱을 재시작해 보세요."
        )
        return False

    log("\n[성공] PDF 출력 패키지가 준비되었습니다.")
    return True

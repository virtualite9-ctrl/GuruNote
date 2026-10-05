"""Inspectable, local-only test runner; run with the parent-provided interpreter."""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".test-artifacts"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="unit")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--lazy", action="store_true")
    args, pytest_args = parser.parse_known_args()
    home = ARTIFACTS / "home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ.update(HOME=str(home), XDG_CACHE_HOME=str(home / ".cache"),
                      HF_HOME=str(home / ".cache/huggingface"),
                      NUMBA_CACHE_DIR=str(home / ".cache/numba"),
                      PYTHONDONTWRITEBYTECODE="1")
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        os.environ.pop(name, None)
    sys.path.insert(0, str(ROOT))
    import gurunote
    assert Path(gurunote.__file__).resolve() == ROOT / "gurunote/__init__.py"
    print(f"gurunote.__file__={gurunote.__file__}", flush=True)
    if args.lazy:
        attempted = []

        class NoModels(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in {
                    "torch", "resemblyzer", "numpy", "librosa", "pyannote", "huggingface_hub"
                }:
                    attempted.append(fullname)
                    raise ImportError(f"Optional model import blocked: {fullname}")

        sys.meta_path.insert(0, NoModels())
        import gurunote.diarization
        import gurunote.stt
        import gurunote.stt_mlx
        import gurunote.mcp_server
        assert attempted == [], attempted
        print("lazy imports: STT, diarization and MCP imported without optional model packages")
        return 0
    if args.probe:
        versions = {}
        for name in ("pytest", "numpy", "torch", "resemblyzer", "librosa", "soundfile"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = None
        missing = [name for name in ("numpy", "torch", "resemblyzer", "librosa")
                   if versions[name] is None]
        if missing:
            try:
                importlib.import_module("resemblyzer")
            except Exception:
                (ARTIFACTS / "actual-model-preflight-failure.log").write_text(traceback.format_exc())
        report = {
            "source": gurunote.__file__, "versions": versions,
            "actual_model_smoke": {
                "status": "blocked" if missing else "not_run",
                "missing_dependencies": missing, "model_executed": False,
                "reason": "Parent owns dependency installation; no public speech fixture loaded",
                "credentials_present": False,
                "audio_fixture": None, "checkpoint_sha256": None,
            },
            "upstream": {
                "source": "https://github.com/resemble-ai/Resemblyzer",
                "license": "https://github.com/resemble-ai/Resemblyzer/blob/master/LICENSE",
                "api": "https://github.com/resemble-ai/Resemblyzer/blob/master/resemblyzer/voice_encoder.py",
                "package": "Resemblyzer==0.1.4", "checkpoint": "bundled resemblyzer/pretrained.pt",
            },
        }
        (ARTIFACTS / "environment.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 0
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
               "--basetemp", str(home / "pytest-tmp"), *pytest_args]
    result = subprocess.run(command, cwd=ROOT, env=os.environ.copy(),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (ARTIFACTS / f"{args.label}.log").write_text(
        f"source={gurunote.__file__}\ncommand={command!r}\nexit={result.returncode}\n" + result.stdout)
    print(result.stdout, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

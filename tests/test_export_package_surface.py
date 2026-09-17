"""`gurunote/export` 패키지 표면 — 파일 분할 후에도 바뀌지 않아야 하는 것들.

1. 기존 호출부가 쓰던 이름이 패키지 레벨에서 그대로 보여야 한다 (`gurunote.export.save_to_vault`).
2. 하위 모듈끼리 이름을 직접 import 하면 patch 지점이 흩어진다 — pdf_installer 는
   pdf_export 의 함수를 함수 안에서 lazy import 하므로, 호출 시점에 정의 모듈을
   patch 하면 반영된다. 그 계약을 실제 patch 로 고정한다.
3. `missing_packages_hint` 는 pdf_export 와 notion_sync 양쪽에 존재하지만 의미가 달라
   패키지 레벨로 re-export 하지 않기로 했다 — 이 결정도 고정한다.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

import gurunote.export as export

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "gurunote" / "export"
SUBMODULES = ("exporter", "notion_sync", "obsidian", "pdf_export", "pdf_installer")


class TestPublicSurfaceSurvived:
    @pytest.mark.parametrize("name", [
        "build_gurunote_markdown", "autosave_result",
        "save_to_notion", "is_notion_sync_available",
        "save_to_vault", "is_obsidian_vault",
        "markdown_to_pdf", "is_pdf_export_available",
        "plan_installation",
    ])
    def test_public_names_importable_from_the_package(self, name):
        assert hasattr(export, name), name

    @pytest.mark.parametrize("name", [
        "AUTOSAVE_DIR", "LANGUAGE_FLAG", "LANGUAGE_LABEL",
        "sanitize_filename", "build_chapters_section",
        "build_full_script_section", "build_original_script_section",
        "DEFAULT_SUBFOLDER", "delete_from_vault", "find_vault_candidates",
        "find_vault_copies", "resolve_subfolder", "resolve_vault_path",
        "has_brew", "is_python_deps_ok", "run_plan", "InstallPlan", "InstallStep",
    ])
    def test_internals_the_tests_rely_on_are_still_re_exported(self, name):
        assert hasattr(export, name), name

    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_every_public_name_is_re_exported(self, mod_name):
        mod = importlib.import_module(f"gurunote.export.{mod_name}")
        missing = [n for n in getattr(mod, "__all__", ())
                   if not hasattr(export, n)]
        assert missing == [], f"{mod_name}: {missing}"

    def test_ambiguous_hint_is_not_re_exported(self):
        """pdf_export / notion_sync 양쪽에 같은 이름이 있어 패키지 노출은 의도적으로 배제."""
        assert not hasattr(export, "missing_packages_hint")


class TestSubmodulesImportCleanly:
    @pytest.mark.parametrize("mod_name", SUBMODULES)
    def test_each_submodule_imports_on_its_own(self, mod_name):
        """순환 import 가 생기면 하위 모듈 단독 import 가 깨진다."""
        code = f"import gurunote.export.{mod_name} as m; print(m.__name__)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr


class TestPatchTargetContract:
    """pdf_export 를 patch 하면 pdf_installer 쪽에서도 그걸 봐야 한다."""

    def test_patching_pdf_export_is_observed_by_pdf_installer(self):
        from gurunote.export import pdf_installer
        from gurunote.export.pdf_installer import InstallPlan, InstallStep

        plan = InstallPlan(steps=[InstallStep(
            label="noop", cmd=[sys.executable, "-c", "pass"])])
        logs: list[str] = []
        with patch("gurunote.export.pdf_export.is_pdf_export_available",
                   return_value=True) as mock:
            ok = pdf_installer.run_plan(plan, log=logs.append)
        assert ok is True
        assert mock.called, "pdf_installer 가 pdf_export 를 patch 한 효과를 보지 못한다"

    def test_no_top_level_name_imports_from_a_sibling(self):
        """`from gurunote.export.<sibling> import name` 은 모듈 레벨에서 금지.

        함수 안 lazy import 는 호출 시점에 다시 실행되므로 patch 계약을 지킨다 —
        허용한다 (pdf_installer → pdf_export).
        """
        offenders = []
        for mod_name in SUBMODULES:
            tree = ast.parse((PKG / f"{mod_name}.py").read_text(encoding="utf-8"))
            for node in tree.body:  # 모듈 레벨만
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.module.startswith("gurunote.export."):
                    offenders.append(f"{mod_name}: {node.module} -> "
                                     f"{[a.name for a in node.names]}")
        assert offenders == [], offenders


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
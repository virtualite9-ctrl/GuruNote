"""내보내기(Export) 모음: Markdown/PDF/Obsidian/Notion.

원래 루트에 있던 `exporter.py`, `pdf_export.py`, `pdf_installer.py`,
`obsidian.py`, `notion_sync.py` 다섯 파일을 패키지로 모았다.

의존 방향은 한쪽으로만 흐른다: pdf_installer → pdf_export.
나머지 네 모듈은 서로를 import 하지 않는다(공통 유틸은 각자 소유).

기존 `from gurunote.exporter import X` 등은 `from gurunote.export.exporter
import X` 로 바뀐다. 여기서는 공개 이름을 re-export 해 두지만, `pdf_export` 와
`notion_sync` 가 `missing_packages_hint` 등 같은 이름의 유틸을 각자 들고 있으므로
이름이 겹치는 것들은 패키지 레벨에서 내보내지 않는다 — 서브모듈 경로가 기준이다.
"""
from __future__ import annotations

from gurunote.export.exporter import (  # noqa: F401
    AUTOSAVE_DIR,
    LANGUAGE_FLAG,
    LANGUAGE_LABEL,
    autosave_result,
    build_chapters_section,
    build_full_script_section,
    build_gurunote_markdown,
    build_original_script_section,
    sanitize_filename,
)
from gurunote.export.notion_sync import (  # noqa: F401
    is_notion_sync_available,
    save_to_notion,
)
from gurunote.export.obsidian import (  # noqa: F401
    DEFAULT_SUBFOLDER,
    delete_from_vault,
    find_vault_candidates,
    find_vault_copies,
    is_obsidian_vault,
    resolve_subfolder,
    resolve_vault_path,
    save_to_vault,
)
from gurunote.export.pdf_export import (  # noqa: F401
    is_pdf_export_available,
    markdown_to_pdf,
)
from gurunote.export.pdf_installer import (  # noqa: F401
    InstallPlan,
    InstallStep,
    ProgressFn,
    has_brew,
    is_python_deps_ok,
    plan_installation,
    run_plan,
)
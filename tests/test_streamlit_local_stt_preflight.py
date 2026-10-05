"""Guard the legacy Streamlit preflight without importing/running its UI."""
import ast
from pathlib import Path


def test_only_explicit_whisperx_triggers_install_or_cloud_prompt():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app.py").read_text(encoding="utf-8"))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "needs_whisperx" for t in node.targets)]
    assert len(assignments) == 1
    expected = ast.parse('engine_to_use == "whisperx"', mode="eval").body
    assert ast.dump(assignments[0].value) == ast.dump(expected)

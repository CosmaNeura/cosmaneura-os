"""Guard stock Mac Python 3.9.6 import of compose-portable-iphone.py."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "scripts/compose-portable-iphone.py"


def _source() -> str:
    return PORTABLE.read_text(encoding="utf-8")


def test_compose_portable_iphone_starts_with_future_annotations() -> None:
    source = _source()
    tree = ast.parse(source)
    body = tree.body
    assert body, "compose-portable-iphone.py must not be empty"
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
        assert len(body) >= 2, "missing from __future__ import annotations after docstring"
        first = body[1]
    assert isinstance(first, ast.ImportFrom), "expected from __future__ import annotations"
    assert first.module == "__future__"
    assert any(alias.name == "annotations" for alias in first.names)

    # Shebang may precede the module docstring; after any docstring the next
    # non-blank, non-comment statement must be the future import.
    stripped = re.sub(r"^#!.*\n", "", source, count=1)
    stripped = re.sub(
        r'^("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')\s*',
        "",
        stripped,
        count=1,
    )
    first_line = next(
        (
            line
            for line in stripped.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        "",
    )
    assert first_line == "from __future__ import annotations"


def test_compose_portable_iphone_compiles_without_pep604_runtime() -> None:
    source = _source()
    compile(source, str(PORTABLE), "exec")
    # Annotation-only PEP 604 unions are fine once postponed evaluation is on.
    # Fail the suite (report) if a runtime bitwise-or of types remains.
    tree = ast.parse(source)
    annotation_ids = set()
    for node in ast.walk(tree):
        annotation = getattr(node, "annotation", None)
        if annotation is not None:
            annotation_ids.add(id(annotation))
            for child in ast.walk(annotation):
                annotation_ids.add(id(child))
        returns = getattr(node, "returns", None)
        if returns is not None:
            annotation_ids.add(id(returns))
            for child in ast.walk(returns):
                annotation_ids.add(id(child))

    runtime_unions: list[str] = []
    for node in ast.walk(tree):
        if id(node) in annotation_ids:
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            runtime_unions.append(
                f"line {getattr(node, 'lineno', '?')}: runtime X | Y "
                "(not an annotation); report instead of fixing for this ticket"
            )
    assert not runtime_unions, "; ".join(runtime_unions)

#!/usr/bin/env python3
"""Read the selected release schema without importing application or migration code."""

from __future__ import annotations

import ast
import json
import os
import re
import stat
import symtable
import sys
from pathlib import Path

# Adapted from W85/W92 prepare_release.py's literal_fields/verify_os_schema.
# The protected runner uses Python 3.10 and its already verified source checkout.
MAX_SOURCE_BYTES = 4_000_000
MAX_MIGRATIONS = 512
_REVISION = re.compile(r"[a-zA-Z0-9_]{1,64}")


class ReleaseSchemaError(ValueError):
    """Selected source, migration graph or release metadata is inconsistent."""


class _ComprehensionScopes(ast.NodeTransformer):
    """Keep lexical scopes explicit when newer Python versions inline comprehensions."""

    def visit_ListComp(self, node: ast.ListComp | ast.SetComp) -> ast.GeneratorExp:
        self.generic_visit(node)
        return ast.copy_location(ast.GeneratorExp(elt=node.elt, generators=node.generators), node)

    visit_SetComp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> ast.GeneratorExp:
        self.generic_visit(node)
        pair = ast.Tuple(elts=[node.key, node.value], ctx=ast.Load())
        return ast.copy_location(ast.GeneratorExp(elt=pair, generators=node.generators), node)


def _source_path(root: Path, relative: str) -> Path:
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ReleaseSchemaError("schema source symlinks are forbidden")
    return path


def _read(root: Path, relative: str, limit: int = MAX_SOURCE_BYTES) -> str:
    path = _source_path(root, relative)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ReleaseSchemaError("schema source must be a regular file")
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ReleaseSchemaError("schema source exceeds its size limit")
        return raw.decode("utf-8")
    except (OSError, UnicodeError):
        raise ReleaseSchemaError("schema source is unavailable or invalid") from None


def _literal_fields(root: Path, relative: str, names: set[str]) -> dict[str, object]:
    try:
        source = _read(root, relative)
        tree = ast.parse(source)
        symtable.symtable(source, relative, "exec")
        values: dict[str, object] = {}
        allowed_targets: list[ast.Name] = []
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name) and target.id in names:
                    if target.id in values:
                        raise ReleaseSchemaError("schema metadata is ambiguous")
                    assert isinstance(node, (ast.Assign, ast.AnnAssign))
                    if node.value is None:
                        raise ReleaseSchemaError("schema metadata is missing")
                    values[target.id] = ast.literal_eval(node.value)
                    allowed_targets.append(target)
        if set(values) != names:
            raise ReleaseSchemaError("schema metadata is missing")
        # Exclude only the accepted literal bindings from this temporary AST.
        # Python's symbol tables distinguish remaining module/global writes
        # from function, class and comprehension locals without executing code.
        for target in allowed_targets:
            target.id = "__cosmas_validated_literal__"
        tree = _ComprehensionScopes().visit(tree)
        pending = [symtable.symtable(ast.unparse(tree), relative, "exec")]
        while pending:
            scope = pending.pop()
            for symbol in scope.get_symbols():
                if (symbol.get_name() in names and symbol.is_global()
                        and (symbol.is_assigned() or symbol.is_imported())):
                    raise ReleaseSchemaError("schema metadata is ambiguous")
            pending.extend(scope.get_children())
        return values
    except (SyntaxError, UnicodeError, TypeError, ValueError, RecursionError) as error:
        if isinstance(error, ReleaseSchemaError):
            raise
        raise ReleaseSchemaError("schema metadata must use literal declarations") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseSchemaError("duplicate release schema field")
        result[key] = value
    return result


def validate_release_schema(repository: Path) -> str:
    if repository.is_symlink() or not repository.is_dir():
        raise ReleaseSchemaError("selected source checkout is invalid")
    root = repository.resolve(strict=True)
    try:
        contract = json.loads(_read(root, "infra/beta/environment/release-schema.json", 4096),
                              object_pairs_hook=_unique_object)
    except json.JSONDecodeError:
        raise ReleaseSchemaError("release schema JSON is invalid") from None
    if (not isinstance(contract, dict) or set(contract) != {"version", "schema_revision"}
            or type(contract["version"]) is not int or contract["version"] != 1):
        raise ReleaseSchemaError("release schema contract is invalid")
    expected = contract["schema_revision"]
    if not isinstance(expected, str) or not _REVISION.fullmatch(expected):
        raise ReleaseSchemaError("release schema revision is invalid")
    runtime = _literal_fields(root, "src/cosmas_os/runtime_schema.py", {"EXPECTED_SCHEMA_REVISION"})
    if runtime["EXPECTED_SCHEMA_REVISION"] != expected:
        raise ReleaseSchemaError("runtime and release schema differ")
    directory = _source_path(root, "migrations/versions")
    if not directory.is_dir():
        raise ReleaseSchemaError("migration source directory is missing")
    paths = sorted(path for path in directory.glob("*.py") if path.name != "__init__.py")
    if not 1 <= len(paths) <= MAX_MIGRATIONS:
        raise ReleaseSchemaError("migration source inventory is invalid")
    graph: dict[str, list[str]] = {}
    for path in paths:
        meta = _literal_fields(root, path.relative_to(root).as_posix(),
                               {"revision", "down_revision", "depends_on"})
        revision, parents = meta["revision"], meta["down_revision"]
        if (not isinstance(revision, str) or not _REVISION.fullmatch(revision)
                or revision in graph or meta["depends_on"] is not None):
            raise ReleaseSchemaError("migration graph metadata is invalid")
        parents = [] if parents is None else [parents] if isinstance(parents, str) else parents
        if (not isinstance(parents, (list, tuple))
                or any(not isinstance(parent, str) or not _REVISION.fullmatch(parent) for parent in parents)
                or len(set(parents)) != len(parents)):
            raise ReleaseSchemaError("migration parents are invalid")
        graph[revision] = list(parents)
    referenced = {parent for parents in graph.values() for parent in parents}
    if not referenced <= set(graph) or set(graph) - referenced != {expected}:
        raise ReleaseSchemaError("migration graph does not have the selected sole head")
    visited: set[str] = set()
    active: set[str] = set()

    def visit(revision: str) -> None:
        if revision in active:
            raise ReleaseSchemaError("migration graph contains a cycle")
        if revision in visited:
            return
        active.add(revision)
        for parent in graph[revision]:
            visit(parent)
        active.remove(revision)
        visited.add(revision)

    visit(expected)
    if visited != set(graph):
        raise ReleaseSchemaError("migration graph is disconnected")
    return expected


def main() -> int:
    if len(sys.argv) != 1:
        print("Release schema validation accepts no path or revision overrides", file=sys.stderr)
        return 1
    try:
        print(validate_release_schema(Path(__file__).resolve().parents[2]))
    except (ReleaseSchemaError, OSError, RecursionError) as error:
        print(f"Release schema refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

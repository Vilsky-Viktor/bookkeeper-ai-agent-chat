"""Checks CLAUDE.md's rule 2 for Python: an empty line before every block statement
(if/for/while/try/with/match, nested def/class) and every return, unless it's the
first statement of its enclosing block. Comments and decorators right above a
statement belong to it, so the empty line goes above them.

    python scripts/blank_lines.py [--fix] PATH...
"""

import ast
import sys
from pathlib import Path

BLOCKS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Return,
)


def statement_lists(tree: ast.AST):
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody", "handlers"):
            stmts = getattr(node, field, None)

            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.AST):
                yield stmts

        if isinstance(node, ast.Match):
            for case in node.cases:
                yield case.body


def missing_lines(source: str) -> list[int]:
    """0-based indexes of lines that need an empty line inserted above them."""
    lines = source.splitlines()
    missing = set()

    for stmts in statement_lists(ast.parse(source)):
        for prev, stmt in zip(stmts, stmts[1:]):
            if not isinstance(stmt, BLOCKS) or stmt.lineno == prev.end_lineno:
                continue

            first = min([stmt.lineno] + [d.lineno for d in getattr(stmt, "decorator_list", [])]) - 1

            while first > 0 and lines[first - 1].strip().startswith("#"):
                first -= 1

            if first > 0 and lines[first - 1].strip():
                missing.add(first)

    return sorted(missing)


def main(args: list[str]) -> int:
    fix = "--fix" in args
    files = [f for p in args if p != "--fix" for f in (Path(p).rglob("*.py") if Path(p).is_dir() else [Path(p)])]
    failed = 0

    for path in files:
        source = path.read_text()
        missing = missing_lines(source)

        if not missing:
            continue

        if fix:
            lines = source.splitlines(keepends=True)

            for index in reversed(missing):
                lines.insert(index, "\n")

            path.write_text("".join(lines))
        else:
            failed += 1

            for index in missing:
                print(f"{path}:{index + 1}: needs an empty line above (CLAUDE.md rule 2)")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Find names used in a function that were only imported inside another one.

`ast.parse()` accepts this happily and the failure only appears when the
function actually runs, which for a background menu-bar app can be days later.
flo.py shipped exactly this: doctor() referenced `Path` while the sole
`from pathlib import Path` lived inside self_test().

Run:  python3 tools/check_module_imports.py *.py
"""
import ast
import builtins
import sys

BUILTIN = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def _module_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    names.add(t.id)
        elif isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    names.add(t.id)
                elif isinstance(t, (ast.Import, ast.ImportFrom)):
                    names.update((a.asname or a.name).split(".")[0]
                                 for a in t.names)
    return names


def _bound_in(fn):
    """Everything a function binds: imports, assignments, args, except-as,
    comprehension targets, and nested def/class names."""
    bound = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            bound.update(n.names)
    return bound


def _outermost_functions(tree):
    """Top-level functions and methods only. Nested functions are checked as
    part of their parent, so a closure using an enclosing local is not flagged."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
        elif isinstance(node, ast.ClassDef):
            out += [n for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return out


def check(path):
    tree = ast.parse(open(path).read(), path)
    top = _module_names(tree)
    problems = []
    for fn in _outermost_functions(tree):
        # Names bound anywhere in the function INCLUDING its nested defs — a
        # closure reading its enclosing scope is ordinary Python, not a bug.
        bound = _bound_in(fn)
        for n in ast.walk(fn):
            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    and n.id not in bound and n.id not in top
                    and n.id not in BUILTIN):
                problems.append(
                    f"{path}:{n.lineno}: {fn.name}() uses {n.id!r}, which is "
                    "not defined at module level")
    return sorted(set(problems))


if __name__ == "__main__":
    failures = []
    for path in sys.argv[1:]:
        found = check(path)
        failures += found
        for line in found:
            print(line)
    print("FAIL" if failures else "clean: every name resolves at module level")
    sys.exit(1 if failures else 0)

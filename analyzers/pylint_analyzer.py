"""Module 3 - Pylint / Flake8 static analysis.

Every check combines our own AST analysis with the messages of the real Pylint and
Flake8 CLIs (run in the sandbox by static_tools.py). Findings on the same line and
category are merged, and the 'source' field shows which tools reported them.
"""
import ast
import builtins

from .base import (FAILED, PASSED, WARNING, finding, grade, is_stub, iter_functions,
                   merge_findings, not_evaluated, result, tests_for)

TOOL = "pylint"
# pylint symbol / flake8 code -> (index of the test, category)
PYLINT_MAP = {
    "unused-variable": (0, "unused-variable"), "unused-argument": (0, "unused-argument"),
    "unused-import": (0, "unused-import"), "wildcard-import": (1, "wildcard"),
    "redefined-builtin": (2, "builtin"), "too-many-nested-blocks": (3, "nesting"),
    "bare-except": (4, "bare-except"), "dangerous-default-value": (4, "mutable-default"),
    "too-many-arguments": (4, "too-many-args"), "unnecessary-pass": (4, "empty-block"),
    "undefined-variable": (4, "undefined"), "pointless-statement": (4, "pointless"),
    "duplicate-key": (4, "dup-key"),
}
FLAKE_MAP = {
    "F401": (0, "unused-import"), "F841": (0, "unused-variable"), "F403": (1, "wildcard"),
    "F811": (4, "redefinition"), "F821": (4, "undefined"),
}
SITE_BUILTINS = {"copyright", "credits", "license", "exit", "quit"}
BUILTIN_NAMES = {n for n in dir(builtins) if not n.startswith("_")} - SITE_BUILTINS
CONTROL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith,
           ast.Match)


def _tool_findings(ctx, index):
    out = []
    for m in ctx.tool_output.get("pylint", []):
        mapped = PYLINT_MAP.get(m["symbol"])
        if mapped and mapped[0] == index:
            out.append(finding(m["line"], m["message"], f"pylint {m['code']}", mapped[1]))
    for m in ctx.tool_output.get("flake8", []):
        mapped = FLAKE_MAP.get(m["code"])
        if mapped and mapped[0] == index:
            out.append(finding(m["line"], m["message"], f"flake8 {m['code']}", mapped[1]))
    return out


def _tools_note(ctx):
    errors = ctx.tool_output.get("errors", {})
    return " (Pylint/Flake8 unavailable: AST analysis only)" if "pylint" in errors and "flake8" in errors else ""


# ---------------------------------------------------------------- 01 unused
def _local_stores(func):
    """(name, line) of simple local assignments, skipping nested function bodies."""
    stores, stack = [], list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            targets = [node.target]
        elif isinstance(node, ast.NamedExpr):
            targets = [node.target]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            targets = [i.optional_vars for i in node.items if isinstance(i.optional_vars, ast.Name)]
        elif isinstance(node, ast.ExceptHandler) and node.name:
            stores.append((node.name, node.lineno))
        for t in targets:
            stores.append((t.id, t.lineno))
        stack.extend(ast.iter_child_nodes(node))
    return stores


def check_unused(ctx):
    tree, found = ctx.tree, []
    loaded_all = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
                  and isinstance(n.ctx, (ast.Load, ast.Del))}
    for name, func in iter_functions(tree):
        used = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)
                and isinstance(n.ctx, (ast.Load, ast.Del))}
        dynamic = used & {"locals", "vars", "eval", "exec"}
        declared = {x for n in ast.walk(func) if isinstance(n, (ast.Global, ast.Nonlocal))
                    for x in n.names}
        seen = set()
        for var, line in _local_stores(func):
            if var in used or var in declared or var.startswith("_") or var in seen or dynamic:
                continue
            seen.add(var)
            found.append(finding(line, f"Local variable '{var}' is assigned but never used "
                                       f"(in '{name}').", "AST", "unused-variable"))
        decorators = {d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                      for d in func.decorator_list}
        if is_stub(func) or func.name.startswith("__") or dynamic or \
                decorators & {"abstractmethod", "overload", "override"}:
            continue
        a = func.args
        for arg in a.posonlyargs + a.args + a.kwonlyargs:
            if arg.arg in ("self", "cls") or arg.arg.startswith("_") or arg.arg in used:
                continue
            found.append(finding(arg.lineno, f"Parameter '{arg.arg}' of '{name}' is never used.",
                                 "AST", "unused-argument"))
    exported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__"
                                                for t in node.targets):
            exported |= {e.value for e in ast.walk(node.value) if isinstance(e, ast.Constant)
                         and isinstance(e.value, str)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name.split(".")[0]
                if bound not in loaded_all and bound not in exported:
                    found.append(finding(node.lineno, f"Imported name '{bound}' is never used.",
                                         "AST", "unused-import"))
    return merge_findings(found, _tool_findings(ctx, 0))


# -------------------------------------------------------------- 02 wildcard
def check_wildcard(ctx):
    found = [finding(n.lineno, f"Wildcard import 'from {'.' * n.level}{n.module or ''} import *' "
                               "hides where names come from.", "AST", "wildcard")
             for n in ast.walk(ctx.tree)
             if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)]
    return merge_findings(found, _tool_findings(ctx, 1))


# ------------------------------------------------------------ 03 shadowing
def check_shadowing(ctx):
    tree, found = ctx.tree, []
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def add(name, line, what):
        if name in BUILTIN_NAMES:
            found.append(finding(line, f"{what} '{name}' shadows the built-in '{name}'.",
                                 "AST", "builtin"))

    for node in ast.walk(tree):
        in_class = isinstance(parents.get(node), ast.ClassDef)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            owner = parents.get(node)
            if isinstance(owner, (ast.Assign, ast.AnnAssign)) and isinstance(parents.get(owner), ast.ClassDef):
                continue
            add(node.id, node.lineno, "Variable")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not in_class:
                add(node.name, node.lineno, "Function")
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                add(arg.arg, arg.lineno, "Parameter")
        elif isinstance(node, ast.ClassDef) and not in_class:
            add(node.name, node.lineno, "Class")
        elif isinstance(node, ast.ExceptHandler) and node.name:
            add(node.name, node.lineno, "Exception variable")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    add(alias.asname, node.lineno, "Import alias")
    return merge_findings(found, _tool_findings(ctx, 2))


# --------------------------------------------------------------- 04 nesting
def _blocks(stmt):
    if isinstance(stmt, ast.If):
        elif_chain = len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If)
        return [stmt.body] + ([] if elif_chain else [stmt.orelse])
    if isinstance(stmt, ast.Try):
        return [stmt.body] + [h.body for h in stmt.handlers] + [stmt.orelse, stmt.finalbody]
    if isinstance(stmt, ast.Match):
        return [c.body for c in stmt.cases]
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        return [stmt.body, stmt.orelse]
    return [stmt.body]


def _depth(stmt):
    if not isinstance(stmt, CONTROL):
        return 0
    best = 0
    for block in _blocks(stmt):
        best = max([best] + [_depth(s) for s in block])
    if isinstance(stmt, ast.If) and len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
        best = max(best, _depth(stmt.orelse[0]) - 1)       # 'elif' does not nest
    return 1 + best


def nesting_report(tree):
    """[(name, depth, line of the outermost block on the deepest path)] for every routine."""
    out = []
    for name, node in list(iter_functions(tree)) + [("<module>", tree)]:
        best = (0, node.lineno if hasattr(node, "lineno") else 1)
        for stmt in node.body:
            d = _depth(stmt)
            if d > best[0]:
                best = (d, stmt.lineno)
        out.append((name, best[0], best[1]))
    return out


def check_nesting(ctx):
    report = nesting_report(ctx.tree)
    found = [finding(line, f"'{name}' nests control blocks {depth} levels deep "
                           "(recommended maximum: 3).", "AST", "nesting")
             for name, depth, line in report if depth >= 4]
    return merge_findings(found, _tool_findings(ctx, 3)), max([d for _, d, _ in report] + [0])


# ---------------------------------------------------------------- 05 smells
def check_smells(ctx):
    tree, found = ctx.tree, []

    def only_pass(block):
        return bool(block) and all(isinstance(s, ast.Pass) or (
            isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
            and s.value.value is Ellipsis) for s in block)

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            if only_pass(node.body):
                found.append(finding(node.body[0].lineno, f"Empty '{type(node).__name__.lower()}' "
                                     "block (only 'pass').", "AST", "empty-block"))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append(finding(node.lineno, "Bare 'except:' catches every exception.",
                                     "AST", "bare-except"))
            if only_pass(node.body):
                found.append(finding(node.body[0].lineno, "Empty 'except' block (only 'pass').",
                                     "AST", "empty-block"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = {d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                          for d in node.decorator_list}
            body = [s for s in node.body if not (isinstance(s, ast.Expr)
                                                 and isinstance(s.value, ast.Constant)
                                                 and isinstance(s.value.value, str))]
            if body and only_pass(body) and not decorators & {"abstractmethod", "overload"}:
                found.append(finding(node.lineno, f"Function '{node.name}' is an empty placeholder.",
                                     "AST", "empty-block"))
            a = node.args
            for default in a.defaults + [d for d in a.kw_defaults if d is not None]:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                        isinstance(default, ast.Call) and isinstance(default.func, ast.Name)
                        and default.func.id in ("list", "dict", "set")):
                    found.append(finding(default.lineno, f"Mutable default argument in '{node.name}' "
                                         "is shared between calls.", "AST", "mutable-default"))
            count = len([x for x in a.posonlyargs + a.args + a.kwonlyargs
                         if x.arg not in ("self", "cls")])
            if count > 5:
                found.append(finding(node.lineno, f"'{node.name}' takes {count} parameters "
                                     "(recommended maximum: 5).", "AST", "too-many-args"))
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > 50:
                found.append(finding(node.lineno, f"'{node.name}' is {length} lines long "
                                     "(recommended maximum: 50).", "AST", "long-function"))
        elif isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) \
                        and right.value is None:
                    found.append(finding(node.lineno, "Compare to None with 'is' / 'is not', "
                                         "not '==' / '!='.", "AST", "none-compare"))
    return merge_findings(found, _tool_findings(ctx, 4))


# ------------------------------------------------------------------- driver
def analyze(ctx):
    ids = tests_for(TOOL)
    if ctx.syntax_error:
        return [not_evaluated(i, ctx) for i in ids]
    note = _tools_note(ctx)
    out = []

    f = check_unused(ctx)
    out.append(result(ids[0], grade(len(f), 3),
                      (f"{len(f)} unused variable/parameter/import(s) found." if f else
                       "No unused variables, parameters or imports.") + note, f,
                      "Remove unused names, or prefix intentionally unused ones with an underscore."))

    f = check_wildcard(ctx)
    out.append(result(ids[1], grade(len(f), 1),
                      (f"{len(f)} wildcard import(s) found." if f else "No wildcard imports.") + note,
                      f, "Import only the names you need, e.g. 'from os.path import join'."))

    f = check_shadowing(ctx)
    out.append(result(ids[2], grade(len(f), 2),
                      (f"{len(f)} name(s) shadow Python built-ins." if f else
                       "No built-in names are shadowed.") + note, f,
                      "Rename the variables (e.g. 'items' instead of 'list', 'identifier' instead of 'id')."))

    f, depth = check_nesting(ctx)
    status = PASSED if depth <= 3 else WARNING if depth == 4 else FAILED
    out.append(result(ids[3], status,
                      f"Deepest nesting is {depth} level(s)" +
                      (f"; {len(f)} routine(s) exceed the recommended maximum of 3." if f else
                       ", within the recommended maximum of 3.") + note, f,
                      "Use guard clauses (early return/continue) and extract inner blocks into helper functions."))

    f = check_smells(ctx)
    out.append(result(ids[4], grade(len(f), 3),
                      (f"{len(f)} code smell(s) found (empty blocks, bare except, mutable defaults, "
                       "long signatures, undefined names...)." if f else
                       "No empty blocks or common code smells found.") + note, f,
                      "Implement or remove empty blocks, catch specific exceptions, use None as default "
                      "and create the list inside the function."))
    return out

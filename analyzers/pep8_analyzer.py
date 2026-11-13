"""Module 5 - PEP 8 / pycodestyle coding standards.

pycodestyle runs in-process on the source text (it never executes the code); naming
and import-grouping rules use the AST.
"""
import ast
import re
import sys

import pycodestyle

import config
from .base import (FAILED, PASSED, WARNING, finding, grade, iter_functions,
                   merge_findings, not_evaluated, result, tests_for)

TOOL = "pep8"
CLASS_OK = re.compile(r"_?[A-Z][A-Za-z0-9]*")
FUNC_OK = re.compile(r"_{0,2}[a-z][a-z0-9_]*_{0,2}|_")
VAR_OK = re.compile(r"_?[a-z][a-z0-9_]*|[A-Z][A-Z0-9_]*|_")
UNITTEST_NAMES = {"setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule",
                  "tearDownModule", "runTest", "maxDiff"}
AMBIGUOUS = {"l", "O", "I"}
INDENT_CODES = ("E101", "W191", "E111", "E112", "E113", "E114", "E115", "E116", "E117")
FORMAT_PREFIXES = ("W29", "W39", "E2", "E3", "E70", "E12", "E13")


class _Collector(pycodestyle.BaseReport):
    def __init__(self, options):
        super().__init__(options)
        self.records = []

    def error(self, line_number, offset, text, check):
        code = super().error(line_number, offset, text, check)
        if code:
            self.records.append((line_number, offset + 1, code, text[5:]))
        return code


def run_pycodestyle(lines):
    """Return [(line, col, code, message)] from pycodestyle (max line length 88)."""
    style = pycodestyle.StyleGuide(reporter=_Collector, max_line_length=config.MAX_LINE_LENGTH)
    style.input_file("submission.py", lines=lines)
    return style.options.report.records


def _from(records, predicate, source_cat):
    return [finding(line, f"{code}: {text}", f"pycodestyle {code}", source_cat(code))
            for line, col, code, text in records if predicate(code)]


def check_naming(ctx):
    tree, found = ctx.tree, []
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def bad(line, message, cat):
        found.append(finding(line, message, "AST", cat))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and not CLASS_OK.fullmatch(node.name):
            bad(node.lineno, f"Class '{node.name}' should use CapWords (e.g. 'BankAccount').", "class-name")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            dunder = node.name.startswith("__") and node.name.endswith("__")
            if not dunder and node.name not in UNITTEST_NAMES and not FUNC_OK.fullmatch(node.name):
                bad(node.lineno, f"Function '{node.name}' should use snake_case (e.g. "
                                 f"'{_snake(node.name)}').", "function-name")
            a = node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs:
                if arg.arg in ("self", "cls"):
                    continue
                if arg.arg in AMBIGUOUS:
                    bad(arg.lineno, f"Parameter '{arg.arg}' is an ambiguous name (looks like 1/0).", "ambiguous")
                elif not VAR_OK.fullmatch(arg.arg):
                    bad(arg.lineno, f"Parameter '{arg.arg}' should use snake_case.", "arg-name")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id in AMBIGUOUS:
                bad(node.lineno, f"Variable '{node.id}' is an ambiguous name (looks like 1/0).", "ambiguous")
            elif not VAR_OK.fullmatch(node.id):
                bad(node.lineno, f"Variable '{node.id}' should use snake_case "
                                 f"(or UPPER_CASE for constants).", "var-name")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) \
                and isinstance(node.value, ast.Name) and node.value.id == "self" \
                and not VAR_OK.fullmatch(node.attr):
            bad(node.lineno, f"Attribute 'self.{node.attr}' should use snake_case.", "attr-name")
    return merge_findings(found)


def _snake(name):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _group(module, level):
    if level:
        return 3
    root = (module or "").split(".")[0]
    if root == "__future__":
        return 0
    return 1 if root in sys.stdlib_module_names else 2


def check_imports(ctx, records):
    found = _from(records, lambda c: c in ("E401", "E402"), lambda c: "import-" + c.lower())
    names = {0: "__future__", 1: "standard-library", 2: "third-party", 3: "local"}
    prev = None
    for node in ctx.tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
        group = _group(module, getattr(node, "level", 0))
        if prev is not None:
            if group < prev[0]:
                found.append(finding(node.lineno, f"{names[group].capitalize()} import should come "
                                     f"before {names[prev[0]]} imports (stdlib, third-party, local).",
                                     "AST", "import-order"))
            elif group > prev[0] and node.lineno - prev[1] == 1:
                found.append(finding(node.lineno, f"Add a blank line between {names[prev[0]]} and "
                                     f"{names[group]} imports.", "AST", "import-group"))
        prev = (group, node.end_lineno or node.lineno)
    return merge_findings(found)


def analyze(ctx):
    ids = tests_for(TOOL)
    out = []
    try:
        records = run_pycodestyle(ctx.lines_keepends)
        ctx.tool_output["pycodestyle"] = records
    except Exception as exc:                               # tokenizer problems etc.
        records = []
        ctx.tool_output["pycodestyle_error"] = f"{type(exc).__name__}: {exc}"
    syntax = ctx.syntax_error is not None

    f = _from(records, lambda c: c in INDENT_CODES, lambda c: "indent-" + c)
    tabs = sum(1 for _, _, c, _ in records if c in ("W191", "E101"))
    out.append(result(ids[0], grade(len(f), 3),
                      (f"{len(f)} indentation problem(s) ({tabs} tab-related)." if f else
                       "Indentation uses four spaces everywhere; no tabs found."),
                      f, "Configure your editor to insert 4 spaces per indent level and convert tabs."))

    f = _from(records, lambda c: c == "E501", lambda c: "line-length")
    longest = max((len(l.rstrip("\r\n")) for l in ctx.lines_keepends), default=0)
    out.append(result(ids[1], grade(len(f), 3),
                      (f"{len(f)} line(s) exceed {config.MAX_LINE_LENGTH} characters (longest: "
                       f"{longest})." if f else
                       f"All lines are within {config.MAX_LINE_LENGTH} characters (longest: {longest})."),
                      f, "Break long expressions across lines inside parentheses or shorten names."))

    if syntax:
        out.append(not_evaluated(ids[2], ctx))
    else:
        f = check_naming(ctx)
        out.append(result(ids[2], grade(len(f), 3),
                          f"{len(f)} naming convention violation(s)." if f else
                          "Classes use CapWords; functions, variables and arguments use snake_case.",
                          f, "Rename: ClassNames in CapWords, functions/variables in snake_case, "
                             "constants in UPPER_CASE."))

    if syntax:
        out.append(not_evaluated(ids[3], ctx))
    else:
        f = check_imports(ctx, records)
        out.append(result(ids[3], grade(len(f), 2),
                          f"{len(f)} import placement/grouping issue(s)." if f else
                          "Imports are at the top of the file and grouped correctly.",
                          f, "Put all imports at the top, grouped stdlib / third-party / local with "
                             "a blank line between groups, one import per line."))

    f = _from(records, lambda c: c.startswith(FORMAT_PREFIXES), lambda c: "format-" + c)
    trailing = sum(1 for _, _, c, _ in records if c in ("W291", "W293"))
    out.append(result(ids[4], grade(len(f), 3),
                      (f"{len(f)} formatting issue(s) ({trailing} trailing-whitespace)." if f else
                       "No trailing whitespace; blank lines and spacing follow PEP 8."),
                      f, "Enable 'trim trailing whitespace' in your editor and run 'black' or "
                         "'autopep8' to fix spacing and blank lines."))
    return out

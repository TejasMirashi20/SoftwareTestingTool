"""Module 2 - Coverage.py. Coverage is measured in the sandbox while the PyTest module
exercises the code; static AST analysis adds branch, reachability and dead-code checks."""
import ast

import config
from .base import (FAILED, PASSED, WARNING, finding, iter_functions, merge_findings,
                   not_evaluated, result, tests_for)

TOOL = "coverage"


def _ranges(lines):
    """[3,4,5,9] -> [(3,5),(9,9)]"""
    out, start, prev = [], None, None
    for n in sorted(lines):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    if start is not None:
        out.append((start, prev))
    return out


def _decision_points(tree):
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        elif isinstance(node, ast.match_case):
            count += 1
    return count


def _unreachable(tree):
    """Definite dead code: statements after return/raise/break/continue/exit, constant tests."""
    found = []
    terminators = (ast.Return, ast.Raise, ast.Break, ast.Continue)

    def is_exit(stmt):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            f = stmt.value.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else "")
            return name in ("exit", "quit", "_exit")
        return False

    def scan(body):
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, terminators) or is_exit(stmt):
                kind = type(stmt).__name__.lower() if isinstance(stmt, terminators) else "exit()"
                found.append(finding(body[i + 1].lineno,
                                     f"Unreachable code after '{kind}' on line {stmt.lineno}.",
                                     "AST", "unreachable"))
                break

    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                scan(block)
        if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Constant):
            if not node.test.value and node.body:
                found.append(finding(node.body[0].lineno,
                                     "Branch can never run: condition is the constant "
                                     f"{node.test.value!r}.", "AST", "constant-false"))
            elif node.test.value and isinstance(node, ast.If) and node.orelse:
                found.append(finding(node.orelse[0].lineno,
                                     "'else' branch can never run: condition is always true.",
                                     "AST", "constant-true"))
    return found


def _unused_private(tree):
    """Private helpers (leading underscore) that nothing refers to."""
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
    out = []
    for name, node in iter_functions(tree):
        short = node.name
        if short.startswith("_") and not short.startswith("__") and short not in used:
            out.append(finding(node.lineno, f"Private function '{name}' is never referenced.",
                               "AST", "unused-private"))
    return out


def analyze(ctx):
    ids = tests_for(TOOL)
    if ctx.syntax_error:
        return [not_evaluated(i, ctx) for i in ids]

    dyn = ctx.dynamic
    cov = dyn["data"]["coverage"] if dyn and dyn["ok"] else None
    reason = (dyn or {}).get("reason") or "coverage data unavailable"
    if cov is not None and not cov.get("available"):
        reason, cov = cov.get("reason", reason), None
    import_err = dyn["data"].get("import_error") if cov else None
    partial_note = (" The module failed to import, so coverage covers only the code that ran "
                    "before the error." if import_err else "")
    out = []

    # ------------------------------------------------------------- TC-COV-01
    if cov is None:
        out.append(not_evaluated(ids[0], ctx, reason))
    elif not cov["num_statements"]:
        out.append(result(ids[0], WARNING, "The file contains no executable statements.",
                          suggestion="Add code (functions/classes) that can be measured."))
    else:
        pct = cov["percent_statements"]
        findings = [finding(a, f"Line {a} was never executed." if a == b else
                            f"Lines {a}-{b} were never executed.", "coverage.py", "missed")
                    for a, b in _ranges(cov["missing_lines"])][:60]
        status = PASSED if pct >= config.COVERAGE_GATE else WARNING if pct >= 50 else FAILED
        out.append(result(ids[0], status,
                          f"{cov['covered_statements']} of {cov['num_statements']} statements "
                          f"executed ({pct:g}% statement coverage).{partial_note}", findings,
                          "Add tests for the highlighted lines (error paths, else-branches)."
                          if findings else ""))

    # ------------------------------------------------------------- TC-COV-02
    decisions = _decision_points(ctx.tree)
    if cov is None:
        out.append(not_evaluated(ids[1], ctx, reason))
    else:
        nb, cb = cov["num_branches"], cov["covered_branches"]
        by_line = {}
        for a, b in cov["missing_branches"]:
            by_line.setdefault(a, []).append("function exit" if b < 0 else f"line {b}")
        findings = [finding(a, "Branch never taken: line %d -> %s." % (a, ", ".join(d)),
                            "coverage.py", "branch") for a, d in sorted(by_line.items())][:60]
        if nb == 0:
            out.append(result(ids[1], PASSED, f"{decisions} decision point(s) identified; "
                                              "no branching statements to cover."))
        else:
            pct = cov["percent_branches"]
            status = PASSED if pct >= 70 else WARNING if pct >= 40 else FAILED
            out.append(result(ids[1], status,
                              f"{decisions} decision point(s) identified (if/elif/loops/except/"
                              f"boolean/ternary). coverage.py tracked {nb} branch exit(s); {cb} taken "
                              f"({pct:g}%), {cov['partial_branches']} partially covered.{partial_note}",
                              findings, "Write tests that drive both the True and False outcome "
                                        "of each highlighted decision." if findings else ""))

    # ------------------------------------------------------------- TC-COV-03
    funcs = list(iter_functions(ctx.tree))
    if not funcs:
        out.append(result(ids[2], WARNING, "No functions are defined, so there is nothing to register or reach.",
                          suggestion="Structure the code into functions."))
    elif cov is None:
        out.append(not_evaluated(ids[2], ctx, reason))
    else:
        executed = set(cov["executed_lines"])
        unreached, unregistered = [], 0
        for name, node in funcs:
            first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            if node.lineno not in executed and first not in executed:
                unregistered += 1
            body = [s for s in node.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            span = range(body[0].lineno if body else node.lineno, (node.end_lineno or node.lineno) + 1)
            if not any(n in executed for n in span):
                unreached.append(finding(node.lineno, f"Function '{name}' is defined but its body "
                                                      "was never executed.", "coverage.py", "unreached"))
        ratio = 1 - len(unreached) / len(funcs)
        status = PASSED if not unreached else WARNING if ratio >= 0.5 else FAILED
        out.append(result(ids[2], status,
                          f"{len(funcs) - unregistered} of {len(funcs)} function(s) registered at import; "
                          f"{len(funcs) - len(unreached)} reached during the test run "
                          f"({ratio * 100:.0f}%).{partial_note}", unreached,
                          "Call the unreached functions from tests, or delete them if they are unused."
                          if unreached else ""))

    # ------------------------------------------------------------- TC-COV-04
    dead = _unreachable(ctx.tree)
    for msg in ctx.tool_output.get("pylint", []):
        if msg["symbol"] == "unreachable":
            dead.append(finding(msg["line"], "Unreachable code.", "pylint W0101", "unreachable"))
    dead = merge_findings(dead)
    suspicious = _unused_private(ctx.tree)
    allf = dead + suspicious
    if dead:
        out.append(result(ids[3], FAILED,
                          f"{len(dead)} block(s) of unreachable code and {len(suspicious)} unused "
                          "private helper(s) detected.", allf,
                          "Delete the unreachable statements or fix the control flow that makes them unreachable."))
    elif suspicious:
        out.append(result(ids[3], WARNING, f"{len(suspicious)} private helper(s) are never used.",
                          allf, "Remove unused helpers or call them."))
    else:
        out.append(result(ids[3], PASSED, "No unreachable statements, constant-false branches "
                                          "or unused private helpers were found."))

    # ------------------------------------------------------------- TC-COV-05
    if cov is None:
        out.append(not_evaluated(ids[4], ctx, reason))
    elif not cov["num_statements"]:
        out.append(not_evaluated(ids[4], ctx, "the file has no executable statements"))
    else:
        combined, gate = cov["percent_combined"], config.COVERAGE_COMBINED_GATE
        status = PASSED if combined >= gate else WARNING if combined >= 50 else FAILED
        br = cov["percent_branches"]
        out.append(result(ids[4], status,
                          f"Combined statement+branch coverage is {combined:g}% against a quality "
                          f"gate of {gate}% (statements {cov['percent_statements']:g}%, branches "
                          f"{'n/a' if br is None else f'{br:g}%'}).{partial_note}",
                          suggestion="" if status == PASSED else
                          f"Raise coverage by at least {gate - combined:.1f} percentage points."))
    return out

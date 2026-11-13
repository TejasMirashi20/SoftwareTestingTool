"""Module 1 - PyTest. The five checks run as real pytest tests inside the sandbox
(runtime/dynamic_suite.py); this module converts their verdicts into dashboard results."""
import ast

from .base import (FAILED, PASSED, WARNING, finding, not_evaluated, result,
                   tests_for)

TOOL = "pytest"


def _fallback_symbols(ctx):
    funcs = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(ctx.tree))
    classes = sum(isinstance(n, ast.ClassDef) for n in ast.walk(ctx.tree))
    imports = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(ctx.tree))
    return funcs, classes, imports


def analyze(ctx):
    ids = tests_for(TOOL)
    out = []
    if ctx.syntax_error:
        err = ctx.syntax_error
        out.append(result(ids[0], FAILED, f"Syntax error: {err['message']}",
                          [finding(err["line"], err["message"], "compile()", "syntax")],
                          "Correct the syntax at the reported line, then re-run the suite.",
                          err["line"]))
        out += [not_evaluated(i, ctx) for i in ids[1:]]
        return out

    dyn = ctx.dynamic or {"ok": False, "reason": "dynamic run was not performed"}
    if not dyn["ok"]:
        reason = dyn["reason"]
        funcs, classes, imports = _fallback_symbols(ctx)
        out.append(result(ids[0], PASSED,
                          f"Compiled successfully. Discovered {funcs} function(s)/method(s), "
                          f"{classes} class(es) and {imports} import statement(s)."))
        out.append(not_evaluated(ids[1], ctx, reason))
        out.append(not_evaluated(ids[2], ctx, reason))
        out.append(not_evaluated(ids[3], ctx, reason))
        if dyn.get("timed_out"):
            out.append(result(ids[4], FAILED, f"Execution did not finish: {reason}.",
                              suggestion="Remove infinite loops / very slow top-level code and avoid "
                                         "heavy computation on import."))
        else:
            out.append(not_evaluated(ids[4], ctx, reason))
        return out

    records = dyn["data"]["records"]
    outcomes = dyn["data"].get("outcomes", {})
    for test_id in ids:
        rec = records.get(test_id)
        if rec is None:
            crashed = outcomes.get("test_" + test_id.lower().replace("-", "_"))
            out.append(not_evaluated(test_id, ctx,
                                     "the pytest test did not finish (see PyTest Logs tab)"))
            continue
        findings = [finding(f.get("line"), f["message"], "pytest", f.get("cat", "x"))
                    for f in rec["findings"]]
        out.append(result(test_id, rec["status"], rec["explanation"], findings,
                          rec["suggestion"], rec.get("line")))
    return out

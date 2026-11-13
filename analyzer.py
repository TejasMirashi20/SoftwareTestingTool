"""Orchestrator: runs the five testing modules + complexity analysis and builds the
JSON document returned by POST /api/analyze. Every number is computed from real results."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config
from analyzers import (bandit_analyzer, complexity_analyzer, coverage_analyzer,
                       pep8_analyzer, pylint_analyzer, pytest_analyzer)
from analyzers.base import CATALOG, FAILED, PASSED, TOOLS, WARNING, Context, not_evaluated, result
from analyzers.dynamic_runner import run_dynamic
from analyzers.static_tools import run_static_tools

MODULES = [("pytest", pytest_analyzer), ("coverage", coverage_analyzer),
           ("pylint", pylint_analyzer), ("bandit", bandit_analyzer), ("pep8", pep8_analyzer)]


def _safe(module, ctx, tool):
    """Run one module; if it crashes, return 'not evaluated' results instead of failing."""
    try:
        return module.analyze(ctx)
    except Exception as exc:                                  # never crash the request
        return [not_evaluated(row[0], ctx, f"the {TOOLS[tool]} module hit an internal error "
                                           f"({type(exc).__name__}: {exc})")
                for row in CATALOG if row[1] == tool]


def _logs(ctx, tests, dyn, errors):
    cut = lambda text: text[:20000]
    data = dyn["data"] if dyn and dyn["ok"] else {}
    pt = data.get("pytest_output") or (dyn or {}).get("reason", "PyTest did not run.")
    calls = data.get("calls", [])
    table = "\n".join(f"{c['phase']:<8} {c['target']:<28} {c['kind']:<12} "
                      f"{(c['exc_type'] + ': ' + c['exc_msg'])[:70] if c['exc_type'] else 'returned'}"
                      for c in calls[:120])
    pytest_log = pt + ("\n\n--- calls executed in the sandbox ---\n" + table if table else "")
    if data.get("violations"):
        pytest_log += "\n\n--- operations blocked by the sandbox ---\n" + "\n".join(data["violations"])

    cov = data.get("coverage") or {}
    if cov.get("available"):
        cov_log = (f"Statements : {cov['covered_statements']}/{cov['num_statements']} "
                   f"({cov['percent_statements']}%)\nBranches   : {cov['covered_branches']}/"
                   f"{cov['num_branches']} ({cov['percent_branches']}%)\nCombined   : "
                   f"{cov['percent_combined']}%\nMissing lines: {cov['missing_lines']}\n"
                   f"Missing branches: {cov['missing_branches']}")
    else:
        cov_log = "Coverage not available: " + (cov.get("reason") or (dyn or {}).get("reason", "unknown"))

    def lines(items, fmt):
        return "\n".join(fmt(i) for i in items) or "(no messages)"
    t = ctx.tool_output
    pylint_log = "Pylint:\n" + lines(t.get("pylint", []), lambda m: f"  line {m['line']}: {m['code']} "
                                     f"{m['symbol']} - {m['message']}")
    pylint_log += "\n\nFlake8 (pyflakes):\n" + lines(t.get("flake8", []), lambda m: f"  line {m['line']}: "
                                                    f"{m['code']} {m['message']}")
    bandit_log = lines(t.get("bandit", []), lambda m: f"line {m['line']}: {m['test_id']} {m['test_name']} "
                       f"[{m['severity']}/{m['confidence']}] {m['message']}")
    pep_log = lines(t.get("pycodestyle", []), lambda r: f"{r[0]}:{r[1]}: {r[2]} {r[3]}")
    if errors:
        pylint_log += "\n\nTool notes: " + "; ".join(errors.values())
    return {"pytest": cut(pytest_log), "coverage": cut(cov_log), "pylint": cut(pylint_log),
            "bandit": cut(bandit_log), "pep8": cut(pep_log)}


def analyze_source(code):
    started = time.monotonic()
    ctx = Context(code)
    errors = {}
    if ctx.tree is not None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_dyn, f_static = pool.submit(run_dynamic, code), pool.submit(run_static_tools, code)
            try:
                ctx.dynamic = f_dyn.result()
            except Exception as exc:
                ctx.dynamic = {"ok": False, "data": None, "timed_out": False,
                               "reason": f"sandbox error: {exc}"}
            try:
                tools = f_static.result()
                errors = tools.pop("errors")
                ctx.tool_output.update(tools)
            except Exception as exc:
                errors = {"static": f"static tools failed: {exc}"}
        ctx.tool_output["errors"] = errors

    tests = []
    for tool, module in MODULES:
        tests += _safe(module, ctx, tool)
    complexity = complexity_analyzer.analyze(ctx)

    # Guarantee exactly one result per catalog id, in catalog order.
    by_id = {t["id"]: t for t in tests}
    tests = [by_id.get(row[0]) or not_evaluated(row[0], ctx, "no result was produced") for row in CATALOG]

    counts = {s: sum(t["status"] == s for t in tests) for s in (PASSED, WARNING, FAILED)}
    total = len(tests)
    health = round((counts[PASSED] + 0.5 * counts[WARNING]) / total * 100, 1)
    modules = []
    for key, label in TOOLS.items():
        mt = [t for t in tests if t["tool_key"] == key]
        p, w, f = (sum(t["status"] == s for t in mt) for s in (PASSED, WARNING, FAILED))
        modules.append({"key": key, "tool": label, "passed": p, "warnings": w, "failed": f,
                        "score": round((p + 0.5 * w) / len(mt) * 100, 1)})

    data = ctx.dynamic["data"] if ctx.dynamic and ctx.dynamic["ok"] else {}
    cov = data.get("coverage") or {"available": False}
    extras = ctx.extra_findings.get("bandit", [])
    security = sum(t["finding_count"] for t in tests if t["tool_key"] == "bandit") + len(extras)
    code_issues = sum(t["finding_count"] for t in tests if t["tool_key"] in ("pylint", "pep8"))

    if complexity.get("available") and cov.get("available") and complexity["risk"] in ("MODERATE", "HIGH", "CRITICAL") \
            and cov["percent_statements"] is not None and cov["percent_statements"] < config.COVERAGE_GATE:
        complexity["recommendations"].append(
            f"Complexity is {complexity['risk'].lower()} while statement coverage is only "
            f"{cov['percent_statements']:g}% - raise coverage on the complex routines first.")
    if security:
        complexity.setdefault("recommendations", []).append(
            f"{security} security issue(s) were found; fix them before measuring anything else.")

    metrics = {
        "health_score": health, "passed": counts[PASSED], "warnings": counts[WARNING],
        "failed": counts[FAILED], "total_tests": total,
        "statement_coverage": cov.get("percent_statements") if cov.get("available") else None,
        "branch_coverage": cov.get("percent_branches") if cov.get("available") else None,
        "combined_coverage": cov.get("percent_combined") if cov.get("available") else None,
        "cyclomatic_complexity": complexity.get("value"),
        "defect_risk": complexity["risk"], "security_issues": security, "code_issues": code_issues,
        "health_formula": "(passed + 0.5 x warnings) / 25 x 100",
    }
    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "syntax_error": ctx.syntax_error,
        "code_stats": {"lines": len(ctx.lines), "characters": len(code)},
        "metrics": metrics, "modules": modules, "tests": tests, "complexity": complexity,
        "coverage": cov, "extra_findings": {"bandit": extras},
        "logs": _logs(ctx, tests, ctx.dynamic, errors),
        "notes": [v for v in errors.values()],
    }

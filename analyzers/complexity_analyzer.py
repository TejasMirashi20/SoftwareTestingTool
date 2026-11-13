"""McCabe cyclomatic complexity and heuristic defect-risk classification.

V(G) = E - N + 2P. For a structured routine (one connected graph, P = 1) this equals
the number of decision points + 1, which is what is computed here. Over the whole
program (P routines) the sum of the per-routine values equals E - N + 2P.
"""
import ast

from .base import iter_functions

RISK_BANDS = [("LOW", 5, "1-5"), ("MODERATE", 12, "6-12"), ("HIGH", 25, "13-25"),
              ("CRITICAL", float("inf"), "26+")]
DISCLAIMER = ("Risk levels are heuristic estimates derived from McCabe's complexity "
              "thresholds. They indicate relative maintainability and testing effort, "
              "not a guaranteed or measured probability of defects.")
FORMULA = ("V(G) = E - N + 2P (edges - nodes + 2 x connected components). For one structured "
           "routine this equals decision points + 1, which is the value computed below.")


def classify(value):
    for name, upper, label in RISK_BANDS:
        if value <= upper:
            return name, label
    return "CRITICAL", "26+"


def rank(value):
    for letter, upper in (("A", 5), ("B", 10), ("C", 20), ("D", 30), ("E", 40)):
        if value <= upper:
            return letter
    return "F"


def decision_points(body):
    """Count decision points in a list of statements, skipping nested function bodies."""
    count, stack = 0, list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While,
                             ast.ExceptHandler)):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            count += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            if not (isinstance(node.pattern, ast.MatchAs) and node.pattern.pattern is None):
                count += 1
        stack.extend(ast.iter_child_nodes(node))
    return count


def _radon(source):
    try:
        from radon.complexity import cc_visit
        return {(b.name, b.lineno): b.complexity for b in cc_visit(source)}
    except Exception:
        return {}


def _extras(source):
    out = {"maintainability_index": None, "loc": None}
    try:
        from radon.metrics import mi_visit
        from radon.raw import analyze
        raw = analyze(source)
        out["maintainability_index"] = round(mi_visit(source, multi=True), 1)
        out["loc"] = {"total": raw.loc, "source": raw.sloc, "comments": raw.comments,
                      "blank": raw.blank}
    except Exception:
        pass
    return out


def recommendations(risk, value, worst):
    if risk == "LOW":
        recs = [f"Complexity is low (maximum V(G) = {value}). Every routine can be covered "
                f"with at most {value} test case(s) (basis-path testing).",
                "Keep routines short and single-purpose so they stay in this band."]
    elif risk == "MODERATE":
        recs = [f"Moderate complexity (maximum V(G) = {value}): plan at least that many test "
                "cases for the most complex routine.",
                "Review routines with V(G) above 5 and extract helper functions or lookup "
                "tables where a branch chain is long.",
                "Aim to keep every routine at or below 10."]
    elif risk == "HIGH":
        recs = [f"High complexity (maximum V(G) = {value}): refactor before release.",
                "Split large routines, replace nested if/elif chains with early returns, "
                "dictionaries or polymorphism.",
                f"Require a code review and at least {value} independent test paths for the "
                "worst routine."]
    else:
        recs = [f"Critical complexity (maximum V(G) = {value}): the routine is very hard to "
                "test and maintain.",
                "Redesign it into smaller units; do not add new features to it before refactoring.",
                "Add regression tests around current behaviour first, then refactor in small steps."]
    for item in worst:
        if item["complexity"] > 10:
            recs.append(f"'{item['name']}' (line {item['line']}) has V(G) = "
                        f"{item['complexity']} - split it into smaller functions.")
    return recs


def analyze(ctx):
    """Return the complexity report dict (not one of the 25 tests)."""
    if ctx.tree is None:
        return {"available": False, "risk": "UNKNOWN",
                "reason": "Complexity cannot be computed because the code has a syntax error.",
                "disclaimer": DISCLAIMER, "formula": FORMULA, "recommendations": [],
                "functions": [], "value": None}
    tree, source = ctx.tree, ctx.source
    radon = _radon(source)
    routines = []
    for name, node in iter_functions(tree):
        dp = decision_points(node.body)
        routines.append({"name": name, "line": node.lineno, "decision_points": dp,
                         "complexity": dp + 1,
                         "radon": radon.get((node.name, node.lineno))})
    module_dp = decision_points(tree.body)
    if module_dp or not routines:
        routines.append({"name": "<module>", "line": 1, "decision_points": module_dp,
                         "complexity": module_dp + 1, "radon": None})
    for r in routines:
        r["rank"] = rank(r["complexity"])
    routines.sort(key=lambda r: (-r["complexity"], r["line"]))
    top = routines[0]
    total = sum(r["complexity"] for r in routines)
    risk, band = classify(top["complexity"])
    extras = _extras(source)
    return {"available": True, "value": top["complexity"], "max_function": top["name"],
            "total": total, "average": round(total / len(routines), 2),
            "routines": len(routines), "risk": risk, "risk_band": band,
            "functions": routines[:30],
            "recommendations": recommendations(risk, top["complexity"], routines[:3]),
            "formula": FORMULA, "disclaimer": DISCLAIMER, **extras}

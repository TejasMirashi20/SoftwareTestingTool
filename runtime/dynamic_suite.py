"""The five PyTest checks. pytest collects and runs these inside the sandbox process.

Each test computes a PASSED / WARNING / FAILED verdict from real evidence, stores it
with dynamic_state.record() and then reports it to pytest (fail / warn / pass).
"""
import ast
import inspect
import warnings

import pytest

import dynamic_state as st


def _finish(test_id, status, explanation, findings=None, suggestion="", line=None):
    if test_id in st.RECORDS:          # the first verdict of a test is final
        return
    st.record(test_id, status, explanation, findings, suggestion, line)
    if status == "FAILED":
        pytest.fail(f"{test_id}: {explanation}", pytrace=False)
    if status == "WARNING":
        warnings.warn(f"{test_id}: {explanation}", UserWarning, stacklevel=2)


def _f(line, message, source="pytest", cat="x"):
    return {"line": line, "message": message, "source": source, "cat": cat}


def _import_failed(test_id):
    st.load_module()
    err = st.import_error()
    if err is None:
        return False
    _finish(test_id, "FAILED",
            f"The module could not be imported in the sandbox: {err['type']}: {err['message']}",
            [_f(err["line"], f"{err['type']}: {err['message']}")],
            "Fix the error raised while the module loads (top-level code must not crash).",
            err["line"])
    return True


# --------------------------------------------------------------- TC-PYTEST-01
def test_tc_pytest_01_syntax_and_symbols():
    source, path = st.CONTEXT["source"], st.CONTEXT["module_path"]
    try:
        tree = ast.parse(source)
        compile(tree, path, "exec")
    except SyntaxError as exc:
        _finish("TC-PYTEST-01", "FAILED", f"Syntax error: {exc.msg}",
                [_f(exc.lineno, exc.msg)], "Correct the syntax at the reported line.",
                exc.lineno)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    summary = (f"Compiled successfully. Discovered {len(funcs)} function(s)/method(s), "
               f"{len(classes)} class(es) and {len(imports)} import statement(s).")
    if not funcs and not classes:
        _finish("TC-PYTEST-01", "WARNING",
                summary + " There are no functions or classes, so there is nothing to unit-test.",
                suggestion="Wrap logic in functions or classes so it can be tested in isolation.")
    _finish("TC-PYTEST-01", "PASSED", summary)


# --------------------------------------------------------------- TC-PYTEST-02
def test_tc_pytest_02_callable_inspection():
    if _import_failed("TC-PYTEST-02"):
        return
    module = st.load_module()
    ns = vars(module)
    targets = st.discover_targets()
    if not targets:
        _finish("TC-PYTEST-02", "WARNING", "The module defines no public functions or classes to inspect.",
                suggestion="Expose public functions/classes (names without a leading underscore).")
    findings, bad, seen, total = [], 0, {}, 0
    for kind, cls_name, node in targets:
        nodes = [node] if kind == "function" else [
            n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not n.name.startswith("_")]
        total += len(nodes) + (1 if kind == "class" else 0)
        if kind == "class" and not ast.get_docstring(node):
            findings.append(_f(node.lineno, f"Class '{node.name}' has no docstring.", cat="doc"))
        if kind == "function":
            seen.setdefault(node.name, []).append(node.lineno)
            obj = ns.get(node.name)
            if not callable(obj):
                bad += 1
                findings.append(_f(node.lineno, f"'{node.name}' is not callable at runtime.", cat="call"))
                continue
            try:
                inspect.signature(obj)
            except (ValueError, TypeError):
                bad += 1
                findings.append(_f(node.lineno, f"Signature of '{node.name}' cannot be read.", cat="sig"))
        for fn in nodes:
            if not ast.get_docstring(fn):
                label = fn.name if kind == "function" else f"{cls_name}.{fn.name}"
                findings.append(_f(fn.lineno, f"'{label}' has no docstring.", cat="doc"))
    for name, lines in seen.items():
        if len(lines) > 1:
            findings.append(_f(lines[1], f"'{name}' is defined {len(lines)} times; the later "
                                         f"definition silently replaces the earlier one.", cat="dup"))
    if bad:
        _finish("TC-PYTEST-02", "FAILED", f"{bad} callable(s) could not be resolved or inspected.",
                findings, "Make sure each public name is a real function or class.")
    if findings:
        _finish("TC-PYTEST-02", "WARNING",
                f"Inspected {total} public callable(s); {len(findings)} documentation/definition "
                f"issue(s) found.", findings,
                "Add docstrings describing purpose, parameters and return values; remove duplicate names.")
    _finish("TC-PYTEST-02", "PASSED",
            f"Inspected {total} public callable(s): all resolve, have readable signatures and docstrings.")


# --------------------------------------------------------------- TC-PYTEST-03
def test_tc_pytest_03_boundary_checks():
    if _import_failed("TC-PYTEST-03"):
        return
    st.exercise()
    boundary = st.calls("boundary")
    tree = ast.parse(st.CONTEXT["source"])
    compares = sum(isinstance(n, ast.Compare) for n in ast.walk(tree))
    defects, seen = [], set()
    for call in boundary:
        if call["kind"] in ("defect", "timeout"):
            key = (call["target"], call["exc_type"])
            if key not in seen:
                seen.add(key)
                defects.append(_f(call["fail_line"] or call["line"],
                                  f"{call['target']}({call['variant']}) raised {call['exc_type']}: "
                                  f"{call['exc_msg'] or 'no message'}", cat="boundary"))
    ok_calls = sum(1 for c in boundary if c["kind"] in ("ok", "validated"))
    if defects:
        status = "FAILED" if len(defects) >= 3 else "WARNING"
        _finish("TC-PYTEST-03", status,
                f"{len(boundary)} boundary call(s) executed; {len(defects)} unhandled failure(s) "
                f"on boundary input (0, -1, empty, very large).", defects,
                "Validate inputs (zero, negative, empty, huge) and raise a clear ValueError or "
                "return a safe default instead of crashing.")
    if not boundary:
        _finish("TC-PYTEST-03", "WARNING",
                "No function with numeric, text or list parameters could be probed with boundary values.",
                suggestion="Give functions typed parameters (e.g. amount: float) so boundaries can be tested.")
    numeric_params = any(c["variant"].endswith(("=0", "=-1", "=100000")) for c in boundary)
    if numeric_params and compares == 0:
        _finish("TC-PYTEST-03", "WARNING",
                f"{len(boundary)} boundary call(s) ran, but the code contains no comparison "
                f"(conditional) checks on its numeric inputs.",
                suggestion="Add explicit checks such as 'if amount <= 0' for boundary values.")
    _finish("TC-PYTEST-03", "PASSED",
            f"{len(boundary)} boundary call(s) executed ({ok_calls} handled correctly or rejected with "
            f"a deliberate exception); {compares} conditional comparison(s) present.")


# --------------------------------------------------------------- TC-PYTEST-04
_RISKY_CALLS = {"int", "float", "open", "json.load", "json.loads"}


def _call_name(node):
    func, parts = node.func, []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def test_tc_pytest_04_exception_handling():
    tree = ast.parse(st.CONTEXT["source"])
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def owner(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return tree

    def guarded(node):
        child = node
        while child in parents:
            parent = parents[child]
            if isinstance(parent, ast.Try) and child in parent.body:
                return True
            child = parent
        return False

    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
    handlers = [h for t in tries for h in t.handlers]
    bad, soft = [], []
    for h in handlers:
        silent = all(isinstance(s, (ast.Pass, ast.Continue)) or
                     (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                     for s in h.body)
        if h.type is None:
            bad.append(_f(h.lineno, "Bare 'except:' catches every error, even KeyboardInterrupt.", cat="bare"))
        elif silent:
            bad.append(_f(h.lineno, "Exception is caught and silently ignored.", cat="silent"))
        elif isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"):
            soft.append(_f(h.lineno, f"Overly broad 'except {h.type.id}'.", cat="broad"))
    handled_scopes = {owner(n) for n in tries + raises}
    for node in ast.walk(tree):
        risky = None
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) \
                and not (isinstance(node.right, ast.Constant) and node.right.value):
            risky = "division by a variable"
        elif isinstance(node, ast.Call) and _call_name(node) in _RISKY_CALLS \
                and not (node.args and isinstance(node.args[0], ast.Constant)
                         and _call_name(node) in ("int", "float")):
            risky = f"call to {_call_name(node)}()"
        if risky and not guarded(node) and owner(node) not in handled_scopes:
            soft.append(_f(node.lineno, f"Unprotected {risky}: no try/except or raise in this scope.",
                           cat="risky"))
    if bad:
        _finish("TC-PYTEST-04", "FAILED",
                f"{len(bad)} unsafe exception handler(s) found (bare or silently swallowed).",
                bad + soft, "Catch specific exceptions, log or re-raise them, never use bare 'except:' or 'pass'.")
    if soft:
        _finish("TC-PYTEST-04", "WARNING",
                f"{len(soft)} exception-handling weakness(es): risky operations without protection "
                f"or overly broad handlers.", soft,
                "Wrap risky operations in try/except with specific exception types, or validate inputs first.")
    _finish("TC-PYTEST-04", "PASSED",
            f"Found {len(tries)} try/except block(s) and {len(raises)} raise statement(s); "
            f"no bare/swallowed handlers and no unprotected risky operations.")


# --------------------------------------------------------------- TC-PYTEST-05
def test_tc_pytest_05_execution_verification():
    if _import_failed("TC-PYTEST-05"):
        return
    st.exercise()
    base = st.calls("baseline")
    if not base:
        _finish("TC-PYTEST-05", "WARNING", "There were no public functions or classes to execute.",
                suggestion="Define functions or classes so their return values can be verified.")
    findings = []
    counts = {}
    for call in base:
        counts[call["kind"]] = counts.get(call["kind"], 0) + 1
        line = call["fail_line"] or call["line"]
        if call["kind"] in ("defect", "timeout"):
            findings.append(_f(line, f"{call['target']} raised {call['exc_type']}: {call['exc_msg']}", cat="defect"))
        elif call["kind"] == "blocked":
            findings.append(_f(line, f"{call['target']} attempted a blocked operation: {call['exc_msg']}", cat="blocked"))
        elif call["kind"] == "inconclusive":
            findings.append(_f(line, f"{call['target']} could not be verified automatically "
                                     f"({call['exc_type']}: {call['exc_msg']}).", cat="inconclusive"))
        elif call["kind"] == "skipped":
            findings.append(_f(line, f"{call['target']} skipped: {call['exc_msg']}", cat="skipped"))
    verified = counts.get("ok", 0) + counts.get("validated", 0) + counts.get("interactive", 0)
    summary = (f"Executed {len(base)} callable(s): {counts.get('ok', 0)} returned normally, "
               f"{counts.get('validated', 0)} rejected the sample input with a deliberate exception, "
               f"{counts.get('interactive', 0)} need keyboard input.")
    defects = counts.get("defect", 0) + counts.get("timeout", 0)
    if defects:
        _finish("TC-PYTEST-05", "FAILED", summary + f" {defects} crashed with an unexpected error.",
                findings, "Fix the crashing statements; functions must not raise ZeroDivisionError, "
                          "IndexError, KeyError or hang on valid input.")
    if findings:
        _finish("TC-PYTEST-05", "WARNING", summary + f" {len(findings)} could not be fully verified.",
                findings, "Use typed parameters and sandbox-safe code so functions can be run automatically.")
    _finish("TC-PYTEST-05", "PASSED", summary)

"""Shared definitions: the 25-test catalog, result builder, parsing context, helpers."""
import ast

PASSED, WARNING, FAILED = "PASSED", "WARNING", "FAILED"

TOOLS = {
    "pytest": "PyTest",
    "coverage": "Coverage.py",
    "pylint": "Pylint / Flake8",
    "bandit": "Bandit",
    "pep8": "PEP 8 / pycodestyle",
}

# (test id, tool key, name, description) - exactly 25 entries, five per tool.
CATALOG = [
    ("TC-PYTEST-01", "pytest", "Syntax compilation and symbol discovery",
     "Compiles the source and discovers functions, classes and imports."),
    ("TC-PYTEST-02", "pytest", "Function and callable inspection",
     "Imports the module in the sandbox and inspects every public callable."),
    ("TC-PYTEST-03", "pytest", "Boundary and conditional checks",
     "Calls functions with boundary values (0, -1, empty, very large) and checks conditionals."),
    ("TC-PYTEST-04", "pytest", "Exception handling inspection",
     "Inspects try/except and raise usage and risky operations."),
    ("TC-PYTEST-05", "pytest", "Function return and execution verification",
     "Executes every public function with generated arguments and verifies it returns."),
    ("TC-COV-01", "coverage", "Statement coverage",
     "Measures executed statements with coverage.py while the test run exercises the code."),
    ("TC-COV-02", "coverage", "Branch and decision identification",
     "Counts decision points and measures how many branches were taken."),
    ("TC-COV-03", "coverage", "Function registration and reachability",
     "Checks that every defined function is registered and actually reached."),
    ("TC-COV-04", "coverage", "Dead code detection",
     "Finds unreachable statements, constant-false branches and unused private helpers."),
    ("TC-COV-05", "coverage", "Coverage threshold compliance",
     "Compares combined statement + branch coverage with the quality gate."),
    ("TC-PYLINT-01", "pylint", "Unused variables and parameters",
     "Finds unused local variables, function parameters and imports."),
    ("TC-PYLINT-02", "pylint", "Wildcard imports",
     "Detects 'from module import *'."),
    ("TC-PYLINT-03", "pylint", "Built-in variable shadowing",
     "Detects names that shadow Python built-ins such as list, id or sum."),
    ("TC-PYLINT-04", "pylint", "Excessive nesting depth",
     "Measures the deepest nesting of if/for/while/try/with blocks."),
    ("TC-PYLINT-05", "pylint", "Empty blocks and code smells",
     "Finds empty blocks, bare except, mutable defaults, long signatures and similar smells."),
    ("TC-BANDIT-01", "bandit", "Dangerous eval() and exec() calls",
     "Finds dynamic code execution with eval() and exec()."),
    ("TC-BANDIT-02", "bandit", "Weak MD5/SHA1 cryptographic algorithms",
     "Finds use of broken hash functions."),
    ("TC-BANDIT-03", "bandit", "Hardcoded passwords and API keys",
     "Finds credentials and tokens written directly in the source."),
    ("TC-BANDIT-04", "bandit", "Unsafe resource and file handling patterns",
     "Finds unclosed files, unsafe temp files, pickle/yaml loading and permissive chmod."),
    ("TC-BANDIT-05", "bandit", "Unsafe subprocess calls and shell=True",
     "Finds shell=True, os.system and other command-execution risks."),
    ("TC-PEP8-01", "pep8", "Four-space indentation and tab detection",
     "Checks indentation width and tab characters."),
    ("TC-PEP8-02", "pep8", "Maximum line length (88 characters)",
     "Checks that no line exceeds 88 characters."),
    ("TC-PEP8-03", "pep8", "Class and function naming conventions",
     "Checks CapWords classes and snake_case functions, variables and arguments."),
    ("TC-PEP8-04", "pep8", "Import placement and grouping",
     "Checks imports are at the top and grouped stdlib / third-party / local."),
    ("TC-PEP8-05", "pep8", "Trailing whitespace and formatting",
     "Checks trailing whitespace, blank lines and operator/bracket spacing."),
]
_META = {row[0]: row for row in CATALOG}


def tests_for(tool):
    return [row[0] for row in CATALOG if row[1] == tool]


def finding(line, message, source="AST", cat="x"):
    """One concrete problem found in the code."""
    return {"line": line, "message": message, "source": source, "cat": cat}


def result(test_id, status, explanation, findings=None, suggestion="", line=None):
    """Build the full result dict for one test (metadata comes from CATALOG)."""
    _, tool, name, desc = _META[test_id]
    findings = findings or []
    if line is None:
        lines = [f["line"] for f in findings if f.get("line")]
        line = min(lines) if lines else None
    return {
        "id": test_id, "tool": TOOLS[tool], "tool_key": tool, "name": name,
        "description": desc, "status": status, "explanation": explanation,
        "line": line, "suggestion": suggestion, "findings": findings[:200],
        "finding_count": len(findings),
    }


def grade(count, warn_max):
    """0 findings -> PASSED, up to warn_max -> WARNING, more -> FAILED."""
    if count == 0:
        return PASSED
    return WARNING if count <= warn_max else FAILED


def merge_findings(*groups):
    """Merge findings from several sources; same (line, category) -> one entry."""
    merged = {}
    for group in groups:
        for item in group:
            key = (item["line"], item["cat"])
            if key in merged:
                known = merged[key]["source"].split(", ")
                if item["source"] not in known:
                    merged[key]["source"] += ", " + item["source"]
            else:
                merged[key] = dict(item)
    return sorted(merged.values(), key=lambda f: (f["line"] or 0, f["cat"]))


def not_evaluated(test_id, ctx, reason=None):
    """WARNING result for a check that could not run (e.g. syntax error)."""
    if reason is None:
        err = ctx.syntax_error or {}
        reason = (f"a syntax error at line {err.get('line')} prevents analysis"
                  if err else "the required analysis data is unavailable")
    line = (ctx.syntax_error or {}).get("line")
    return result(test_id, WARNING, f"Not evaluated: {reason}.",
                  suggestion="Fix the syntax error first, then run the suite again.",
                  line=line)


class Context:
    """Everything the analyzers share about one submission."""

    def __init__(self, source):
        self.source = source
        self.lines = source.splitlines()
        self.lines_keepends = source.splitlines(keepends=True)
        self.tree = None
        self.syntax_error = None
        self.dynamic = None          # filled by analyzer.py (sandbox output)
        self.tool_output = {}        # raw pylint / flake8 / bandit findings
        self.extra_findings = {}     # tool findings that belong to no single test
        try:
            tree = ast.parse(source)
            compile(tree, "<submission>", "exec")     # catches compile-time errors
            self.tree = tree
        except SyntaxError as exc:
            self.syntax_error = {"line": exc.lineno, "offset": exc.offset,
                                 "message": exc.msg}
        except (ValueError, RecursionError, MemoryError, OverflowError) as exc:
            self.syntax_error = {"line": None, "offset": None,
                                 "message": f"{type(exc).__name__}: {exc}"}


def iter_functions(tree):
    """Yield (qualified_name, node) for every function/method, including nested ones."""
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                yield name, child
                yield from walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def call_name(node):
    """Dotted name of a call target, e.g. 'hashlib.md5' (or '' when dynamic)."""
    func = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def is_stub(func):
    """True for functions whose body is only a docstring, pass, ... or raise NotImplementedError."""
    for stmt in func.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Raise):
            continue
        return False
    return True


def import_aliases(tree):
    """Map local names to what they import: {'md5': 'hashlib.md5', 'sp': 'subprocess'}."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[(a.asname or a.name.split(".")[0])] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name != "*":
                    aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def resolved_call_name(node, aliases):
    """call_name() with import aliases resolved, e.g. md5(...) -> 'hashlib.md5'."""
    name = call_name(node)
    if not name:
        return ""
    head, _, rest = name.partition(".")
    if head in aliases:
        return aliases[head] + ("." + rest if rest else "")
    return name


def parent_map(tree):
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents

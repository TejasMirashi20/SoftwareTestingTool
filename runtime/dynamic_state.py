"""Helpers used INSIDE the sandbox process: import the submission, synthesise arguments,
call every public function with time limits and classify what happens.

Nothing in this file runs in the Flask process.
"""
import ast
import contextlib
import copy
import enum
import inspect
import io
import re
import signal
import sys
import threading
import time
import traceback
import _thread

MODULE_NAME = "submission_under_test"
CONTEXT = {}        # source, module_path, deadline - filled by sandbox_runner
RECORDS = {}        # test id -> result dict, filled by dynamic_suite
CALLS = []          # every function call that was executed
_STATE = {"loaded": False, "module": None, "import_error": None, "exercised": False}
UNKNOWN = object()
P = inspect.Parameter


class SandboxViolation(PermissionError):
    """Raised by the audit hook when submitted code attempts a forbidden operation."""


class LimitedWriter(io.TextIOBase):
    """Captures output from submitted code, keeping at most 20 000 characters."""

    def __init__(self):
        self.parts, self.size = [], 0

    def write(self, text):
        if self.size < 20000:
            self.parts.append(text[:20000 - self.size])
            self.size += len(text)
        return len(text)

    def getvalue(self):
        return "".join(self.parts)


def record(test_id, status, explanation, findings=None, suggestion="", line=None):
    RECORDS[test_id] = {"status": status, "explanation": explanation,
                        "findings": findings or [], "suggestion": suggestion,
                        "line": line}


def time_left():
    return CONTEXT["deadline"] - time.monotonic()


@contextlib.contextmanager
def time_limit(seconds):
    """Raise TimeoutError if the block runs longer than ``seconds``."""
    message = f"exceeded the {seconds:g}s time limit"
    if hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM"):
        def handler(signum, frame):
            raise TimeoutError(message)
        old = signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
    else:                                   # Windows: watchdog thread interrupts main
        timer = threading.Timer(seconds, _thread.interrupt_main)
        timer.start()
        try:
            yield
        except KeyboardInterrupt:
            raise TimeoutError(message) from None
        finally:
            timer.cancel()


def _failure_line(exc, default=None):
    """Line number (inside the submission) where an exception was raised."""
    path = CONTEXT["module_path"]
    line = default
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == path:
            line = frame.lineno
    if isinstance(exc, SyntaxError) and exc.lineno:
        line = exc.lineno
    return line


# --------------------------------------------------------------------- import
def load_module():
    """Import the submission once (under coverage). Returns the module or None."""
    import importlib.util
    if _STATE["loaded"]:
        return _STATE["module"]
    _STATE["loaded"] = True
    path = CONTEXT["module_path"]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    sink = LimitedWriter()
    try:
        with time_limit(min(5.0, max(1.0, time_left()))), \
                contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            spec.loader.exec_module(module)
        _STATE["module"] = module
    except BaseException as exc:             # includes SystemExit / KeyboardInterrupt
        if isinstance(exc, KeyboardInterrupt):
            exc = TimeoutError("exceeded the import time limit")
        _STATE["import_error"] = {"type": type(exc).__name__, "message": str(exc)[:300],
                                  "line": _failure_line(exc)}
        sys.modules.pop(MODULE_NAME, None)
    return _STATE["module"]


def import_error():
    return _STATE["import_error"]


# ------------------------------------------------------------------ discovery
def discover_targets():
    """Public top-level functions and classes (with their public methods), from the AST."""
    tree = ast.parse(CONTEXT["source"])
    targets = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and not node.name.startswith("_"):
            targets.append(("function", None, node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            targets.append(("class", node.name, node))
    return targets


def raised_names(tree):
    """Names of exception classes the module raises explicitly (intentional errors)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(exc, ast.Name):
                names.add(exc.id)
            elif isinstance(exc, ast.Attribute):
                names.add(exc.attr)
    return names


# ------------------------------------------------------------------- synthesis
_SIMPLE = {"int": 4, "float": 4.0, "complex": 4j, "number": 4, "str": "sample",
           "bool": True, "list": [1, 2, 3], "sequence": [1, 2, 3], "iterable": [1, 2, 3],
           "tuple": (1, 2), "set": {1, 2}, "frozenset": frozenset({1, 2}),
           "dict": {"a": 1}, "mapping": {"a": 1}, "bytes": b"abc"}
_LIST_HINTS = {"items", "list", "lst", "nums", "numbers", "values", "data", "array",
               "arr", "elements", "products", "orders", "scores", "records", "entries",
               "rows", "history", "prices", "cart"}
_STR_HINTS = {"name", "text", "string", "msg", "message", "word", "sentence", "title",
              "owner", "holder", "email", "user", "username", "label", "sku", "id",
              "code", "path", "filename", "description", "query", "key", "customer"}
_NUM_HINTS = {"amount", "price", "qty", "quantity", "count", "num", "number", "value",
              "balance", "total", "rate", "x", "y", "z", "a", "b", "n", "k", "i", "j",
              "age", "size", "length", "width", "height", "radius", "angle", "degrees",
              "base", "exp", "exponent", "percent", "discount", "tax", "limit", "index",
              "idx", "weight", "score", "celsius", "fahrenheit", "cost", "fee",
              "interest", "years", "months", "days", "level", "start", "stop", "step"}


def _from_name(name):
    tokens = set(name.lower().split("_"))
    if tokens & {"expr", "expression", "formula"}:
        return "2 + 2"
    if tokens & _LIST_HINTS:
        return [1, 2, 3]
    if tokens & _STR_HINTS:
        return "sample"
    if tokens & _NUM_HINTS:
        return 4
    return UNKNOWN


def _from_annotation(ann, ns, depth):
    text = ann if isinstance(ann, str) else (getattr(ann, "__name__", None) or str(ann))
    text = text.replace("typing.", "").strip("'\" ")
    match = re.match(r"Optional\[(.+)\]$", text)
    if match:
        text = match.group(1)
    text = re.split(r"\s*\|\s*", text)[0]
    base = re.split(r"[\[\s]", text)[0]
    if base.lower() in _SIMPLE:
        return copy.deepcopy(_SIMPLE[base.lower()])
    cls = ns.get(base)
    if inspect.isclass(cls) and depth < 2:
        rec = _call_with_attempts(cls, ns, depth + 1, set())
        return rec["value"] if rec["status"] == "returned" else UNKNOWN
    return UNKNOWN


def _value_for(param, ns, depth):
    if param.annotation is not P.empty:
        value = _from_annotation(param.annotation, ns, depth)
        if value is not UNKNOWN:
            return value
    return _from_name(param.name)


def _required_params(func):
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return None
    return [p for p in sig.parameters.values()
            if p.name not in ("self", "cls") and p.default is P.empty
            and p.kind not in (P.VAR_POSITIONAL, P.VAR_KEYWORD)]


def _build_args(params, ns, depth, filler):
    args, kwargs, unknown = [], {}, False
    for param in params:
        value = _value_for(param, ns, depth)
        if value is UNKNOWN:
            value, unknown = copy.deepcopy(filler), True
        if param.kind is P.KEYWORD_ONLY:
            kwargs[param.name] = value
        else:
            args.append(value)
    return args, kwargs, unknown


# --------------------------------------------------------------------- calling
_DEFECTS = (ZeroDivisionError, NameError, OverflowError, IndexError, KeyError,
            RecursionError, MemoryError)


def _intentional(exc, raised):
    for cls in type(exc).__mro__:
        if cls not in (BaseException, Exception, object) and cls.__name__ in raised:
            return True
    return False


def classify(exc, raised):
    """ok-ish categories: validated, defect, timeout, blocked, interactive, inconclusive."""
    if isinstance(exc, SandboxViolation):
        return "blocked"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, EOFError):
        return "interactive"
    if isinstance(exc, (RecursionError, MemoryError)):
        return "defect"
    if _intentional(exc, raised):
        return "validated"
    if isinstance(exc, _DEFECTS):
        return "defect"
    return "inconclusive"


def _safe_call(func, args, kwargs):
    sink = LimitedWriter()
    limit = max(0.2, min(2.0, time_left()))
    try:
        with time_limit(limit), contextlib.redirect_stdout(sink), \
                contextlib.redirect_stderr(sink):
            value = func(*args, **kwargs)
        if inspect.iscoroutine(value):
            value.close()
        return "returned", value, None
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            exc = TimeoutError("exceeded the time limit")
        return "raised", None, exc


def _call_with_attempts(func, ns, depth, raised):
    """Call ``func`` with synthesised arguments, retrying generic fillers on type errors."""
    params = _required_params(func)
    if params is None:
        params = []
    best = None
    for filler in (4, "sample", [1, 2, 3], {"a": 1}):
        args, kwargs, unknown = _build_args(params, ns, depth, filler)
        status, value, exc = _safe_call(func, args, kwargs)
        rec = {"status": status, "value": value, "exc": exc, "args": args,
               "kwargs": kwargs, "params": params, "kind": "ok"}
        if status == "returned":
            return rec
        rec["kind"] = classify(exc, raised)
        best = best or rec
        if rec["kind"] != "inconclusive" or not unknown:
            return rec
    return best


def _log(label, line, rec, phase, variant=""):
    exc = rec["exc"]
    CALLS.append({
        "target": label, "line": line, "phase": phase, "variant": variant,
        "args": repr((rec["args"], rec["kwargs"]) if rec["kwargs"] else rec["args"])[:90],
        "outcome": rec["status"], "kind": rec["kind"],
        "exc_type": type(exc).__name__ if exc else "", "exc_msg": str(exc)[:160] if exc else "",
        "fail_line": _failure_line(exc, line) if exc else None,
    })


def _variants(value):
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [0, -1, 100000]
    if isinstance(value, str):
        return ["", "x" * 300]
    if isinstance(value, list):
        return [[]]
    if isinstance(value, dict):
        return [{}]
    return []


def exercise():
    """Run baseline and boundary calls once; results land in CALLS."""
    if _STATE["exercised"]:
        return
    _STATE["exercised"] = True
    module = load_module()
    if module is None:
        return
    ns = vars(module)
    raised = raised_names(ast.parse(CONTEXT["source"]))
    specs = []                                   # (label, line, factory, rec)

    for kind, cls_name, node in discover_targets():
        if time_left() <= 0:
            CALLS.append({"target": node.name, "line": node.lineno, "phase": "baseline",
                          "variant": "", "args": "", "outcome": "skipped", "kind": "skipped",
                          "exc_type": "", "exc_msg": "time budget used up", "fail_line": None})
            continue
        if kind == "function":
            func = ns.get(node.name)
            if not callable(func):
                continue
            rec = _call_with_attempts(func, ns, 0, raised)
            _log(node.name, node.lineno, rec, "baseline")
            specs.append((node.name, node.lineno, (lambda f=func: f), rec))
            continue
        cls = ns.get(cls_name)
        if not inspect.isclass(cls) or issubclass(cls, (BaseException, enum.Enum)):
            continue
        ctor = _call_with_attempts(cls, ns, 0, raised)
        _log(f"{cls_name}()", node.lineno, ctor, "baseline")
        if ctor["status"] != "returned":
            continue

        def factory(c=cls, a=ctor["args"], k=ctor["kwargs"]):
            return c(*copy.deepcopy(a), **copy.deepcopy(k))
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    or item.name.startswith("_"):
                continue
            if any(isinstance(d, ast.Name) and d.id in ("property", "cached_property")
                   or isinstance(d, ast.Attribute) and d.attr in ("setter", "getter", "deleter")
                   for d in item.decorator_list):
                continue
            if time_left() <= 0:
                break
            label = f"{cls_name}.{item.name}"
            try:
                method = getattr(factory(), item.name)
            except BaseException:
                continue
            rec = _call_with_attempts(method, ns, 0, raised)
            _log(label, item.lineno, rec, "baseline")
            specs.append((label, item.lineno,
                          (lambda f=factory, n=item.name: getattr(f(), n)), rec))

    # boundary-value phase: change one argument at a time
    budget = 90
    for label, line, getter, rec in specs:
        if rec["status"] != "returned" and rec["kind"] != "validated":
            continue
        params = rec["params"]
        for index, param in enumerate(params):
            positional = param.kind is not P.KEYWORD_ONLY
            original = rec["args"][index] if positional else rec["kwargs"].get(param.name)
            for value in _variants(original):
                if budget <= 0 or time_left() <= 0:
                    break
                budget -= 1
                args, kwargs = copy.deepcopy(rec["args"]), copy.deepcopy(rec["kwargs"])
                if positional:
                    args[index] = value
                else:
                    kwargs[param.name] = value
                try:
                    func = getter()
                except BaseException:
                    break
                status, result, exc = _safe_call(func, args, kwargs)
                brec = {"status": status, "value": result, "exc": exc, "args": args,
                        "kwargs": kwargs, "kind": "ok" if status == "returned"
                        else classify(exc, raised)}
                _log(label, line, brec, "boundary", f"{param.name}={value!r}"[:40])


def calls(phase):
    return [c for c in CALLS if c["phase"] == phase]

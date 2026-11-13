"""Module 4 - Bandit security analysis.

Own AST rules and the real Bandit CLI are combined; findings on the same line are
merged. Bandit results that fit none of the five tests are kept as 'extra' findings
and still counted in the total security issue metric.
"""
import ast
import re

from .base import (FAILED, PASSED, WARNING, finding, import_aliases, merge_findings,
                   not_evaluated, parent_map, resolved_call_name, result, tests_for)

TOOL = "bandit"
BANDIT_MAP = {
    "B307": (0, "eval-exec"), "B102": (0, "eval-exec"),
    "B324": (1, "weak-hash"), "B303": (1, "weak-hash"),
    "B105": (2, "secret"), "B106": (2, "secret"), "B107": (2, "secret"),
    "B301": (3, "deserialize"), "B302": (3, "deserialize"), "B506": (3, "deserialize"),
    "B306": (3, "mktemp"), "B108": (3, "tmp-path"), "B103": (3, "chmod"),
    "B602": (4, "shell"), "B604": (4, "shell"), "B605": (4, "shell"),
    "B603": (4, "subprocess"), "B606": (4, "subprocess"), "B607": (4, "subprocess"),
}
SECRET_NAME = re.compile(r"(passw(or)?d|passwd|pwd|secret|api[_-]?key|apikey|token|"
                         r"private[_-]?key|access[_-]?key|auth[_-]?key|credential)", re.I)
SAFE_SUFFIX = re.compile(r"_(type|name|field|url|path|label|prompt|length|file|count|id)$", re.I)
SECRET_VALUE = re.compile(r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|"
                          r"xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (RSA |EC )?PRIVATE KEY-----)")
WEAK_HASHES = {"hashlib.md5", "hashlib.sha1", "Crypto.Hash.MD5.new", "Crypto.Hash.SHA.new",
               "MD5.new", "SHA.new", "SHA1.new"}
DESERIALIZE = {"pickle.load", "pickle.loads", "cPickle.load", "cPickle.loads", "marshal.load",
               "marshal.loads", "shelve.open", "dill.load", "dill.loads", "yaml.unsafe_load"}
SUBPROCESS = {"subprocess.run", "subprocess.call", "subprocess.check_call",
              "subprocess.check_output", "subprocess.Popen", "subprocess.getoutput",
              "subprocess.getstatusoutput"}
OS_SHELL = {"os.system", "os.popen", "os.popen2", "os.popen3", "commands.getoutput"}


def _hi(line, msg, cat):
    f = finding(line, msg, "AST", cat)
    f["sev"] = "high"
    return f


def _lo(line, msg, cat):
    f = finding(line, msg, "AST", cat)
    f["sev"] = "low"
    return f


def _tool(ctx, index, sev):
    out = []
    for m in ctx.tool_output.get("bandit", []):
        mapped = BANDIT_MAP.get(m["test_id"])
        if mapped and mapped[0] == index:
            f = finding(m["line"], f"{m['message']} ({m['severity']} severity)",
                        f"Bandit {m['test_id']}", mapped[1])
            f["sev"] = sev(m)
            out.append(f)
    return out


def _sev(m):
    return "high" if m["severity"] in ("HIGH", "MEDIUM") else "low"


def _merge(a, b):
    """Merge and keep the highest severity per merged finding."""
    merged = merge_findings(a, b)
    rank = {}
    for item in a + b:
        key = (item["line"], item["cat"])
        if item.get("sev") == "high" or key not in rank:
            rank[key] = item.get("sev", "low") if rank.get(key) != "high" else "high"
    for item in merged:
        item["sev"] = rank.get((item["line"], item["cat"]), "low")
    return merged


# -------------------------------------------------------------------- 01
def check_eval_exec(ctx, aliases):
    found = []
    for node in ast.walk(ctx.tree):
        if isinstance(node, ast.Call):
            name = resolved_call_name(node, aliases)
            if name in ("eval", "exec", "builtins.eval", "builtins.exec"):
                const = node.args and isinstance(node.args[0], ast.Constant)
                maker = _lo if const else _hi
                found.append(maker(node.lineno, f"{name.split('.')[-1]}() executes arbitrary code"
                                   + (" (constant argument)." if const else
                                      " built from non-constant input."), "eval-exec"))
    return _merge(found, _tool(ctx, 0, _sev))


# -------------------------------------------------------------------- 02
def check_weak_hash(ctx, aliases):
    found = []
    for node in ast.walk(ctx.tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolved_call_name(node, aliases)
        weak = name in WEAK_HASHES or (
            name in ("hashlib.new",) and node.args and isinstance(node.args[0], ast.Constant)
            and str(node.args[0].value).lower() in ("md5", "sha1"))
        if weak and not any(k.arg == "usedforsecurity" and isinstance(k.value, ast.Constant)
                            and k.value.value is False for k in node.keywords):
            found.append(_hi(node.lineno, f"Weak hash algorithm via {name}(): MD5/SHA-1 are "
                             "broken for security use.", "weak-hash"))
    return _merge(found, _tool(ctx, 1, _sev))


# -------------------------------------------------------------------- 03
def _is_secret_name(name):
    return bool(name) and bool(SECRET_NAME.search(name)) and not SAFE_SUFFIX.search(name)


def _literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 1


def check_secrets(ctx):
    found = []

    def add(line, what):
        found.append(_hi(line, f"Hardcoded secret: {what}.", "secret"))

    for node in ast.walk(ctx.tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None and _literal(node.value):
                for t in targets:
                    name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else (
                        t.slice.value if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and isinstance(t.slice.value, str) else "")
                    if _is_secret_name(name):
                        add(node.lineno, f"'{name}' is assigned a string literal")
        elif isinstance(node, ast.keyword) and node.arg and _literal(node.value) and _is_secret_name(node.arg):
            add(node.value.lineno, f"argument '{node.arg}' is given a string literal")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = a.posonlyargs + a.args
            for arg, default in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                if _literal(default) and _is_secret_name(arg.arg):
                    add(default.lineno, f"parameter '{arg.arg}' has a hardcoded default")
            for arg, default in zip(a.kwonlyargs, a.kw_defaults):
                if default is not None and _literal(default) and _is_secret_name(arg.arg):
                    add(default.lineno, f"parameter '{arg.arg}' has a hardcoded default")
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is not None and _literal(k) and _literal(v) and _is_secret_name(k.value):
                    add(v.lineno, f"dictionary key '{k.value}' holds a string literal")
        elif isinstance(node, ast.Compare):
            sides = [node.left] + node.comparators
            names = [s.id for s in sides if isinstance(s, ast.Name)]
            if any(_is_secret_name(n) for n in names) and any(_literal(s) for s in sides):
                add(node.lineno, "a password-like variable is compared with a string literal")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and SECRET_VALUE.search(node.value):
            add(node.lineno, "a string looks like an API key or private key")
    return _merge(found, _tool(ctx, 2, lambda m: "high"))


# -------------------------------------------------------------------- 04
def _scope(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            return node
    return node


def check_resources(ctx, aliases):
    found, parents = [], parent_map(ctx.tree)
    for node in ast.walk(ctx.tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.startswith(("/tmp/", "/var/tmp/", "/dev/shm/")):
            found.append(_lo(node.lineno, f"Hardcoded temporary path '{node.value[:30]}' is predictable.",
                             "tmp-path"))
        if not isinstance(node, ast.Call):
            continue
        name = resolved_call_name(node, aliases)
        if name == "open":
            parent = parents.get(node)
            if isinstance(parent, ast.withitem):
                continue
            var = None
            if isinstance(parent, ast.Assign) and isinstance(parent.targets[0], ast.Name):
                var = parent.targets[0].id
            elif isinstance(parent, ast.Return):
                continue
            scope = _scope(node, parents)
            closed = var and any(
                (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "close"
                 and isinstance(c.func.value, ast.Name) and c.func.value.id == var)
                or (isinstance(c, ast.withitem) and isinstance(c.context_expr, ast.Name)
                    and c.context_expr.id == var)
                for c in ast.walk(scope))
            if not closed:
                found.append(_lo(node.lineno, "File opened without 'with' and never closed "
                                 "(resource leak).", "open-leak"))
        elif name in ("tempfile.mktemp",):
            found.append(_hi(node.lineno, "tempfile.mktemp() is insecure (race condition); use "
                             "NamedTemporaryFile or mkstemp.", "mktemp"))
        elif name in DESERIALIZE:
            found.append(_hi(node.lineno, f"{name}() can execute arbitrary code when loading "
                             "untrusted data.", "deserialize"))
        elif name == "yaml.load":
            safe = any(k.arg == "Loader" and "Safe" in ast.unparse(k.value) for k in node.keywords)
            if not safe:
                found.append(_hi(node.lineno, "yaml.load() without SafeLoader can execute code.",
                                 "deserialize"))
        elif name == "os.chmod" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, int) and node.args[1].value & 0o002:
            found.append(_hi(node.lineno, f"os.chmod() makes a file world-writable "
                             f"({oct(node.args[1].value)}).", "chmod"))
    return _merge(found, _tool(ctx, 3, _sev))


# -------------------------------------------------------------------- 05
def check_subprocess(ctx, aliases):
    found = []
    for node in ast.walk(ctx.tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolved_call_name(node, aliases)
        if name in OS_SHELL:
            found.append(_hi(node.lineno, f"{name}() runs a command through the shell.", "shell"))
        elif name.startswith(("os.exec", "os.spawn")):
            found.append(_hi(node.lineno, f"{name}() starts a process.", "shell"))
        elif name in SUBPROCESS:
            shell = next((k for k in node.keywords if k.arg == "shell"), None)
            if shell is not None and not (isinstance(shell.value, ast.Constant)
                                          and shell.value.value is False):
                found.append(_hi(node.lineno, f"{name}() is called with shell=True: command "
                                 "injection risk.", "shell"))
            elif not (node.args and isinstance(node.args[0], (ast.List, ast.Tuple))
                      and all(isinstance(e, ast.Constant) for e in node.args[0].elts)):
                found.append(_lo(node.lineno, f"{name}() is called with a non-literal command.",
                                 "subprocess"))
    return _merge(found, _tool(ctx, 4, _sev))


# ------------------------------------------------------------------- driver
def _verdict(found, high_fails=True):
    if not found:
        return PASSED
    if any(f.get("sev") == "high" for f in found):
        return FAILED if high_fails else WARNING
    return WARNING


def _strip(found):
    for f in found:
        f.pop("sev", None)
    return found


def analyze(ctx):
    ids = tests_for(TOOL)
    if ctx.syntax_error:
        return [not_evaluated(i, ctx) for i in ids]
    aliases = import_aliases(ctx.tree)
    note = " (Bandit CLI unavailable: AST rules only)" if "bandit" in ctx.tool_output.get("errors", {}) else ""
    checks = [
        (ids[0], check_eval_exec(ctx, aliases), "eval()/exec() call(s)",
         "Use ast.literal_eval() for data, or explicit dispatch tables instead of executing strings."),
        (ids[1], check_weak_hash(ctx, aliases), "weak MD5/SHA-1 hash use(s)",
         "Use hashlib.sha256()/sha3 (or bcrypt/argon2 for passwords)."),
        (ids[2], check_secrets(ctx), "hardcoded credential(s)",
         "Load secrets from environment variables (os.environ) or a secret manager."),
        (ids[3], check_resources(ctx, aliases), "unsafe resource/file handling pattern(s)",
         "Open files with 'with', use tempfile.NamedTemporaryFile, avoid pickle/yaml.load on "
         "untrusted data and never chmod 777."),
        (ids[4], check_subprocess(ctx, aliases), "unsafe command-execution call(s)",
         "Pass an argument list to subprocess.run([...], shell=False) and validate all input."),
    ]
    out = []
    for test_id, found, label, advice in checks:
        status = _verdict(found)
        text = f"{len(found)} {label} found." if found else f"No {label} found."
        out.append(result(test_id, status, text + note, _strip(found), advice))

    # Bandit findings that none of the five checks cover
    used = {(m["line"], m["test_id"]) for m in ctx.tool_output.get("bandit", [])
            if m["test_id"] in BANDIT_MAP}
    extras = [finding(m["line"], f"{m['message']} ({m['severity']} severity)", f"Bandit {m['test_id']}",
                      m["test_id"]) for m in ctx.tool_output.get("bandit", [])
              if (m["line"], m["test_id"]) not in used]
    ctx.extra_findings["bandit"] = extras
    return out

"""Runs the real Pylint, Flake8 and Bandit CLIs in resource-limited sandbox processes.

They only *read* the submitted file (they never import or execute it) and run in
parallel with the dynamic test run, which uses a different temporary directory.
"""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import sandbox

FILE = "submission.py"
PYLINT_ENABLE = ",".join([
    "unused-variable", "unused-argument", "unused-import", "wildcard-import",
    "unused-wildcard-import", "redefined-builtin", "too-many-nested-blocks",
    "bare-except", "dangerous-default-value", "too-many-arguments", "unnecessary-pass",
    "unreachable", "undefined-variable", "pointless-statement", "duplicate-key",
])
BANDIT_IMPORT_NOISE = {f"B{n}" for n in range(401, 417)}


def _pylint(workdir):
    Path(workdir, "pylintrc").write_text("[MASTER]\n", encoding="utf-8")
    proc = sandbox.run_python(
        ["-m", "pylint", "--rcfile=pylintrc", "--output-format=json", "--disable=all",
         f"--enable={PYLINT_ENABLE}", "--max-nested-blocks=3", "--max-args=5",
         "--persistent=n", "--score=n", "--jobs=1", FILE],
        workdir, config.TOOL_TIMEOUT)
    if proc.timed_out:
        return [], "Pylint timed out"
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], "Pylint produced no readable output: " + (proc.stderr or "")[-200:]
    return [{"line": m.get("line"), "symbol": m.get("symbol"), "code": m.get("message-id"),
             "message": m.get("message")} for m in data if isinstance(m, dict)], None


def _flake8(workdir):
    proc = sandbox.run_python(
        ["-m", "flake8", "--isolated", "--select=F", "--max-line-length=88",
         "--format=%(row)d|%(col)d|%(code)s|%(text)s", FILE], workdir, config.TOOL_TIMEOUT)
    if proc.timed_out:
        return [], "Flake8 timed out"
    out = []
    for raw in proc.stdout.splitlines():
        parts = raw.split("|", 3)
        if len(parts) == 4 and parts[0].isdigit():
            out.append({"line": int(parts[0]), "col": int(parts[1]), "code": parts[2],
                        "message": parts[3]})
    if proc.returncode not in (0, 1) and not out:
        return [], "Flake8 failed: " + (proc.stderr or "")[-200:]
    return out, None


def _bandit(workdir):
    proc = sandbox.run_python(
        ["-m", "bandit", "-f", "json", "-q", "--skip", "B101", FILE],
        workdir, config.TOOL_TIMEOUT)
    if proc.timed_out:
        return [], "Bandit timed out"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "Bandit produced no readable output: " + (proc.stderr or "")[-200:]
    out = []
    for r in data.get("results", []):
        if r.get("test_id") in BANDIT_IMPORT_NOISE:
            continue
        out.append({"line": r.get("line_number"), "test_id": r.get("test_id"),
                    "test_name": r.get("test_name"), "severity": r.get("issue_severity"),
                    "confidence": r.get("issue_confidence"), "message": r.get("issue_text")})
    return out, None


def run_static_tools(source):
    """Return {'pylint': [...], 'flake8': [...], 'bandit': [...], 'errors': {...}}."""
    with tempfile.TemporaryDirectory(prefix="cctd_static_") as workdir:
        Path(workdir, FILE).write_text(source, encoding="utf-8")
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {"pylint": pool.submit(_pylint, workdir),
                       "flake8": pool.submit(_flake8, workdir),
                       "bandit": pool.submit(_bandit, workdir)}
            results = {}
            for name, fut in futures.items():
                try:
                    results[name] = fut.result()
                except Exception as exc:                      # never crash the analysis
                    results[name] = ([], f"{name} failed: {exc}")
    return {"pylint": results["pylint"][0], "flake8": results["flake8"][0],
            "bandit": results["bandit"][0],
            "errors": {k: v[1] for k, v in results.items() if v[1]}}

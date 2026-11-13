"""Run untrusted or heavy work in a separate, resource-limited Python process.

The Flask process never imports or executes submitted code. Every external tool
and every dynamic test runs through ``run_python`` which provides:
  * a separate interpreter in isolated mode (-I) with a scrubbed environment
  * a wall-clock timeout and a whole-process-group kill
  * CPU / memory / file-size limits (Linux/macOS via ``resource``; on Windows the
    limits are unavailable, the timeout and the in-process guard still apply)
"""
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import config

LAUNCHER = Path(__file__).resolve().parent / "runtime" / "limited_run.py"
MAX_OUTPUT_CHARS = 3_000_000


@dataclass
class ProcResult:
    returncode: "int | None"
    stdout: str
    stderr: str
    timed_out: bool
    duration: float


def _safe_env(workdir):
    """Minimal environment: no server secrets or tokens are passed to children."""
    env = {
        "HOME": workdir, "TMPDIR": workdir, "TEMP": workdir, "TMP": workdir,
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "PYLINTHOME": workdir, "XDG_CACHE_HOME": workdir, "LC_ALL": "C.UTF-8",
    }
    if os.name == "nt":
        for key in ("SystemRoot", "SYSTEMROOT", "COMSPEC", "PATH", "PATHEXT"):
            if key in os.environ:
                env[key] = os.environ[key]
    else:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    return env


def run_python(args, workdir, timeout, memory_mb=None):
    """Run ``python -I limited_run.py ... -- <args>`` and return a ProcResult."""
    memory_mb = memory_mb or config.SANDBOX_MEMORY_MB
    cmd = [sys.executable, "-I", str(LAUNCHER), "--mem", str(memory_mb),
           "--cpu", str(int(timeout) + 5), "--", *args]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd, cwd=workdir, env=_safe_env(workdir), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    except OSError as exc:
        return ProcResult(None, "", f"could not start sandbox: {exc}", False, 0.0)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        out, err = proc.communicate()
    decode = lambda b: (b or b"").decode("utf-8", "replace")[:MAX_OUTPUT_CHARS]
    return ProcResult(proc.returncode, decode(out), decode(err), timed_out,
                      time.monotonic() - started)

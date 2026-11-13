"""Parent-side wrapper: runs the sandbox process for the dynamic PyTest + coverage run."""
import json
import secrets
import tempfile
from pathlib import Path

import config
import sandbox

RUNNER = Path(__file__).resolve().parent.parent / "runtime" / "sandbox_runner.py"
MODULE_FILE = "submission_under_test.py"


def run_dynamic(source):
    """Execute the submission ONLY inside the sandbox process.

    Returns {"ok", "data", "reason", "timed_out"}. ``data`` is the JSON written by
    sandbox_runner.py (records, calls, coverage, pytest output...).
    """
    nonce = "@@CCTD" + secrets.token_hex(8) + "@@"
    budget = max(5, config.DYNAMIC_TIMEOUT - 15)
    with tempfile.TemporaryDirectory(prefix="cctd_dyn_") as workdir:
        Path(workdir, MODULE_FILE).write_text(source, encoding="utf-8")
        proc = sandbox.run_python(
            [str(RUNNER), workdir, MODULE_FILE, nonce, str(budget)],
            workdir, timeout=config.DYNAMIC_TIMEOUT)
    parts = proc.stdout.split(nonce)
    if len(parts) >= 3:
        try:
            data = json.loads(parts[1])
            if not data.get("fatal"):
                return {"ok": True, "data": data, "reason": "", "timed_out": proc.timed_out}
            return {"ok": False, "data": data, "timed_out": proc.timed_out,
                    "reason": f"sandbox runner error: {data['fatal']}"}
        except json.JSONDecodeError:
            pass
    if proc.timed_out:
        reason = f"the sandbox exceeded the {config.DYNAMIC_TIMEOUT}s limit and was terminated"
    elif proc.returncode is not None and proc.returncode < 0:
        reason = f"the sandbox process was killed (signal {-proc.returncode}: CPU or memory limit)"
    else:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        reason = "the sandbox produced no result: " + " | ".join(tail)[:300]
    return {"ok": False, "data": None, "reason": reason, "timed_out": proc.timed_out}

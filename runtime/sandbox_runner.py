"""Entry point of the sandbox process (run via limited_run.py in an isolated interpreter).

argv: workdir module_file nonce time_budget_seconds
1. imports pytest/coverage, 2. installs the audit-hook guard, 3. starts coverage,
4. runs the five PyTest checks, 5. prints one JSON document between nonce markers.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)


def install_guard(workdir, state):
    """Audit hook: block network, process creation, ctypes and writes outside workdir.

    Defence in depth only - the hard boundary is the separate process, its resource
    limits and the (container) host. See README section 'Security model'.
    """
    import site
    import sysconfig
    real = os.path.realpath
    read_roots = {real(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix,
                                    sys.base_exec_prefix, workdir, HERE,
                                    os.path.dirname(HERE)) if p}
    read_roots |= {real(p) for p in sys.path if p and os.path.exists(p)}
    read_roots |= {real(p) for p in sysconfig.get_paths().values() if p}
    try:
        read_roots |= {real(p) for p in site.getsitepackages()}
    except Exception:
        pass
    extra_ok = {"/dev/null", "/dev/urandom", "/dev/random", "/etc/localtime"}
    workdir = real(workdir)
    deny_exact = {
        "socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg",
        "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
        "socket.getnameinfo", "subprocess.Popen", "os.system", "os.exec",
        "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "os.kill", "os.killpg",
        "os.startfile", "signal.pthread_kill", "urllib.Request", "http.client.connect",
        "ftplib.connect", "smtplib.connect", "telnetlib.Telnet.open", "pty.spawn",
        "os.setuid", "os.setgid", "os.chroot",
    }
    deny_prefix = ("ctypes.", "winreg.", "webbrowser.", "msvcrt.")
    write_events = {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                    "os.truncate", "os.utime", "os.chdir", "os.symlink", "os.link",
                    "os.rename", "os.setxattr", "os.removexattr"}
    import dynamic_state as st

    def inside(path, roots):
        return any(path == r or path.startswith(r + os.sep) for r in roots)

    def canon(target):
        if isinstance(target, int) or target is None:
            return None
        try:
            return real(os.fsdecode(os.fspath(target)))
        except (TypeError, ValueError):
            return None

    def block(event, detail):
        if len(state["violations"]) < 25:
            state["violations"].append(f"{event}: {detail}")
        raise st.SandboxViolation(f"sandbox blocked {event} ({detail})")

    def hook(event, args):
        if event == "open":
            path = canon(args[0])
            if path is None:
                return
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND
                                                     | os.O_CREAT | os.O_TRUNC))
            if writing:
                if not inside(path, [workdir]) and path not in extra_ok:
                    block("file write", path)
            elif not inside(path, read_roots) and path not in extra_ok:
                block("file read", path)
        elif event in deny_exact or event.startswith(deny_prefix):
            block(event, "operation not permitted in the test sandbox")
        elif event in write_events:
            for target in args[:2]:
                path = canon(target)
                if path is not None and not inside(path, [workdir]):
                    block(event, path)
        elif event in ("os.listdir", "os.scandir"):
            path = canon(args[0]) if args and args[0] is not None else workdir
            ancestor = path is not None and any(r.startswith(path + os.sep) for r in read_roots)
            if path is not None and not ancestor and not inside(path, read_roots):
                block(event, path)

    sys.addaudithook(hook)


def main():
    workdir, module_file, nonce, budget = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
    real_stdout = sys.__stdout__
    state = {"violations": []}
    result = {"violations": state["violations"], "records": {}, "calls": [],
              "coverage": {"available": False, "reason": "not started"},
              "import_error": None, "pytest_output": "", "outcomes": {}, "fatal": None}
    try:
        import time
        import coverage
        import pytest
        import dynamic_state as st
        module_path = os.path.realpath(os.path.join(workdir, module_file))
        with open(module_path, encoding="utf-8") as handle:
            source = handle.read()
        st.CONTEXT.update(source=source, module_path=module_path,
                          deadline=time.monotonic() + budget)
        sys.stdin = io.StringIO("")              # input() -> EOFError instead of blocking
        install_guard(workdir, state)

        cov = coverage.Coverage(branch=True, data_file=None, include=[module_path],
                                config_file=False)
        outcomes, sink = {}, io.StringIO()

        class Reporter:
            def pytest_runtest_logreport(self, report):
                if report.when == "call" or report.outcome == "failed":
                    outcomes[report.nodeid.split("::")[-1]] = report.outcome

        cov.start()
        try:
            real_out, real_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = sink
            pytest.main(["-p", "no:cacheprovider", "--assert=plain", "--color=no", "-q",
                         "--tb=short", "--capture=sys", "--rootdir", workdir,
                         os.path.join(HERE, "dynamic_suite.py")], plugins=[Reporter()])
        finally:
            sys.stdout, sys.stderr = real_out, real_err
            cov.stop()
        result["pytest_output"] = sink.getvalue()[-30000:]
        result["outcomes"] = outcomes
        result["records"] = st.RECORDS
        result["calls"] = st.CALLS
        result["import_error"] = st.import_error()
        try:
            report_path = os.path.join(workdir, "cov_report.json")
            cov.json_report(outfile=report_path, ignore_errors=True)
            with open(report_path, encoding="utf-8") as handle:
                data = json.load(handle)
            entry = next(iter(data["files"].values()), None)
            if entry is None:
                result["coverage"] = {"available": False, "reason": "no statements were measured"}
            else:
                s = entry["summary"]
                n_stmt, n_br = s["num_statements"], s.get("num_branches", 0)
                result["coverage"] = {
                    "available": True, "num_statements": n_stmt,
                    "covered_statements": s["covered_lines"],
                    "missing_lines": entry["missing_lines"],
                    "executed_lines": entry["executed_lines"],
                    "percent_statements": round(100.0 * s["covered_lines"] / n_stmt, 1) if n_stmt else None,
                    "num_branches": n_br, "covered_branches": s.get("covered_branches", 0),
                    "partial_branches": s.get("num_partial_branches", 0),
                    "missing_branches": entry.get("missing_branches", []),
                    "percent_branches": round(100.0 * s.get("covered_branches", 0) / n_br, 1) if n_br else None,
                    "percent_combined": round(s["percent_covered"], 1),
                }
        except Exception as exc:                         # coverage failure must not hide tests
            result["coverage"] = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    except BaseException as exc:
        result["fatal"] = f"{type(exc).__name__}: {exc}"
    real_stdout.write("\n" + nonce + json.dumps(result, default=repr) + nonce + "\n")
    real_stdout.flush()


if __name__ == "__main__":
    main()

"""Tiny launcher: apply OS resource limits, then run a module or script.

Usage: python -I limited_run.py --mem MB --cpu SECONDS -- -m pylint file.py
       python -I limited_run.py --mem MB --cpu SECONDS -- script.py args...
Using a launcher (instead of subprocess preexec_fn) is safe in multi-threaded servers.
"""
import argparse
import runpy
import sys


def apply_limits(mem_mb, cpu_s):
    try:
        import resource
    except ImportError:          # Windows: no resource module
        return

    def limit(which, value):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            pass

    if mem_mb:
        limit(resource.RLIMIT_AS, mem_mb * 1024 * 1024)
    if cpu_s:
        limit(resource.RLIMIT_CPU, cpu_s)
    limit(resource.RLIMIT_FSIZE, 10 * 1024 * 1024)
    limit(resource.RLIMIT_NOFILE, 256)
    limit(resource.RLIMIT_CORE, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mem", type=int, default=0)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    rest = ns.rest[1:] if ns.rest and ns.rest[0] == "--" else ns.rest
    apply_limits(ns.mem, ns.cpu)
    if rest and rest[0] == "-m":
        sys.argv = [rest[1]] + rest[2:]
        runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = rest
        runpy.run_path(rest[0], run_name="__main__")


if __name__ == "__main__":
    main()

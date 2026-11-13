"""Central configuration. Every value can be overridden with an environment variable."""
import os


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


MAX_CODE_BYTES = _int("MAX_CODE_BYTES", 100_000)      # largest accepted submission
DYNAMIC_TIMEOUT = _int("DYNAMIC_TIMEOUT", 40)         # seconds, sandboxed test run
TOOL_TIMEOUT = _int("TOOL_TIMEOUT", 60)               # seconds, pylint/flake8/bandit
SANDBOX_MEMORY_MB = _int("SANDBOX_MEMORY_MB", 1024)   # address-space cap (Linux only)
MAX_CONCURRENT = _int("MAX_CONCURRENT_ANALYSES", 2)   # simultaneous analyses per worker
COVERAGE_GATE = 80                                    # % statement-coverage target
COVERAGE_COMBINED_GATE = 75                           # % statement+branch target
MAX_LINE_LENGTH = 88

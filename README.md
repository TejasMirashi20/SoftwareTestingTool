# PyAssure – Complex Code Testing Dashboard (Python Edition)

A browser-based dashboard where you paste or upload Python source code and run **25 automated checks**
across five tools. It reports test results, coverage, cyclomatic complexity, security findings and a
heuristic defect-risk level. Built with Flask, Bootstrap 5.3 and Chart.js; deployable on Render.

Reference ideas came from the TestPulse site (same workflow: editor → 25 tests → metrics/charts/table);
the code, branding and UI here are original.

## The 25 tests (5 per module)

| Module | Real tools used | Tests |
|---|---|---|
| **PyTest** | `pytest` running inside the sandbox | 01 syntax compile + symbols · 02 callable inspection · 03 boundary values · 04 exception handling · 05 execution/return verification |
| **Coverage.py** | `coverage.py` (statement + branch) + AST | 01 statement coverage · 02 branches/decisions · 03 function reachability · 04 dead code · 05 threshold gate |
| **Pylint / Flake8** | `pylint`, `flake8` (pyflakes) + AST | 01 unused vars/params/imports · 02 wildcard imports · 03 built-in shadowing · 04 nesting depth · 05 empty blocks & smells |
| **Bandit** | `bandit` + AST rules | 01 eval/exec · 02 MD5/SHA-1 · 03 hardcoded secrets · 04 unsafe file/resource handling · 05 subprocess / `shell=True` |
| **PEP 8** | `pycodestyle` + AST | 01 4-space indent/tabs · 02 line length 88 · 03 naming · 04 import placement/grouping · 05 whitespace/formatting |

Each result has: ID, tool, name, description, **PASSED / WARNING / FAILED**, explanation, line number
(click it to jump in the editor), suggested correction and the individual findings.


### How the numbers are calculated (nothing is hard-coded)
* **Health score** = (passed + 0.5 × warnings) / 25 × 100
* **Statement coverage** – measured by coverage.py while the PyTest module imports the code and calls every
  public function/method with generated arguments (typed from annotations/names) and boundary values.
* **Cyclomatic complexity** – V(G) = E − N + 2P, computed as *decision points + 1* per routine
  (`if/elif/for/while/except/and/or/ternary/comprehension/match`). The headline value and risk band use the
  **most complex routine**; the program total and average are shown too. Radon's value is shown as a cross-check
  in the JSON.
* **Defect risk**: LOW 1–5 · MODERATE 6–12 · HIGH 13–25 · CRITICAL > 25. This is a **heuristic estimate** based on
  McCabe's thresholds, **not** a measured or guaranteed defect probability.
* **Security issues** = findings in the five Bandit tests + extra Bandit findings. **Code issues** = findings in
  the Pylint/Flake8 and PEP 8 tests.
* If a syntax error prevents a check from running, it is reported as WARNING "Not evaluated" (never faked).

## Project structure
```
ComplexCodeTestingDashboard/
  app.py                 Flask app + REST API (/api/analyze, /api/health, /api/samples)
  analyzer.py            orchestrator: runs the modules, builds metrics and logs
  sandbox.py             runs child processes with limits, timeouts and a scrubbed environment
  config.py              limits (env-overridable)
  analyzers/             pytest_, coverage_, pylint_, bandit_, pep8_, complexity_analyzer.py,
                         base.py (catalog of the 25 tests), static_tools.py, dynamic_runner.py
  runtime/               code that runs INSIDE the sandbox process (sandbox_runner, dynamic_suite, ...)
  templates/index.html   static/css/style.css   static/js/dashboard.js
  samples/               calculator.py  bank.py  ecommerce.py  buggy_code.py
  tests/test_dashboard.py   pytest suite for the project itself
  requirements.txt  Procfile  render.yaml  TESTING_CHECKLIST.md
```

## Run locally on Windows 10
1. Install **Python 3.11** from python.org (tick *Add python.exe to PATH*). Check: `python --version`.
2. Open **PowerShell** or **Command Prompt** in the project folder:
   ```
   cd path\to\ComplexCodeTestingDashboard
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
   (PowerShell: if activation is blocked run `Set-ExecutionPolicy -Scope Process Bypass` first.)
3. Open **http://localhost:5000**. Load a sample, click **Run Automated Testing Suite (25 Tests)**.
4. The page loads Bootstrap, Chart.js and CodeMirror from CDNs, so it needs internet access.
5. Run the project's own tests: `python -m pytest tests -v`

> Windows note: the memory/CPU limits use the `resource` module, which exists only on Linux/macOS. On Windows
> the timeout, the isolated child process and the in-process guard still apply, but memory is not capped.
> The Windows path was written carefully but **not run on Windows** while building this; Linux (Render) was.

## API
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | `{"status":"ok", ...}` |
| GET | `/api/samples` | the four sample programs (`id,title,description,code`) |
| POST | `/api/analyze` | body `{"code": "..."}` → metrics, 25 tests, complexity, coverage, logs. `400` empty/invalid, `413` too large, `503` busy |

## Security model (read before hosting publicly)
* Submitted code is **never executed in the Flask process**. Dynamic tests run in a separate
  `python -I` process with a scrubbed environment (no server secrets), a wall-clock timeout (process group is
  killed), per-call 2 s timeouts, and on Linux CPU / memory (`RLIMIT_AS`) / file-size / open-file limits.
* Inside that process an **audit hook** blocks network access, subprocess/exec/fork, `os.kill`, `ctypes`, writes
  outside the temp directory and reads outside the Python installation + temp directory.
* Static tools (Pylint, Flake8, Bandit, pycodestyle, AST) only *read* the code; they run separately.
* Uploads/pastes are limited to 100 KB (`MAX_CODE_BYTES`), `.py` only on upload; at most 2 concurrent analyses
  per worker (`503` otherwise).
* **Honest limits:** audit hooks are defence in depth, not a perfect jail, and `RLIMIT_AS` is per process. For a
  public multi-user service, run each analysis in a throw-away container (gVisor/nsjail/Docker with
  `--network none --read-only`). Render's container already isolates the app from other customers.

## Push to GitHub
```
git init
git add .
git commit -m "PyAssure: Complex Code Testing Dashboard"
git branch -M main
git remote add origin https://github.com/<your-user>/complex-code-testing-dashboard.git
git push -u origin main
```
Create the empty repository first on github.com (*New repository*, no README). If asked for a password,
use a **personal access token** (Settings → Developer settings → Tokens).

## Deploy on Render
1. Sign in at https://render.com with GitHub and click **New + → Web Service** (or **Blueprint** to use `render.yaml`).
2. Select your repository.
3. Settings (a Blueprint fills these in): **Runtime** Python 3 · **Build** `pip install -r requirements.txt` ·
   **Start** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120` ·
   **Health check path** `/api/health`.
4. Environment: `PYTHON_VERSION=3.11.9` (optional: `MAX_CODE_BYTES`, `SANDBOX_MEMORY_MB`, `MAX_CONCURRENT_ANALYSES`).
5. Click **Create Web Service**; the first build takes a few minutes. Open the `onrender.com` URL.
6. Free instances sleep after inactivity (first request ≈ 30–60 s) and have 512 MB RAM, so keep `--workers 1`.
   `$PORT` is provided by Render; `app.py` also reads `PORT` for local runs.

## Troubleshooting
* *Page has no styling/editor* → the CDN is blocked; check your internet connection.
* *Some tests say "Not evaluated"* → the code has a syntax error, or the sandbox exceeded its time limit.
* *Very slow first analysis* → Pylint start-up; later runs are faster. Raise `TOOL_TIMEOUT` if needed.

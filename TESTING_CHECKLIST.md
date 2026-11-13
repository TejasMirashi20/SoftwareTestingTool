# Testing checklist – verify all 25 test cases

Run the app (`python app.py`), open http://localhost:5000 and tick each row.
Expected statuses were produced by running the project itself; the buggy sample is
deterministic (`python -m pytest tests -v` asserts them automatically).

## A. Per-test verification
| # | Test ID | Module | How to trigger it | Calculator sample | Buggy sample | Done |
|---|---|---|---|---|---|---|
| 1 | TC-PYTEST-01 | Syntax compilation and symbol discovery | Type `def f(:` → FAILED with line number. Clean code → PASSED. | PASSED | PASSED | ☐ |
| 2 | TC-PYTEST-02 | Function and callable inspection | Remove a docstring from any function → WARNING. | PASSED | WARNING | ☐ |
| 3 | TC-PYTEST-03 | Boundary and conditional checks | `def d(a: float, b: float): return a / b` → boundary b=0 crashes. | PASSED | FAILED | ☐ |
| 4 | TC-PYTEST-04 | Exception handling inspection | Add `except:` + `pass` → FAILED; division without try/raise → WARNING. | PASSED | FAILED | ☐ |
| 5 | TC-PYTEST-05 | Function return and execution verification | `def f(items: list): return items[10]` → crashes on sample input. | PASSED | FAILED | ☐ |
| 6 | TC-COV-01 | Statement coverage | Add a function with an unexecuted `else` branch → coverage drops. | PASSED | PASSED | ☐ |
| 7 | TC-COV-02 | Branch and decision identification | Branches never taken are listed as `line A -> line B`. | PASSED | WARNING | ☐ |
| 8 | TC-COV-03 | Function registration and reachability | Define a private helper that nothing calls → WARNING (unreached). | PASSED | WARNING | ☐ |
| 9 | TC-COV-04 | Dead code detection | Put a statement after `return`, or use `if False:` → FAILED. | PASSED | FAILED | ☐ |
| 10 | TC-COV-05 | Coverage threshold compliance | Compare combined statement+branch coverage with the 75 % gate. | PASSED | PASSED | ☐ |
| 11 | TC-PYLINT-01 | Unused variables and parameters | Assign a variable and never use it; add an unused import/parameter. | PASSED | FAILED | ☐ |
| 12 | TC-PYLINT-02 | Wildcard imports | `from os.path import *` | PASSED | WARNING | ☐ |
| 13 | TC-PYLINT-03 | Built-in variable shadowing | `def f(id, type): max = 1` | PASSED | FAILED | ☐ |
| 14 | TC-PYLINT-04 | Excessive nesting depth | Nest if/for/while 4+ levels deep (5+ → FAILED). | PASSED | FAILED | ☐ |
| 15 | TC-PYLINT-05 | Empty blocks and code smells | Empty `if x: pass`, bare `except:`, `def f(x=[])`. | PASSED | FAILED | ☐ |
| 16 | TC-BANDIT-01 | Dangerous eval() and exec() calls | `eval(user_text)` or `exec(code)` | PASSED | FAILED | ☐ |
| 17 | TC-BANDIT-02 | Weak MD5/SHA1 cryptographic algorithms | `hashlib.md5(...)` or `hashlib.sha1(...)` | PASSED | FAILED | ☐ |
| 18 | TC-BANDIT-03 | Hardcoded passwords and API keys | `PASSWORD = "admin123"`, `API_KEY = "sk-..."` | PASSED | FAILED | ☐ |
| 19 | TC-BANDIT-04 | Unsafe resource and file handling patterns | `open(p)` without `with`, `pickle.loads`, `tempfile.mktemp`, `os.chmod(p, 0o777)` | PASSED | FAILED | ☐ |
| 20 | TC-BANDIT-05 | Unsafe subprocess calls and shell=True | `subprocess.call(cmd, shell=True)`, `os.system(...)` | PASSED | FAILED | ☐ |
| 21 | TC-PEP8-01 | Four-space indentation and tab detection | Indent a function with a TAB or 2 spaces. | PASSED | FAILED | ☐ |
| 22 | TC-PEP8-02 | Maximum line length (88 characters) | Write a line longer than 88 characters. | PASSED | WARNING | ☐ |
| 23 | TC-PEP8-03 | Class and function naming conventions | `def calculateTotal(theValue)` or `class manager:` | PASSED | FAILED | ☐ |
| 24 | TC-PEP8-04 | Import placement and grouping | `import os, sys` or an `import` after code; stdlib/third-party not grouped. | PASSED | WARNING | ☐ |
| 25 | TC-PEP8-05 | Trailing whitespace and formatting | Trailing spaces, missing blank lines, `x=1+2`. | PASSED | FAILED | ☐ |

## B. Whole-dashboard checks
- [ ] Each sample (Calculator, Bank, E-commerce, Buggy) loads from the dropdown and runs without error.
- [ ] After a run exactly **25** rows exist, grouped in **5** tool groups of 5; no ID is duplicated.
- [ ] Passed + Warnings + Failed = 25 and equals the three counters and the doughnut chart.
- [ ] Health score = (passed + 0.5 × warnings) / 25 × 100.
- [ ] Coverage card equals the Statements bar and the Coverage tab in *Raw tool output*.
- [ ] Complexity card equals the top row of the complexity table; risk band matches 1–5 / 6–12 / 13–25 / >25
      (Calculator LOW, E-commerce HIGH, Buggy CRITICAL).
- [ ] "Heuristic estimate" wording is visible on the Defect Risk card and the disclaimer.
- [ ] Security issues = sum of findings in the five Bandit tests (+ extra Bandit findings in the Bandit tab).
- [ ] Search box, status filter and tool pills filter the rows; the "showing N of 25" counter updates.
- [ ] Clicking a row expands explanation, suggestion and findings; clicking `line N` highlights it in the editor.
- [ ] Download report works for HTML, JSON and CSV; Reset analysis clears the results.
- [ ] Timestamp and duration are shown.

## C. Error handling
- [ ] Empty editor → red message, no request is sent.
- [ ] `def f(:` → all 25 rows shown, TC-PYTEST-01 FAILED, red syntax-error banner, risk UNKNOWN.
- [ ] Upload a `.txt` file → "Only .py files can be uploaded".
- [ ] Paste more than 100 KB → "too large" message.
- [ ] `while True: pass` → finishes within ~10 s; TC-PYTEST-05 FAILED (time limit).
- [ ] `import os; os.system("echo hi")` inside a function → listed under "operations blocked by the sandbox".
- [ ] Mobile width (< 576 px): layout stacks, nothing overflows horizontally.

## D. API (curl)
```
curl http://localhost:5000/api/health
curl http://localhost:5000/api/samples
curl -X POST http://localhost:5000/api/analyze -H "Content-Type: application/json" -d "{\"code\": \"print(1)\"}"
```

"""Flask application: serves the dashboard and the REST API."""
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import config
from analyzer import analyze_source

BASE = Path(__file__).resolve().parent
SAMPLES = [
    ("calculator", "Scientific Calculator", "Clean, modular, defensive code."),
    ("bank", "Bank Account Management", "Classes, custom exceptions, validation."),
    ("ecommerce", "E-commerce Order Management", "Many business rules / high branching."),
    ("buggy_code", "Intentionally Buggy Python Program", "Triggers findings in every module."),
]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CODE_BYTES * 4 + 4096   # JSON escaping overhead
app.config["JSON_SORT_KEYS"] = False
_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT)


def _error(message, status):
    return jsonify({"ok": False, "error": message}), status


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(413)
def too_large(_):
    return _error(f"Submission too large. The limit is {config.MAX_CODE_BYTES // 1000} KB.", 413)


@app.errorhandler(404)
def not_found(_):
    return _error("Not found.", 404)


@app.errorhandler(500)
def server_error(_):
    return _error("Unexpected server error. Please try again.", 500)


@app.get("/")
def index():
    return render_template("index.html", max_bytes=config.MAX_CODE_BYTES)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "complex-code-testing-dashboard",
                    "tests": 25, "max_code_bytes": config.MAX_CODE_BYTES})


@app.get("/api/samples")
def samples():
    out = []
    for sample_id, title, description in SAMPLES:
        code = (BASE / "samples" / f"{sample_id}.py").read_text(encoding="utf-8")
        out.append({"id": sample_id, "title": title, "description": description, "code": code})
    return jsonify({"ok": True, "samples": out})


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "code" not in payload:
        return _error("Send JSON like {\"code\": \"<python source>\"}.", 400)
    code = payload["code"]
    if not isinstance(code, str):
        return _error("'code' must be a string.", 400)
    if not code.strip():
        return _error("The code editor is empty. Paste or upload some Python code first.", 400)
    if "\x00" in code:
        return _error("The submission contains null bytes and is not valid Python text.", 400)
    if len(code.encode("utf-8")) > config.MAX_CODE_BYTES:
        return _error(f"Submission too large. The limit is {config.MAX_CODE_BYTES // 1000} KB.", 413)
    if not _slots.acquire(blocking=False):
        return _error("The server is busy analysing other submissions. Try again in a few seconds.", 503)
    try:
        return jsonify(analyze_source(code))
    except Exception as exc:                                   # meaningful diagnostics, no crash
        app.logger.exception("analysis failed")
        return _error(f"Analysis failed unexpectedly ({type(exc).__name__}). "
                      "Please check the code and try again.", 500)
    finally:
        _slots.release()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")

"""Automated tests for the dashboard itself. Run with:  python -m pytest tests -v"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analyzer import analyze_source          # noqa: E402
from analyzers.base import CATALOG           # noqa: E402
from app import app                          # noqa: E402

EXPECTED_IDS = [row[0] for row in CATALOG]


def sample(name):
    return (ROOT / "samples" / f"{name}.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def results():
    return {n: analyze_source(sample(n)) for n in ("calculator", "bank", "ecommerce", "buggy_code")}


def test_catalog_has_25_unique_ids_five_per_tool():
    assert len(EXPECTED_IDS) == 25 == len(set(EXPECTED_IDS))
    for tool in ("pytest", "coverage", "pylint", "bandit", "pep8"):
        assert sum(1 for row in CATALOG if row[1] == tool) == 5


@pytest.mark.parametrize("name", ["calculator", "bank", "ecommerce", "buggy_code"])
def test_every_id_appears_exactly_once(results, name):
    assert [t["id"] for t in results[name]["tests"]] == EXPECTED_IDS
    for t in results[name]["tests"]:
        assert t["status"] in ("PASSED", "WARNING", "FAILED")
        assert t["explanation"] and t["name"] and t["description"]


@pytest.mark.parametrize("name", ["calculator", "bank", "ecommerce", "buggy_code"])
def test_metrics_match_results(results, name):
    r = results[name]
    m, tests = r["metrics"], r["tests"]
    count = lambda s: sum(t["status"] == s for t in tests)
    assert (m["passed"], m["warnings"], m["failed"]) == (count("PASSED"), count("WARNING"), count("FAILED"))
    assert m["passed"] + m["warnings"] + m["failed"] == 25
    assert m["health_score"] == round((m["passed"] + 0.5 * m["warnings"]) / 25 * 100, 1)
    assert m["statement_coverage"] == r["coverage"]["percent_statements"]
    assert m["cyclomatic_complexity"] == r["complexity"]["value"]
    sec = sum(t["finding_count"] for t in tests if t["tool_key"] == "bandit")
    assert m["security_issues"] == sec + len(r["extra_findings"]["bandit"])
    assert m["code_issues"] == sum(t["finding_count"] for t in tests if t["tool_key"] in ("pylint", "pep8"))


def test_clean_samples_pass_everything(results):
    for name in ("calculator", "bank", "ecommerce"):
        assert results[name]["metrics"]["failed"] == 0
        assert results[name]["metrics"]["security_issues"] == 0


def test_risk_bands(results):
    assert results["calculator"]["metrics"]["defect_risk"] == "LOW"
    assert results["ecommerce"]["metrics"]["defect_risk"] == "HIGH"
    assert results["buggy_code"]["metrics"]["defect_risk"] == "CRITICAL"


def test_buggy_sample_triggers_every_module(results):
    by_id = {t["id"]: t for t in results["buggy_code"]["tests"]}
    for test_id in ("TC-PYTEST-03", "TC-PYTEST-04", "TC-PYTEST-05", "TC-COV-04", "TC-PYLINT-01",
                    "TC-PYLINT-03", "TC-PYLINT-04", "TC-PYLINT-05", "TC-BANDIT-01", "TC-BANDIT-02",
                    "TC-BANDIT-03", "TC-BANDIT-04", "TC-BANDIT-05", "TC-PEP8-01", "TC-PEP8-03",
                    "TC-PEP8-05"):
        assert by_id[test_id]["status"] == "FAILED", test_id
    assert by_id["TC-PYLINT-02"]["status"] != "PASSED"
    assert by_id["TC-PEP8-02"]["status"] != "PASSED"


def test_syntax_error_is_reported_not_crashed():
    r = analyze_source("def broken(:\n    pass\n")
    assert r["ok"] and len(r["tests"]) == 25 and r["syntax_error"]["line"] == 1
    assert r["tests"][0]["status"] == "FAILED"
    assert r["metrics"]["defect_risk"] == "UNKNOWN"


def test_sandbox_blocks_dangerous_operations():
    code = ("import os, socket\n"
            "def kill():\n    os.kill(os.getppid(), 9)\n"
            "def net():\n    socket.create_connection(('example.com', 80))\n"
            "def write():\n    open('/etc/cctd_should_not_exist', 'w')\n")
    r = analyze_source(code)
    log = r["logs"]["pytest"]
    assert "os.kill" in log and "/etc/cctd_should_not_exist" in log
    assert not Path("/etc/cctd_should_not_exist").exists()


def test_infinite_loop_is_terminated():
    r = analyze_source("while True:\n    pass\n")
    assert r["tests"][4]["status"] == "FAILED" and "time limit" in r["tests"][4]["explanation"]


def test_api_validation_and_samples():
    client = app.test_client()
    assert client.get("/api/health").json["status"] == "ok"
    assert len(client.get("/api/samples").json["samples"]) == 4
    assert client.post("/api/analyze", json={"code": ""}).status_code == 400
    assert client.post("/api/analyze", json={"code": 5}).status_code == 400
    assert client.post("/api/analyze", data="nope", content_type="text/plain").status_code == 400
    assert client.post("/api/analyze", json={"code": "#" * 200000}).status_code == 413
    ok = client.post("/api/analyze", json={"code": sample("calculator")})
    assert ok.status_code == 200 and len(ok.json["tests"]) == 25

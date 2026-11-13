/* PyAssure dashboard: editor, API calls, rendering, filtering and report download. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const MAX_BYTES = parseInt(document.body.dataset.maxBytes, 10) || 100000;
  const COLORS = { PASSED: "#16a34a", WARNING: "#f59e0b", FAILED: "#dc2626" };
  const TOOL_ICONS = { pytest: "bi-bug", coverage: "bi-bullseye", pylint: "bi-search",
                       bandit: "bi-shield-lock", pep8: "bi-braces" };
  const state = { result: null, charts: {}, toolFilter: "", samples: [] };

  // HTML-escape everything that comes from analysed code or tools (prevents XSS).
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtPct = (v) => (v === null || v === undefined ? "N/A" : `${Number(v)}%`);

  // ------------------------------------------------------------------ editor
  const editor = CodeMirror.fromTextArea($("codeInput"), {
    mode: "python", theme: "dracula", lineNumbers: true, indentUnit: 4,
    indentWithTabs: false, matchBrackets: true, lineWrapping: false,
    extraKeys: { Tab: (cm) => cm.replaceSelection("    ", "end") },
  });
  const updateStats = () => {
    const text = editor.getValue();
    const bytes = new Blob([text]).size;
    $("codeStats").textContent = `${editor.lineCount()} lines · ${text.length} characters · ` +
      `${(bytes / 1000).toFixed(1)} KB of ${(MAX_BYTES / 1000).toFixed(0)} KB`;
  };
  editor.on("change", updateStats);
  updateStats();

  const showInputError = (msg) => {
    const box = $("inputError");
    box.textContent = msg;
    box.classList.toggle("d-none", !msg);
  };

  async function loadSamples() {
    try {
      const res = await fetch("/api/samples");
      const data = await res.json();
      state.samples = data.samples || [];
      state.samples.forEach((s, i) => {
        const opt = document.createElement("option");
        opt.value = i;
        opt.textContent = `${i + 1}. ${s.title}`;
        $("sampleSelect").appendChild(opt);
      });
    } catch (e) {
      showInputError("Could not load sample programs from the server.");
    }
  }
  $("sampleSelect").addEventListener("change", (e) => {
    const sample = state.samples[e.target.value];
    if (sample) { editor.setValue(sample.code); showInputError(""); }
    e.target.value = "";
  });
  $("uploadBtn").addEventListener("click", () => $("fileInput").click());
  $("fileInput").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".py")) return showInputError("Only .py files can be uploaded.");
    if (file.size > MAX_BYTES) return showInputError(`File too large (limit ${MAX_BYTES / 1000} KB).`);
    const reader = new FileReader();
    reader.onload = () => { editor.setValue(String(reader.result)); showInputError(""); };
    reader.onerror = () => showInputError("Could not read that file.");
    reader.readAsText(file);
  });
  $("clearBtn").addEventListener("click", () => { editor.setValue(""); showInputError(""); editor.focus(); });

  // --------------------------------------------------------------------- run
  const STEPS = ["Compiling and discovering symbols…", "Running pytest in the sandbox…",
    "Measuring coverage…", "Running Pylint & Flake8…", "Scanning with Bandit…",
    "Checking PEP 8 style…", "Computing McCabe complexity…"];
  let stepTimer = null;
  function setRunning(on) {
    $("runBtn").disabled = on;
    $("runSpinner").classList.toggle("d-none", !on);
    $("runIcon").classList.toggle("d-none", on);
    clearInterval(stepTimer);
    if (on) {
      let i = 0;
      $("runLabel").textContent = STEPS[0];
      stepTimer = setInterval(() => { i = (i + 1) % STEPS.length; $("runLabel").textContent = STEPS[i]; }, 1400);
    } else {
      $("runLabel").textContent = "Run Automated Testing Suite (25 Tests)";
    }
  }

  async function runSuite() {
    const code = editor.getValue();
    showInputError("");
    if (!code.trim()) return showInputError("The editor is empty. Paste, upload or load a sample program first.");
    if (new Blob([code]).size > MAX_BYTES) return showInputError(`Code is too large (limit ${MAX_BYTES / 1000} KB).`);
    setRunning(true);
    try {
      const res = await fetch("/api/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
      });
      let data = null;
      try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
      if (!res.ok || !data || !data.ok) {
        return showInputError((data && data.error) || `Server returned an error (HTTP ${res.status}).`);
      }
      state.result = data;
      render(data);
      $("resultsArea").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showInputError("Network error: could not reach the analysis server.");
    } finally {
      setRunning(false);
    }
  }
  $("runBtn").addEventListener("click", runSuite);

  function resetAnalysis() {
    state.result = null;
    Object.values(state.charts).forEach((c) => c.destroy());
    state.charts = {};
    $("resultsArea").classList.add("d-none");
    $("placeholder").classList.remove("d-none");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  $("resetBtn").addEventListener("click", resetAnalysis);

  // ------------------------------------------------------------------ render
  function setRing(id, valueId, pct, color) {
    const ring = $(id);
    ring.style.setProperty("--p", pct ?? 0);
    ring.style.setProperty("--c", color);
    $(valueId).textContent = pct === null || pct === undefined ? "N/A" : `${pct}%`;
  }
  const ringColor = (p) => (p === null ? "#94a3b8" : p >= 80 ? "#16a34a" : p >= 50 ? "#f59e0b" : "#dc2626");

  function render(r) {
    const m = r.metrics;
    $("placeholder").classList.add("d-none");
    $("resultsArea").classList.remove("d-none");
    $("timestamp").innerHTML = `<i class="bi bi-clock"></i> ${esc(new Date(r.timestamp).toLocaleString())}`;
    $("duration").innerHTML = `<i class="bi bi-stopwatch"></i> ${(r.duration_ms / 1000).toFixed(1)} s`;

    const se = r.syntax_error;
    $("syntaxBanner").classList.toggle("d-none", !se);
    if (se) $("syntaxBanner").innerHTML = `<strong><i class="bi bi-x-octagon"></i> Syntax error</strong> ` +
      `${se.line ? `on line ${esc(se.line)}` : ""}: ${esc(se.message)}. Tests that need a parsed program ` +
      `could not be evaluated; fix the error and run again.`;
    $("notesBanner").classList.toggle("d-none", !(r.notes && r.notes.length));
    $("notesBanner").innerHTML = (r.notes || []).map(esc).join("<br>");

    setRing("ringHealth", "mHealth", m.health_score, ringColor(m.health_score));
    setRing("ringCov", "mCov", m.statement_coverage, ringColor(m.statement_coverage));
    $("mCovSub").textContent = m.branch_coverage === null ? "coverage.py" : `branch ${m.branch_coverage}%`;
    $("mCC").textContent = m.cyclomatic_complexity ?? "N/A";
    $("mCCSub").textContent = r.complexity.max_function ? `max V(G) in ${r.complexity.max_function}` : "max V(G)";
    const risk = $("mRisk");
    risk.textContent = m.defect_risk;
    risk.className = `risk-pill risk-${m.defect_risk}`;
    $("mPassed").textContent = m.passed; $("mWarn").textContent = m.warnings;
    $("mFailed").textContent = m.failed; $("mSec").textContent = m.security_issues;
    $("mCode").textContent = m.code_issues;

    renderComplexity(r.complexity);
    renderCharts(r);
    renderResults(r);
    renderLogs(r.logs);
  }

  function renderComplexity(c) {
    $("ccFormula").textContent = c.formula || "";
    $("ccDisclaimer").innerHTML = `<i class="bi bi-info-circle"></i> ${esc(c.disclaimer)}`;
    const marker = $("bandMarker");
    if (!c.available) {
      marker.style.left = "-50px";
      $("ccSummary").textContent = c.reason || "Complexity unavailable.";
      $("ccTable").innerHTML = ""; $("ccRecs").innerHTML = "";
      return;
    }
    const v = c.value;
    const pos = v <= 5 ? (v / 5) * 25 : v <= 12 ? 25 + ((v - 5) / 7) * 25 : v <= 25 ? 50 + ((v - 12) / 13) * 25
      : 75 + Math.min((v - 25) / 25, 1) * 25;
    marker.style.left = `${Math.min(pos, 99)}%`;
    $("ccSummary").innerHTML = `Highest V(G): <strong>${esc(v)}</strong> in <code>${esc(c.max_function)}</code> ` +
      `(${esc(c.risk)}, band ${esc(c.risk_band)}). Program total: <strong>${esc(c.total)}</strong> over ` +
      `${esc(c.routines)} routine(s), average ${esc(c.average)}.` +
      (c.maintainability_index !== null && c.maintainability_index !== undefined
        ? ` Maintainability index: ${esc(c.maintainability_index)}.` : "");
    $("ccTable").innerHTML = c.functions.slice(0, 8).map((f) =>
      `<tr><td><code>${esc(f.name)}</code></td><td><span class="line-link text-primary" data-line="${esc(f.line)}">${esc(f.line)}</span></td>` +
      `<td class="text-end fw-semibold">${esc(f.complexity)}</td><td><span class="badge text-bg-secondary">${esc(f.rank)}</span></td></tr>`).join("");
    $("ccRecs").innerHTML = c.recommendations.map((t) => `<li>${esc(t)}</li>`).join("");
  }

  function renderCharts(r) {
    Object.values(state.charts).forEach((c) => c.destroy());
    const m = r.metrics;
    state.charts.radar = new Chart($("radarChart"), {
      type: "radar",
      data: { labels: r.modules.map((x) => x.tool),
        datasets: [{ label: "Score (%)", data: r.modules.map((x) => x.score), fill: true,
          backgroundColor: "rgba(79,70,229,.2)", borderColor: "#4f46e5", pointBackgroundColor: "#4f46e5" }] },
      options: { maintainAspectRatio: false, scales: { r: { min: 0, max: 100, ticks: { stepSize: 25 } } },
        plugins: { legend: { display: false } } },
    });
    state.charts.doughnut = new Chart($("doughnutChart"), {
      type: "doughnut",
      data: { labels: ["Passed", "Warning", "Failed"],
        datasets: [{ data: [m.passed, m.warnings, m.failed], backgroundColor: [COLORS.PASSED, COLORS.WARNING, COLORS.FAILED] }] },
      options: { maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom" } } },
    });
    const bar = (label, v, note) => {
      const color = v === null ? "bg-secondary" : v >= 80 ? "bg-success" : v >= 50 ? "bg-warning" : "bg-danger";
      return `<div class="mb-3"><div class="d-flex justify-content-between small"><span>${label}</span>` +
        `<strong>${fmtPct(v)}</strong></div><div class="progress" style="height:14px"><div class="progress-bar ${color}" ` +
        `style="width:${v ?? 0}%"></div></div>${note ? `<small class="text-secondary">${note}</small>` : ""}</div>`;
    };
    $("covBars").innerHTML = bar("Statements", m.statement_coverage, "Gate: 80%") +
      bar("Branches", m.branch_coverage, "") + bar("Combined", m.combined_coverage, "Gate: 75%") +
      (r.coverage && r.coverage.available ? `<small class="text-secondary">${esc(r.coverage.covered_statements)} of ` +
        `${esc(r.coverage.num_statements)} statements executed</small>` : `<small class="text-secondary">Coverage unavailable.</small>`);
  }

  function renderResults(r) {
    const groups = {};
    r.tests.forEach((t) => (groups[t.tool_key] = groups[t.tool_key] || []).push(t));
    $("toolPills").innerHTML = `<button class="btn btn-sm btn-primary pill-btn" data-tool="">All (${r.tests.length})</button>` +
      r.modules.map((mod) => `<button class="btn btn-sm btn-outline-primary pill-btn" data-tool="${mod.key}">` +
        `<i class="bi ${TOOL_ICONS[mod.key]}"></i> ${esc(mod.tool)}</button>`).join("");
    state.toolFilter = "";
    $("resultGroups").innerHTML = r.modules.map((mod) => {
      const rows = groups[mod.key].map((t) => testRow(t)).join("");
      return `<div class="tool-group" data-tool="${mod.key}"><div class="tool-head">` +
        `<i class="bi ${TOOL_ICONS[mod.key]} text-primary fs-5"></i><strong>${esc(mod.tool)}</strong>` +
        `<span class="st st-PASSED">${mod.passed} passed</span><span class="st st-WARNING">${mod.warnings} warning</span>` +
        `<span class="st st-FAILED">${mod.failed} failed</span><span class="score">Score ${mod.score}%</span></div>${rows}</div>`;
    }).join("");
    applyFilters();
  }

  function testRow(t) {
    const id = `d-${t.id}`;
    const lineBadge = t.line ? `<span class="badge text-bg-light border line-link" data-line="${esc(t.line)}" title="Jump to line in editor">` +
      `<i class="bi bi-geo-alt"></i> line ${esc(t.line)}</span>` : "";
    const findings = t.findings.length ? `<dt>Findings (${t.finding_count})</dt><dd><ul class="finding-list">` +
      t.findings.map((f) => `<li>${f.line ? `<span class="line-link text-primary" data-line="${esc(f.line)}">L${esc(f.line)}</span> – ` : ""}` +
        `${esc(f.message)} <span class="src">[${esc(f.source)}]</span></li>`).join("") + `</ul></dd>` : "";
    return `<div class="test-row" data-status="${t.status}" data-tool="${t.tool_key}" ` +
      `data-text="${esc((t.id + " " + t.name + " " + t.explanation + " " + t.tool).toLowerCase())}">` +
      `<button type="button" data-bs-toggle="collapse" data-bs-target="#${id}" aria-expanded="false">` +
      `<span class="test-id">${esc(t.id)}</span><span class="test-name">${esc(t.name)}</span>${lineBadge}` +
      `<span class="st st-${t.status}">${t.status}</span><i class="bi bi-chevron-down"></i></button>` +
      `<div class="collapse" id="${id}"><div class="test-detail"><dl class="mb-0">` +
      `<dt>What is tested</dt><dd>${esc(t.description)}</dd>` +
      `<dt>Explanation</dt><dd>${esc(t.explanation)}</dd>` +
      `<dt>Tool</dt><dd>${esc(t.tool)}</dd>` +
      (t.suggestion ? `<dt>Suggested correction</dt><dd><i class="bi bi-lightbulb text-warning"></i> ${esc(t.suggestion)}</dd>` : "") +
      findings + `</dl></div></div></div>`;
  }

  function applyFilters() {
    const q = $("searchBox").value.trim().toLowerCase();
    const status = $("statusFilter").value;
    let shown = 0;
    document.querySelectorAll("#resultGroups .test-row").forEach((row) => {
      const ok = (!status || row.dataset.status === status) && (!state.toolFilter || row.dataset.tool === state.toolFilter) &&
        (!q || row.dataset.text.includes(q));
      row.classList.toggle("d-none", !ok);
      if (ok) shown += 1;
    });
    document.querySelectorAll("#resultGroups .tool-group").forEach((g) =>
      g.classList.toggle("d-none", !g.querySelector(".test-row:not(.d-none)")));
    const total = state.result ? state.result.tests.length : 0;
    $("shownCount").textContent = `(showing ${shown} of ${total})`;
  }
  $("searchBox").addEventListener("input", applyFilters);
  $("statusFilter").addEventListener("change", applyFilters);
  $("toolPills").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tool]");
    if (!btn) return;
    state.toolFilter = btn.dataset.tool;
    $("toolPills").querySelectorAll("button").forEach((b) => {
      const active = b === btn;
      b.classList.toggle("btn-primary", active);
      b.classList.toggle("btn-outline-primary", !active);
    });
    applyFilters();
  });

  function renderLogs(logs) {
    const names = { pytest: "PyTest", coverage: "Coverage", pylint: "Pylint / Flake8", bandit: "Bandit", pep8: "PEP 8" };
    const keys = Object.keys(names);
    $("logTabs").innerHTML = keys.map((k, i) => `<li class="nav-item"><button class="nav-link ${i ? "" : "active"}" ` +
      `data-bs-toggle="tab" data-bs-target="#log-${k}" type="button">${names[k]}</button></li>`).join("");
    $("logPanes").innerHTML = keys.map((k, i) => `<div class="tab-pane fade ${i ? "" : "show active"}" id="log-${k}">` +
      `<pre class="log">${esc(logs[k] || "(empty)")}</pre></div>`).join("");
  }

  // Click any "line N" reference to highlight it in the editor.
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".line-link");
    if (!link) return;
    e.stopPropagation();
    const line = parseInt(link.dataset.line, 10) - 1;
    if (isNaN(line) || line < 0 || line >= editor.lineCount()) return;
    $("editor").scrollIntoView({ behavior: "smooth", block: "center" });
    editor.setCursor({ line, ch: 0 });
    editor.scrollIntoView({ line, ch: 0 }, 120);
    editor.addLineClass(line, "background", "cm-flash");
    setTimeout(() => editor.removeLineClass(line, "background", "cm-flash"), 2200);
  });

  // ---------------------------------------------------------------- downloads
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function htmlReport(r) {
    const m = r.metrics;
    const rows = r.tests.map((t) => `<tr><td>${esc(t.id)}</td><td>${esc(t.tool)}</td><td>${esc(t.name)}</td>` +
      `<td class="s-${t.status}">${t.status}</td><td>${t.line ?? ""}</td><td>${esc(t.explanation)}</td><td>${esc(t.suggestion)}</td></tr>`).join("");
    return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>PyAssure report</title><style>` +
      `body{font-family:Segoe UI,Arial,sans-serif;margin:2rem;color:#1e293b}h1{color:#4f46e5}table{border-collapse:collapse;width:100%;font-size:13px}` +
      `td,th{border:1px solid #cbd5e1;padding:6px 8px;text-align:left;vertical-align:top}th{background:#eef2ff}` +
      `.s-PASSED{color:#16a34a;font-weight:700}.s-WARNING{color:#b45309;font-weight:700}.s-FAILED{color:#dc2626;font-weight:700}` +
      `.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:1rem 0}.k{border:1px solid #cbd5e1;border-radius:8px;padding:10px}` +
      `.k b{display:block;font-size:22px}</style></head><body><h1>PyAssure – Test Report</h1>` +
      `<p>Generated: ${esc(new Date(r.timestamp).toLocaleString())} · Duration ${(r.duration_ms / 1000).toFixed(1)} s · ${r.code_stats.lines} lines analysed</p>` +
      `<div class="grid"><div class="k"><b>${m.health_score}%</b>Health score</div><div class="k"><b>${m.passed}</b>Passed</div>` +
      `<div class="k"><b>${m.warnings}</b>Warnings</div><div class="k"><b>${m.failed}</b>Failed</div>` +
      `<div class="k"><b>${fmtPct(m.statement_coverage)}</b>Statement coverage</div><div class="k"><b>${m.cyclomatic_complexity ?? "N/A"}</b>Cyclomatic complexity</div>` +
      `<div class="k"><b>${esc(m.defect_risk)}</b>Defect risk (heuristic)</div><div class="k"><b>${m.security_issues}</b>Security issues</div>` +
      `<div class="k"><b>${m.code_issues}</b>Code issues</div></div>` +
      `<h2>Test results</h2><table><tr><th>ID</th><th>Tool</th><th>Test</th><th>Status</th><th>Line</th><th>Explanation</th><th>Suggestion</th></tr>${rows}</table>` +
      `<h2>Complexity recommendations</h2><ul>${(r.complexity.recommendations || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
      `<p><em>${esc(r.complexity.disclaimer)}</em></p></body></html>`;
  }
  function csvReport(r) {
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    return ["Test ID,Tool,Test,Status,Line,Explanation,Suggestion"].concat(r.tests.map((t) =>
      [t.id, t.tool, t.name, t.status, t.line, t.explanation, t.suggestion].map(q).join(","))).join("\r\n");
  }
  document.querySelectorAll("[data-dl]").forEach((btn) => btn.addEventListener("click", () => {
    const r = state.result;
    if (!r) return;
    const stamp = r.timestamp.replace(/[:T]/g, "-").slice(0, 19);
    const kind = btn.dataset.dl;
    if (kind === "html") download(`pyassure-report-${stamp}.html`, htmlReport(r), "text/html");
    if (kind === "json") download(`pyassure-report-${stamp}.json`, JSON.stringify(r, null, 2), "application/json");
    if (kind === "csv") download(`pyassure-report-${stamp}.csv`, csvReport(r), "text/csv");
  }));

  loadSamples();
})();

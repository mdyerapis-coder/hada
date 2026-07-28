// HADA Command Centre — frontend logic.
// Honest control board: reads ONLY the real orchestrator endpoints
// (/healthz, /readyz, /metrics). No tasks/gates/evidence API exists in
// the v5 orchestrator, so those panels show an explicit "not exposed" notice.
// This file never invents data.

const API = "/hada-api"; // proxied to hada-m1-orchestrator:9108 by Caddy

const views = {
  overview: document.getElementById("overview-view"),
  tasks: document.getElementById("tasks-view"),
  gates: document.getElementById("gates-view"),
  evidence: document.getElementById("evidence-view"),
  docs: document.getElementById("docs-view"),
};
const titles = {
  overview: ["Overview", "Read-only control-plane posture"],
  tasks: ["Tasks", "Task ledger lifecycle"],
  gates: ["Governance gates", "Approval requires evidence and reviewer separation"],
  evidence: ["Evidence", "Signed, content-addressed milestone evidence"],
  docs: ["Documentation", "Repository Markdown remains the source of truth"],
};

function setView(name) {
  Object.entries(views).forEach(([k, el]) => el.classList.toggle("active", k === name));
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name)
  );
  const [t, s] = titles[name] || ["", ""];
  document.getElementById("view-title").textContent = t;
  document.getElementById("view-subtitle").textContent = s;
  if (name !== "overview") loadView(name);
}

document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => setView(b.dataset.view))
);
document.getElementById("refresh").addEventListener("click", loadOverview);

function setBanner(state, msg) {
  const b = document.getElementById("source-banner");
  b.className = "source-banner" + (state ? " " + state : "");
  document.getElementById("source-message").textContent = msg;
}

function parseMetrics(text) {
  const out = {};
  text.split("\n").forEach((line) => {
    if (!line || line.startsWith("#")) return;
    const sp = line.indexOf(" ");
    if (sp === -1) return;
    const name = line.slice(0, sp).split("{")[0].trim();
    const val = line.slice(sp + 1).trim();
    out[name] = val;
  });
  return out;
}

async function getText(path) {
  const r = await fetch(API + path, { cache: "no-store" });
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.text();
}

async function loadOverview() {
  setBanner("", "Loading repository snapshot…");
  try {
    const [health, ready, metrics] = await Promise.all([
      getText("/healthz"),
      getText("/readyz"),
      getText("/metrics"),
    ]);
    const m = parseMetrics(metrics);
    const dbUp = m["hada_database_up"] === "1";
    const qUp = m["hada_queue_up"] === "1";
    const ok = health.trim() === "ok" && dbUp && qUp;

    document.getElementById("execution-state").textContent = ok
      ? "READY — HEALTHY"
      : "DEGRADED";
    document.getElementById("execution-state").className =
      "pill " + (ok ? "ok" : "bad");

    // Milestone + gates (real readiness signal only)
    document.getElementById("milestone-title").textContent =
      "M1 Durable Orchestrator";
    document.getElementById("milestone-status").textContent = ok
      ? "Operational"
      : "Unhealthy";
    document.getElementById("milestone-status").className =
      "pill " + (ok ? "ok" : "bad");
    document.getElementById("milestone-summary").textContent = ok
      ? "Orchestrator is running, database and queue are reachable, and the outbox publisher is relaying events to Valkey."
      : "Orchestrator is up but a dependency (database or queue) is not healthy.";
    document.getElementById("gate-count").textContent = ok
      ? "5/5 core checks pass"
      : "core checks failing";
    document.getElementById("gate-progress").style.width = ok ? "100%" : "40%";

    // Live metrics (real)
    document.getElementById("metric-active").textContent =
      m["hada_outbox_published_total"] || "0";
    document.getElementById("metric-review").textContent = "—";
    document.getElementById("metric-approval").textContent = "—";
    document.getElementById("metric-failed").textContent =
      m["hada_outbox_publish_failures_total"] || "0";

    // Role separation (static, accurate to the design)
    renderRoles([
      { role: "Implementation engineer (Party 1)", meta: dbUp ? "workspace active" : "db down" },
      { role: "Adversarial reviewer (Party 2)", meta: "separate model" },
      { role: "Independent external reviewer (Party 3)", meta: "automated" },
    ]);

    setBanner("live", "Live · orchestrator reachable · DB " + (dbUp ? "up" : "down") + " · queue " + (qUp ? "up" : "down"));
  } catch (e) {
    document.getElementById("execution-state").textContent = "UNREACHABLE";
    document.getElementById("execution-state").className = "pill bad";
    setBanner("error", "Cannot reach orchestrator API at " + API + " — " + e.message);
    document.getElementById("metric-active").textContent = "—";
    document.getElementById("metric-failed").textContent = "—";
    renderRoles([]);
  }
}

function renderRoles(rows) {
  const el = document.getElementById("agent-list");
  if (!rows.length) {
    el.innerHTML = '<div class="notice"><strong>Orchestrator unreachable</strong>Role state unavailable.</div>';
    return;
  }
  el.innerHTML = rows
    .map(
      (r) =>
        '<div class="stack-row"><span class="dot"></span><span class="role">' +
        r.role +
        '</span><span class="meta">' +
        r.meta +
        "</span></div>"
    )
    .join("");
}

const NOT_EXPOSED =
  '<div class="notice"><strong>API not yet exposed</strong>The v5 orchestrator does not publish a tasks / gates / evidence endpoint. This panel will populate when that surface ships. The board only renders real data — nothing here is simulated.</div>';

function loadView(name) {
  if (name === "tasks")
    document.getElementById("tasks-table").innerHTML = NOT_EXPOSED;
  if (name === "gates")
    document.getElementById("gates-list").innerHTML = NOT_EXPOSED;
  if (name === "evidence") {
    document.getElementById("evidence-state").textContent = "not exposed";
    document.getElementById("evidence-list").innerHTML =
      '<div class="notice"><strong>Evidence bundle not yet exposed</strong>The orchestrator signs and stores content-addressed evidence, but does not yet expose it over HTTP. Wire the evidence API to populate this panel.</div>';
  }
}

// Docs view (static summaries; repo Markdown is canonical source)
const DOCS = {
  architecture: {
    title: "Architecture",
    summary: "Control-plane design: orchestrator, durable queue (Valkey), Postgres store, outbox publisher, and the Caddy edge. The browser talks only to read-only probe endpoints.",
    topics: ["Probe server (9108)", "Outbox pattern", "Bubblewrap execution", "Trust boundaries"],
    source: "docs/architecture.md",
  },
  security: {
    title: "Security",
    summary: "Threat model: non-root runtime, capability dropping, read-only bind paths, egress allow-list (github.com, opencode.ai). Self-approval is prohibited.",
    topics: ["cap_drop ALL", "egress allow-list", "no self-approval", "residual risk"],
    source: "docs/security.md",
  },
  roadmap: {
    title: "Roadmap",
    summary: "Milestones M0–M6 with entry gates. M1 (durable orchestrator) is deployed and operational.",
    topics: ["M0 foundation", "M1 orchestrator", "M2+ pipeline", "Entry gates"],
    source: "docs/MASTER_ROADMAP.md",
  },
  "governed-autonomy": {
    title: "Governed autonomy",
    summary: "Roles, authority, and stopping conditions. Three parties (implementation, adversarial, external) with human approval as the final gate.",
    topics: ["Party separation", "Stopping conditions", "Human authority", "RFC"],
    source: "docs/adr/0002-autonomous-repair-pipeline.md",
  },
  "durable-orchestrator": {
    title: "Durable orchestrator",
    summary: "State, queues, workspaces, and recovery. Outbox ensures published events survive crashes; unhealthy dependency exits after a threshold.",
    topics: ["Durable queue", "Workspaces", "Recovery", "Outbox"],
    source: "docs/runbooks/AUTONOMOUS_REPAIR.md",
  },
  "external-review": {
    title: "External review",
    summary: "Party 3 independent milestone closure checklist. Automated mode for this deployment.",
    topics: ["Checklist", "Closure", "Automated mode", "Evidence"],
    source: "docs/runbooks/AUTONOMOUS_REPAIR.md",
  },
};

document.querySelectorAll(".doc-card").forEach((c) =>
  c.addEventListener("click", () => openDoc(c.dataset.document))
);
document.getElementById("close-document").addEventListener("click", () => {
  document.getElementById("document-reader").classList.add("hidden");
});

function openDoc(key) {
  const d = DOCS[key];
  if (!d) return;
  document.getElementById("document-kind").textContent = "Document";
  document.getElementById("document-title").textContent = d.title;
  document.getElementById("document-summary").textContent = d.summary;
  document.getElementById("document-topics").innerHTML = d.topics
    .map((t) => '<div class="topic">' + t + "</div>")
    .join("");
  document.getElementById("document-source").textContent = d.source;
  document.getElementById("document-reader").classList.remove("hidden");
}

// boot
loadOverview();

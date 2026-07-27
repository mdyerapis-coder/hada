const fallbackState = {
  generated_at: "bundled snapshot",
  operating_mode: "LOCAL_ONLY",
  execution_state: "READY_NOT_EXECUTED",
  milestone: { id: "M1", title: "Durable Orchestrator", status: "external_review_required", summary: "Implementation candidate complete; independent Party 3 review remains required." },
  metrics: { active_tasks: 0, awaiting_review: 1, human_approvals: 1, failed_gates: 0 },
  tasks: [],
  gates: [
    { name: "Architecture", status: "approved", owner: "Party 2" },
    { name: "Security", status: "approved", owner: "Party 2" },
    { name: "Tests", status: "approved", owner: "Party 2" },
    { name: "Documentation", status: "approved", owner: "Party 2" },
    { name: "Milestone report", status: "approved", owner: "Party 2" },
    { name: "External review", status: "pending", owner: "Party 3" },
  ],
  evidence: { bundle: "artifacts/M1/SIGNED-EVIDENCE-INDEX.json", public_key_fingerprint: "artifacts/M1/PUBLIC-KEY-FINGERPRINT.txt", verification: "artifacts/M1/validation/evidence-verification.txt", state: "available" },
  agents: [
    { name: "Party 1", role: "Implementation", authority: "Cannot approve own work" },
    { name: "Party 2", role: "Adversarial review", authority: "Cannot mutate implementation" },
    { name: "Party 3", role: "External approval", authority: "Cannot mutate internal state" },
  ],
};

const titles = {
  overview: ["Overview", "Read-only control-plane posture"],
  tasks: ["Tasks", "Governed task lifecycle"],
  gates: ["Governance gates", "Evidence-backed independent decisions"],
  evidence: ["Evidence", "Signed milestone artefacts"],
  docs: ["Documentation", "Source-of-truth project records"],
};

const documents = {
  architecture: {
    kind: "Architecture",
    title: "Control-plane design",
    source: "docs/architecture/ARCHITECTURE.md",
    summary: "Defines the HADA appliance boundary, durable control-plane components, trust separation, state ownership and the flow from governed work to independently reviewed evidence.",
    topics: [["System boundary", "HADA governs work without becoming Hermesctl."], ["Durable state", "PostgreSQL owns authoritative records; Valkey carries queues and leases."], ["Evidence flow", "Signed, content-addressed evidence supports independent review."]],
  },
  security: {
    kind: "Security",
    title: "Threat model",
    source: "docs/security/THREAT-MODEL.md",
    summary: "Documents untrusted inputs, attacker goals, privilege boundaries, fail-closed execution controls and the risks that must remain visible to operators and external reviewers.",
    topics: [["Untrusted inputs", "Repository content, agent output and commands are not trusted."], ["Least authority", "Each party is prevented from exercising conflicting powers."], ["Fail closed", "Unavailable isolation or unmet policy denies execution."]],
  },
  roadmap: {
    kind: "Roadmap",
    title: "Milestones M0–M6",
    source: "docs/ROADMAP.md",
    summary: "Sequences the governed foundation, durable orchestrator, inference plane, implementation workflow, adversarial review, external evidence exchange and production hardening.",
    topics: [["Current milestone", "M1 is an implementation candidate awaiting independent review."], ["Entry gates", "Later milestones cannot begin until their prerequisites are approved."], ["Hardening", "Backups, SLOs and supply-chain controls arrive through governed milestones."]],
  },
  "governed-autonomy": {
    kind: "RFC 0001",
    title: "Governed autonomy",
    source: "docs/rfc/RFC-0001-GOVERNED-AUTONOMY.md",
    summary: "Sets the constitutional model for bounded agent activity: explicit scope, separated roles, evidence-backed gates, stopping conditions and authority retained by people.",
    topics: [["Bounded scope", "Agents operate only within an approved milestone."], ["Role separation", "Implementation, review and external approval remain independent."], ["Human authority", "High-impact transitions cannot be self-promoted by an agent."]],
  },
  "durable-orchestrator": {
    kind: "RFC 0002",
    title: "Durable orchestrator",
    source: "docs/rfc/RFC-0002-DURABLE-ORCHESTRATOR.md",
    summary: "Specifies durable task state, optimistic transitions, queues and leases, transactional publication, isolated Git workspaces, evidence capture and bounded recovery.",
    topics: [["Task lifecycle", "Transitions are explicit, versioned and validated."], ["Workspace isolation", "Tasks use pinned commits in dedicated worktrees."], ["Recovery", "Retries and lease recovery remain bounded and auditable."]],
  },
  "external-review": {
    kind: "Independent review",
    title: "Party 3 checklist",
    source: "docs/reports/M1-EXTERNAL-REVIEW-CHECKLIST.md",
    summary: "Provides the evidence and verification path for a reviewer outside HADA to decide whether M1 may close without relying on the implementing or reviewing agents' assertions.",
    topics: [["Signer identity", "Verify the evidence signer and published fingerprint."], ["Evidence integrity", "Check manifests, hashes and the signed audit chain."], ["Independent decision", "Party 3 records approval or rejection outside internal task mutation."]],
  },
};

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function statusClass(value) {
  if (["approved", "available", "completed"].includes(value)) return "good";
  if (["pending", "ready", "external_review_required"].includes(value)) return "warn";
  if (["blocked", "rejected", "failed"].includes(value)) return "bad";
  return "neutral";
}

function label(value) { return String(value ?? "unknown").replaceAll("_", " "); }
function pill(value) { return `<span class="pill ${statusClass(value)}">${escapeHtml(label(value))}</span>`; }

function render(state, source) {
  document.querySelector("#mode-state").textContent = label(state.operating_mode).toUpperCase();
  document.querySelector("#execution-state").textContent = label(state.execution_state).toUpperCase().replace("READY NOT EXECUTED", "READY — NOT EXECUTED");
  document.querySelector("#metric-active").textContent = state.metrics.active_tasks;
  document.querySelector("#metric-review").textContent = state.metrics.awaiting_review;
  document.querySelector("#metric-approval").textContent = state.metrics.human_approvals;
  document.querySelector("#metric-failed").textContent = state.metrics.failed_gates;
  document.querySelector("#milestone-title").textContent = `${state.milestone.id} — ${state.milestone.title}`;
  document.querySelector("#milestone-summary").textContent = state.milestone.summary;
  document.querySelector("#milestone-status").outerHTML = pill(state.milestone.status).replace("<span", '<span id="milestone-status"');

  const approved = state.gates.filter((gate) => gate.status === "approved").length;
  document.querySelector("#gate-count").textContent = `${approved} / ${state.gates.length} approved`;
  document.querySelector("#gate-progress").style.width = `${Math.round((approved / state.gates.length) * 100)}%`;

  document.querySelector("#agent-list").innerHTML = state.agents.map((agent, index) => `
    <div class="stack-item"><div><strong>${escapeHtml(agent.name)} · ${escapeHtml(agent.role)}</strong><span>${escapeHtml(agent.authority)}</span></div><div class="party-badge">P${index + 1}</div></div>`).join("");

  document.querySelector("#tasks-table").innerHTML = state.tasks.length ? `
    <table><thead><tr><th>Task</th><th>Milestone</th><th>Status</th><th>Workspace</th></tr></thead><tbody>${state.tasks.map((task) => `<tr><td>${escapeHtml(task.title)}</td><td>${escapeHtml(task.milestone_id)}</td><td>${pill(task.status)}</td><td>${escapeHtml(task.workspace_id || "—")}</td></tr>`).join("")}</tbody></table>` :
    `<div class="empty-state"><strong>No active task records in this snapshot</strong><span>The dashboard does not invent runtime state when no authoritative task feed is connected.</span></div>`;

  document.querySelector("#gates-list").innerHTML = state.gates.map((gate) => `
    <article class="gate-card"><span>${escapeHtml(gate.owner)}</span><strong>${escapeHtml(gate.name)}</strong>${pill(gate.status)}</article>`).join("");

  document.querySelector("#evidence-state").outerHTML = pill(state.evidence.state).replace("<span", '<span id="evidence-state"');
  const evidenceRows = [["Signed index", state.evidence.bundle], ["Public-key fingerprint", state.evidence.public_key_fingerprint], ["Verification record", state.evidence.verification]];
  document.querySelector("#evidence-list").innerHTML = evidenceRows.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");

  const banner = document.querySelector("#source-banner");
  banner.classList.toggle("live", source === "status.json");
  document.querySelector("#source-message").textContent = source === "status.json" ? `Repository snapshot loaded · ${state.generated_at}` : "Bundled snapshot shown · serve this directory locally to load status.json";
}

function showError(message) {
  const banner = document.querySelector("#error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
  window.clearTimeout(showError.timeoutId);
  showError.timeoutId = window.setTimeout(() => banner.classList.add("hidden"), 6000);
}

async function refreshData() {
  const button = document.querySelector("#refresh");
  button.disabled = true;
  button.textContent = "Refreshing…";
  try {
    const response = await fetch("./status.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    render(await response.json(), "status.json");
  } catch (error) {
    render(fallbackState, "fallback");
    if (window.location.protocol !== "file:") showError(`Snapshot unavailable: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Refresh";
  }
}

function activateView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `${name}-view`));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  const [title, subtitle] = titles[name];
  document.querySelector("#view-title").textContent = title;
  document.querySelector("#view-subtitle").textContent = subtitle;
}

function openDocument(name) {
  const documentRecord = documents[name];
  if (!documentRecord) return;
  document.querySelectorAll(".doc-card").forEach((card) => card.classList.toggle("active", card.dataset.document === name));
  document.querySelector("#document-kind").textContent = documentRecord.kind;
  document.querySelector("#document-title").textContent = documentRecord.title;
  document.querySelector("#document-summary").textContent = documentRecord.summary;
  document.querySelector("#document-source").textContent = documentRecord.source;
  document.querySelector("#document-topics").innerHTML = documentRecord.topics.map(([title, summary]) => `<article class="topic-card"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(summary)}</span></article>`).join("");
  document.querySelector("#document-reader").classList.remove("hidden");
  document.querySelector("#document-reader").scrollIntoView({ block: "start" });
}

function closeDocument() {
  document.querySelector("#document-reader").classList.add("hidden");
  document.querySelectorAll(".doc-card").forEach((card) => card.classList.remove("active"));
  document.querySelector(".docs-grid").scrollIntoView({ block: "start" });
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => activateView(item.dataset.view)));
document.querySelectorAll(".doc-card").forEach((card) => card.addEventListener("click", () => openDocument(card.dataset.document)));
document.querySelector("#close-document").addEventListener("click", closeDocument);
document.querySelector("#refresh").addEventListener("click", refreshData);
refreshData();

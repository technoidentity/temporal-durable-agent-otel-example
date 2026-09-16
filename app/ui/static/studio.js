"use strict";
const $ = (selector) => document.querySelector(selector);
const icons = {
  workflow: "M4 4h6v6H4z M14 14h6v6h-6z M14 4h6v6h-6z M7 10v7h7 M10 7h4",
  history: "M3 11a9 9 0 1 1 2.5 7 M3 4v7h7 M12 7v5l3 2",
  chart: "M4 4v16h16 M8 15v-4 M12 15V7 M16 15v-6",
  plus: "M12 5v14 M5 12h14",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M9 12l2 2 4-4",
  bolt: "M13 2L4 14h7l-1 8 10-13h-7z",
  play: "M7 4l13 8-13 8z",
  intake: "M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h5",
  inventory: "M3 7l9-4 9 4-9 4z M3 7v10l9 4 9-4V7 M12 11v10 M8 5l9 4",
  pricing: "M4 4h9l7 7-9 9-7-7z M8 8h.01",
  fulfillment: "M3 6h11v12H3z M14 10h4l3 4v4h-7 M6 18v.01 M17 18v.01 M14 14h7",
  account: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M5 21v-3a7 7 0 0 1 14 0v3",
  supervisor: "M12 3l3 6 6 1-4 5 1 6-6-3-6 3 1-6-4-5 6-1z",
  flag: "M5 21V3 M5 3c4-3 9 3 14 0v11c-5 3-10-3-14 0",
  sliders: "M4 7h5 M15 7h5 M4 17h9 M19 17h1 M9 4v6 M15 14v6",
  lock: "M6 10h12v11H6z M8 10V7a4 4 0 0 1 8 0v3 M12 14v3",
  arrow: "M4 12h16 M15 7l5 5-5 5",
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.workflow}"/></svg>`;
}
function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function text(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
const roles = {
  intake: {
    title: "Order intake",
    short: "Intake",
    description:
      "Reads the distributor request and produces an intake summary for the next agents.",
    input: ["request"],
  },
  inventory: {
    title: "Inventory",
    short: "Inventory",
    description:
      "Reviews the order and intake summary to reason about stock availability.",
    input: ["request", "intake"],
  },
  pricing: {
    title: "Pricing",
    short: "Pricing",
    description:
      "Uses the order, intake, and inventory context to prepare a pricing recommendation.",
    input: ["request", "intake", "inventory"],
  },
  fulfillment: {
    title: "Fulfillment",
    short: "Fulfillment",
    description:
      "Uses inventory and pricing recommendations to assess delivery and fulfillment risk.",
    input: ["request", "inventory", "pricing"],
  },
  account: {
    title: "Account",
    short: "Account",
    description:
      "Reviews the distributor request and intake summary from an account perspective.",
    input: ["request", "intake"],
  },
  supervisor: {
    title: "Supervisor",
    short: "Supervisor",
    description:
      "Brings together the five agent outputs into a proposed outcome for the distributor.",
    input: ["intake", "inventory", "pricing", "fulfillment", "account"],
  },
};
const scenarios = {
  standard: {
    request: "Metro Foods: 200 cases of Mountain Dew 500ml at 10% discount",
    help: "A routine order. The approval rule decides whether a human is needed.",
    mode: "none",
  },
  approval: {
    request: "Star Distributors: 500 cases of Pepsi 330ml at 20% discount",
    help: "A discount exception. The approval rule decides whether a human is needed.",
    mode: "none",
  },
  recovery: {
    request: "Metro Foods: 200 cases of Mountain Dew 500ml at 10% discount",
    help: "Inventory fails once, then Temporal retries. Earlier agents keep their completed work.",
    mode: "transient_error",
  },
  risk: {
    request:
      "URGENT rush: 8000 cases in 24h, stock may be insufficient, 10% discount",
    help: "A rush order. When enabled, ServiceNow receives an incident if fulfillment flags a risk.",
    mode: "none",
  },
};
let meta,
  pipeline = Object.keys(roles),
  selectedId = null,
  selectedRole = "intake",
  activeTab = "workflow";
let runs = new Map(),
  polling = false,
  loading = false,
  decisionBusy = false,
  lastInspector = "",
  lastList = "",
  lastAnnouncement = "";
const decisionSent = new Set();
const TERMINAL = new Set([
  "COMPLETED",
  "FAILED",
  "TIMED_OUT",
  "TERMINATED",
  "CANCELED",
  "CONTINUED_AS_NEW",
]);
const STORAGE = "pepsico-agent-studio-runs-v1";
let storageAvailable = true;
async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}). Check that the UI and Temporal services are running, then try again.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail))
        message = body.detail.map((e) => e.msg).join(" ");
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
function current() {
  return runs.get(selectedId);
}
function save() {
  try {
    localStorage.setItem(
      STORAGE,
      JSON.stringify(
        [...runs.values()]
          .slice(0, 25)
          .map((r) => ({ id: r.id, request: r.request })),
      ),
    );
  } catch {
    storageAvailable = false;
  }
}
function stateOf(run) {
  if (!run) return { key: "neutral", label: "Ready to run" };
  if (run.pending?.pending) return { key: "approval", label: "Needs approval" };
  if (run.status === "COMPLETED" && run.result?.approval?.approved === false)
    return { key: "rejected", label: "Order rejected" };
  if (run.status === "COMPLETED")
    return { key: "completed", label: "Completed" };
  if (TERMINAL.has(run.status))
    return {
      key: "failed",
      label: run.status.toLowerCase().replaceAll("_", " "),
    };
  return { key: "running", label: run.status ? "Running" : "Starting" };
}
function stageFor(role) {
  if (role === "servicenow")
    return (
      current()?.incident_activity || { role, status: "waiting", attempt: 0 }
    );
  return (
    current()?.stages?.find((s) => s.role === role) || {
      role,
      status: "waiting",
      attempt: 0,
    }
  );
}
function duration(start, end) {
  if (!start) return "";
  const ms = new Date(end || Date.now()) - new Date(start);
  if (!Number.isFinite(ms) || ms < 0) return "";
  return ms < 1000
    ? `${Math.round(ms)} ms`
    : ms < 60000
      ? `${(ms / 1000).toFixed(1)} s`
      : `${Math.floor(ms / 60000)}m ${Math.floor(ms / 1000) % 60}s`;
}
function shortState(s) {
  if (s.status === "completed")
    return s.attempt > 1 ? `Recovered · ${s.attempt} attempts` : "Complete";
  if (s.status === "running")
    return `Running${s.attempt > 1 ? " · attempt " + s.attempt : ""}`;
  if (s.status === "retrying") return `Retrying · attempt ${s.attempt}`;
  if (s.status === "scheduled") return "Queued";
  if (s.status === "failed") return "Failed";
  if (TERMINAL.has(current()?.status)) return "Not reached";
  return "Waiting";
}
function setHTML(el, html) {
  if (el.innerHTML !== html) el.innerHTML = html;
}
function setError(selector, message) {
  const el = $(selector);
  el.hidden = !message;
  el.textContent = message || "";
}
function buildMap() {
  const grid = $("#agent-grid");
  grid.replaceChildren();
  pipeline.forEach((role, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "agent-node";
    button.dataset.role = role;
    const row = Math.floor(i / 3),
      column = row % 2 ? 3 - (i % 3) : (i % 3) + 1;
    button.style.gridColumn = column;
    button.style.gridRow = row + 1;
    button.innerHTML = `<span class="node-top"><span class="node-icon">${icon(role)}</span><span class="node-number">${String(i + 1).padStart(2, "0")}</span></span><span class="node-title">${esc(roles[role].title)}</span><span class="node-state"><i></i><span>Waiting</span></span>`;
    button.onclick = () => selectRole(role);
    grid.append(button);
  });
  new ResizeObserver(drawConnectors).observe(grid);
}
function drawConnectors() {
  const canvas = $("#flow-canvas");
  if (!canvas.offsetWidth) return;
  const bounds = canvas.getBoundingClientRect();
  const nodes = [...$("#agent-grid").children];
  const defs =
    '<defs><marker id="arrowhead" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M1 1l4 2-4 2" stroke="#9baec2" fill="none"/></marker></defs>';
  let paths = "";
  for (let i = 0; i < nodes.length - 1; i++) {
    const a = nodes[i].getBoundingClientRect(),
      b = nodes[i + 1].getBoundingClientRect();
    let path;
    if (Math.abs(a.top - b.top) < 5) {
      const right = b.left > a.left;
      const x1 = (right ? a.right : a.left) - bounds.left,
        x2 = (right ? b.left : b.right) - bounds.left,
        y = a.top + a.height / 2 - bounds.top;
      path = `M${x1} ${y}H${x2 + (right ? -3 : 3)}`;
    } else {
      const x = a.left + a.width / 2 - bounds.left;
      path = `M${x} ${a.bottom - bounds.top}V${b.top - bounds.top - 3}`;
    }
    const target = stageFor(pipeline[i + 1]);
    const cls =
      target.status === "completed"
        ? "done"
        : ["running", "retrying", "scheduled"].includes(target.status)
          ? "active"
          : "";
    paths += `<path class="${cls}" d="${path}" marker-end="url(#arrowhead)"/>`;
  }
  setHTML($("#connectors"), defs + paths);
  // Tail follows the actual final node, including custom pipeline lengths.
  const last = nodes.at(-1)?.getBoundingClientRect();
  if (last) {
    const center = last.left + last.width / 2 - bounds.left;
    document
      .querySelectorAll(".tail-connector")
      .forEach((el) => (el.style.marginLeft = `${center}px`));
  }
}
function reveal(element) {
  element.focus({ preventScroll: true });
  element.scrollIntoView({
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
    block: "start",
  });
}
function selectRole(role) {
  selectedRole = role;
  lastInspector = "";
  renderMap();
  renderInspector();
  if (innerWidth <= 1250 && role !== "approval") reveal($(".inspector"));
}
function serviceState(run) {
  if (run?.incident_activity) return shortState(run.incident_activity);
  if (!run || !TERMINAL.has(run.status)) return "Conditional";
  if (run.status !== "COMPLETED" || run.result?.approval?.approved === false)
    return "Not reached";
  return run.result ? "Not needed" : "Unavailable";
}
function serviceExplanation(run) {
  if (!run || !TERMINAL.has(run.status))
    return "The response will appear here if an incident is requested.";
  if (run.status !== "COMPLETED")
    return "Execution stopped before the ServiceNow handoff was reached.";
  if (run.result?.approval?.approved === false)
    return "The order was rejected, so the ServiceNow handoff was skipped.";
  return run.result
    ? "The workflow completed without requiring an incident handoff."
    : "The completed result is unavailable. Open Temporal to inspect the handoff.";
}
function selectRun(id) {
  selectedId = id;
  lastInspector = "";
  decisionBusy = false;
  $("#decision-note").value = "";
  setError("#decision-feedback", "");
  render();
  poll();
  if (innerWidth <= 800) reveal($(".execution-header"));
}
function renderMap() {
  for (const button of $("#agent-grid").children) {
    const role = button.dataset.role,
      s = stageFor(role);
    button.dataset.state = s.status;
    button.setAttribute("aria-pressed", String(selectedRole === role));
    button.setAttribute(
      "aria-label",
      `${roles[role].title}: ${shortState(s)}. Inspect step`,
    );
    button.querySelector(".node-state span").textContent = shortState(s);
  }
  const r = current(),
    ap = r?.result?.approval,
    pending = r?.pending?.pending;
  $("#approval-node").classList.toggle("attention", !!pending);
  $("#approval-node").setAttribute(
    "aria-pressed",
    String(selectedRole === "approval"),
  );
  $("#gate-caption").textContent = pending
    ? "Workflow paused for your decision"
    : ap
      ? ap.required
        ? `Decision recorded · ${ap.via}`
        : "No human decision required"
      : "Automatic or human decision";
  $("#gate-state").textContent = pending
    ? "Needs approval"
    : ap
      ? ap.approved
        ? "Approved"
        : "Rejected"
      : TERMINAL.has(r?.status)
        ? "Not reached"
        : "Waiting";
  $("#service-step").hidden =
    !meta?.servicenow_enabled && !r?.incident_activity;
  $("#service-node").setAttribute(
    "aria-pressed",
    String(selectedRole === "servicenow"),
  );
  $("#service-state").textContent = serviceState(r);
  $("#finish-state").textContent = r ? stateOf(r).label : "Waiting";
  $("#finish-caption").textContent =
    ap?.approved === false ? "Order rejected" : "Order outcome";
  $("#flow-live").textContent = r
    ? TERMINAL.has(r.status)
      ? "Recorded run"
      : "Live execution"
    : "Preview";
  $("#integration-caption").textContent = r?.incident_activity
    ? `ServiceNow · ${shortState(r.incident_activity)} via A2A`
    : r?.result?.incident
      ? text(r.result.incident)
      : meta?.servicenow_enabled
        ? `ServiceNow ${meta.servicenow_mode === "simulator" ? "simulator" : "integration"} · optional handoff on approved fulfillment risk`
        : "ServiceNow handoff is not enabled.";
  drawConnectors();
}
function renderInspector() {
  const r = current(),
    s = stageFor(selectedRole),
    ap = r?.result?.approval;
  const signature = JSON.stringify([
    selectedId,
    selectedRole,
    s,
    r?.pending,
    ap,
    r?.status,
  ]);
  if (signature === lastInspector) return;
  lastInspector = signature;
  const el = $("#inspector-content");
  if (selectedRole === "servicenow") {
    el.innerHTML = `<div class="inspector-title">${icon("workflow")}<h3>ServiceNow agent</h3></div><p class="inspector-description">When an approved order has fulfillment risk, Temporal calls the ServiceNow agent over A2A to open an incident.</p><div class="inspector-meta"><span class="status neutral">${esc(serviceState(r))}</span></div><div class="inspector-section"><h4>Connection</h4><p>${esc(meta?.servicenow_mode === "simulator" ? "Local ServiceNow simulator. No external ticket is created." : "Configured ServiceNow integration.")}</p></div><div class="inspector-section"><h4>Handoff</h4><p>${esc(s.input?.message || "Receives the order request and the fulfillment risk summary after approval.")}</p></div><div class="inspector-section"><h4>Response</h4><p>${esc(s.output || r?.result?.incident || serviceExplanation(r))}</p></div>`;
    return;
  }
  if (selectedRole === "approval") {
    const pending = r?.pending?.pending;
    el.innerHTML = `<div class="inspector-title">${icon("shield")}<h3>Approval gate</h3></div><p class="inspector-description">After the agents finish, Temporal checks the requested discount against the approval rule.</p><div class="inspector-section"><h4>Decision rule</h4><p>${esc(r?.pending?.details || (ap ? `Requested: ${ap.discount ?? "not specified"}%\nThreshold: ${ap.threshold}%` : r?.options?.discount_threshold != null ? `Threshold: ${r.options.discount_threshold}%` : "Uses the threshold set when the order starts."))}</p></div><div class="inspector-section"><h4>${pending ? "Waiting for you" : ap ? "Recorded decision" : "What happens here"}</h4><p>${esc(pending ? "The workflow is waiting. Approve or reject below to continue." : ap ? `${ap.approved ? "Approved" : "Rejected"} via ${ap.via}${ap.approver ? " by " + ap.approver : ""}${ap.note ? "\n" + ap.note : ""}` : "A human decision is required when the discount exceeds the threshold, or approval is forced. Otherwise the gate passes automatically.")}</p></div>${r?.child_workflow_id ? `<div class="inspector-section"><h4>Child workflow</h4><p>${esc(r.child_workflow_id)}</p><a class="detail-link" href="${esc(temporalLink(r.child_workflow_id))}" target="_blank" rel="noopener">Inspect approval workflow ↗</a></div>` : ""}`;
    return;
  }
  const definition = roles[selectedRole];
  if (!definition) return;
  const inputs = s.input
    ? definition.input
        .filter((k) => s.input[k] != null)
        .map(
          (k) =>
            `${k === "request" ? "Distributor request" : roles[k]?.short || k}\n${text(s.input[k])}`,
        )
        .join("\n\n")
    : null;
  const next = pipeline[pipeline.indexOf(selectedRole) + 1];
  const output =
    s.output ??
    r?.result?.[selectedRole === "supervisor" ? "outcome" : selectedRole];
  const key =
    s.status === "completed"
      ? "completed"
      : s.status === "failed"
        ? "failed"
        : ["retrying"].includes(s.status)
          ? "approval"
          : ["running", "scheduled"].includes(s.status)
            ? "running"
            : "neutral";
  el.innerHTML = `<div class="inspector-title">${icon(selectedRole)}<h3>${esc(definition.title)}</h3></div><p class="inspector-description">${esc(definition.description)}</p><div class="inspector-meta"><span class="status ${key}">${esc(shortState(s))}</span>${s.attempt ? `<span>Attempt ${s.attempt}</span>` : ""}${s.completed_at ? `<span>${esc(duration(s.started_at, s.completed_at))}</span>` : ""}</div><div class="inspector-section"><h4>Receives</h4>${inputs ? `<p>${esc(inputs)}</p>` : `<p>${esc(definition.input.map((k) => (k === "request" ? "Distributor request" : `${roles[k]?.short || k} output`)).join(" + "))}</p>`}</div><div class="inspector-section"><h4>${output != null ? "Agent output" : "Produces"}</h4><p>${esc(output != null ? text(output) : r ? (s.status === "failed" ? "This step failed before producing an output." : "Output will appear here when this agent completes.") : "Start an order to see the actual response.")}</p>${meta?.provider === "fake" && output != null ? '<p class="demo-output-note">Demo model: this response echoes input; it is not a verified business recommendation.</p>' : ""}</div>${s.error || s.last_failure ? `<div class="inspector-section"><h4>${s.error ? "Failure" : "Previous attempt"}</h4><p>${esc(s.error || s.last_failure)}</p></div>` : ""}<div class="handoff">${icon("arrow")}<span>Hands off to ${esc(next ? roles[next].short : "approval gate")}</span></div>${s.input ? `<div class="inspector-section"><details><summary>Technical details</summary><pre class="raw">${esc(JSON.stringify({ activity_id: s.activity_id, attempt: s.attempt, started_at: s.started_at, completed_at: s.completed_at, input: s.input }, null, 2))}</pre></details></div>` : ""}`;
  el.getAnimations().forEach((a) => a.cancel());
  el.animate(
    [{ transform: "translateY(4px)" }, { transform: "translateY(0)" }],
    {
      duration: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : 200,
      easing: "cubic-bezier(.16,1,.3,1)",
    },
  );
}
function temporalLink(id) {
  return `${(meta?.links.temporal_ui || "").replace(/\/$/, "")}/namespaces/${encodeURIComponent(meta?.namespace || "default")}/workflows/${encodeURIComponent(id)}`;
}
function renderRecent() {
  const list = [...runs.values()];
  $("#run-count").textContent = list.length;
  const signature = JSON.stringify(
    list.map((r) => [
      r.id,
      r.request,
      stateOf(r),
      r.id === selectedId,
      r.stale,
    ]),
  );
  if (signature === lastList) return;
  lastList = signature;
  const el = $("#recent-runs");
  el.replaceChildren();
  if (!list.length) {
    el.innerHTML =
      '<p class="muted empty-runs">Your runs will appear here.</p>';
    return;
  }
  for (const r of list.slice(0, 8)) {
    const state = stateOf(r),
      button = document.createElement("button");
    button.type = "button";
    button.className = "recent-run";
    button.setAttribute("aria-current", String(r.id === selectedId));
    button.title = r.request || r.id;
    button.innerHTML = `<i class="legend-dot ${state.key}"></i><span class="run-info"><strong>${esc(r.request?.split(":")[0] || r.id)}</strong><small>${esc(state.label)}${r.stale ? " · status unavailable" : ""} · ${esc(r.id.slice(-6))}</small></span><span class="arrow">${icon("arrow")}</span>`;
    button.onclick = () => selectRun(r.id);
    el.append(button);
  }
}
function renderApproval() {
  const r = current(),
    pending = !!r?.pending?.pending;
  $("#approval-action").hidden = !pending;
  if (!pending) return;
  $("#approval-details").textContent =
    r.pending.details || "Review this order before it continues.";
  $("#approval-location").textContent = r.child_workflow_id
    ? "Waiting in a child approval workflow. Your decision is sent to that workflow."
    : "Waiting in the order workflow. Your decision is recorded in Temporal.";
  const sent = decisionSent.has(r.id);
  $("#approve").disabled = decisionBusy || sent;
  $("#reject").disabled = decisionBusy || sent;
  $("#decision-note").disabled = decisionBusy || sent;
  if (sent) {
    $("#decision-feedback").hidden = false;
    $("#decision-feedback").textContent =
      "Decision sent. Waiting for the workflow to record it…";
  }
}
function renderTimeline() {
  const events = current()?.timeline || [];
  $("#event-count").textContent = events.length;
  setHTML(
    $("#timeline"),
    events.length
      ? events
          .map(
            (event) =>
              `<li class="${esc(event.kind)}"><time>${event.at ? esc(new Date(event.at).toLocaleTimeString([], { hour12: false })) : ""}</time><span>${esc(event.label)}${event.attempt > 1 ? `<small>Attempt ${event.attempt} · retried</small>` : ""}</span></li>`,
          )
          .join("")
      : "<li>Start an order to see its execution history.</li>",
  );
}
function renderResult() {
  const r = current(),
    result = r?.result,
    el = $("#result-content");
  let html;
  if (!r)
    html =
      '<h3>An outcome starts with a request</h3><p class="muted">Run an order to see the supervisor’s response and approval decision.</p>';
  else if (!TERMINAL.has(r.status))
    html = `<h3>${r.pending?.pending ? "Waiting for your decision" : "The agents are working"}</h3><p class="muted">${r.pending?.pending ? "Review the approval below to finish this run." : "Select a step in Workflow to follow the handoffs as they happen."}</p>`;
  else if (r.status !== "COMPLETED")
    html = `<h3>Workflow ${esc(r.status.toLowerCase().replaceAll("_", " "))}</h3><p class="result-summary">${esc(r.error || "Open Temporal history for the execution details.")}</p><p class="muted">Completed agent outputs remain available in the workflow inspector.</p>`;
  else if (!result)
    html =
      '<h3>Workflow completed</h3><p class="muted">The result is unavailable. Open Temporal to inspect the recorded output.</p>';
  else
    html = `<h3>${result.approval?.approved === false ? "Order rejected" : "Order workflow completed"}</h3><p class="muted">${result.approval?.approved === false ? "The human decision rejected this order. The agent recommendation is preserved below." : result.approval?.required ? "Approval recorded. The workflow reached its final outcome." : "No human approval was required."}</p>${meta.provider === "fake" ? '<p class="muted">Demo model output is an echo of the supplied context.</p>' : ""}<div class="result-summary">${esc(result.outcome || "No supervisor output was produced by this pipeline.")}</div>${result.incident ? `<div class="inspector-section"><h4>ServiceNow handoff</h4><p>${esc(result.incident)}</p></div>` : ""}<div class="result-outputs">${pipeline
      .map((role) => {
        const output = result[role === "supervisor" ? "outcome" : role];
        return output
          ? `<details><summary>${esc(roles[role].title)} output</summary><p>${esc(text(output))}</p></details>`
          : "";
      })
      .join(
        "",
      )}<details><summary>Full result JSON</summary><p>${esc(JSON.stringify(result, null, 2))}</p></details></div>`;
  setHTML(el, html);
}
function render() {
  const r = current(),
    state = stateOf(r);
  $("#run-status").className = `status ${state.key}`;
  $("#run-status").textContent = state.label;
  $("#run-request").textContent =
    r?.request || "Start an order to follow the agent handoffs in real time.";
  $("#workflow-id").textContent = r?.id || "No run selected";
  $("#workflow-link").hidden = !r;
  if (r) $("#workflow-link").href = temporalLink(r.id);
  $("#elapsed").textContent = r?.started_at
    ? `${TERMINAL.has(r.status) ? "Duration" : "Elapsed"} ${duration(r.started_at, r.closed_at)}`
    : "";
  const stale = r?.stale;
  $("#sync-status").className =
    `sync-status ${r && !stale && !TERMINAL.has(r.status) ? "live" : ""}`;
  setHTML(
    $("#sync-status"),
    `<i></i>${!r ? "Waiting for a run" : stale ? "Status unavailable" : TERMINAL.has(r.status) ? "Recorded in Temporal" : "Live · every second"}`,
  );
  setError(
    "#connection-error",
    stale
      ? "Status could not be refreshed. Showing the last known state; reconnecting automatically."
      : r?.pending?.unavailable
        ? "Approval status is temporarily unavailable. Retrying automatically."
        : "",
  );
  renderMap();
  renderInspector();
  renderRecent();
  renderApproval();
  renderTimeline();
  if (activeTab === "result") renderResult();
  const announcement = `${r?.id || ""}:${state.label}`;
  if (r && announcement !== lastAnnouncement) {
    $("#announcement").textContent = `${r.request}. ${state.label}.`;
    lastAnnouncement = announcement;
  }
}
function tab(name) {
  activeTab = name;
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
    b.tabIndex = b.dataset.tab === name ? 0 : -1;
  });
  for (const view of ["workflow", "timeline", "result"])
    $(`#panel-${view}`).hidden = view !== name;
  if (name === "workflow") requestAnimationFrame(drawConnectors);
  if (name === "result") renderResult();
}
function updateControls() {
  const mode = $("#chaos-mode").value;
  $("#fault-fields").hidden = mode === "none";
  $("#latency-field").hidden = mode !== "latency";
  $("#fault-summary").textContent =
    mode === "none" ? "Off" : mode === "latency" ? "Slow response" : "Failure";
  $("#approval-summary").textContent = $("#no-hitl").checked
    ? "Skipped"
    : $("#force-hitl").checked
      ? "Always"
      : `Above ${$("#threshold").value}%`;
}
async function startOrder(event) {
  event.preventDefault();
  if (loading) return;
  if (!meta) {
    setError(
      "#form-error",
      "Configuration is unavailable. Refresh the page to reconnect.",
    );
    return;
  }
  if (!$("#order-form").reportValidity()) return;
  const request = $("#request").value.trim();
  if (!request) {
    setError("#form-error", "Enter a distributor request.");
    $("#request").focus();
    return;
  }
  const mode = $("#chaos-mode").value,
    body = {
      request,
      threshold: Number($("#threshold").value),
      hitl_mode: $("#hitl-mode").value,
      no_hitl: $("#no-hitl").checked,
      chaos: {
        target: mode === "none" ? "" : $("#chaos-target").value,
        mode,
        attempts: Number($("#chaos-attempts").value),
        latency_seconds: Number($("#chaos-latency").value),
        force_hitl: $("#force-hitl").checked,
      },
    };
  loading = true;
  $("#run").disabled = true;
  $("#run-label").textContent = "Starting workflow…";
  setError("#form-error", "");
  try {
    const response = await api("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const r = { id: response.workflow_id, request, status: "RUNNING" };
    runs = new Map([[r.id, r], ...[...runs].slice(0, 24)]);
    selectedId = r.id;
    selectedRole = pipeline[0];
    lastInspector = "";
    save();
    $("#decision-note").value = "";
    setError("#decision-feedback", "");
    tab("workflow");
    render();
    await poll();
    if (innerWidth <= 800)
      $("#execution-title").scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
        block: "start",
      });
  } catch (error) {
    setError("#form-error", error.message);
  } finally {
    loading = false;
    $("#run").disabled = false;
    $("#run-label").textContent = "Run order";
  }
}
async function decide(approved) {
  const r = current();
  if (!r || decisionBusy || decisionSent.has(r.id)) return;
  const id = r.id,
    note = $("#decision-note").value;
  decisionBusy = true;
  renderApproval();
  setError("#decision-feedback", "");
  try {
    await api(`/api/orders/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved,
        approver: "demo-ui",
        note: note || `${approved ? "Approved" : "Rejected"} in Agent Studio`,
      }),
    });
    decisionSent.add(id);
    if (selectedId === id) {
      $("#decision-feedback").hidden = false;
      $("#decision-feedback").textContent =
        "Decision sent. Waiting for the workflow to record it…";
    }
    await poll();
  } catch (error) {
    if (selectedId === id) {
      $("#decision-feedback").hidden = false;
      $("#decision-feedback").textContent = error.message;
    }
  } finally {
    decisionBusy = false;
    renderApproval();
  }
}
async function poll() {
  if (polling || document.hidden) return;
  polling = true;
  try {
    const targets = [...runs.values()].filter(
      (r) => !TERMINAL.has(r.status) || !r.loaded,
    );
    await Promise.all(
      targets.map(async (run) => {
        try {
          const data = await api(`/api/orders/${encodeURIComponent(run.id)}`);
          Object.assign(run, data, { loaded: true, stale: false });
        } catch {
          run.stale = true;
        }
      }),
    );
    render();
  } finally {
    polling = false;
  }
}
async function init() {
  document
    .querySelectorAll("[data-icon]")
    .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
  $("#order-form").addEventListener("submit", startOrder);
  $("#decision-form").addEventListener("submit", (e) => {
    e.preventDefault();
    decide(true);
  });
  $("#reject").onclick = () => decide(false);
  $("#approval-node").onclick = () => {
    selectRole("approval");
    if (current()?.pending?.pending)
      $("#approval-action").scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
        block: "nearest",
      });
  };
  $("#service-node").onclick = () => selectRole("servicenow");
  $("#scenario").onchange = () => {
    const scenario = scenarios[$("#scenario").value];
    $("#request").value = scenario.request;
    $("#scenario-help").textContent = scenario.help;
    $("#chaos-mode").value = scenario.mode;
    $("#chaos-target").value = "inventory";
    $("#chaos-attempts").value = 1;
    $("#no-hitl").checked = false;
    $("#force-hitl").checked = false;
    updateControls();
  };
  for (const id of ["chaos-mode", "threshold", "no-hitl", "force-hitl"])
    $(`#${id}`).addEventListener("input", updateControls);
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => tab(b.dataset.tab);
    b.onkeydown = (e) => {
      const names = ["workflow", "timeline", "result"],
        i = names.indexOf(activeTab);
      let next;
      if (e.key === "ArrowRight") next = names[(i + 1) % 3];
      if (e.key === "ArrowLeft") next = names[(i + 2) % 3];
      if (e.key === "Home") next = names[0];
      if (e.key === "End") next = names[2];
      if (next) {
        e.preventDefault();
        tab(next);
        $(`#tab-${next}`).focus();
      }
    };
  });
  try {
    meta = await api("/api/meta");
    pipeline = meta.pipeline?.length ? meta.pipeline : Object.keys(roles);
    selectedRole = pipeline[0];
    $("#environment").textContent = `${meta.environment} workspace`;
    $("#provider").textContent =
      meta.provider === "fake"
        ? "Demo model · no API calls"
        : `Model provider · ${meta.provider}`;
    $("#run-mode").textContent =
      `Runs on Temporal · ${meta.provider === "fake" ? "demo model" : meta.provider}`;
    $("#threshold").value = meta.hitl.threshold;
    $("#hitl-mode").value = meta.hitl.mode;
    $("#chaos-target").replaceChildren(
      ...pipeline.map((role) => new Option(roles[role].short, role)),
    );
    $("#chaos-target").value = pipeline.includes("inventory")
      ? "inventory"
      : pipeline[0];
    for (const [id, key] of [
      ["temporal", "temporal_ui"],
      ["phoenix", "phoenix"],
      ["grafana", "grafana"],
      ["prom", "prometheus"],
    ])
      $(`#lnk-${id}`).href = meta.links[key];
    if (!meta.hitl.enabled) {
      $("#no-hitl").checked = true;
      $("#no-hitl").disabled = true;
      $("#force-hitl").disabled = true;
      $("#threshold").disabled = true;
      $("#hitl-mode").disabled = true;
    }
    const stored = (() => {
      try {
        return JSON.parse(localStorage.getItem(STORAGE) || "[]");
      } catch {
        return [];
      }
    })();
    const server = await api("/api/orders");
    const entries = [...server.runs, ...(Array.isArray(stored) ? stored : [])];
    for (const r of entries) {
      if (
        typeof r.id === "string" &&
        r.id.startsWith(meta.graph_name + "-") &&
        !runs.has(r.id) &&
        runs.size < 25
      )
        runs.set(r.id, { id: r.id, request: r.request || "" });
    }
    selectedId = runs.keys().next().value || null;
    const remembered = new URLSearchParams(location.search).get("run");
    if (remembered && runs.has(remembered)) selectedId = remembered;
    save();
  } catch (error) {
    setError("#form-error", error.message);
    $("#provider").textContent = "Configuration unavailable";
    $("#run").disabled = true;
  }
  buildMap();
  updateControls();
  render();
  await poll();
  setInterval(poll, 1000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });
}
init();

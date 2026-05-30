"use strict";

const DEFAULT_API_URL = "http://127.0.0.1:8767";
const MAX_LOG_ENTRIES = 300;

const ENDPOINTS = Object.freeze({
  health: "/health",
  agents: "/agents",
  sessions: "/sessions",
  sessionDetail: "/sessions/{session_id}",
  sessionLogs: "/sessions/{session_id}/logs",
  sessionStop: "/sessions/{session_id}/stop",
  sessionRetry: "/sessions/{session_id}/retry",
  sessionEvents: "/sessions/{session_id}/events",
  sessionTimeline: "/sessions/{session_id}/timeline",
  sessionAttach: "/sessions/{session_id}/attach",
  sessionRun: "/sessions",
  sessionSummary: "/sessions/{session_id}/memory/summary",
  sessionReview: "/sessions/{session_id}/memory/review",
  memoryReview: "/memory/review",
  memoryApprove: "/memory/review/{item_id}/approve",
  memoryReject: "/memory/review/{item_id}/reject",
  memoryList: "/memory",
  memorySearch: "/memory/search",
  skills: "/skills",
  mcp: "/mcp",
  policySummary: "/policy",
  policyEvaluate: "/policy/evaluate",
  approvals: "/approvals",
  approvalApprove: "/approvals/{approval_id}/approve",
  approvalReject: "/approvals/{approval_id}/reject",
  fleetHealth: "/fleet/health",
  fleetInstanceHealth: "/fleet/{agent_id}/health",
  fleetEvents: "/fleet/events",
  fleetCapacity: "/fleet/capacity",
  fleetProbe: "/fleet/probe",
  auditEvents: "/audit/events",
  auditPolicyCoverage: "/audit/policy-coverage",
  harnesses: "/harnesses",
  harnessHealth: "/harnesses/{harness_id}/health",
  harnessInstanceHealth: "/harnesses/{agent_id}/health",
  catalogSurfaces: "/catalog/{harness}/surfaces",
  harnessConfigEffective: "/harness-config/{harness_id}/effective",
  approvalsFiltered: "/approvals",
  auditEvents: "/audit/events",
});

const HTML_ENTITIES = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
});

const state = {
  activeTab: "agents",
  logEntries: [],
  logSessionId: "",
  logStream: "",
  afterCursor: 0,
};

document.addEventListener("DOMContentLoaded", () => {
  byId("api-url").value = DEFAULT_API_URL;
  bindTabs();
  bindControls();
  refreshAll();
});

function byId(id) {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element;
}

function bindTabs() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      showTab(button.dataset.tab);
    });
  });
}

function bindControls() {
  byId("refresh-all").addEventListener("click", refreshAll);
  byId("refresh-agents").addEventListener("click", loadAgents);
  byId("refresh-sessions").addEventListener("click", loadSessions);
  byId("load-logs").addEventListener("click", loadLogs);
  byId("refresh-memory").addEventListener("click", loadMemory);
  byId("refresh-skills").addEventListener("click", loadSkillsMcp);
  byId("run-policy-eval").addEventListener("click", evaluatePolicy);
  byId("refresh-fleet").addEventListener("click", loadFleet);
  byId("fleet-probe-btn").addEventListener("click", triggerFleetProbe);
  byId("load-audit-events").addEventListener("click", loadAuditEvents);
  byId("run-submit").addEventListener("click", submitRunForm);
  byId("run-cancel").addEventListener("click", hideRunForm);
  byId("search-memory").addEventListener("click", () => {
    loadMemories(byId("memory-search").value.trim());
  });
  byId("memory-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      loadMemories(byId("memory-search").value.trim());
    }
  });
  byId("log-stream").addEventListener("change", () => {
    resetLogState();
  });
  byId("catalog-load").addEventListener("click", loadCatalog);
  byId("harness-config-load").addEventListener("click", loadHarnessNativeConfig);
  byId("approval-load").addEventListener("click", loadApprovalsTab);
  byId("load-audit").addEventListener("click", loadAuditStandalone);
  document.body.addEventListener("click", handleActionClick);
}

function showTab(tabName, options = {}) {
  state.activeTab = tabName;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const isActive = button.dataset.tab === tabName;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
  document.querySelectorAll("[role='tabpanel']").forEach((panel) => {
    const isActive = panel.id === `panel-${tabName}`;
    panel.classList.toggle("is-active", isActive);
    panel.hidden = !isActive;
  });
  if (!options.skipLoad) {
    loadActiveTab();
  }
}

function loadActiveTab() {
  if (state.activeTab === "agents") {
    loadAgents();
  } else if (state.activeTab === "sessions") {
    loadSessions();
    const selectedSession = byId("log-session-id").value.trim();
    if (selectedSession) {
      loadSessionTimeline(selectedSession);
    }
  } else if (state.activeTab === "logs") {
    loadLogs();
  } else if (state.activeTab === "memory") {
    loadMemory();
  } else if (state.activeTab === "skills") {
    loadSkillsMcp();
  } else if (state.activeTab === "fleet") {
    loadFleet();
  } else if (state.activeTab === "harnesses") {
    loadHarnesses();
  } else if (state.activeTab === "catalog") {
    // Catalog is manually loaded
  } else if (state.activeTab === "approvals") {
    loadApprovalsTab();
  } else if (state.activeTab === "audit") {
    // Audit is manually loaded
  } else if (state.activeTab === "overview") {
    loadOverview();
  }
}

async function refreshAll() {
  await loadHealth();
  await Promise.allSettled([loadAgents(), loadSessions(), loadMemory(), loadSkillsMcp(), loadFleet(), loadHarnesses()]);
  if (state.activeTab === "logs" && byId("log-session-id").value.trim()) {
    await loadLogs();
  }
}

function apiBase() {
  const value = byId("api-url").value.trim() || DEFAULT_API_URL;
  return value.replace(/\/+$/, "");
}

function buildEndpoint(name, params = {}) {
  let path = ENDPOINTS[name];
  Object.entries(params).forEach(([key, value]) => {
    path = path.replace(`{${key}}`, encodeURIComponent(value));
  });
  return path;
}

async function apiFetch(path, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(`${apiBase()}${path}`, { ...options, headers });
  const text = await response.text();
  const payload = text ? parseJson(text) : {};

  if (!response.ok) {
    const detail = normalizeErrorDetail(payload.detail || response.statusText);
    const error = new Error(`${response.status} ${detail}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function normalizeErrorDetail(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  return JSON.stringify(detail);
}

async function postEmpty(path) {
  return apiFetch(path, { method: "POST", body: JSON.stringify({}) });
}

async function postJson(path, payload) {
  return apiFetch(path, { method: "POST", body: JSON.stringify(payload) });
}

async function loadSessionDetail(sessionId) {
  return apiFetch(buildEndpoint("sessionDetail", { session_id: sessionId }), { method: "GET" });
}

async function loadSessionSummary(sessionId) {
  return apiFetch(buildEndpoint("sessionSummary", { session_id: sessionId }), { method: "GET" });
}

async function loadHealth() {
  const status = byId("api-status");
  status.className = "status is-unknown";
  status.textContent = "checking";
  try {
    const health = await apiFetch(buildEndpoint("health"));
    status.className = "status is-ok";
    status.textContent = health.status || "ok";
    return true;
  } catch (error) {
    status.className = "status is-error";
    status.textContent = `offline: ${error.message}`;
    return false;
  }
}

async function loadAgents() {
  const body = byId("agents-body");
  try {
    const data = await apiFetch(buildEndpoint("agents"));
    const agents = asArray(data.agents);
    if (agents.length === 0) {
      renderEmptyRow(body, 7, "No agents returned.");
      return;
    }
    body.innerHTML = agents
      .map(
        (agent) => `
          <tr>
            <td class="cell-id">${escapeHtml(agent.id)}</td>
            <td>${escapeHtml(agent.label)}</td>
            <td>${escapeHtml(String(agent.enabled !== false))}</td>
            <td>${escapeHtml(agent.cwd_mode)}</td>
            <td>${escapeHtml(agent.stop_policy)}</td>
            <td class="cell-code">${escapeHtml(commandPreview(agent.command))}</td>
            <td>
              <button type="button" data-action="run-agent" data-agent-id="${escapeHtml(agent.id)}" ${
                agent.enabled === false ? "disabled" : ""
              }>Run</button>
            </td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 7, error.message);
  }
}

async function loadSessions() {
  const body = byId("sessions-body");
  try {
    const data = await apiFetch(buildEndpoint("sessions"));
    const sessions = asArray(data.sessions);
    if (sessions.length === 0) {
      renderEmptyRow(body, 7, "No sessions returned.");
      return;
    }
    body.innerHTML = sessions.map(renderSessionRow).join("");
  } catch (error) {
    renderErrorRow(body, 7, error.message);
  }
}

function renderSessionRow(session) {
  const status = String(session.status || "unknown");
  const canStop = ["queued", "running", "stopping"].includes(status);
  const canRetry = !["queued", "running", "stopping"].includes(status);
  const canAttach = session.attach_status === "available" || session.attachable === true;
  return `
    <tr>
      <td class="cell-id">${escapeHtml(session.id)}</td>
      <td>${escapeHtml(session.agent_id)}</td>
      <td class="cell-code">${escapeHtml(session.cwd)}</td>
      <td><span class="${statusPillClass(status)}">${escapeHtml(status)}</span></td>
      <td>${escapeHtml(valueOrDash(session.exit_code))}</td>
      <td>${escapeHtml(session.updated_at)}</td>
      <td>
        <div class="actions">
          <button type="button" data-action="select-session" data-session-id="${escapeHtml(session.id)}">
            open
          </button>
          <button type="button" data-action="logs" data-session-id="${escapeHtml(session.id)}">
            logs
          </button>
          <button type="button" data-action="attach-preview" data-session-id="${escapeHtml(session.id)}" ${
            canAttach ? "" : "disabled"
          }>
            attach
          </button>
          <button type="button" data-action="summarize" data-session-id="${escapeHtml(session.id)}">
            summarize
          </button>
          <button type="button" data-action="review-create" data-session-id="${escapeHtml(session.id)}">
            review create
          </button>
          <button type="button" data-action="retry" data-session-id="${escapeHtml(session.id)}" ${
            canRetry ? "" : "disabled"
          }>
            retry
          </button>
          <button type="button" data-action="stop" data-session-id="${escapeHtml(session.id)}" ${
            canStop ? "" : "disabled"
          }>
            stop
          </button>
        </div>
      </td>
    </tr>
  `;
}

async function selectSession(sessionId) {
  if (!sessionId) {
    return;
  }
  byId("log-session-id").value = sessionId;
  byId("runs-selected-session").textContent = `Selected: ${sessionId}`;
  showTab("sessions", { skipLoad: true });
  resetLogState();
  await Promise.allSettled([loadSessionTimeline(sessionId), loadLogs()]);
}

async function loadSessionTimeline(sessionId) {
  const container = byId("session-timeline");
  if (!sessionId) {
    container.innerHTML = '<p class="message">Select a session from the list.</p>';
    return;
  }
  try {
    const data = await apiFetch(buildEndpoint("sessionTimeline", { session_id: sessionId }));
    const timeline = asArray(data.timeline);
    if (timeline.length === 0) {
      container.innerHTML = '<p class="message">No timeline entries.</p>';
      return;
    }
    container.innerHTML = timeline.map(renderTimelineEntry).join("");
  } catch (error) {
    container.innerHTML = `<p class="message is-error">${escapeHtml(error.message)}</p>`;
  }
}

function renderTimelineEntry(entry) {
  const type = String(entry.type || "event")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
  return `
    <article class="timeline-entry timeline-entry--${escapeHtml(type)}">
      <header>
        <span class="badge">${escapeHtml(entry.type || "event")}</span>
        <span class="timeline-ts">${escapeHtml(entry.timestamp || "")}</span>
      </header>
      <p>${escapeHtml(entry.message || "")}</p>
    </article>
  `;
}

async function loadLogs() {
  const sessionId = byId("log-session-id").value.trim();
  const stream = byId("log-stream").value;
  const afterInput = byId("log-after");
  const requestedAfter = normalizeCursor(afterInput.value);

  if (!sessionId) {
    byId("log-output").textContent = "";
    renderSessionDetail(null);
    loadSessionEvents(null);
    setMessage("logs-message", "Enter a session id.");
    return;
  }

  if (
    state.logSessionId !== sessionId ||
    state.logStream !== stream ||
    requestedAfter < state.afterCursor
  ) {
    state.logEntries = [];
  }
  state.logSessionId = sessionId;
  state.logStream = stream;

  try {
    const session = await loadSessionDetail(sessionId);
    renderSessionDetail(session);
    loadSessionEvents(sessionId);

    const query = new URLSearchParams({ after: String(requestedAfter) });
    if (stream) {
      query.set("stream", stream);
    }
    const path = `${buildEndpoint("sessionLogs", { session_id: sessionId })}?${query}`;
    const data = await apiFetch(path);
    const entries = asArray(data.entries);
    state.logEntries = trimLogEntries([...state.logEntries, ...entries]);
    state.afterCursor = entries.reduce(
      (cursor, entry) => Math.max(cursor, Number(entry.index) || cursor),
      requestedAfter,
    );
    afterInput.value = String(state.afterCursor);
    renderLogs();
    setMessage(
      "logs-message",
      `loaded ${entries.length} entries, showing last ${state.logEntries.length}`,
    );
  } catch (error) {
    setMessage("logs-message", error.message, true);
  }
}

function trimLogEntries(entries) {
  return entries.slice(-MAX_LOG_ENTRIES);
}

function renderSessionDetail(session) {
  const target = byId("log-session-detail");
  const detail = session || {};
  target.innerHTML = `
    <dt>Session</dt>
    <dd class="cell-id">${escapeHtml(detail.id)}</dd>
    <dt>Agent</dt>
    <dd>${escapeHtml(detail.agent_id)}</dd>
    <dt>Status</dt>
    <dd>${escapeHtml(detail.status)}</dd>
    <dt>Updated</dt>
    <dd>${escapeHtml(detail.updated_at)}</dd>
  `;
}

function renderLogs() {
  byId("log-output").textContent = state.logEntries
    .map((entry) => {
      const index = valueOrDash(entry.index);
      const stream = valueOrDash(entry.stream);
      const line = valueOrDash(entry.line);
      return `${index} [${stream}] ${line}`;
    })
    .join("\n");
}

function resetLogState() {
  state.logEntries = [];
  state.afterCursor = 0;
  byId("log-after").value = "0";
  renderLogs();
}

async function loadMemory() {
  await Promise.allSettled([loadMemoryReview(), loadMemories()]);
}

async function loadMemoryReview() {
  const body = byId("memory-review-body");
  try {
    const data = await apiFetch(buildEndpoint("memoryReview"));
    const items = asArray(data.items);
    if (items.length === 0) {
      renderEmptyRow(body, 6, "No review items returned.");
      return;
    }
    body.innerHTML = items.map(renderReviewRow).join("");
    setMessage("memory-message", "");
  } catch (error) {
    renderErrorRow(body, 6, error.message);
  }
}

function renderReviewRow(item) {
  const status = String(item.status || "unknown");
  const isPending = status === "pending";
  return `
    <tr>
      <td class="cell-id">${escapeHtml(item.id)}</td>
      <td class="cell-id">${escapeHtml(item.session_id)}</td>
      <td><span class="${statusPillClass(status)}">${escapeHtml(status)}</span></td>
      <td>${escapeHtml(item.title)}</td>
      <td class="cell-code">${escapeHtml(item.source)}</td>
      <td>
        <div class="actions">
          <button type="button" data-action="view-summary" data-session-id="${escapeHtml(item.session_id)}">
            summary
          </button>
          <button type="button" data-action="approve-memory" data-item-id="${escapeHtml(item.id)}" ${
            isPending ? "" : "disabled"
          }>
            approve
          </button>
          <button type="button" data-action="reject-memory" data-item-id="${escapeHtml(item.id)}" ${
            isPending ? "" : "disabled"
          }>
            reject
          </button>
        </div>
      </td>
    </tr>
  `;
}

async function loadMemories(query = "") {
  const body = byId("memories-body");
  try {
    const trimmed = query.trim();
    const path = trimmed
      ? `${buildEndpoint("memorySearch")}?${new URLSearchParams({ q: trimmed })}`
      : buildEndpoint("memoryList");
    const data = await apiFetch(path);
    const memories = asArray(data.memories);
    if (memories.length === 0) {
      renderEmptyRow(body, 4, "No approved memory returned.");
      return;
    }
    body.innerHTML = memories
      .map(
        (memory) => `
          <tr>
            <td class="cell-id">${escapeHtml(memory.id)}</td>
            <td>${escapeHtml(memory.kind)}</td>
            <td>${escapeHtml(memory.title)}</td>
            <td class="cell-code">${escapeHtml(memory.source)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 4, error.message);
  }
}

async function loadSkillsMcp() {
  await Promise.allSettled([loadSkills(), loadMcpServers(), loadPolicies(), loadApprovals()]);
}

async function loadSkills() {
  const body = byId("skills-body");
  try {
    const data = await apiFetch(buildEndpoint("skills"));
    const skills = asArray(data.skills);
    if (skills.length === 0) {
      renderEmptyRow(body, 8, "No skills returned.");
      return;
    }
    body.innerHTML = skills
      .map(
        (skill) => `
          <tr>
            <td class="cell-id">${escapeHtml(skill.id)}</td>
            <td>${escapeHtml(skill.label)}</td>
            <td>${skill.deprecated ? '<span class="pill is-deprecated">deprecated</span>' : escapeHtml(String(skill.enabled !== false))}</td>
            <td>${escapeHtml(skill.source)}</td>
            <td>${escapeHtml(asArray(skill.tags).join(", "))}</td>
            <td>${escapeHtml(skill.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(skill.replacement_id)}</td>
            <td>${escapeHtml(skill.sunset_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 8, error.message);
  }
}

async function loadMcpServers() {
  const body = byId("mcp-body");
  try {
    const data = await apiFetch(buildEndpoint("mcp"));
    const servers = asArray(data.servers);
    if (servers.length === 0) {
      renderEmptyRow(body, 8, "No MCP servers returned.");
      return;
    }
    body.innerHTML = servers
      .map(
        (server) => `
          <tr>
            <td class="cell-id">${escapeHtml(server.id)}</td>
            <td>${escapeHtml(server.label)}</td>
            <td>${server.deprecated ? '<span class="pill is-deprecated">deprecated</span>' : escapeHtml(String(server.enabled !== false))}</td>
            <td>${escapeHtml(server.transport)}</td>
            <td class="cell-code">${escapeHtml(asArray(server.command_preview).join(" "))}</td>
            <td>${escapeHtml(server.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(server.replacement_id)}</td>
            <td>${escapeHtml(server.sunset_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 8, error.message);
  }
}

async function loadApprovals() {
  const body = byId("approvals-embed-body");
  try {
    const data = await apiFetch(buildEndpoint("approvals"));
    const approvals = asArray(data.approvals);
    if (approvals.length === 0) {
      renderEmptyRow(body, 6, "No approvals returned.");
      return;
    }
    body.innerHTML = approvals.map(renderApprovalRow).join("");
  } catch (error) {
    renderErrorRow(body, 6, error.message);
  }
}

function renderApprovalRow(approval) {
  const status = String(approval.status || "unknown");
  const isPending = status === "pending";
  return `
    <tr>
      <td class="cell-id">${escapeHtml(approval.id)}</td>
      <td>${escapeHtml(approval.agent_id)}</td>
      <td><span class="${statusPillClass(status)}">${escapeHtml(status)}</span></td>
      <td class="cell-id">${escapeHtml(approval.source_session_id)}</td>
      <td class="cell-code">${escapeHtml(approval.reason)}</td>
      <td>
        <div class="actions">
          <button type="button" data-action="approve-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>approve</button>
          <button type="button" data-action="reject-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>reject</button>
        </div>
      </td>
    </tr>
  `;
}

async function loadPolicies() {
  const body = byId("policy-summary-body");
  try {
    const data = await apiFetch(buildEndpoint("policySummary"));
    const policies = asArray(data.policies);
    if (policies.length === 0) {
      renderEmptyRow(body, 7, "No policies returned.");
      return;
    }
    body.innerHTML = policies
      .map(
        (policy) => `
          <tr>
            <td class="cell-id">${escapeHtml(policy.agent_id)}</td>
            <td>${policy.deprecated ? '<span class="pill is-deprecated">deprecated</span>' : escapeHtml(String(policy.enabled !== false))}</td>
            <td>${escapeHtml(policy.readonly ? "readonly" : "write")}</td>
            <td>${escapeHtml(policy.rate_limit_per_minute)}</td>
            <td>${escapeHtml(policy.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(policy.replacement_id)}</td>
            <td>${escapeHtml(policy.sunset_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 7, error.message);
  }
}

async function evaluatePolicy() {
  const result = byId("policy-eval-result");
  const agentId = byId("policy-eval-agent").value.trim();
  if (!agentId) {
    result.textContent = "agent_id is required";
    return;
  }
  try {
    const payload = {
      agent_id: agentId,
      skill_id: emptyToNull(byId("policy-eval-skill").value),
      mcp_server_id: emptyToNull(byId("policy-eval-mcp").value),
      tool_name: emptyToNull(byId("policy-eval-tool").value),
      model_id: emptyToNull(byId("policy-eval-model").value),
      cwd: emptyToNull(byId("policy-eval-cwd").value),
    };
    const data = await apiFetch(buildEndpoint("policyEvaluate"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
    result.textContent = [
      `decision: ${valueOrDash(data.decision)}`,
      `reason: ${valueOrDash(data.reason)}`,
      `readonly: ${valueOrDash(data.readonly)}`,
      `rate_limit_per_minute: ${valueOrDash(data.rate_limit_per_minute)}`,
    ].join("\n");
  } catch (error) {
    result.textContent = error.message;
  }
}

function renderSessionSummary(summary) {
  const lines = [
    `session_id: ${valueOrDash(summary.session_id)}`,
    `agent_id: ${valueOrDash(summary.agent_id)}`,
    `status: ${valueOrDash(summary.status)}`,
    `one_liner: ${valueOrDash(summary.one_liner)}`,
    `last_task: ${valueOrDash(summary.last_task)}`,
    `stdout_lines: ${valueOrDash(summary.stdout_lines)}`,
    `stderr_lines: ${valueOrDash(summary.stderr_lines)}`,
    `error_lines: ${valueOrDash(summary.error_lines)}`,
  ];
  byId("memory-summary-output").textContent = lines.join("\n");
}

function formatPolicyError(error) {
  const p = error.payload || {};
  if (p.decision && p.session_id) {
    return `${error.message}\ndecision: ${p.decision}  session_id: ${p.session_id}`;
  }
  return error.message;
}

function showRunForm(agentId) {
  byId("run-agent-id").value = agentId;
  byId("run-cwd").value = "";
  byId("run-message").value = "";
  byId("run-result").textContent = "";
  byId("run-form-section").hidden = false;
  byId("run-message").focus();
}

function hideRunForm() {
  byId("run-form-section").hidden = true;
}

async function submitRunForm() {
  const agentId = byId("run-agent-id").value.trim();
  const cwd = emptyToNull(byId("run-cwd").value);
  const message = byId("run-message").value.trim();
  const result = byId("run-result");

  if (!agentId || !message) {
    result.textContent = "agent and message are required";
    return;
  }

  byId("run-submit").disabled = true;
  try {
    const data = await apiFetch(buildEndpoint("sessionRun"), {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, cwd: cwd, message: message }),
    });
    result.textContent = `session created: ${data.id}  status: ${data.status}`;
    setMessage("agents-message", `started session ${data.id}`);
    await loadSessions();
  } catch (error) {
    result.textContent = formatPolicyError(error);
    setMessage("agents-message", formatPolicyError(error), true);
  } finally {
    byId("run-submit").disabled = false;
  }
}

async function loadSessionEvents(sessionId) {
  const body = byId("events-body");
  if (!sessionId) {
    renderEmptyRow(body, 4, "Load a session to see events.");
    return;
  }
  try {
    const data = await apiFetch(
      buildEndpoint("sessionEvents", { session_id: sessionId }),
    );
    const events = asArray(data.events);
    if (events.length === 0) {
      renderEmptyRow(body, 4, "No events for this session.");
      return;
    }
    body.innerHTML = events
      .map(
        (evt) => `
          <tr>
            <td>${escapeHtml(evt.id)}</td>
            <td>${escapeHtml(evt.event_type)}</td>
            <td class="cell-code">${escapeHtml(evt.message)}</td>
            <td>${escapeHtml(evt.created_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 4, error.message);
  }
}

async function handleActionClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }

  const action = button.dataset.action;
  const sessionId = button.dataset.sessionId;
  const agentId = button.dataset.agentId;
  const itemId = button.dataset.itemId;
  const approvalId = button.dataset.approvalId;
  button.disabled = true;

  try {
    if (action === "run-agent" && agentId) {
      showRunForm(agentId);
      button.disabled = false;
      return;
    } else if ((action === "logs" || action === "select-session") && sessionId) {
      await selectSession(sessionId);
    } else if (action === "attach-preview" && sessionId) {
      const data = await postJson(buildEndpoint("sessionAttach", { session_id: sessionId }), {
        mode: "preview",
      });
      const preview = byId("attach-preview-output");
      preview.hidden = false;
      preview.textContent = JSON.stringify(data, null, 2);
      setMessage("sessions-message", `attach preview: ${data.decision}`);
    } else if (action === "summarize" && sessionId) {
      await postEmpty(buildEndpoint("sessionSummary", { session_id: sessionId }));
      const summary = await loadSessionSummary(sessionId);
      renderSessionSummary(summary);
      setMessage("sessions-message", `summary created for ${sessionId}: ${summary.one_liner}`);
    } else if (action === "review-create" && sessionId) {
      await postEmpty(buildEndpoint("sessionReview", { session_id: sessionId }));
      const summary = await loadSessionSummary(sessionId);
      renderSessionSummary(summary);
      setMessage("sessions-message", `review item created for ${sessionId}`);
      await loadMemoryReview();
    } else if (action === "retry" && sessionId) {
      try {
        await postEmpty(buildEndpoint("sessionRetry", { session_id: sessionId }));
        setMessage("sessions-message", `retry started for ${sessionId}`);
      } catch (retryError) {
        setMessage("sessions-message", formatPolicyError(retryError), true);
      }
      await loadSessions();
    } else if (action === "stop" && sessionId) {
      await postEmpty(buildEndpoint("sessionStop", { session_id: sessionId }));
      setMessage("sessions-message", `stop requested for ${sessionId}`);
      await loadSessions();
    } else if (action === "approve-memory" && itemId) {
      await postEmpty(buildEndpoint("memoryApprove", { item_id: itemId }));
      setMessage("memory-message", `approved ${itemId}`);
      await loadMemory();
    } else if (action === "reject-memory" && itemId) {
      await postEmpty(buildEndpoint("memoryReject", { item_id: itemId }));
      setMessage("memory-message", `rejected ${itemId}`);
      await loadMemory();
    } else if (action === "view-summary" && sessionId) {
      const summary = await loadSessionSummary(sessionId);
      renderSessionSummary(summary);
      setMessage("memory-message", `loaded summary for ${sessionId}`);
    } else if (action === "approve-approval" && approvalId) {
      await approveApproval(approvalId);
    } else if (action === "reject-approval" && approvalId) {
      await rejectApproval(approvalId);
    }
  } catch (error) {
    if (["approve-memory", "reject-memory", "view-summary"].includes(action)) {
      setMessage("memory-message", error.message, true);
    } else if (["approve-approval", "reject-approval"].includes(action)) {
      setMessage("agents-message", error.message, true);
    } else {
      setMessage("sessions-message", error.message, true);
    }
  } finally {
    button.disabled = false;
  }
}

async function approveApproval(approvalId) {
  await postEmpty(buildEndpoint("approvalApprove", { approval_id: approvalId }));
  setMessage("agents-message", `approved ${approvalId}`);
  await Promise.allSettled([loadApprovals(), loadApprovalsTab(), loadSessions()]);
}

async function rejectApproval(approvalId) {
  const reason = window.prompt("Rejection reason", "") || "";
  await postJson(buildEndpoint("approvalReject", { approval_id: approvalId }), { reason });
  setMessage("agents-message", `rejected ${approvalId}`);
  await Promise.allSettled([loadApprovals(), loadApprovalsTab()]);
}

async function loadFleet() {
  await Promise.allSettled([loadFleetHealth(), loadFleetCapacity(), loadFleetEvents(), loadAuditEvents()]);
}

async function loadFleetHealth() {
  const body = byId("fleet-health-body");
  try {
    const data = await apiFetch(buildEndpoint("fleetHealth"));
    const instances = asArray(data.instances);
    if (instances.length === 0) {
      renderEmptyRow(body, 6, "No fleet health data. Click Probe Now.");
      return;
    }
    body.innerHTML = instances
      .map(
        (inst) => `
          <tr>
            <td class="cell-id">${escapeHtml(inst.agent_id)}</td>
            <td><span class="${healthPillClass(inst.state)}">${escapeHtml(inst.state)}</span></td>
            <td>${escapeHtml(inst.version)}</td>
            <td class="cell-code">${escapeHtml(inst.config_fingerprint)}</td>
            <td>${escapeHtml(inst.message)}</td>
            <td>${escapeHtml(inst.updated_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 6, error.message);
  }
}

async function loadFleetCapacity() {
  const el = byId("fleet-capacity-display");
  try {
    const data = await apiFetch(buildEndpoint("fleetCapacity"));
    el.innerHTML =
      `<p>Sessions: ${escapeHtml(data.running_sessions)}/${escapeHtml(data.max_running_sessions)}` +
      ` | Instances: ${escapeHtml(data.registered_instances)}/${escapeHtml(data.max_registered_instances)}</p>`;
  } catch (error) {
    el.innerHTML = `<p class="message is-error">${escapeHtml(error.message)}</p>`;
  }
}

async function loadFleetEvents() {
  const body = byId("fleet-events-body");
  try {
    const data = await apiFetch(buildEndpoint("fleetEvents"));
    const events = asArray(data.events);
    if (events.length === 0) {
      renderEmptyRow(body, 5, "No fleet events.");
      return;
    }
    body.innerHTML = events
      .map(
        (evt) => `
          <tr>
            <td>${escapeHtml(evt.id)}</td>
            <td class="cell-id">${escapeHtml(evt.agent_id)}</td>
            <td>${escapeHtml(evt.event_type)}</td>
            <td class="cell-code">${escapeHtml(evt.message)}</td>
            <td>${escapeHtml(evt.created_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 5, error.message);
  }
}

async function triggerFleetProbe() {
  const btn = byId("fleet-probe-btn");
  btn.disabled = true;
  btn.textContent = "Probing...";
  try {
    const data = await postEmpty(buildEndpoint("fleetProbe"));
    setMessage("fleet-message", `Probed ${data.probed} instances`);
    await loadFleet();
  } catch (error) {
    setMessage("fleet-message", error.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Probe Now";
  }
}

async function loadAuditEvents() {
  const body = byId("audit-events-body");
  const domain = byId("audit-domain").value;
  try {
    const query = new URLSearchParams({ limit: "100" });
    if (domain) {
      query.set("domain", domain);
    }
    const data = await apiFetch(`${buildEndpoint("auditEvents")}?${query}`);
    const events = asArray(data.events);
    if (events.length === 0) {
      renderEmptyRow(body, 6, "No audit events.");
      return;
    }
    body.innerHTML = events
      .map(
        (evt) => `
          <tr>
            <td>${escapeHtml(evt.id)}</td>
            <td>${escapeHtml(evt.domain)}</td>
            <td class="cell-id">${escapeHtml(evt.entity_id)}</td>
            <td>${escapeHtml(evt.event_type)}</td>
            <td class="cell-code">${escapeHtml(evt.message)}</td>
            <td>${escapeHtml(evt.created_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 6, error.message);
  }
}

async function loadHarnessNativeConfig() {
  const harnessId = byId("harness-config-id").value;
  const snippet = byId("harness-config-snippet");
  snippet.textContent = "Loading…";
  try {
    const data = await apiFetch(buildEndpoint("harnessConfigEffective", { harness_id: harnessId }));
    const payload = {
      harness_id: data.harness_id,
      scopes_present: data.scopes_present,
      entries: data.entries,
    };
    const text = JSON.stringify(payload, null, 2);
    snippet.textContent = text.length > 4096 ? `${text.slice(0, 4096)}\n… (truncated)` : text;
  } catch (error) {
    snippet.textContent = error.message;
  }
}

async function loadHarnesses() {
  try {
    const data = await apiFetch("harnesses");
    const body = byId("harnesses-body");
    const rows = asArray(data.harnesses);
    if (!rows.length) {
      renderEmptyRow(body, 6, "No harness instances configured.");
      return;
    }
    body.innerHTML = rows
      .map(
        (h) => `
          <tr>
            <td class="cell-id">${escapeHtml(h.id)}</td>
            <td>${escapeHtml(h.name)}</td>
            <td>${valueOrDash(h.default_provider)}</td>
            <td><span class="${healthPillClass('unknown')}">unknown</span></td>
            <td>${(h.log_paths || []).length || "-"}</td>
            <td>
              <button class="btn" onclick="loadHarnessHealth('${escapeHtml(h.id)}')">Check</button>
            </td>
          </tr>
        `,
      )
      .join("");
    // Also load fleet health in parallel
    await loadHarnessHealth();
  } catch (error) {
    renderErrorRow(byId("harnesses-body"), 6, error.message);
  }
}

async function loadHarnessHealth(harnessId) {
  try {
    if (harnessId) {
      const data = await apiFetch("harnessInstanceHealth", { agent_id: harnessId });
      const body = byId("harness-health-body");
      body.innerHTML = `
        <tr>
          <td class="cell-id">${escapeHtml(data.id)}</td>
          <td><span class="${healthPillClass(data.state)}">${escapeHtml(data.state)}</span></td>
          <td>${escapeHtml(data.message || "")}</td>
          <td>-</td>
        </tr>
      `;
    } else {
      // Load all harness health checks
      const allData = await apiFetch("harnesses");
      const body = byId("harness-health-body");
      const harnesses = asArray(allData.harnesses);
      if (!harnesses.length) {
        renderEmptyRow(body, 4, "No harness instances.");
        return;
      }
      const results = await Promise.allSettled(
        harnesses.map((h) =>
          apiFetch("harnessHealth", { harness_id: h.id })
            .then((r) => ({ ...r, id: h.id }))
            .catch((e) => ({ id: h.id, state: "error", message: e.message }))
        )
      );
      body.innerHTML = results
        .map((r) => {
          const data = r.status === "fulfilled" ? r.value : { id: "?", state: "error", message: r.reason?.message || "failed" };
          return `
            <tr>
              <td class="cell-id">${escapeHtml(data.id)}</td>
              <td><span class="${healthPillClass(data.state)}">${escapeHtml(data.state)}</span></td>
              <td>${escapeHtml(data.message || "")}</td>
              <td>-</td>
            </tr>
          `;
        })
        .join("");
    }
  } catch (error) {
    renderErrorRow(byId("harness-health-body"), 4, error.message);
  }
}

async function loadCatalog() {
  const harness = byId("catalog-harness").value;
  const type = byId("catalog-type").value;
  const body = byId("catalog-body");
  try {
    let path = buildEndpoint("catalogSurfaces", { harness });
    if (type) {
      path += `?surface_type=${encodeURIComponent(type)}`;
    }
    const data = await apiFetch(path);
    const surfaces = asArray(data.surfaces);
    if (!surfaces.length) {
      renderEmptyRow(body, 8, "No surfaces found.");
      return;
    }
    body.innerHTML = surfaces
      .map(
        (s) => `
          <tr>
            <td class="cell-id">${escapeHtml(s.id)}</td>
            <td>${escapeHtml(s.type)}</td>
            <td>${escapeHtml(s.name)}</td>
            <td><span class="pill">${escapeHtml(s.scope)}</span></td>
            <td>${escapeHtml(s.source)}</td>
            <td>${s.enabled ? "enabled" : "disabled"}</td>
            <td>${valueOrDash(s.overridden_by)}</td>
            <td>${valueOrDash(s.overrides)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 8, error.message);
  }
}

async function loadApprovalsTab() {
  try {
    const status = byId("approval-status-filter").value;
    const params = status ? { status } : {};
    const query = new URLSearchParams(params);
    const path = query.toString()
      ? `${buildEndpoint("approvals")}?${query}`
      : buildEndpoint("approvals");
    const data = await apiFetch(path);
    const body = byId("approvals-tab-body");
    const approvals = asArray(data.approvals);
    if (!approvals.length) {
      renderEmptyRow(body, 7, "No approvals.");
      return;
    }
    body.innerHTML = approvals.map(renderApprovalTabRow).join("");
  } catch (error) {
    renderErrorRow(byId("approvals-tab-body"), 7, error.message);
  }
}

function renderApprovalTabRow(approval) {
  const status = String(approval.status || "unknown");
  const isPending = status === "pending";
  return `
    <tr>
      <td class="cell-id">${escapeHtml(approval.id)}</td>
      <td>${escapeHtml(approval.agent_id)}</td>
      <td><span class="${statusPillClass(status)}">${escapeHtml(status)}</span></td>
      <td class="cell-id">
        <button type="button" class="btn-primary" data-action="select-session" data-session-id="${escapeHtml(approval.source_session_id)}">
          ${escapeHtml(approval.source_session_id)}
        </button>
      </td>
      <td class="cell-id">
        ${
          approval.approved_session_id
            ? `<button type="button" class="btn-primary" data-action="select-session" data-session-id="${escapeHtml(approval.approved_session_id)}">${escapeHtml(approval.approved_session_id)}</button>`
            : "-"
        }
      </td>
      <td>${escapeHtml(approval.reason || "")}</td>
      <td>
        <div class="actions">
          <button type="button" data-action="approve-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>approve</button>
          <button type="button" data-action="reject-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>reject</button>
        </div>
      </td>
    </tr>
  `;
}

async function loadAuditStandalone() {
  try {
    const domain = byId("audit-domain").value;
    const limit = byId("audit-limit").value;
    const params = { limit: Number(limit) };
    if (domain) params.domain = domain;
    const data = await apiFetch("auditEvents", params);
    const body = byId("audit-standalone-body");
    const events = asArray(data.events);
    if (!events.length) {
      renderEmptyRow(body, 6, "No audit events.");
      return;
    }
    body.innerHTML = events
      .map(
        (evt) => `
          <tr>
            <td>${escapeHtml(evt.id)}</td>
            <td>${escapeHtml(evt.domain)}</td>
            <td class="cell-id">${escapeHtml(evt.entity_id)}</td>
            <td>${escapeHtml(evt.event_type)}</td>
            <td class="cell-code">${escapeHtml(evt.message)}</td>
            <td>${escapeHtml(evt.created_at)}</td>
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(byId("audit-standalone-body"), 6, error.message);
  }
}

async function loadOverview() {
  // Load fleet health summary
  try {
    const healthData = await apiFetch(buildEndpoint("fleetHealth"));
    const instances = asArray(healthData.instances);
    const upCount = instances.filter((i) => i.state === "up").length;
    const downCount = instances.filter((i) => i.state === "down").length;
    byId("overview-health-body").innerHTML = `${upCount} up, ${downCount} down, ${instances.length} total`;
  } catch {
    byId("overview-health-body").textContent = "error";
  }

  // Load capacity
  try {
    const capData = await apiFetch(buildEndpoint("fleetCapacity"));
    byId("overview-capacity-body").textContent = `${capData.running_sessions}/${capData.max_running_sessions} sessions`;
  } catch {
    byId("overview-capacity-body").textContent = "error";
  }

  // Load sessions count
  try {
    const sessData = await apiFetch(buildEndpoint("sessions"));
    const sessions = asArray(sessData.sessions);
    const running = sessions.filter((s) => s.status === "running").length;
    const total = sessions.length;
    byId("overview-sessions-body").textContent = `${running} running, ${total} total`;
  } catch {
    byId("overview-sessions-body").textContent = "error";
  }

  // Load pending approvals count
  try {
    const appData = await apiFetch(`${buildEndpoint("approvals")}?status=pending`);
    const pending = asArray(appData.approvals).length;
    byId("overview-approvals-body").textContent = `${pending} pending`;
  } catch {
    byId("overview-approvals-body").textContent = "error";
  }
}

function healthPillClass(state) {
  const safe = String(state || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
  return `pill is-${safe}`;
}

function renderEmptyRow(body, colspan, message) {
  body.innerHTML = `<tr><td colspan="${colspan}">${escapeHtml(message)}</td></tr>`;
}

function renderErrorRow(body, colspan, message) {
  body.innerHTML = `<tr><td colspan="${colspan}" class="message is-error">${escapeHtml(
    message,
  )}</td></tr>`;
}

function setMessage(id, message, isError = false) {
  const target = byId(id);
  target.textContent = message;
  target.classList.toggle("is-error", isError);
}

function statusPillClass(status) {
  const safe = String(status || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
  return `pill is-${safe}`;
}

function commandPreview(command) {
  return Array.isArray(command) ? command.join(" ") : valueOrDash(command);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeCursor(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function valueOrDash(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function emptyToNull(value) {
  const trimmed = String(value || "").trim();
  return trimmed ? trimmed : null;
}

function escapeHtml(value) {
  return valueOrDash(value).replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
}

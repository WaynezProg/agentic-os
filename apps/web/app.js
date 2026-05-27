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
  sessionSummary: "/sessions/{session_id}/memory/summary",
  sessionReview: "/sessions/{session_id}/memory/review",
  memoryReview: "/memory/review",
  memoryApprove: "/memory/review/{item_id}/approve",
  memoryReject: "/memory/review/{item_id}/reject",
  memoryList: "/memory",
  memorySearch: "/memory/search",
  skills: "/skills",
  mcp: "/mcp",
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
  } else if (state.activeTab === "logs") {
    loadLogs();
  } else if (state.activeTab === "memory") {
    loadMemory();
  } else if (state.activeTab === "skills") {
    loadSkillsMcp();
  }
}

async function refreshAll() {
  await loadHealth();
  await Promise.allSettled([loadAgents(), loadSessions(), loadMemory(), loadSkillsMcp()]);
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
    throw new Error(`${response.status} ${detail}`);
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
      renderEmptyRow(body, 6, "No agents returned.");
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
          </tr>
        `,
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 6, error.message);
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
          <button type="button" data-action="logs" data-session-id="${escapeHtml(session.id)}">
            logs
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

async function loadLogs() {
  const sessionId = byId("log-session-id").value.trim();
  const stream = byId("log-stream").value;
  const afterInput = byId("log-after");
  const requestedAfter = normalizeCursor(afterInput.value);

  if (!sessionId) {
    byId("log-output").textContent = "";
    renderSessionDetail(null);
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
  await Promise.allSettled([loadSkills(), loadMcpServers()]);
}

async function loadSkills() {
  const body = byId("skills-body");
  try {
    const data = await apiFetch(buildEndpoint("skills"));
    renderRegistryRows(body, asArray(data.skills), "No skills returned.");
  } catch (error) {
    renderErrorRow(body, 3, error.message);
  }
}

async function loadMcpServers() {
  const body = byId("mcp-body");
  try {
    const data = await apiFetch(buildEndpoint("mcp"));
    renderRegistryRows(body, asArray(data.servers), "No MCP servers returned.");
  } catch (error) {
    renderErrorRow(body, 3, error.message);
  }
}

function renderRegistryRows(body, rows, emptyMessage) {
  if (rows.length === 0) {
    renderEmptyRow(body, 3, emptyMessage);
    return;
  }
  body.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td class="cell-id">${escapeHtml(row.id)}</td>
          <td>${escapeHtml(row.label)}</td>
          <td><span class="${statusPillClass(row.status)}">${escapeHtml(row.status)}</span></td>
        </tr>
      `,
    )
    .join("");
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

async function handleActionClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }

  const action = button.dataset.action;
  const sessionId = button.dataset.sessionId;
  const itemId = button.dataset.itemId;
  button.disabled = true;

  try {
    if (action === "logs" && sessionId) {
      byId("log-session-id").value = sessionId;
      resetLogState();
      showTab("logs", { skipLoad: true });
      await loadLogs();
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
      await postEmpty(buildEndpoint("sessionRetry", { session_id: sessionId }));
      setMessage("sessions-message", `retry started for ${sessionId}`);
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
    }
  } catch (error) {
    if (["approve-memory", "reject-memory", "view-summary"].includes(action)) {
      setMessage("memory-message", error.message, true);
    } else {
      setMessage("sessions-message", error.message, true);
    }
  } finally {
    button.disabled = false;
  }
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

function escapeHtml(value) {
  return valueOrDash(value).replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
}

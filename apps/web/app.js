"use strict";

const Ao = window.AgenticOs;
const DEFAULT_API_URL = Ao.DEFAULT_API_URL;
const ENDPOINTS = Ao.ENDPOINTS;
const MAX_LOG_ENTRIES = 300;

const HTML_ENTITIES = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
});

const state = {
  activeTab: "agents",
  agentsById: {},
  logEntries: [],
  logSessionId: "",
  logStream: "",
  afterCursor: 0,
  connectionProfile: null,
};

document.addEventListener("DOMContentLoaded", async () => {
  byId("api-url").value = DEFAULT_API_URL;
  await initDesktopConnection();
  if (Ao.RemoteConsole?.init) {
    await Ao.RemoteConsole.init();
  }
  if (Ao.Workspace?.init) {
    await Ao.Workspace.init();
  }
  Ao.ProductPolish?.bind?.();
  Ao.CatalogEditor.init();
  Ao.HarnessConfigEditor.init();
  Ao.ProfileEditor.init();
  Ao.RegistryEditor.init();
  Ao.ProviderSwitchboard?.init?.();
  Ao.RunTemplateLauncher?.init?.();
  Ao.DailyDashboard?.init?.();
  Ao.ControlPlaneEditor.bindEvents?.();
  Ao.ControlPlaneEditor.toggleEditorChrome();
  bindTabs();
  bindControls();
  refreshAll();
});

async function initDesktopConnection() {
  const invoke = window.__TAURI__?.core?.invoke;
  if (!invoke) {
    return;
  }
  try {
    const profile = await invoke("get_connection_profile");
    state.connectionProfile = profile;
    Ao.setConnectionProfile(profile);
    if (profile.mode === "remote") {
      byId("api-url").value = profile.api_url;
      byId("api-url").readOnly = true;
      byId("api-url").title = "Remote gateway (Bearer via desktop Keychain)";
    }
    if (Ao.RemoteConsole?.init) {
      await Ao.RemoteConsole.init();
    } else {
      Ao.ProductPolish?.toggleLocalOnlyActions?.();
    }
  } catch (error) {
    console.warn("desktop connection profile unavailable", error);
  }
}

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
  byId("run-message").addEventListener("input", updateRunCommandPreview);
  byId("run-cwd").addEventListener("input", updateRunCommandPreview);
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

Ao.showTab = showTab;

function loadActiveTab() {
  if (state.activeTab === "agents") {
    loadAgents();
    Ao.ProviderSwitchboard?.refresh?.();
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

const apiBase = Ao.apiBase;
const buildEndpoint = Ao.buildEndpoint.bind(Ao);
const apiFetch = Ao.apiFetch.bind(Ao);
const postEmpty = Ao.postEmpty.bind(Ao);
const postJson = Ao.postJson.bind(Ao);

async function loadSessionDetail(sessionId) {
  return apiFetch(buildEndpoint("sessionDetail", { session_id: sessionId }), { method: "GET" });
}

async function loadSessionSummary(sessionId) {
  return apiFetch(buildEndpoint("sessionSummary", { session_id: sessionId }), { method: "GET" });
}

async function loadHealth() {
  const status = byId("api-status");
  status.className = "status is-unknown";
  status.textContent = t("statusChecking");
  try {
    const health = await apiFetch(buildEndpoint("health"));
    status.className = "status is-ok";
    status.textContent = t("statusConnected");
    status.removeAttribute("title");
    return true;
  } catch (error) {
    status.className = "status is-error";
    status.textContent = t("statusOffline");
    status.title = error.message;
    return false;
  }
}

Ao.loadAgents = loadAgents;

async function loadAgents() {
  const body = byId("agents-body");
  try {
    const data = await apiFetch(buildEndpoint("agents"));
    const agents = asArray(data.agents);
    state.agentsById = {};
    agents.forEach((agent) => {
      state.agentsById[agent.id] = agent;
    });
    if (agents.length === 0) {
      renderEmptyRow(body, 7, t("emptyNoAgents"));
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
            <td class="cell-code">${escapeHtml(formatCommandTemplate(agent.command))}</td>
            <td>
              <button type="button" data-action="run-agent" data-agent-id="${escapeHtml(agent.id)}" ${
                agent.enabled === false ? "disabled" : ""
              }>${t("btnRun")}</button>
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
      renderEmptyRow(body, 7, t("emptyNoSessions"));
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
  const canAttach = session.attach_status === "available";
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
            ${t("btnOpen")}
          </button>
          <button type="button" data-action="logs" data-session-id="${escapeHtml(session.id)}">
            ${t("btnLogs")}
          </button>
          <button type="button" data-action="attach-preview" data-session-id="${escapeHtml(session.id)}" ${
            canAttach ? "" : "disabled"
          }>
            ${t("btnAttach")}
          </button>
          <button type="button" data-action="summarize" data-session-id="${escapeHtml(session.id)}">
            ${t("btnSummarize")}
          </button>
          <button type="button" data-action="review-create" data-session-id="${escapeHtml(session.id)}">
            ${t("btnReviewCreate")}
          </button>
          <button type="button" data-action="retry" data-session-id="${escapeHtml(session.id)}" ${
            canRetry ? "" : "disabled"
          }>
            ${t("btnRetry")}
          </button>
          <button type="button" data-action="stop" data-session-id="${escapeHtml(session.id)}" ${
            canStop ? "" : "disabled"
          }>
            ${t("btnStop")}
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
  byId("runs-selected-session").textContent = t("selectedSession", { id: sessionId });
  showTab("sessions", { skipLoad: true });
  resetLogState();
  await Promise.allSettled([loadSessionTimeline(sessionId), loadLogs()]);
}

async function loadSessionTimeline(sessionId) {
  const container = byId("session-timeline");
  if (!sessionId) {
    container.innerHTML = `<p class="message">${escapeHtml(t("emptySelectSession"))}</p>`;
    return;
  }
  try {
    const data = await apiFetch(buildEndpoint("sessionTimeline", { session_id: sessionId }));
    const timeline = asArray(data.timeline);
    if (timeline.length === 0) {
      container.innerHTML = `<p class="message">${escapeHtml(t("emptyNoTimeline"))}</p>`;
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
    setMessage("logs-message", t("enterSessionId"));
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
      t("logsLoaded", { count: entries.length, shown: state.logEntries.length }),
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
    <dt>${t("detailSession")}</dt>
    <dd class="cell-id">${escapeHtml(detail.id)}</dd>
    <dt>${t("detailAgent")}</dt>
    <dd>${escapeHtml(detail.agent_id)}</dd>
    <dt>${t("detailStatus")}</dt>
    <dd>${escapeHtml(detail.status)}</dd>
    <dt>${t("detailUpdated")}</dt>
    <dd>${escapeHtml(detail.updated_at)}</dd>
    <dt>工作目錄</dt>
    <dd class="cell-code">${escapeHtml(valueOrDash(detail.cwd))}</dd>
    <dt>啟動指令</dt>
    <dd class="cell-code">${escapeHtml(formatArgv(detail.argv))}</dd>
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
      renderEmptyRow(body, 6, t("emptyNoReview"));
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
            ${t("btnSummary")}
          </button>
          <button type="button" data-action="approve-memory" data-item-id="${escapeHtml(item.id)}" ${
            isPending ? "" : "disabled"
          }>
            ${t("btnApprove")}
          </button>
          <button type="button" data-action="reject-memory" data-item-id="${escapeHtml(item.id)}" ${
            isPending ? "" : "disabled"
          }>
            ${t("btnReject")}
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
      renderEmptyRow(body, 4, t("emptyNoMemory"));
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
  Ao.ControlPlaneEditor.toggleEditorChrome();
}

Ao.reloadControlPlaneTables = loadSkillsMcp;

function renderControlPlaneActions(domain, recordId) {
  const writable =
    Ao.RemoteConsole?.isActionAllowed?.("ui.write.control-plane") ?? Ao.isLocalWritable();
  if (!writable) {
    return "";
  }
  const historyContainer = `cp-history-${domain}-${recordId}`.replace(/[^a-zA-Z0-9_-]/g, "_");
  return `
    <td class="control-plane-action-col">
      <div class="actions">
        <button type="button" data-action="cp-edit" data-domain="${escapeHtml(domain)}" data-record-id="${escapeHtml(recordId)}">編輯</button>
        <button type="button" data-action="cp-history" data-domain="${escapeHtml(domain)}" data-record-id="${escapeHtml(recordId)}" data-history-container="${escapeHtml(historyContainer)}">歷史</button>
        ${
          domain !== "policy"
            ? `<button type="button" data-action="cp-disable" data-domain="${escapeHtml(domain)}" data-record-id="${escapeHtml(recordId)}">停用</button>`
            : ""
        }
      </div>
    </td>
  `;
}

function renderControlPlaneHistoryRow(domain, recordId, colspan) {
  const historyContainer = `cp-history-${domain}-${recordId}`.replace(/[^a-zA-Z0-9_-]/g, "_");
  return `
    <tr id="${escapeHtml(historyContainer)}" class="cp-history-row" hidden data-history-domain="${escapeHtml(domain)}" data-history-id="${escapeHtml(recordId)}">
      <td colspan="${colspan}">
        <table class="nested-table" aria-label="歷史紀錄">
          <thead>
            <tr>
              <th>patch_id</th>
              <th>target</th>
              <th>surface</th>
              <th>source</th>
              <th>建立時間</th>
              <th>還原時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="${escapeHtml(historyContainer)}-body">
            <tr><td colspan="7">載入中…</td></tr>
          </tbody>
        </table>
      </td>
    </tr>
  `;
}

async function loadSkills() {
  const body = byId("skills-body");
  try {
    const data = await apiFetch(buildEndpoint("skills"));
    const skills = asArray(data.skills);
    if (skills.length === 0) {
      renderEmptyRow(body, 9, t("emptyNoSkills"));
      return;
    }
    body.innerHTML = skills
      .flatMap(
        (skill) => [
          `
          <tr>
            <td class="cell-id">${escapeHtml(skill.id)}</td>
            <td>${escapeHtml(skill.label)}</td>
            <td>${skill.deprecated ? `<span class="pill is-deprecated">${escapeHtml(t("deprecated"))}</span>` : escapeHtml(String(skill.enabled !== false))}</td>
            <td>${escapeHtml(skill.source)}</td>
            <td>${escapeHtml(asArray(skill.tags).join(", "))}</td>
            <td>${escapeHtml(skill.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(skill.replacement_id)}</td>
            <td>${escapeHtml(skill.sunset_at)}</td>
            ${renderControlPlaneActions("skills", skill.id)}
          </tr>
        `,
          renderControlPlaneHistoryRow("skills", skill.id, 9),
        ],
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 9, error.message);
  }
}

async function loadMcpServers() {
  const body = byId("mcp-body");
  try {
    const data = await apiFetch(buildEndpoint("mcp"));
    const servers = asArray(data.servers);
    if (servers.length === 0) {
      renderEmptyRow(body, 9, t("emptyNoMcp"));
      return;
    }
    body.innerHTML = servers
      .flatMap(
        (server) => [
          `
          <tr>
            <td class="cell-id">${escapeHtml(server.id)}</td>
            <td>${escapeHtml(server.label)}</td>
            <td>${server.deprecated ? `<span class="pill is-deprecated">${escapeHtml(t("deprecated"))}</span>` : escapeHtml(String(server.enabled !== false))}</td>
            <td>${escapeHtml(server.transport)}</td>
            <td class="cell-code">${escapeHtml(asArray(server.command_preview).join(" "))}</td>
            <td>${escapeHtml(server.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(server.replacement_id)}</td>
            <td>${escapeHtml(server.sunset_at)}</td>
            ${renderControlPlaneActions("mcp", server.id)}
          </tr>
        `,
          renderControlPlaneHistoryRow("mcp", server.id, 9),
        ],
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 9, error.message);
  }
}

async function loadApprovals() {
  const body = byId("approvals-embed-body");
  try {
    const data = await apiFetch(buildEndpoint("approvals"));
    const approvals = asArray(data.approvals);
    if (approvals.length === 0) {
      renderEmptyRow(body, 6, t("emptyNoApprovals"));
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
          }>${t("btnApprove")}</button>
          <button type="button" data-action="reject-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>${t("btnReject")}</button>
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
      renderEmptyRow(body, 8, t("emptyNoPolicies"));
      return;
    }
    body.innerHTML = policies
      .flatMap(
        (policy) => [
          `
          <tr>
            <td class="cell-id">${escapeHtml(policy.agent_id)}</td>
            <td>${policy.deprecated ? `<span class="pill is-deprecated">${escapeHtml(t("deprecated"))}</span>` : escapeHtml(String(policy.enabled !== false))}</td>
            <td>${escapeHtml(policy.readonly ? t("policyReadonly") : t("policyWrite"))}</td>
            <td>${escapeHtml(policy.rate_limit_per_minute)}</td>
            <td>${escapeHtml(policy.deprecation_reason)}</td>
            <td class="cell-id">${escapeHtml(policy.replacement_id)}</td>
            <td>${escapeHtml(policy.sunset_at)}</td>
            ${renderControlPlaneActions("policy", policy.agent_id)}
          </tr>
        `,
          renderControlPlaneHistoryRow("policy", policy.agent_id, 8),
        ],
      )
      .join("");
  } catch (error) {
    renderErrorRow(body, 8, error.message);
  }
}

async function evaluatePolicy() {
  const result = byId("policy-eval-result");
  const agentId = byId("policy-eval-agent").value.trim();
  if (!agentId) {
    result.textContent = t("agentIdRequired");
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
  updateRunCommandPreview();
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
    result.textContent = t("agentMessageRequired");
    return;
  }

  byId("run-submit").disabled = true;
  try {
    const data = await apiFetch(buildEndpoint("sessionRun"), {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, cwd: cwd, message: message }),
    });
    const argvText = formatArgv(data.argv);
    result.textContent =
      argvText === "-"
        ? t("sessionCreated", { id: data.id, status: data.status })
        : t("sessionCreatedWithArgv", {
            id: data.id,
            status: data.status,
            argv: argvText,
          });
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
    renderEmptyRow(body, 4, t("emptyLoadSessionEvents"));
    return;
  }
  try {
    const data = await apiFetch(
      buildEndpoint("sessionEvents", { session_id: sessionId }),
    );
    const events = asArray(data.events);
    if (events.length === 0) {
      renderEmptyRow(body, 4, t("emptyNoEvents"));
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

  if (Ao.isDelegatedAction(action)) {
    const writable = Ao.RemoteConsole?.isActionAllowed?.("ui.write.catalog") ?? Ao.isLocalWritable();
    if (!writable) {
      return;
    }
    button.disabled = true;
    try {
      await Ao.dispatchDelegatedAction(action, button);
    } catch (error) {
      const message = document.getElementById("catalog-patch-message");
      if (message) {
        message.textContent = error.message;
        message.classList.add("is-error");
      }
    } finally {
      button.disabled = false;
    }
    return;
  }

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
    } else if (action === "view-session-events" && sessionId) {
      showTab("sessions");
      await selectSession(sessionId);
      await loadSessionTimeline(sessionId);
    } else if (action === "retry-approval-session" && sessionId) {
      await Ao.ApprovalWorkbench.retrySession(sessionId, approvalId || button.dataset.approvalId);
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
  const reason = window.prompt(t("rejectionPrompt"), "") || "";
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
      renderEmptyRow(body, 6, t("emptyNoFleetHealth"));
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
      renderEmptyRow(body, 5, t("emptyNoFleetEvents"));
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
  btn.textContent = t("probing");
  try {
    const data = await postEmpty(buildEndpoint("fleetProbe"));
    setMessage("fleet-message", t("fleetProbed", { count: data.probed }));
    await loadFleet();
  } catch (error) {
    setMessage("fleet-message", error.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = t("probeNow");
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
      renderEmptyRow(body, 6, t("emptyNoAudit"));
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
  await Ao.HarnessConfigEditor.loadEffective();
}

async function loadHarnesses() {
  try {
    const data = await apiFetch(buildEndpoint("harnesses"));
    const body = byId("harnesses-body");
    const rows = asArray(data.harnesses);
    if (!rows.length) {
      renderEmptyRow(body, 6, t("emptyNoHarnesses"));
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
              <button class="btn" onclick="loadHarnessHealth('${escapeHtml(h.id)}')">${t("btnCheck")}</button>
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
      const data = await apiFetch(buildEndpoint("harnessHealth", { harness_id: harnessId }));
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
      const allData = await apiFetch(buildEndpoint("harnesses"));
      const body = byId("harness-health-body");
      const harnesses = asArray(allData.harnesses);
      if (!harnesses.length) {
        renderEmptyRow(body, 4, t("emptyNoHarnessHealth"));
        return;
      }
      const results = await Promise.allSettled(
        harnesses.map((h) =>
          apiFetch(buildEndpoint("harnessHealth", { harness_id: h.id }))
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
  await Ao.CatalogEditor.loadCatalog();
}

async function loadApprovalsTab() {
  await Ao.ApprovalWorkbench.loadWorkbench();
  Ao.ApprovalWorkbench.connectApprovalStream();
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
      renderEmptyRow(body, 7, t("emptyNoApprovalsTab"));
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
          }>${t("btnApprove")}</button>
          <button type="button" data-action="reject-approval" data-approval-id="${escapeHtml(approval.id)}" ${
            isPending ? "" : "disabled"
          }>${t("btnReject")}</button>
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
    const query = new URLSearchParams(params);
    const data = await apiFetch(`${buildEndpoint("auditEvents")}?${query}`);
    const body = byId("audit-standalone-body");
    const events = asArray(data.events);
    if (!events.length) {
      renderEmptyRow(body, 6, t("emptyNoAudit"));
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
  if (Ao.DailyDashboard?.loadDashboard) {
    await Ao.DailyDashboard.loadDashboard();
    return;
  }
  byId("overview-health-body").textContent = t("overviewError");
  byId("overview-capacity-body").textContent = t("overviewError");
  byId("overview-sessions-body").textContent = t("overviewError");
  byId("overview-approvals-body").textContent = t("overviewError");
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
  return formatArgv(command);
}

function formatCommandTemplate(command) {
  if (!Array.isArray(command)) {
    return valueOrDash(command);
  }
  return command.map((part) => part.replace(/\{\{message\}\}/g, "…")).join(" ");
}

function renderCommandArgv(command, message) {
  if (!Array.isArray(command)) {
    return [];
  }
  return command.map((part) => part.replace(/\{\{message\}\}/g, message));
}

function formatArgv(argv) {
  return Array.isArray(argv) && argv.length > 0 ? argv.join(" ") : "-";
}

function updateRunCommandPreview() {
  const target = byId("run-command-preview");
  const agentId = byId("run-agent-id").value.trim();
  const agent = state.agentsById[agentId];
  if (!agent) {
    target.textContent = "—";
    return;
  }
  const message = byId("run-message").value;
  const cwd = byId("run-cwd").value.trim();
  const cwdLine = cwd
    ? t("runPreviewCwd", { cwd })
    : t("runPreviewCwdEmpty");
  if (!message.trim()) {
    target.textContent = `${cwdLine}\n${t("runPreviewWaitingMessage")}\n${t("runPreviewArgv", {
      argv: formatCommandTemplate(agent.command),
    })}`;
    return;
  }
  target.textContent = `${cwdLine}\n${t("runPreviewArgv", {
    argv: formatArgv(renderCommandArgv(agent.command, message)),
  })}`;
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

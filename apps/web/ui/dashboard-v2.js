/**
 * Daily Operator Dashboard v2 (P38)
 * Two-column layout: Vibe Coding (left) / Agentic Runtime (right)
 */

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initDashboardV2(Ao) {
  const VIBE_AGENT_IDS = new Set(["claude", "codex", "cursor", "opencode", "qwen", "gemini"]);

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  async function fetchJson(path) {
    try {
      return await Ao.apiFetch(path);
    } catch {
      return null;
    }
  }

  function renderQuickActions() {
    return `
      <div class="quick-actions-bar">
        <button type="button" class="btn-primary btn-sm" data-dash-tab="agents">Switch Profile</button>
        <button type="button" class="btn-primary btn-sm" data-dash-tab="approvals">Approvals</button>
        <button type="button" class="btn-primary btn-sm" data-dash-tab="vibe-coding">Launch Session</button>
        <button type="button" class="btn-primary btn-sm" data-dash-tab="sessions">Attach Session</button>
        <button type="button" class="btn-primary btn-sm" data-dash-tab="agentic">Agentic Inventory</button>
      </div>
    `;
  }

  async function loadLiveSessions() {
    const data = await fetchJson(`${Ao.buildEndpoint("liveSessions")}?within_hours=24&limit=20`);
    return { sessions: data?.sessions || [], errors: data?.errors || [] };
  }

  function relativeTime(iso) {
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return iso || "-";
    const minutes = Math.round((Date.now() - then) / 60000);
    if (minutes < 1) return "now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }

  function renderLiveSessionRow(session) {
    const wsParts = String(session.workspace || "").split("/").filter(Boolean);
    const wsName = wsParts.length ? wsParts[wsParts.length - 1] : session.workspace;
    return `<tr class="live-session-row" data-log-path="${escapeHtml(session.log_path)}" data-row-tool="${escapeHtml(session.tool)}">
      <td><span class="live-dot ${session.active ? "live-dot-active" : "live-dot-idle"}"></span></td>
      <td><span class="tool-badge tool-badge-${escapeHtml(session.tool)}">${escapeHtml(session.tool)}</span></td>
      <td title="${escapeHtml(session.workspace)}">${escapeHtml(wsName)}</td>
      <td class="live-title" data-transcript-toggle title="點擊預覽對話：${escapeHtml(session.title)}">${escapeHtml(session.title)}</td>
      <td>${escapeHtml(relativeTime(session.last_activity_at))}</td>
      <td class="live-actions">
        <button type="button" class="btn-sm" data-resume-command="${escapeHtml(session.resume_command)}">Copy resume</button>
        <button type="button" class="btn-sm" data-open-terminal data-tool="${escapeHtml(session.tool)}"
          data-session-id="${escapeHtml(session.session_id)}" data-workspace="${escapeHtml(session.workspace)}">Terminal</button>
      </td>
    </tr>`;
  }

  async function loadTranscript(tool, logPath) {
    const params = new URLSearchParams({ tool, log_path: logPath, limit: "20" });
    return Ao.apiFetch(`${Ao.buildEndpoint("liveTranscript")}?${params.toString()}`);
  }

  function renderTranscriptMessages(data) {
    const messages = data?.messages || [];
    if (messages.length === 0) {
      return '<p class="muted">這個 session 沒有可預覽的對話。</p>';
    }
    return messages
      .map(
        (message) => `<div class="transcript-msg transcript-msg-${escapeHtml(message.role)}">
          <span class="transcript-role">${message.role === "user" ? "你" : "AI"}</span>
          <span class="transcript-text">${escapeHtml(message.text)}</span>
        </div>`,
      )
      .join("");
  }

  function bindTranscriptToggles(container) {
    container.querySelectorAll("[data-transcript-toggle]").forEach((cell) => {
      cell.addEventListener("click", async () => {
        const row = cell.closest("tr");
        if (!row) return;
        const existing = row.nextElementSibling;
        if (existing && existing.classList.contains("transcript-row")) {
          existing.remove();
          return;
        }
        const panel = document.createElement("tr");
        panel.className = "transcript-row";
        panel.innerHTML = '<td colspan="6"><div class="transcript-panel loading">載入對話中…</div></td>';
        row.insertAdjacentElement("afterend", panel);
        try {
          const data = await loadTranscript(row.dataset.rowTool, row.dataset.logPath);
          panel.innerHTML = `<td colspan="6"><div class="transcript-panel">${renderTranscriptMessages(data)}</div></td>`;
        } catch (error) {
          panel.innerHTML = `<td colspan="6"><div class="transcript-panel error-text">對話載入失敗：${escapeHtml(error.message)}</div></td>`;
        }
      });
    });
  }

  function renderLiveSessionsCard(live) {
    const activeCount = live.sessions.filter((session) => session.active).length;
    let html = '<div class="dash-card" id="live-sessions-card">';
    html += `<h4>Live Sessions <span class="muted">(real · ${activeCount} active)</span>
      <button type="button" class="btn-sm" id="live-sessions-refresh" title="Refresh">↻</button></h4>`;
    if (live.sessions.length === 0) {
      html += '<p class="muted">No claude/codex sessions in the last 24h.</p>';
    } else {
      html += '<table class="session-table live-session-table"><tbody>';
      html += live.sessions.map(renderLiveSessionRow).join("");
      html += "</tbody></table>";
    }
    if (live.errors.length > 0) {
      html += `<p class="inventory-err">⚠ ${escapeHtml(
        live.errors.map((entry) => `${entry.tool}: ${entry.error}`).join("; "),
      )}</p>`;
    }
    html += "</div>";
    return html;
  }

  function bindLiveSessionActions(container) {
    container.querySelectorAll("[data-resume-command]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(button.dataset.resumeCommand);
          button.textContent = "Copied ✓";
        } catch {
          window.prompt("Copy resume command:", button.dataset.resumeCommand);
        }
        setTimeout(() => {
          button.textContent = "Copy resume";
        }, 1500);
      });
    });
    container.querySelectorAll("[data-open-terminal]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await Ao.postJson(Ao.buildEndpoint("liveOpenTerminal"), {
            tool: button.dataset.tool,
            session_id: button.dataset.sessionId,
            workspace: button.dataset.workspace,
          });
          button.textContent = "Opened ✓";
        } catch (error) {
          button.textContent = "Failed";
          console.error("open-terminal failed", error);
        }
        setTimeout(() => {
          button.textContent = "Terminal";
        }, 1500);
      });
    });
    const refresh = container.querySelector("#live-sessions-refresh");
    if (refresh) refresh.addEventListener("click", () => loadDashboardV2());
  }

  async function loadVibeCodingColumn() {
    const [sessionsData, templatesData, agentsData] = await Promise.all([
      Ao.DataCache.get("sessions", () => fetchJson(Ao.buildEndpoint("sessions")), 1000),
      fetchJson(`${Ao.buildEndpoint("runTemplates")}${cwdQuery()}`),
      fetchJson(`${Ao.buildEndpoint("agents")}?tool_kind=vibe_coding`),
    ]);

    const vibeAgentIds = new Set(
      (agentsData?.agents || []).map((agent) => agent.id).concat([...VIBE_AGENT_IDS]),
    );
    const sessions = sessionsData?.sessions || [];
    const vibeSessions = sessions.filter((session) => vibeAgentIds.has(session.agent_id));
    const recentSessions = vibeSessions.slice(0, 10);
    const failedSessions = vibeSessions.filter((session) => session.status === "failed");
    const templates = templatesData?.templates || [];

    return { recentSessions, failedSessions, templates };
  }

  function cwdQuery() {
    const cwd = Ao.Workspace?.getActiveCwd?.() || "";
    return cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
  }

  async function loadAgenticColumn() {
    const [inventoryData, approvalsData, sessionsData] = await Promise.all([
      fetchJson(Ao.buildEndpoint("agenticInventory")),
      Ao.DataCache.get(
        "approvals-pending",
        () => fetchJson(`${Ao.buildEndpoint("approvals")}?status=pending`),
        1000,
      ),
      Ao.DataCache.get("sessions", () => fetchJson(Ao.buildEndpoint("sessions")), 1000),
    ]);

    const inventory = inventoryData?.agents || [];
    const pendingApprovals = approvalsData?.approvals || [];
    const attachedSessions = (sessionsData?.sessions || []).filter(
      (session) => session.external_session_id && session.attach_status !== "unsupported",
    );

    return { inventory, pendingApprovals, attachedSessions };
  }

  function renderSessionRow(session) {
    const message = Array.isArray(session.argv) ? session.argv.join(" ") : "";
    return `<tr>
      <td><span class="pill status-${escapeHtml(session.status)}">${escapeHtml(session.status)}</span></td>
      <td>${escapeHtml(session.agent_id)}</td>
      <td>${escapeHtml(message.slice(0, 40))}</td>
      <td>${escapeHtml(session.started_at || "-")}</td>
    </tr>`;
  }

  function renderVibeCodingColumn(data, live) {
    const { recentSessions, failedSessions, templates } = data;

    let html = '<div class="dashboard-column" id="vibe-column">';
    html += "<h3>Vibe Coding</h3>";

    html += renderLiveSessionsCard(live);

    html += '<div class="dash-card">';
    html += "<h4>Managed Runs</h4>";
    if (recentSessions.length === 0) {
      html += '<p class="muted">No sessions yet</p>';
    } else {
      html +=
        '<table class="session-table"><thead><tr><th>Status</th><th>Agent</th><th>Message</th><th>Started</th></tr></thead><tbody>';
      html += recentSessions.map(renderSessionRow).join("");
      html += "</tbody></table>";
    }
    html += '<button type="button" class="btn-primary btn-sm" data-dash-tab="vibe-coding">Launch New</button>';
    html += "</div>";

    if (failedSessions.length > 0) {
      html += '<div class="dash-card dash-card-warn">';
      html += `<h4>Failed (${failedSessions.length})</h4>`;
      html += '<table class="session-table"><tbody>';
      html += failedSessions.slice(0, 5).map(renderSessionRow).join("");
      html += "</tbody></table>";
      html += "</div>";
    }

    if (templates.length > 0) {
      html += '<div class="dash-card">';
      html += '<h4>Templates</h4><ul class="template-list">';
      html += templates
        .slice(0, 5)
        .map(
          (template) =>
            `<li><strong>${escapeHtml(template.name || template.id)}</strong>
              <button type="button" class="btn-sm" data-dash-tab="agents">Launch</button></li>`,
        )
        .join("");
      html += "</ul></div>";
    }

    html += "</div>";
    return html;
  }

  function renderAgenticColumn(data) {
    const { inventory, pendingApprovals, attachedSessions } = data;

    let html = '<div class="dashboard-column" id="agentic-column">';
    html += "<h3>Agentic Runtime</h3>";

    html += '<div class="dash-card">';
    html += "<h4>Inventory</h4>";
    if (inventory.length === 0) {
      html += '<p class="muted">No agentic agents found</p>';
    } else {
      html += '<ul class="inventory-summary-list">';
      html += inventory
        .map((agent) => {
          const skillCount = (agent.skills || []).length;
          const toolCount = (agent.tools || []).length;
          const flowCount = (agent.flows || []).length;
          return `<li>
            <strong>${escapeHtml(agent.agent_id)}</strong>
            <span class="inventory-stats">${skillCount} skills, ${toolCount} tools${flowCount ? `, ${flowCount} flows` : ""}</span>
            ${agent.error ? `<span class="inventory-err">⚠ ${escapeHtml(agent.error)}</span>` : ""}
          </li>`;
        })
        .join("");
      html += "</ul>";
    }
    html += '<button type="button" class="btn-primary btn-sm" data-dash-tab="agentic">View Details</button>';
    html += "</div>";

    html += '<div class="dash-card">';
    html += "<h4>Attached Sessions</h4>";
    if (attachedSessions.length === 0) {
      html += '<p class="muted">No attached sessions</p>';
    } else {
      html += '<ul class="session-list">';
      html += attachedSessions
        .slice(0, 5)
        .map(
          (session) =>
            `<li><span class="pill status-${escapeHtml(session.status)}">${escapeHtml(session.status)}</span>
              <strong>${escapeHtml(session.agent_id)}</strong>
              <code>${escapeHtml(session.external_session_id || "")}</code></li>`,
        )
        .join("");
      html += "</ul>";
    }
    html += '<button type="button" class="btn-sm" data-dash-tab="sessions">Scan Sessions</button>';
    html += "</div>";

    if (pendingApprovals.length > 0) {
      html += '<div class="dash-card dash-card-warn">';
      html += `<h4>Pending Approvals (${pendingApprovals.length})</h4>`;
      html += '<ul class="approval-list">';
      html += pendingApprovals
        .slice(0, 5)
        .map(
          (approval) =>
            `<li>${escapeHtml(approval.agent_id || "unknown")} — ${escapeHtml(approval.action || "")}</li>`,
        )
        .join("");
      html += "</ul>";
      html += '<button type="button" class="btn-sm" data-dash-tab="approvals">Review</button>';
      html += "</div>";
    }

    html += "</div>";
    return html;
  }

  function bindQuickActions(container) {
    container.querySelectorAll("[data-dash-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        Ao.showTab(button.dataset.dashTab);
      });
    });
  }

  async function loadDashboardV2() {
    const layout = byId("dashboard-v2-layout");
    const leftContainer = byId("dashboard-v2-left");
    const rightContainer = byId("dashboard-v2-right");
    if (!layout || !leftContainer || !rightContainer) return;

    layout.innerHTML = renderQuickActions();
    leftContainer.innerHTML = '<p class="loading">Loading...</p>';
    rightContainer.innerHTML = '<p class="loading">Loading...</p>';

    const [vibeData, agenticData, liveData] = await Promise.all([
      loadVibeCodingColumn(),
      loadAgenticColumn(),
      loadLiveSessions(),
    ]);

    leftContainer.innerHTML = renderVibeCodingColumn(vibeData, liveData);
    rightContainer.innerHTML = renderAgenticColumn(agenticData);
    bindQuickActions(layout);
    bindQuickActions(leftContainer);
    bindQuickActions(rightContainer);
    bindLiveSessionActions(leftContainer);
    bindTranscriptToggles(leftContainer);
  }

  function init() {
    document.addEventListener("click", (event) => {
      const button = event.target.closest("#dashboard-v2 [data-dash-tab]");
      if (!button) return;
      Ao.showTab(button.dataset.dashTab);
    });
  }

  Ao.DashboardV2 = { init, loadDashboardV2 };
})(window.AgenticOs);

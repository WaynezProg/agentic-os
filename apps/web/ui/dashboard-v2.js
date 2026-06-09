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

  async function loadVibeCodingColumn() {
    const [sessionsData, templatesData, agentsData] = await Promise.all([
      fetchJson(Ao.buildEndpoint("sessions")),
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
      fetchJson(`${Ao.buildEndpoint("approvals")}?status=pending`),
      fetchJson(Ao.buildEndpoint("sessions")),
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

  function renderVibeCodingColumn(data) {
    const { recentSessions, failedSessions, templates } = data;

    let html = '<div class="dashboard-column" id="vibe-column">';
    html += "<h3>Vibe Coding</h3>";

    html += '<div class="dash-card">';
    html += "<h4>Recent Sessions</h4>";
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

    const [vibeData, agenticData] = await Promise.all([
      loadVibeCodingColumn(),
      loadAgenticColumn(),
    ]);

    leftContainer.innerHTML = renderVibeCodingColumn(vibeData);
    rightContainer.innerHTML = renderAgenticColumn(agenticData);
    bindQuickActions(layout);
    bindQuickActions(leftContainer);
    bindQuickActions(rightContainer);
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

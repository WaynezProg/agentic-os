/**
 * Agentic Runtime Inventory UI (P37)
 * Read-only display of skills/MCP/tools/flows for agentic agents.
 */

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initAgenticInventory(Ao) {
  function escapeHtml(value) {
    if (value === null || value === undefined || value === "") return "-";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderSurfaceList(items, emptyLabel) {
    if (!items || items.length === 0) {
      return `<p class="muted">${escapeHtml(emptyLabel)}</p>`;
    }
    return `<ul class="inventory-list">${items
      .map((item) => {
        const enabled =
          item.enabled === true
            ? '<span class="badge badge-ok">enabled</span>'
            : item.enabled === false
              ? '<span class="badge badge-off">disabled</span>'
              : "";
        const detail = item.detail ? `<span class="inventory-source">${escapeHtml(item.detail)}</span>` : "";
        return `<li><span class="inventory-name">${escapeHtml(item.identifier)}</span>${enabled}${detail}</li>`;
      })
      .join("")}</ul>`;
  }

  function renderMcpList(servers) {
    if (!servers || servers.length === 0) {
      return '<p class="muted">No MCP servers</p>';
    }
    return `<ul class="inventory-list">${servers
      .map(
        (server) =>
          `<li><span class="inventory-name">${escapeHtml(server.identifier)}</span>
            <span class="badge badge-warn">${escapeHtml(server.status || "unknown")}</span></li>`,
      )
      .join("")}</ul>`;
  }

  function renderAgentCard(agent) {
    const errorHtml = agent.error
      ? `<div class="inventory-error">⚠ ${escapeHtml(agent.error)}</div>`
      : "";

    return `
      <div class="inventory-card">
        <h4>${escapeHtml(agent.agent_id)}
          <span class="badge badge-agentic">${escapeHtml(agent.tool_kind || "agentic_runtime")}</span>
        </h4>
        ${errorHtml}
        <div class="inventory-section">
          <h5>Skills (${(agent.skills || []).length})</h5>
          ${renderSurfaceList(agent.skills, "No skills found")}
        </div>
        <div class="inventory-section">
          <h5>MCP Servers (${(agent.mcp_servers || []).length})</h5>
          ${renderMcpList(agent.mcp_servers)}
        </div>
        <div class="inventory-section">
          <h5>Tools (${(agent.tools || []).length})</h5>
          ${renderSurfaceList(agent.tools, "No tools found")}
        </div>
        <div class="inventory-section">
          <h5>Flows (${(agent.flows || []).length})</h5>
          ${renderSurfaceList(agent.flows, "No workflows found")}
        </div>
      </div>
    `;
  }

  async function render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading agentic inventory...</p>';

    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("agenticInventory"));
      const agents = data.agents || [];

      if (agents.length === 0) {
        container.innerHTML = "<p>No agentic runtime agents found.</p>";
        return;
      }

      container.innerHTML = `<div class="inventory-grid">${agents.map(renderAgentCard).join("")}</div>`;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load inventory: ${escapeHtml(err.message)}</p>`;
    }
  }

  Ao.AgenticInventory = { render };
})(window.AgenticOs);

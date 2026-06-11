/**
 * Tool Discovery UI (P34)
 * Read-only display of installed tools and their config summaries.
 */

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initToolDiscovery(Ao) {
  function escapeHtml(value) {
    if (value === null || value === undefined || value === "") return "-";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toolKindBadge(kind) {
    if (kind === "vibe_coding") {
      return '<span class="badge badge-vibe">Vibe Coding</span>';
    }
    if (kind === "agentic_runtime") {
      return '<span class="badge badge-agentic">Agentic</span>';
    }
    return '<span class="badge">Unknown</span>';
  }

  function installedIcon(installed) {
    return installed
      ? '<span class="status-ok" title="Installed">✓</span>'
      : '<span class="status-error" title="Not installed">✗</span>';
  }

  function renderRow(tool, inventory) {
    const inv = inventory || {};
    const model = inv.model || "—";
    const provider = inv.provider || "—";
    const configSource = inv.config_source || "—";
    const parseError = inv.parse_error
      ? `<div class="error-text" title="${escapeHtml(inv.parse_error)}">⚠ config error</div>`
      : "";

    return `
      <tr>
        <td>${installedIcon(tool.installed)}</td>
        <td><strong>${escapeHtml(tool.agent_id)}</strong></td>
        <td>${toolKindBadge(tool.tool_kind)}</td>
        <td>${escapeHtml(tool.version) || "—"}</td>
        <td><code>${escapeHtml(configSource)}</code></td>
        <td>${escapeHtml(model)}</td>
        <td>${escapeHtml(provider)}</td>
        <td>${parseError}</td>
      </tr>
    `;
  }

  function nameChips(names, max) {
    const shown = names.slice(0, max);
    let html = shown
      .map((name) => `<span class="cap-chip">${escapeHtml(name)}</span>`)
      .join("");
    if (names.length > max) {
      html += `<span class="cap-chip cap-chip-more">+${names.length - max}</span>`;
    }
    return html || '<span class="muted">—</span>';
  }

  function renderCapabilityCard(entry) {
    if (!entry.present) {
      return `<div class="capability-card capability-card-missing">
        <h4>${escapeHtml(entry.tool)}</h4>
        <p class="muted">未安裝</p>
      </div>`;
    }
    const memory = (entry.memory_files || [])
      .map(
        (file) =>
          `<div class="cap-memory" title="${escapeHtml(file.path)}">
            <code>${escapeHtml(file.path.split("/").pop())}</code>
            <span class="muted">${(file.size_bytes / 1024).toFixed(1)}KB · ${escapeHtml(
              (file.modified_at || "").slice(0, 10),
            )}</span>
          </div>`,
      )
      .join("");
    const error = entry.error
      ? `<div class="error-text" title="${escapeHtml(entry.error)}">⚠ 部分讀取失敗</div>`
      : "";
    return `<div class="capability-card">
      <h4>${escapeHtml(entry.tool)}</h4>
      <div class="cap-row"><span class="cap-label">skills ${entry.skills.length}</span>${nameChips(entry.skills, 8)}</div>
      <div class="cap-row"><span class="cap-label">MCP ${entry.mcp_servers.length}</span>${nameChips(entry.mcp_servers, 8)}</div>
      <div class="cap-row"><span class="cap-label">plugins ${entry.plugins.length}</span>${nameChips(entry.plugins, 8)}</div>
      <div class="cap-row"><span class="cap-label">記憶</span>${memory || '<span class="muted">—</span>'}</div>
      ${error}
    </div>`;
  }

  function renderCapabilities(tools) {
    let html = '<h3 class="capability-heading">Capabilities（真實設定）</h3>';
    html += '<div class="capability-grid">';
    html += tools.map(renderCapabilityCard).join("");
    html += "</div>";
    return html;
  }

  async function render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading tools...</p>';

    try {
      const [discoveryRes, inventoryRes, capabilitiesRes] = await Promise.all([
        Ao.apiFetch(Ao.buildEndpoint("toolsDiscovery")),
        Ao.apiFetch(Ao.buildEndpoint("toolsInventory")),
        Ao.apiFetch(Ao.buildEndpoint("toolCapabilities")).catch(() => null),
      ]);

      const discovery = discoveryRes.tools || [];
      const inventory = inventoryRes.tools || [];

      // Build inventory lookup by agent_id
      const invMap = {};
      for (const inv of inventory) {
        invMap[inv.agent_id] = inv;
      }

      if (discovery.length === 0) {
        container.innerHTML = "<p>No tools found in registry.</p>";
        return;
      }

      // Separate by tool_kind
      const vibe = discovery.filter((t) => t.tool_kind === "vibe_coding");
      const agentic = discovery.filter((t) => t.tool_kind === "agentic_runtime");
      const other = discovery.filter(
        (t) => t.tool_kind !== "vibe_coding" && t.tool_kind !== "agentic_runtime"
      );

      let html = '<table class="tool-discovery-table">';
      html += "<thead><tr>";
      html += "<th></th><th>Tool</th><th>Kind</th><th>Version</th>";
      html += "<th>Config Source</th><th>Model</th><th>Provider</th><th></th>";
      html += "</tr></thead><tbody>";

      if (vibe.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Vibe Coding</strong> (${vibe.length})</td></tr>`;
        for (const tool of vibe) {
          html += renderRow(tool, invMap[tool.agent_id]);
        }
      }

      if (agentic.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Agentic Runtime</strong> (${agentic.length})</td></tr>`;
        for (const tool of agentic) {
          html += renderRow(tool, invMap[tool.agent_id]);
        }
      }

      if (other.length > 0) {
        html += `<tr class="section-header"><td colspan="8"><strong>Other</strong> (${other.length})</td></tr>`;
        for (const tool of other) {
          html += renderRow(tool, invMap[tool.agent_id]);
        }
      }

      html += "</tbody></table>";
      if (capabilitiesRes?.tools?.length) {
        html += renderCapabilities(capabilitiesRes.tools);
      }
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load tools: ${err.message}</p>`;
    }
  }

  Ao.ToolDiscovery = { render };
})(window.AgenticOs);

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

  async function render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading tools...</p>';

    try {
      const apiBase = Ao.apiBase;
      const [discoveryRes, inventoryRes] = await Promise.all([
        fetch(`${apiBase}/tools/discovery`).then((r) => r.json()),
        fetch(`${apiBase}/tools/inventory`).then((r) => r.json()),
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
      container.innerHTML = html;
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load tools: ${err.message}</p>`;
    }
  }

  Ao.ToolDiscovery = { render };
})(window.AgenticOs);

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

  function renderMcpMatrix(matrix) {
    const tools = matrix.tools || [];
    const servers = matrix.servers || [];
    let html = '<h3 class="capability-heading">MCP 對齊矩陣</h3>';
    if (servers.length === 0) {
      return html + '<p class="muted">沒有發現任何 MCP server 設定。</p>';
    }
    html += '<table class="mcp-matrix-table"><thead><tr><th>server</th>';
    html += tools.map((tool) => `<th>${escapeHtml(tool)}</th>`).join("");
    html += "</tr></thead><tbody>";
    for (const server of servers) {
      const present = tools.filter((tool) => server.tools[tool]);
      const drift = present.length > 0 && present.length < tools.length;
      html += `<tr class="${drift ? "mcp-drift" : ""}"><td><code>${escapeHtml(server.name)}</code></td>`;
      for (const tool of tools) {
        if (server.tools[tool]) {
          html += `<td class="mcp-cell mcp-cell-yes">✓
            <button type="button" class="btn-sm mcp-cell-action" title="從 ${escapeHtml(tool)} 移除"
              data-mcp-remove data-server="${escapeHtml(server.name)}" data-tool="${escapeHtml(tool)}">✕</button></td>`;
        } else {
          const sources = present.join(",");
          html += `<td class="mcp-cell mcp-cell-no">—
            ${present.length ? `<button type="button" class="btn-sm mcp-cell-action" title="複製到 ${escapeHtml(tool)}"
              data-mcp-copy data-server="${escapeHtml(server.name)}" data-to="${escapeHtml(tool)}"
              data-sources="${escapeHtml(sources)}">＋</button>` : ""}</td>`;
        }
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    html += '<div id="mcp-confirm" class="mcp-confirm" hidden></div>';
    return html;
  }

  async function activeToolWarning(tool) {
    try {
      const data = await Ao.apiFetch(`${Ao.buildEndpoint("liveSessions")}?within_hours=1&limit=50`);
      const active = (data?.sessions || []).filter((s) => s.active && s.tool === tool).length;
      return active > 0
        ? `<p class="error-text">⚠ ${escapeHtml(tool)} 目前有 ${active} 個 active session — 它可能會覆寫剛寫入的設定。</p>`
        : "";
    } catch {
      return "";
    }
  }

  function summaryHtml(summary) {
    const fields = (summary?.fields || []).map((f) => `<code>${escapeHtml(f)}</code>`).join(" ");
    return `<p>transport：<code>${escapeHtml(summary?.transport || "-")}</code>　欄位：${fields || "-"}　<span class="muted">（值不顯示，僅鍵名）</span></p>`;
  }

  async function runMcpAction(container, payload, isCopy) {
    const endpoint = isCopy ? "mcpCopy" : "mcpRemove";
    const confirmBox = container.querySelector("#mcp-confirm");
    if (!confirmBox) return;
    confirmBox.hidden = false;
    confirmBox.innerHTML = '<p class="loading">dry-run 檢查中…</p>';
    let dry;
    try {
      dry = await Ao.postJson(Ao.buildEndpoint(endpoint), { ...payload, dry_run: true });
    } catch (error) {
      confirmBox.innerHTML = `<p class="error-text">無法執行：${escapeHtml(error.message)}</p>
        <button type="button" class="btn-sm" data-mcp-cancel>關閉</button>`;
      bindConfirmButtons(container, null, null);
      return;
    }
    const warning = await activeToolWarning(isCopy ? payload.to_tool : payload.tool);
    const title = isCopy
      ? `複製 <code>${escapeHtml(payload.server)}</code>：${escapeHtml(payload.from_tool)} → ${escapeHtml(payload.to_tool)}`
      : `從 ${escapeHtml(payload.tool)} 移除 <code>${escapeHtml(payload.server)}</code>`;
    confirmBox.innerHTML = `<h4>${title}</h4>
      ${summaryHtml(dry.summary)}
      <p class="muted">寫入前會自動備份；可由 patches 介面回滾。backup：<code>${escapeHtml(dry.backup_path || "-")}</code></p>
      ${warning}
      <button type="button" class="btn-primary btn-sm" data-mcp-apply>確認寫入</button>
      <button type="button" class="btn-sm" data-mcp-cancel>取消</button>`;
    bindConfirmButtons(container, dry.change_id);
    if (dry.change_id) {
      Ao.ChangeCenter?.open?.(dry.change_id)?.catch((error) => {
        console.warn("change center unavailable", error);
      });
    }
  }

  function bindConfirmButtons(container, changeId) {
    const confirmBox = container.querySelector("#mcp-confirm");
    confirmBox.querySelector("[data-mcp-cancel]")?.addEventListener("click", () => {
      confirmBox.hidden = true;
      confirmBox.innerHTML = "";
    });
    confirmBox.querySelector("[data-mcp-apply]")?.addEventListener("click", async () => {
      confirmBox.innerHTML = '<p class="loading">寫入中…</p>';
      try {
        const result = await Ao.postEmpty(
          Ao.buildEndpoint("changeApply", { change_id: changeId }),
        );
        confirmBox.innerHTML = `<p class="status-ok">完成 ✓ patch：<code>${escapeHtml(result.backup_ref)}</code></p>`;
        setTimeout(() => render("tool-discovery-container"), 900);
      } catch (error) {
        confirmBox.innerHTML = `<p class="error-text">寫入失敗：${escapeHtml(error.message)}</p>
          <button type="button" class="btn-sm" data-mcp-cancel>關閉</button>`;
        bindConfirmButtons(container, null, null);
      }
    });
  }

  function bindMatrixActions(container) {
    container.querySelectorAll("[data-mcp-copy]").forEach((button) => {
      button.addEventListener("click", () => {
        const sources = (button.dataset.sources || "").split(",").filter(Boolean);
        const fromTool = sources.length === 1
          ? sources[0]
          : window.prompt(`從哪個工具複製？（${sources.join(" / ")}）`, sources[0]);
        if (!fromTool || !sources.includes(fromTool)) return;
        runMcpAction(
          container,
          { server: button.dataset.server, from_tool: fromTool, to_tool: button.dataset.to },
          true,
        );
      });
    });
    container.querySelectorAll("[data-mcp-remove]").forEach((button) => {
      button.addEventListener("click", () => {
        runMcpAction(
          container,
          { tool: button.dataset.tool, server: button.dataset.server },
          false,
        );
      });
    });
  }

  async function render(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading tools...</p>';

    try {
      const [discoveryRes, inventoryRes, capabilitiesRes, matrixRes] = await Promise.all([
        Ao.apiFetch(Ao.buildEndpoint("toolsDiscovery")),
        Ao.apiFetch(Ao.buildEndpoint("toolsInventory")),
        Ao.apiFetch(Ao.buildEndpoint("toolCapabilities")).catch(() => null),
        Ao.apiFetch(Ao.buildEndpoint("mcpMatrix")).catch(() => null),
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
      if (matrixRes) {
        html += renderMcpMatrix(matrixRes);
      }
      container.innerHTML = html;
      bindMatrixActions(container);
    } catch (err) {
      container.innerHTML = `<p class="error-text">Failed to load tools: ${err.message}</p>`;
    }
  }

  Ao.ToolDiscovery = { render };
})(window.AgenticOs);

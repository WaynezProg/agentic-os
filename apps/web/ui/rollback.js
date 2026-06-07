"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initPatchRollback(Ao) {
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

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function renderEmptyRow(body, colspan, message) {
    body.innerHTML = `<tr><td colspan="${colspan}">${escapeHtml(message)}</td></tr>`;
  }

  function renderErrorRow(body, colspan, message) {
    body.innerHTML = `<tr><td colspan="${colspan}" class="message is-error">${escapeHtml(message)}</td></tr>`;
  }

  async function rollbackPatch(patchIdOrPath, source) {
    if (typeof patchIdOrPath === "string" && patchIdOrPath.startsWith("/")) {
      const query = source ? `?source=${encodeURIComponent(source)}` : "";
      return Ao.postEmpty(`${patchIdOrPath}${query}`);
    }
    const patchId = patchIdOrPath;
    const query = source ? `?source=${encodeURIComponent(source)}` : "";
    return Ao.postEmpty(`${Ao.buildEndpoint("patchRollback", { patch_id: patchId })}${query}`);
  }

  function renderPatchRow(patch, options) {
    const rolledBack = Boolean(patch.rolled_back_at);
    const canRollback = options.canRollback !== false && !rolledBack;
    const rollbackPath = options.rollbackPathFn ? options.rollbackPathFn(patch) : null;
    const action = rollbackPath ? "control-plane-rollback" : "patch-rollback";
    const rollbackAttrs = rollbackPath
      ? `data-rollback-path="${escapeHtml(rollbackPath)}"`
      : `data-patch-id="${escapeHtml(patch.patch_id)}"`;
    return `
      <tr>
        <td class="cell-id">${escapeHtml(patch.patch_id)}</td>
        <td>${escapeHtml(patch.target_kind)}</td>
        <td class="cell-code">${escapeHtml(patch.surface_id || patch.target_path || "")}</td>
        <td>${escapeHtml(patch.source)}</td>
        <td>${escapeHtml(patch.created_at)}</td>
        <td>${rolledBack ? escapeHtml(patch.rolled_back_at) : "-"}</td>
        <td>
          <button
            type="button"
            id="patch-rollback-${escapeHtml(patch.patch_id)}"
            data-action="${action}"
            ${rollbackAttrs}
            ${canRollback ? "" : "disabled"}
          >還原</button>
        </td>
      </tr>
    `;
  }

  async function loadPatchHistory(options) {
    const {
      harness,
      historyPath,
      rollbackPathFn,
      containerId = "patch-history-body",
      limit = 50,
      emptyMessage = "尚無修補紀錄。",
      canRollback = true,
    } = options;
    const body = document.getElementById(containerId);
    if (!body) {
      return;
    }
    try {
      let data;
      if (historyPath) {
        const params = new URLSearchParams({ limit: String(limit) });
        const separator = historyPath.includes("?") ? "&" : "?";
        data = await Ao.apiFetch(`${historyPath}${separator}${params}`);
      } else {
        const params = new URLSearchParams({ limit: String(limit) });
        if (harness) {
          params.set("harness", harness);
        }
        data = await Ao.apiFetch(`${Ao.buildEndpoint("patches")}?${params}`);
      }
      const patches = asArray(data.patches);
      if (!patches.length) {
        renderEmptyRow(body, 7, emptyMessage);
        return;
      }
      body.innerHTML = patches
        .map((patch) => renderPatchRow(patch, { canRollback, rollbackPathFn }))
        .join("");
    } catch (error) {
      renderErrorRow(body, 7, error.message);
    }
  }

  Ao.PatchRollback = {
    loadPatchHistory,
    rollbackPatch,
    renderPatchRow,
  };
})(window.AgenticOs);

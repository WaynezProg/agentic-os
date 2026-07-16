"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initCatalogEditor(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  const PATCH_SOURCE = "web-catalog-editor";

  let pendingOps = null;
  let pendingChangeId = null;
  let enableTarget = null;

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function valueOrDash(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    return String(value);
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Missing element: ${id}`);
    }
    return element;
  }

  function setEditorMessage(message, isError = false) {
    const target = byId("catalog-patch-message");
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function setPendingOps(ops) {
    pendingOps = ops;
    pendingChangeId = null;
    const hasPending = Array.isArray(ops) && ops.length > 0;
    const dryRunBtn = byId("catalog-dry-run");
    const applyBtn = byId("catalog-apply");
    dryRunBtn.disabled = !hasPending;
    applyBtn.disabled = true;
    if (!hasPending) {
      byId("catalog-diff-preview").textContent = "選擇 MCP 變更後按「預覽變更」。";
    }
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.catalog") ?? Ao.isLocalWritable();
  }

  function withWorkspaceCwd(path) {
    if (Ao.Workspace?.appendCwdQuery) {
      return Ao.Workspace.appendCwdQuery(path);
    }
    return path;
  }

  function toggleEditorChrome() {
    const writable = isWritable();
    const controls = byId("catalog-editor-controls");
    const history = byId("catalog-patch-history");
    const future = byId("catalog-future-surfaces");
    controls.hidden = !writable;
    history.hidden = !writable;
    future.hidden = !writable;
    const actionHeader = document.querySelector("#panel-catalog thead th:last-child");
    if (actionHeader) {
      actionHeader.hidden = !writable;
    }
  }

  function parseArgs(text) {
    return String(text || "")
      .trim()
      .split(/\s+/)
      .filter((part) => part.length > 0);
  }

  function parseEnvKeys(text) {
    return String(text || "")
      .split(",")
      .map((key) => key.trim())
      .filter((key) => key.length > 0);
  }

  function showEnableForm(name, scope) {
    enableTarget = { name, scope: scope || "project" };
    byId("catalog-enable-name").textContent = name;
    [
      "catalog-enable-command",
      "catalog-enable-args",
      "catalog-enable-url",
      "catalog-enable-env",
    ].forEach((id) => {
      byId(id).value = "";
    });
    byId("catalog-enable-form").hidden = false;
    byId("catalog-enable-command").focus();
    setEditorMessage(`填入「${name}」的實際設定後按「加入變更」。`);
  }

  function hideEnableForm() {
    enableTarget = null;
    const form = document.getElementById("catalog-enable-form");
    if (form) {
      form.hidden = true;
    }
  }

  // Enable config comes from operator-entered values only. The catalog command
  // preview / url are redacted at storage time, so deriving config from them
  // would write "[REDACTED]" into the real harness config. Secrets are
  // referenced by env-var name (${KEY}), never inlined.
  function buildEnableConfigFromForm() {
    const url = byId("catalog-enable-url").value.trim();
    const command = byId("catalog-enable-command").value.trim();
    const envKeys = parseEnvKeys(byId("catalog-enable-env").value);
    let config = null;
    if (url) {
      config = { url };
    } else if (command) {
      config = { command };
      const args = parseArgs(byId("catalog-enable-args").value);
      if (args.length) {
        config.args = args;
      }
    } else {
      return null;
    }
    if (envKeys.length) {
      config.env = Object.fromEntries(envKeys.map((key) => [key, `\${${key}}`]));
    }
    return config;
  }

  function stageEnableFromForm() {
    if (!enableTarget) {
      return;
    }
    const config = buildEnableConfigFromForm();
    if (!config) {
      setEditorMessage("請至少填入 command 或 url。", true);
      return;
    }
    const op = {
      op: "enable_mcp_server",
      name: enableTarget.name,
      scope: enableTarget.scope,
      config,
    };
    const targetName = enableTarget.name;
    hideEnableForm();
    setPendingOps([op]);
    setEditorMessage(`已選擇啟用 MCP「${targetName}」，請預覽變更。`);
  }

  function buildDisableOp(serverName, scope) {
    return {
      op: "disable_mcp_server",
      name: serverName,
      scope: scope || "project",
    };
  }

  function renderSurfaceRow(surface, writable) {
    const isMcp = surface.type === "mcp_server";
    const isProject = surface.scope === "project";
    const showActions = writable && isMcp && isProject;
    let actionCell = "";
    if (writable) {
      actionCell = showActions
        ? `<td>
            <div class="actions">
              ${
                surface.enabled
                  ? `<button type="button" id="catalog-disable-${escapeHtml(surface.name)}" data-action="catalog-disable-mcp" data-mcp-name="${escapeHtml(surface.name)}" data-mcp-scope="${escapeHtml(surface.scope)}">停用</button>`
                  : `<button type="button" id="catalog-enable-${escapeHtml(surface.name)}" data-action="catalog-enable-mcp" data-mcp-name="${escapeHtml(surface.name)}" data-mcp-scope="${escapeHtml(surface.scope)}">啟用</button>`
              }
            </div>
          </td>`
        : "<td>-</td>";
    }
    return `
      <tr>
        <td class="cell-id">${escapeHtml(surface.id)}</td>
        <td>${escapeHtml(surface.type)}</td>
        <td>${escapeHtml(surface.name)}</td>
        <td><span class="pill">${escapeHtml(surface.scope)}</span></td>
        <td>${escapeHtml(surface.source)}</td>
        <td>${surface.enabled ? "enabled" : "disabled"}</td>
        <td>${valueOrDash(surface.overridden_by)}</td>
        <td>${valueOrDash(surface.overrides)}</td>
        ${actionCell}
      </tr>
    `;
  }

  function renderSurfaces(surfaces) {
    const body = byId("catalog-body");
    const writable = isWritable();
    const colspan = writable ? 9 : 8;
    toggleEditorChrome();
    if (!surfaces.length) {
      body.innerHTML = `<tr><td colspan="${colspan}">尚無介面。</td></tr>`;
      return;
    }
    body.innerHTML = surfaces.map((surface) => renderSurfaceRow(surface, writable)).join("");
  }

  async function loadCatalog() {
    toggleEditorChrome();
    hideEnableForm();
    const harness = byId("catalog-harness").value;
    const type = byId("catalog-type").value;
    const body = byId("catalog-body");
    const writable = isWritable();
    const colspan = writable ? 9 : 8;
    try {
      let path = Ao.buildEndpoint("catalogSurfaces", { harness });
      if (type) {
        path += `?surface_type=${encodeURIComponent(type)}`;
      }
      const data = await Ao.apiFetch(withWorkspaceCwd(path));
      const surfaces = asArray(data.surfaces);
      if (!surfaces.length) {
        body.innerHTML = `<tr><td colspan="${colspan}">尚無介面。</td></tr>`;
      } else {
        renderSurfaces(surfaces);
      }
      setPendingOps(null);
      if (writable) {
        await Ao.PatchRollback.loadPatchHistory({
          harness,
          containerId: "catalog-patch-history-body",
        });
      }
    } catch (error) {
      body.innerHTML = `<tr><td colspan="${colspan}" class="message is-error">${escapeHtml(error.message)}</td></tr>`;
    }
  }

  function stageEnableMcp(name, scope) {
    showEnableForm(name, scope);
  }

  function stageDisableMcp(name, scope) {
    hideEnableForm();
    setPendingOps([buildDisableOp(name, scope)]);
    setEditorMessage(`已選擇停用 MCP「${name}」，請預覽變更。`);
  }

  function formatDiff(diff) {
    if (!diff) {
      return "（無 diff）";
    }
    return JSON.stringify(diff, null, 2);
  }

  async function runPatch(dryRun) {
    if (!pendingOps?.length) {
      setEditorMessage("請先選擇 MCP 變更。", true);
      return null;
    }
    const harness = byId("catalog-harness").value;
    const path = withWorkspaceCwd(
      `${Ao.buildEndpoint("catalogPatch", { harness })}?dry_run=${dryRun ? "true" : "false"}`,
    );
    const payload = {
      ops: pendingOps,
      source: PATCH_SOURCE,
      base_mtime: null,
    };
    return Ao.postJson(path, payload);
  }

  async function dryRunPatch() {
    const preview = byId("catalog-diff-preview");
    preview.textContent = "預覽中…";
    try {
      const result = await runPatch(true);
      pendingChangeId = result.change_id || null;
      preview.textContent = formatDiff(result.diff);
      byId("catalog-apply").disabled = false;
      setEditorMessage("預覽完成，確認後可套用。");
      if (pendingChangeId) {
        Ao.ChangeCenter?.open?.(pendingChangeId)?.catch((error) => {
          console.warn("change center unavailable", error);
        });
      }
    } catch (error) {
      preview.textContent = formatDiff(error.payload?.detail || error.message);
      byId("catalog-apply").disabled = true;
      setEditorMessage(error.message, true);
    }
  }

  async function applyPatch() {
    if (!pendingChangeId) {
      setEditorMessage("請先預覽變更。", true);
      return;
    }
    try {
      const result = await Ao.postEmpty(
        Ao.buildEndpoint("changeApply", { change_id: pendingChangeId }),
      );
      const patchId = result.backup_ref || "(unknown)";
      byId("catalog-diff-preview").textContent = formatDiff(result.diff);
      setEditorMessage(`已套用並驗證 patch_id=${patchId}（${result.status}）`);
      setPendingOps(null);
      await loadCatalog();
    } catch (error) {
      if (error.payload?.status === "stale") {
        setEditorMessage("目標已改變，這筆變更已 stale；請重新預覽。", true);
        return;
      }
      setEditorMessage(error.message, true);
    }
  }

  function bindControls() {
    byId("catalog-dry-run").addEventListener("click", () => {
      dryRunPatch();
    });
    byId("catalog-apply").addEventListener("click", () => {
      applyPatch();
    });
    byId("catalog-enable-stage").addEventListener("click", () => {
      stageEnableFromForm();
    });
    byId("catalog-enable-cancel").addEventListener("click", () => {
      hideEnableForm();
      setEditorMessage("已取消啟用。");
    });
  }

  function init() {
    bindControls();
    toggleEditorChrome();
    setPendingOps(null);
  }

  Ao.CatalogEditor = {
    init,
    loadCatalog,
    stageEnableMcp,
    stageDisableMcp,
    isWritable,
    toggleEditorChrome,
  };
})(window.AgenticOs);

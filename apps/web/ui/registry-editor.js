"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initRegistryEditor(Ao) {
  const PATCH_SOURCE = "web-registry-editor";

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let previewBaseMtime = null;
  let pendingAgent = null;
  let cwdModeOptions = ["required", "optional", "ignored"];

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Missing element: ${id}`);
    }
    return element;
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.registry") ?? Ao.isLocalWritable();
  }

  function toggleEditorChrome() {
    const writable = isWritable();
    const controls = document.getElementById("registry-editor-controls");
    const history = document.getElementById("registry-patch-history");
    if (controls) {
      controls.hidden = !writable;
    }
    if (history) {
      history.hidden = !writable;
    }
  }

  function setMessage(message, isError = false) {
    const target = byId("registry-patch-message");
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function clearValidationErrors() {
    byId("registry-validation-errors").hidden = true;
    byId("registry-validation-errors").textContent = "";
    byId("registry-validation-warnings").hidden = true;
    byId("registry-validation-warnings").textContent = "";
  }

  function renderValidationErrors(errors) {
    const target = byId("registry-validation-errors");
    const list = Array.isArray(errors) ? errors : [String(errors)];
    target.hidden = false;
    target.innerHTML = list.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
  }

  function renderValidationWarnings(warnings) {
    const target = byId("registry-validation-warnings");
    const list = Array.isArray(warnings) ? warnings : [];
    if (!list.length) {
      target.hidden = true;
      target.textContent = "";
      return;
    }
    target.hidden = false;
    target.innerHTML = list.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
  }

  function resetApplyState() {
    previewBaseMtime = null;
    pendingAgent = null;
    byId("registry-apply").disabled = true;
  }

  function formatDiff(diff) {
    if (!diff) {
      return "（無 diff）";
    }
    return JSON.stringify(diff, null, 2);
  }

  function parseCommandList(text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) {
      return [];
    }
    if (trimmed.startsWith("[")) {
      const parsed = JSON.parse(trimmed);
      if (!Array.isArray(parsed)) {
        throw new Error("command 必須是 JSON array");
      }
      return parsed.map(String);
    }
    return trimmed.split(/\s+/).filter((part) => part.length > 0);
  }

  function parseLogPaths(text) {
    return String(text || "")
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
  }

  function buildAgentFromForm() {
    const id = byId("registry-id").value.trim();
    const label = byId("registry-label").value.trim();
    const command = parseCommandList(byId("registry-command").value);
    if (!id || !label || !command.length) {
      throw new Error("id、label、command 為必填");
    }
    const agent = {
      id,
      label,
      command,
      cwd_mode: byId("registry-cwd-mode").value,
      enabled: true,
    };
    const health = parseCommandList(byId("registry-health-command").value);
    if (health.length) {
      agent.health_command = health;
    }
    const attach = parseCommandList(byId("registry-attach-command").value);
    if (attach.length) {
      agent.attach_command = attach;
    }
    const logPaths = parseLogPaths(byId("registry-log-paths").value);
    if (logPaths.length) {
      agent.log_paths = logPaths;
    }
    const provider = byId("registry-default-provider").value.trim();
    if (provider) {
      agent.default_provider = provider;
    }
    const configPath = byId("registry-config-path").value.trim();
    if (configPath) {
      agent.config_path = configPath;
    }
    return agent;
  }

  function fillCwdModeOptions(options) {
    const select = byId("registry-cwd-mode");
    select.innerHTML = options
      .map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`)
      .join("");
  }

  async function loadSchema() {
    const data = await Ao.apiFetch(Ao.buildEndpoint("registrySchema"));
    if (Array.isArray(data.cwd_mode) && data.cwd_mode.length) {
      cwdModeOptions = data.cwd_mode;
      fillCwdModeOptions(cwdModeOptions);
    }
  }

  async function loadRegistryEditor() {
    toggleEditorChrome();
    clearValidationErrors();
    resetApplyState();
    byId("registry-diff-preview").textContent = "編輯 instance 後按「預覽變更」。";
    try {
      await loadSchema();
      if (isWritable()) {
        await Ao.PatchRollback.loadPatchHistory({
          harness: "agentic_os",
          containerId: "registry-patch-history-body",
          emptyMessage: "尚無 registry 修補紀錄。",
        });
      }
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  function buildRegistryQuery(dryRun, baseMtime) {
    const params = new URLSearchParams({
      dry_run: dryRun ? "true" : "false",
      source: PATCH_SOURCE,
    });
    if (baseMtime !== null && baseMtime !== undefined) {
      params.set("base_mtime", String(baseMtime));
    }
    return params.toString();
  }

  async function dryRunRegistry() {
    clearValidationErrors();
    resetApplyState();
    const preview = byId("registry-diff-preview");
    preview.textContent = "預覽中…";
    try {
      const agent = buildAgentFromForm();
      pendingAgent = agent;
      const path = `${Ao.buildEndpoint("registryAgents")}?${buildRegistryQuery(true, null)}`;
      const result = await Ao.postJson(path, agent);
      previewBaseMtime = result.base_mtime ?? null;
      preview.textContent = formatDiff(result.diff);
      renderValidationWarnings(result.validation?.warnings || []);
      byId("registry-apply").disabled = false;
      setMessage(
        previewBaseMtime === null || previewBaseMtime === undefined
          ? "預覽完成，確認後可套用。"
          : `預覽完成，base_mtime=${previewBaseMtime}。`,
      );
    } catch (error) {
      preview.textContent = formatDiff(error.payload?.detail || error.message);
      handleRegistryError(error);
    }
  }

  async function applyRegistry() {
    if (!pendingAgent) {
      setMessage("請先預覽變更。", true);
      return;
    }
    clearValidationErrors();
    try {
      const path = `${Ao.buildEndpoint("registryAgents")}?${buildRegistryQuery(false, previewBaseMtime)}`;
      const result = await Ao.postJson(path, pendingAgent);
      byId("registry-diff-preview").textContent = formatDiff(result.diff);
      renderValidationWarnings(result.validation?.warnings || []);
      setMessage(`已套用 instance：${pendingAgent.id}`);
      resetApplyState();
      if (typeof Ao.loadAgents === "function") {
        await Ao.loadAgents();
      }
    } catch (error) {
      if (error.status === 409 && error.payload?.detail?.error === "stale_target") {
        setMessage("檔案已變更（stale_target），已重新預覽。", true);
        await dryRunRegistry();
        return;
      }
      handleRegistryError(error);
    }
  }

  async function disableRegistryInstance() {
    const id = byId("registry-id").value.trim();
    if (!id) {
      setMessage("請填入要停用的 id。", true);
      return;
    }
    try {
      const path = `${Ao.buildEndpoint("registryAgentDisable", { id })}?${buildRegistryQuery(false, null)}`;
      const result = await Ao.postJson(path, {});
      byId("registry-diff-preview").textContent = formatDiff(result.diff);
      setMessage(`已停用 instance：${id}`);
      if (typeof Ao.loadAgents === "function") {
        await Ao.loadAgents();
      }
    } catch (error) {
      handleRegistryError(error);
    }
  }

  function handleRegistryError(error) {
    const detail = error.payload?.detail;
    if (detail && Array.isArray(detail.validation_errors)) {
      renderValidationErrors(detail.validation_errors);
      setMessage("驗證失敗", true);
      return;
    }
    if (error.status === 403 && detail?.error === "forbidden_path") {
      setMessage(detail.message || "forbidden_path", true);
      return;
    }
    setMessage(error.message, true);
  }

  async function reloadAfterRollback() {
    await loadRegistryEditor();
    if (typeof window.loadAgents === "function") {
      await window.loadAgents();
    }
  }

  function bindControls() {
    byId("registry-load").addEventListener("click", () => {
      loadRegistryEditor();
    });
    byId("registry-dry-run").addEventListener("click", () => {
      dryRunRegistry();
    });
    byId("registry-apply").addEventListener("click", () => {
      applyRegistry();
    });
    byId("registry-disable").addEventListener("click", () => {
      disableRegistryInstance();
    });
  }

  function init() {
    bindControls();
    toggleEditorChrome();
    resetApplyState();
  }

  Ao.RegistryEditor = {
    init,
    loadRegistryEditor,
    reloadAfterRollback,
    isWritable,
    toggleEditorChrome,
  };
})(window.AgenticOs);

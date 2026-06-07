"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initRemoteConsole(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  const UI_LOCALHOST_ONLY_FALLBACK = Object.freeze([
    "ui.write.catalog",
    "ui.write.control-plane",
    "ui.write.harness-config",
    "ui.write.profile",
    "ui.write.registry",
    "ui.write.setup-import",
    "ui.download.logs-zip",
    "ui.repair.config",
  ]);

  const REMOTE_ADMIN_FALLBACK = Object.freeze([
    "remote.pairing.start",
    "remote.devices.list",
    "remote.devices.delete",
    "remote.devices.rotate",
  ]);

  let localhostOnly = new Set();

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function isRemote() {
    return Ao.getConnectionProfile()?.mode === "remote";
  }

  function isActionAllowed(actionId) {
    if (!isRemote()) {
      return true;
    }
    return !localhostOnly.has(actionId);
  }

  function actionHidden(actionId) {
    return !isActionAllowed(actionId);
  }

  async function loadAffordances() {
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("remoteAffordances"));
      localhostOnly = new Set(Array.isArray(data.localhost_only) ? data.localhost_only : []);
    } catch {
      localhostOnly = new Set([...REMOTE_ADMIN_FALLBACK, ...UI_LOCALHOST_ONLY_FALLBACK]);
    }
    renderActionGates();
    refreshWriteGating();
  }

  function renderActionGates() {
    document.querySelectorAll("[data-localhost-action]").forEach((element) => {
      const actionId = element.dataset.localhostAction;
      element.hidden = actionHidden(actionId);
    });
  }

  function refreshWriteGating() {
    Ao.ProductPolish?.toggleLocalOnlyActions?.();
    Ao.CatalogEditor?.toggleEditorChrome?.();
    Ao.HarnessConfigEditor?.toggleEditorChrome?.();
    Ao.ProfileEditor?.toggleEditorChrome?.();
    Ao.RegistryEditor?.toggleEditorChrome?.();
    Ao.ControlPlaneEditor?.toggleEditorChrome?.();
  }

  async function refreshStatus() {
    const healthEl = byId("remote-console-health");
    const tokenEl = byId("remote-console-token");
    const modeEl = byId("remote-console-mode");
    if (!healthEl || !tokenEl || !modeEl) {
      return;
    }
    const profile = Ao.getConnectionProfile();
    modeEl.textContent = profile?.mode || "local";
    if (isRemote()) {
      try {
        await Ao.apiFetch(Ao.buildEndpoint("health"));
        healthEl.textContent = "gateway 可達";
        healthEl.className = "message";
      } catch (error) {
        healthEl.textContent = `gateway 不可達：${error.message}`;
        healthEl.className = "message is-error";
      }
      tokenEl.textContent = profile?.token_present
        ? "token 已設定（值不顯示）"
        : "token 未設定";
      return;
    }
    healthEl.textContent = "本機 daemon";
    try {
      const devices = await Ao.apiFetch(Ao.buildEndpoint("remoteDevices"));
      const list = Array.isArray(devices.devices) ? devices.devices : [];
      tokenEl.innerHTML = list.length
        ? list
            .map(
              (device) =>
                `<div>${escapeHtml(device.device_id)} — expires_at=${escapeHtml(device.expires_at || "n/a")}</div>`,
            )
            .join("")
        : "尚無已配對裝置";
    } catch (error) {
      tokenEl.textContent = `裝置列表：${error.message}`;
    }
  }

  async function init() {
    await loadAffordances();
    await refreshStatus();
    if (isRemote() && Ao.ApprovalWorkbench?.connectApprovalStream) {
      Ao.ApprovalWorkbench.connectApprovalStream();
    }
  }

  Ao.RemoteConsole = {
    init,
    refreshStatus,
    loadAffordances,
    actionHidden,
    isActionAllowed,
    refreshWriteGating,
  };
})(window.AgenticOs);

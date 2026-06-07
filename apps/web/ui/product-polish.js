"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initProductPolish(Ao) {
  function byId(id) {
    return document.getElementById(id);
  }

  async function loadVersion() {
    const target = byId("product-version");
    if (!target) {
      return;
    }
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("versionInfo"));
      target.textContent = `版本 ${data.version}（update_check=${data.update_check || "stub"}）`;
    } catch (error) {
      target.textContent = `版本未知：${error.message}`;
    }
  }

  async function loadDiagnostics() {
    const target = byId("diagnostics-snapshot");
    if (!target) {
      return;
    }
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("diagnosticsResources"));
      target.textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      target.textContent = `診斷失敗：${error.message}`;
    }
  }

  async function checkUpdates() {
    const target = byId("product-update-result");
    if (!target) {
      return;
    }
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("versionInfo"));
      target.textContent = data.update_available
        ? "有可用更新（stub，不自動下載）"
        : "已是最新版本（stub）";
    } catch (error) {
      target.textContent = error.message;
      target.classList.add("is-error");
    }
  }

  async function downloadLogs() {
    const path = `${Ao.apiBase()}${Ao.buildEndpoint("setupLogsZip")}`;
    if (Ao.getConnectionProfile()?.mode === "remote" && window.__TAURI__?.core?.invoke) {
      const text = await window.__TAURI__.core.invoke("connection_api_fetch", {
        method: "GET",
        path: Ao.buildEndpoint("setupLogsZip"),
        body: null,
      });
      const blob = new Blob([text], { type: "application/zip" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "agentic-os-logs.zip";
      anchor.click();
      URL.revokeObjectURL(url);
      return;
    }
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`${response.status} logs download failed`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "agentic-os-logs.zip";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function readSetupBundle() {
    const bundleInput = byId("setup-bundle-input");
    const bundleText = bundleInput?.value?.trim();
    if (!bundleText) {
      throw new Error("先匯出 bundle 或貼上有效 JSON");
    }
    return JSON.parse(bundleText);
  }

  function writeSetupBundle(data) {
    const bundleInput = byId("setup-bundle-input");
    if (bundleInput) {
      bundleInput.value = JSON.stringify(data, null, 2);
    }
  }

  function writeImportResult(data) {
    const output = byId("setup-import-result-output");
    if (output) {
      output.textContent = JSON.stringify(data, null, 2);
    }
  }

  function writeImportError(message) {
    const output = byId("setup-import-result-output");
    if (output) {
      output.textContent = message;
    }
  }

  async function exportSetup() {
    const cwd = byId("setup-cwd")?.value.trim() || "";
    const query = cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
    const data = await Ao.apiFetch(`${Ao.buildEndpoint("setupExport")}${query}`);
    writeSetupBundle(data);
    writeImportResult("已匯出 bundle 至上方輸入區。");
    return data;
  }

  async function importSetup(dryRun) {
    const bundle = readSetupBundle();
    const cwd = byId("setup-cwd")?.value.trim() || "";
    const params = new URLSearchParams({ dry_run: dryRun ? "true" : "false" });
    if (cwd) {
      params.set("cwd", cwd);
    }
    const result = await Ao.postJson(`${Ao.buildEndpoint("setupImport")}?${params}`, bundle);
    writeImportResult(result);
    return result;
  }

  function bindEvents() {
    byId("product-diagnostics-refresh")?.addEventListener("click", loadDiagnostics);
    byId("product-update-check")?.addEventListener("click", checkUpdates);
    byId("product-logs-download")?.addEventListener("click", () => {
      downloadLogs().catch((error) => {
        byId("product-update-result").textContent = error.message;
      });
    });
    byId("setup-export-btn")?.addEventListener("click", () => {
      exportSetup().catch((error) => {
        writeImportError(error.message);
      });
    });
    byId("setup-import-dry-run")?.addEventListener("click", () => {
      importSetup(true).catch((error) => {
        writeImportError(error.message);
      });
    });
    byId("setup-import-apply")?.addEventListener("click", () => {
      if (!Ao.isLocalWritable()) {
        writeImportError("遠端模式不可套用匯入");
        return;
      }
      importSetup(false).catch((error) => {
        writeImportError(error.message);
      });
    });
    byId("remote-console-refresh")?.addEventListener("click", () => {
      Ao.RemoteConsole?.refreshStatus();
    });
  }

  async function init() {
    bindEvents();
    await Promise.allSettled([loadVersion(), loadDiagnostics()]);
    if (Ao.RemoteConsole?.init) {
      await Ao.RemoteConsole.init();
    }
  }

  Ao.ProductPolish = {
    init,
    loadDiagnostics,
    loadVersion,
    exportSetup,
    importSetup,
  };
})(window.AgenticOs);

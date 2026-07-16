"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initSettingsHome(Ao) {
  let initialized = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function setMessage(message, isError = false) {
    const target = byId("settings-message");
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function revealTarget(button) {
    const area = button.dataset.settingsArea;
    const view = button.dataset.settingsView;
    if (area && view) {
      Ao.Navigation.show(area, view);
    }
    requestAnimationFrame(() => {
      const target = byId(button.dataset.settingsTarget);
      if (!target) {
        setMessage(`找不到設定 owner：${button.dataset.settingsTarget}`, true);
        return;
      }
      if (target.tagName === "DETAILS") {
        target.open = true;
      }
      target.closest("details")?.setAttribute("open", "");
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      if (typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
      if (target.id === "provider-switchboard-section") {
        Ao.ProviderSwitchboard?.refresh?.();
      } else if (target.id === "profile-editor-section") {
        Ao.ProfileEditor?.loadProfiles?.();
      } else if (target.id === "run-template-section") {
        Ao.RunTemplateLauncher?.loadTemplates?.();
      }
    });
  }

  async function openDesktopSettings() {
    const invoke = window.__TAURI__?.core?.invoke;
    if (!invoke) {
      setMessage("Desktop Settings 只在 packaged Desktop app 可開啟。", true);
      return;
    }
    try {
      await invoke("open_desktop_settings");
      setMessage("已開啟 Desktop Settings。");
    } catch (error) {
      setMessage(`Desktop Settings 開啟失敗：${String(error)}`, true);
    }
  }

  function load() {
    const profile = Ao.getConnectionProfile();
    const connectionSummary = byId("settings-connection-summary");
    if (connectionSummary) {
      connectionSummary.textContent =
        profile?.mode === "remote"
          ? `Remote · ${profile.api_url || "gateway 未設定"}`
          : `Local · ${profile?.api_url || Ao.DEFAULT_API_URL}`;
    }
    const workspaceSummary = byId("settings-workspace-summary");
    if (workspaceSummary) {
      workspaceSummary.textContent = Ao.Workspace?.getActiveCwd?.() || "尚未選擇工作區。";
    }
  }

  function init() {
    if (initialized) {
      return;
    }
    initialized = true;
    byId("settings-open-desktop")?.addEventListener("click", openDesktopSettings);
    byId("panel-settings-home")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-settings-target]");
      if (button) {
        revealTarget(button);
      }
    });
    document.addEventListener("workspace-changed", load);
  }

  Ao.SettingsHome = { init, load, revealTarget, openDesktopSettings };
})(window.AgenticOs);

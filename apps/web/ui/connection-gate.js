"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initConnectionGate(Ao) {
  let onConnected = null;
  let lastState = null;
  let pollTimer = null;

  function el() {
    return document.getElementById("connection-gate");
  }

  function setText(selector, text) {
    const node = el()?.querySelector(selector);
    if (node) node.textContent = text;
  }

  function render(stateName, detail) {
    const gate = el();
    if (!gate) return;
    const wasConnected = lastState === "connected";

    if (stateName === "connected") {
      gate.hidden = true;
      if (!wasConnected) onConnected?.();
      lastState = stateName;
      return;
    }

    gate.hidden = false;
    const failed = stateName === "failed";
    const occupied = (detail || "").startsWith("port_occupied:");
    setText("[data-gate-title]", failed ? "無法連線到本地 daemon" : "連線中…");
    setText(
      "[data-gate-detail]",
      failed
        ? occupied
          ? `埠 8767 已被其他程序佔用 (pid ${detail.split(":")[1]})；請先停止該程序再重試。`
          : "daemon 多次啟動失敗，已停止自動重試。"
        : "正在啟動 / 等待 agentd…",
    );
    const actions = gate.querySelector("[data-gate-actions]");
    if (actions) actions.hidden = !failed;
    lastState = stateName;
  }

  async function pollHealth() {
    try {
      await Ao.apiFetch(Ao.ENDPOINTS.health);
      render("connected", "ok");
      stopPolling();
    } catch {
      render("connecting", "");
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollHealth();
    pollTimer = window.setInterval(pollHealth, 3000);
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  Ao.ConnectionGate = {
    init({ onConnected: callback } = {}) {
      onConnected = callback || null;
      const tauri = window.__TAURI__;
      const listen = tauri?.event?.listen;
      const invoke = tauri?.core?.invoke;

      const retryBtn = document.querySelector("[data-gate-retry]");
      const logBtn = document.querySelector("[data-gate-log]");
      if (retryBtn) {
        retryBtn.addEventListener("click", async () => {
          render("connecting", "");
          if (invoke) {
            try {
              await invoke("retry_daemon");
            } catch (error) {
              console.warn("retry_daemon failed", error);
            }
          } else {
            startPolling();
          }
        });
      }
      if (logBtn) {
        logBtn.hidden = !invoke;
        logBtn.addEventListener("click", () => {
          invoke?.("open_daemon_log");
        });
      }

      if (listen) {
        // Seed initial state immediately (events emitted before we subscribed are missed),
        // then react to subsequent transitions.
        render("connecting", "");
        pollHealth();
        listen("connection-state", (event) => {
          const payload = event.payload || {};
          render(payload.state, payload.detail);
        });
      } else {
        startPolling();
      }
    },
  };
})(window.AgenticOs);

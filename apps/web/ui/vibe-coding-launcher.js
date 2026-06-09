"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initVibeCodingLauncher(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let launcherSessionId = null;
  let launcherLogTimer = null;

  function escapeHtml(value) {
    const text =
      value === null || value === undefined || value === "" ? "" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setMessage(message, isError = false) {
    const target = byId("vibe-coding-message");
    if (!target) return;
    target.textContent = message || "";
    target.classList.toggle("is-error", !!isError);
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.vibe-coding") ?? Ao.isLocalWritable();
  }

  function toggleChrome() {
    const writable = isWritable();
    const controls = byId("vibe-coding-launcher-controls");
    if (controls) controls.hidden = !writable;
  }

  async function fetchVibeCodingAgents() {
    const agents = (await Ao.apiFetch("/agents?tool_kind=vibe_coding")).agents;

    let installedIds = new Set(agents.map((a) => a.id));
    try {
      const tools = (await Ao.apiFetch("/tools/discovery")).tools;
      installedIds = new Set(
        tools
          .filter((t) => t.installed && t.tool_kind === "vibe_coding")
          .map((t) => t.agent_id)
      );
    } catch (error) {
      // Discovery is best-effort: fall back to listing all agents.
    }
    return agents
      .filter((a) => installedIds.has(a.id))
      .map((a) => ({ id: a.id, label: a.label || a.id }));
  }

  async function fetchProfiles() {
    const payload = await Ao.apiFetch("/profiles");
    return payload.profiles || [];
  }

  function renderAgentPicker(agents) {
    const select = byId("vibe-coding-agent");
    if (!select) return;
    if (!agents.length) {
      select.innerHTML =
        '<option value="">— 沒有已安裝的 vibe coding agents —</option>';
      select.disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = [
      '<option value="">— 選擇 agent —</option>',
      ...agents.map(
        (a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.label)}</option>`
      ),
    ].join("");
  }

  function renderProfilePicker(profiles) {
    const select = byId("vibe-coding-profile");
    if (!select) return;
    select.innerHTML = [
      '<option value="">— 預設（不指定 profile）—</option>',
      ...profiles.map(
        (p) => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`
      ),
    ].join("");
  }

  async function refreshLaunchers() {
    try {
      const [agents, profiles] = await Promise.all([
        fetchVibeCodingAgents(),
        fetchProfiles(),
      ]);
      renderAgentPicker(agents);
      renderProfilePicker(profiles);
      toggleChrome();
      if (!agents.length) {
        setMessage("目前沒有任何已安裝的 vibe coding agent。請先用 P34 discovery 檢查工具狀態。", true);
      } else {
        setMessage("");
      }
    } catch (error) {
      setMessage(`無法載入 agent/profile 清單：${error.message}`, true);
    }
  }

  function readCwd() {
    return Ao.Workspace?.getActiveCwd?.() || "";
  }

  function readMessage() {
    const field = byId("vibe-coding-message-input");
    return field ? field.value.trim() : "";
  }

  function readSelection() {
    return {
      agentId: byId("vibe-coding-agent")?.value || "",
      profileName: byId("vibe-coding-profile")?.value || "",
      cwd: readCwd(),
      message: readMessage(),
    };
  }

  function clearLogPanels() {
    byId("vibe-coding-log-stdout")?.replaceChildren();
    byId("vibe-coding-log-stderr")?.replaceChildren();
  }

  function setActiveSession(sessionId) {
    launcherSessionId = sessionId || null;
    const detail = byId("vibe-coding-session-detail");
    if (detail) {
      detail.textContent = sessionId
        ? `Session: ${sessionId}`
        : "尚未啟動 session。";
    }
    const downloadBtn = byId("vibe-coding-download");
    if (downloadBtn) {
      downloadBtn.disabled = !sessionId;
    }
    const stopBtn = byId("vibe-coding-stop");
    if (stopBtn) stopBtn.disabled = !sessionId;
    const retryBtn = byId("vibe-coding-retry");
    if (retryBtn) retryBtn.disabled = !sessionId;
  }

  async function launch() {
    const { agentId, profileName, cwd, message } = readSelection();
    if (!agentId) {
      setMessage("請先選擇 agent。", true);
      return;
    }
    if (!cwd) {
      setMessage("請先選擇 workspace。", true);
      return;
    }
    if (!message) {
      setMessage("請輸入訊息內容。", true);
      return;
    }

    setMessage("啟動中...");
    const launchBtn = byId("vibe-coding-launch");
    if (launchBtn) launchBtn.disabled = true;
    clearLogPanels();
    setActiveSession(null);

    const payload = {
      agent_id: agentId,
      cwd,
      message,
    };

    try {
      const session = await Ao.postJson("/sessions", payload);
      setActiveSession(session.id);
      setMessage(`已啟動 session ${session.id}（狀態：${session.status}）`);
      startLogPolling(session.id);
      // Notify other panels (sessions list) to refresh.
      Ao.refreshSessions?.();
    } catch (error) {
      setMessage(`啟動失敗：${error.message}`, true);
    } finally {
      if (launchBtn) launchBtn.disabled = false;
    }
  }

  async function stop() {
    if (!launcherSessionId) return;
    try {
      await Ao.postEmpty(`/sessions/${launcherSessionId}/stop`);
      setMessage(`已請求停止 ${launcherSessionId}`);
    } catch (error) {
      setMessage(`停止失敗：${error.message}`, true);
    }
  }

  async function retry() {
    if (!launcherSessionId) return;
    try {
      const session = await Ao.postEmpty(`/sessions/${launcherSessionId}/retry`);
      setActiveSession(session.id);
      setMessage(`已重啟 session ${session.id}`);
      clearLogPanels();
      startLogPolling(session.id);
      Ao.refreshSessions?.();
    } catch (error) {
      setMessage(`重啟失敗：${error.message}`, true);
    }
  }

  function downloadEvidence() {
    if (!launcherSessionId) return;
    window.location.href = `${Ao.apiBase?.() || ""}/sessions/${launcherSessionId}/evidence.zip`;
  }

  async function fetchLog(stream) {
    if (!launcherSessionId) return;
    try {
      const data = await Ao.apiFetch(
        `/sessions/${launcherSessionId}/logs?stream=${stream}`
      );
      const panel = byId(`vibe-coding-log-${stream}`);
      if (!panel) return;
      panel.textContent = (data.entries || [])
        .map((entry) => entry.line)
        .join("\n");
    } catch (error) {
      // Best-effort: keep last good content.
    }
  }

  async function pollLogs() {
    if (!launcherSessionId) return;
    await Promise.all([fetchLog("stdout"), fetchLog("stderr")]);
  }

  function startLogPolling(sessionId) {
    stopLogPolling();
    pollLogs();
    launcherLogTimer = window.setInterval(pollLogs, 2000);
  }

  function stopLogPolling() {
    if (launcherLogTimer !== null) {
      window.clearInterval(launcherLogTimer);
      launcherLogTimer = null;
    }
  }

  function init() {
    const launchBtn = byId("vibe-coding-launch");
    if (launchBtn) launchBtn.addEventListener("click", launch);
    const stopBtn = byId("vibe-coding-stop");
    if (stopBtn) stopBtn.addEventListener("click", stop);
    const retryBtn = byId("vibe-coding-retry");
    if (retryBtn) retryBtn.addEventListener("click", retry);
    const downloadBtn = byId("vibe-coding-download");
    if (downloadBtn) downloadBtn.addEventListener("click", downloadEvidence);
    setActiveSession(null);
    refreshLaunchers();
  }

  Ao.VibeCodingLauncher = {
    init,
    refresh: refreshLaunchers,
  };
})(window.AgenticOs);

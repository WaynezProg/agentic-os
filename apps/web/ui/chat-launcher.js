"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initChatLauncher(Ao) {
  const HISTORY_KEY = "agentic-os-chat-history";
  const AGENT_KEY = "agentic-os-chat-agent";
  const HISTORY_LIMIT = 200;
  const POLL_INTERVAL_MS = 1500;
  const TERMINAL_STATUSES = new Set(["succeeded", "failed", "stopped"]);

  let bound = false;
  let history = [];
  const pollers = new Map();

  function byId(id) {
    return document.getElementById(id);
  }

  function setMessage(message, isError = false) {
    const target = byId("chat-message");
    if (!target) return;
    target.textContent = message || "";
    target.classList.toggle("is-error", !!isError);
  }

  function loadHistory() {
    try {
      const raw = window.localStorage.getItem(HISTORY_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function saveHistory() {
    try {
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-HISTORY_LIMIT)));
    } catch {
      // Best-effort: history is a convenience, not a record of truth.
    }
  }

  function statusClass(status) {
    if (status === "succeeded") return "is-ok";
    if (status === "failed" || status === "stopped") return "is-bad";
    return "is-warn";
  }

  function statusLabel(status) {
    if (status === "succeeded") return "成功";
    if (status === "failed") return "失敗";
    if (status === "stopped") return "已停止";
    if (status === "running") return "執行中";
    if (status === "queued") return "排隊中";
    return status || "未知";
  }

  function renderBubble(entry) {
    const bubble = document.createElement("div");
    if (entry.role === "user") {
      bubble.className = "chat-bubble chat-bubble--user";
      const meta = document.createElement("div");
      meta.className = "chat-bubble-meta";
      meta.textContent = `你 → ${entry.agentId}`;
      const body = document.createElement("div");
      body.className = "chat-bubble-text";
      body.textContent = entry.text;
      bubble.append(meta, body);
      return bubble;
    }
    if (entry.role === "tool") {
      bubble.className = "chat-bubble chat-bubble--tool";
      const meta = document.createElement("div");
      meta.className = "chat-bubble-meta";
      const name = document.createElement("span");
      name.textContent = entry.agentId;
      const status = document.createElement("span");
      status.className = `chat-status ${statusClass(entry.status)}`;
      status.textContent = statusLabel(entry.status);
      meta.append(name, status);
      if (entry.sessionId) {
        const link = document.createElement("button");
        link.type = "button";
        link.className = "chat-session-link";
        link.textContent = `session ${entry.sessionId.slice(0, 8)}… 日誌`;
        link.addEventListener("click", () => openSessionLogs(entry.sessionId));
        meta.append(link);
      }
      const body = document.createElement("pre");
      body.className = "chat-output";
      body.textContent = entry.text || (TERMINAL_STATUSES.has(entry.status) ? "（無輸出）" : "等待輸出…");
      bubble.append(meta, body);
      return bubble;
    }
    bubble.className = "chat-bubble chat-bubble--system";
    bubble.textContent = entry.text;
    if (entry.sessionId) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "chat-session-link";
      link.textContent = `稽核 session ${entry.sessionId.slice(0, 8)}…`;
      link.addEventListener("click", () => openSessionLogs(entry.sessionId));
      bubble.append(" ", link);
    }
    return bubble;
  }

  function renderThread() {
    const thread = byId("chat-thread");
    if (!thread) return;
    thread.replaceChildren();
    if (!history.length) {
      const empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent =
        "選一個 harness、輸入訊息送出，就會啟動一次 run；工具輸出會以回覆形式出現在這裡。每則回覆都連回完整 session 日誌。";
      thread.append(empty);
      return;
    }
    history.forEach((entry) => thread.append(renderBubble(entry)));
    thread.scrollTop = thread.scrollHeight;
  }

  function openSessionLogs(sessionId) {
    const input = byId("log-session-id");
    if (input) input.value = sessionId;
    Ao.showTab?.("sessions");
    byId("load-logs")?.click();
  }

  function readCwd() {
    return Ao.Workspace?.getActiveCwd?.() || "";
  }

  function updateCwdHint() {
    const hint = byId("chat-cwd-hint");
    if (!hint) return;
    const cwd = readCwd();
    hint.textContent = cwd
      ? `工作目錄：${cwd}（跟隨上方工作區選擇）`
      : "未選工作區：cwd_mode=required 的 harness 會拒絕啟動。";
  }

  async function refreshAgents() {
    const select = byId("chat-agent");
    if (!select) return;
    try {
      const payload = await Ao.apiFetch(Ao.buildEndpoint("agents"));
      const agents = (payload.agents || []).filter((agent) => agent.enabled !== false);
      if (!agents.length) {
        select.innerHTML = '<option value="">— 沒有可用的 harness —</option>';
        select.disabled = true;
        return;
      }
      const remembered = window.localStorage.getItem(AGENT_KEY) || "";
      select.disabled = false;
      select.replaceChildren(
        ...agents.map((agent) => {
          const option = document.createElement("option");
          option.value = agent.id;
          option.textContent = agent.label || agent.id;
          if (agent.id === remembered) option.selected = true;
          return option;
        })
      );
    } catch (error) {
      setMessage(`無法載入 harness 清單：${error.message}`, true);
    }
  }

  function entryForSession(sessionId) {
    return history.find((entry) => entry.role === "tool" && entry.sessionId === sessionId);
  }

  async function fetchReplyText(sessionId, status) {
    let text = "";
    try {
      const stdout = await Ao.apiFetch(
        `${Ao.buildEndpoint("sessionLogs", { session_id: sessionId })}?stream=stdout`
      );
      text = (stdout.entries || []).map((entry) => entry.line).join("\n");
    } catch {
      // Logs may not exist yet; keep placeholder.
    }
    if (status === "failed") {
      try {
        const stderr = await Ao.apiFetch(
          `${Ao.buildEndpoint("sessionLogs", { session_id: sessionId })}?stream=stderr`
        );
        const errText = (stderr.entries || []).map((entry) => entry.line).join("\n");
        if (errText) {
          text = text ? `${text}\n[stderr]\n${errText}` : `[stderr]\n${errText}`;
        }
      } catch {
        // Best-effort.
      }
    }
    return text;
  }

  function stopPolling(sessionId) {
    const timer = pollers.get(sessionId);
    if (timer !== undefined) {
      window.clearInterval(timer);
      pollers.delete(sessionId);
    }
  }

  async function syncSession(sessionId) {
    const entry = entryForSession(sessionId);
    if (!entry) {
      stopPolling(sessionId);
      return;
    }
    try {
      const session = await Ao.apiFetch(Ao.buildEndpoint("sessionDetail", { session_id: sessionId }));
      entry.status = session.status;
      if (TERMINAL_STATUSES.has(session.status)) {
        stopPolling(sessionId);
        entry.text = await fetchReplyText(sessionId, session.status);
        if (session.exit_code !== null && session.exit_code !== undefined && session.status !== "succeeded") {
          entry.text = entry.text
            ? `${entry.text}\n（exit code ${session.exit_code}）`
            : `（exit code ${session.exit_code}）`;
        }
      }
      saveHistory();
      renderThread();
    } catch {
      // Transient fetch failures: retry on next tick.
    }
  }

  function trackSession(sessionId) {
    stopPolling(sessionId);
    syncSession(sessionId);
    pollers.set(
      sessionId,
      window.setInterval(() => syncSession(sessionId), POLL_INTERVAL_MS)
    );
  }

  function policyDetail(error) {
    // Policy rejections are flat: {detail: <reason>, decision, session_id}.
    const payload = error?.payload;
    if (payload && typeof payload === "object" && payload.decision) {
      return {
        decision: payload.decision,
        reason: typeof payload.detail === "string" ? payload.detail : "",
        session_id: payload.session_id || null,
      };
    }
    return null;
  }

  async function send() {
    const select = byId("chat-agent");
    const input = byId("chat-input");
    const agentId = select?.value || "";
    const text = input?.value.trim() || "";
    if (!agentId) {
      setMessage("請先選擇 harness。", true);
      return;
    }
    if (!text) {
      setMessage("請輸入訊息。", true);
      return;
    }
    setMessage("");
    window.localStorage.setItem(AGENT_KEY, agentId);
    const sendBtn = byId("chat-send");
    if (sendBtn) sendBtn.disabled = true;

    history.push({ role: "user", text, agentId, ts: Date.now() });
    renderThread();

    const payload = { agent_id: agentId, message: text };
    const cwd = readCwd();
    if (cwd) payload.cwd = cwd;

    try {
      const session = await Ao.postJson(Ao.buildEndpoint("sessionRun"), payload);
      history.push({
        role: "tool",
        agentId,
        sessionId: session.id,
        status: session.status,
        text: "",
        ts: Date.now(),
      });
      saveHistory();
      renderThread();
      if (TERMINAL_STATUSES.has(session.status)) {
        syncSession(session.id);
      } else {
        trackSession(session.id);
      }
      if (input) input.value = "";
      Ao.refreshSessions?.();
    } catch (error) {
      const detail = policyDetail(error);
      if (detail?.decision) {
        history.push({
          role: "system",
          text: `policy ${detail.decision === "deny" ? "拒絕" : "要求核准"}：${detail.reason || "未提供原因"}`,
          sessionId: detail.session_id || null,
          ts: Date.now(),
        });
      } else {
        history.push({ role: "system", text: `啟動失敗：${error.message}`, ts: Date.now() });
      }
      saveHistory();
      renderThread();
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  function clearHistory() {
    history = [];
    saveHistory();
    renderThread();
    setMessage("已清除聊天歷史（session 紀錄仍保留在「執行」頁）。");
  }

  function resumePendingPolls() {
    history
      .filter((entry) => entry.role === "tool" && !TERMINAL_STATUSES.has(entry.status))
      .forEach((entry) => trackSession(entry.sessionId));
  }

  function init() {
    if (!bound) {
      bound = true;
      history = loadHistory();
      byId("chat-send")?.addEventListener("click", send);
      byId("chat-clear")?.addEventListener("click", clearHistory);
      byId("chat-input")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          send();
        }
      });
      document.addEventListener("workspace-changed", updateCwdHint);
      renderThread();
      resumePendingPolls();
    }
    refreshAgents();
    updateCwdHint();
  }

  Ao.ChatLauncher = {
    init,
    refresh: refreshAgents,
  };
})(window.AgenticOs);

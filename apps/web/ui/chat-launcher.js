"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initChatLauncher(Ao) {
  const HISTORY_KEY = "agentic-os-chat-history";
  const AGENT_KEY = "agentic-os-chat-agent";
  const HISTORY_LIMIT = 200;
  const POLL_INTERVAL_MS = 1500;
  const TERMINAL_STATUSES = new Set(["succeeded", "failed", "stopped"]);
  // Replies are bounded previews, not the durable record: cap what we
  // fetch, what we render, and what lands in localStorage. Full output
  // stays behind the session log link.
  const REPLY_FETCH_MAX_LINES = 400;
  const REPLY_TAIL_LINES = 120;
  const REPLY_TAIL_CHARS = 4000;
  const STDERR_TAIL_LINES = 40;
  const STDERR_TAIL_CHARS = 1500;
  const TRUNCATION_MARKER = "⋯（輸出過長，僅顯示片段預覽；完整輸出請點上方日誌連結）";

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
      const bounded = history.slice(-HISTORY_LIMIT).map((entry) => ({
        ...entry,
        text: typeof entry.text === "string" ? entry.text.slice(0, REPLY_TAIL_CHARS + 200) : entry.text,
      }));
      window.localStorage.setItem(HISTORY_KEY, JSON.stringify(bounded));
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

  function boundTail(payload, maxLines, maxChars) {
    let lines = (payload.entries || []).map((entry) => entry.line);
    let clipped = Boolean(payload.truncated);
    if (lines.length > maxLines) {
      lines = lines.slice(-maxLines);
      clipped = true;
    }
    let text = lines.join("\n");
    if (text.length > maxChars) {
      text = text.slice(-maxChars);
      clipped = true;
    }
    return { text, clipped };
  }

  async function fetchStreamTail(sessionId, stream, maxLines, maxChars) {
    const path = Ao.buildEndpoint("sessionLogs", { session_id: sessionId });
    const payload = await Ao.apiFetch(
      `${path}?stream=${stream}&max_lines=${REPLY_FETCH_MAX_LINES}`
    );
    return boundTail(payload, maxLines, maxChars);
  }

  async function fetchReplyText(sessionId, status) {
    let text = "";
    let clipped = false;
    try {
      const stdout = await fetchStreamTail(sessionId, "stdout", REPLY_TAIL_LINES, REPLY_TAIL_CHARS);
      text = stdout.text;
      clipped = stdout.clipped;
    } catch {
      // Logs may not exist yet; keep placeholder.
    }
    if (status === "failed") {
      try {
        const stderr = await fetchStreamTail(sessionId, "stderr", STDERR_TAIL_LINES, STDERR_TAIL_CHARS);
        if (stderr.text) {
          text = text ? `${text}\n[stderr]\n${stderr.text}` : `[stderr]\n${stderr.text}`;
          clipped = clipped || stderr.clipped;
        }
      } catch {
        // Best-effort.
      }
    }
    return clipped ? `${TRUNCATION_MARKER}\n${text}` : text;
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

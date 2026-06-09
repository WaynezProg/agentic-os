"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initDiscoverBind(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  function escapeHtml(value) {
    const text = value === null || value === undefined ? "" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setMessage(message, isError = false) {
    const target = byId("discover-message");
    if (!target) return;
    target.textContent = message || "";
    target.classList.toggle("is-error", !!isError);
  }

  function readCwd() {
    return Ao.Workspace?.getActiveCwd?.() || "";
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.discover-bind") ?? Ao.isLocalWritable();
  }

  function toggleChrome() {
    const writable = isWritable();
    const controls = byId("discover-controls");
    if (controls) controls.hidden = !writable;
  }

  function renderResults(discovered) {
    const body = byId("discover-results-body");
    if (!body) return;
    if (!discovered.length) {
      body.innerHTML =
        '<tr><td colspan="5">沒有找到外部 session。換個 workspace 或先啟動一個 agent。</td></tr>';
      return;
    }
    body.innerHTML = discovered
      .map(
        (d, idx) => `
        <tr data-discover-idx="${idx}">
          <td>${escapeHtml(d.agent_id)}</td>
          <td class="cell-code">${escapeHtml(d.external_session_id)}</td>
          <td class="cell-code">${escapeHtml(d.started_at || "-")}</td>
          <td class="cell-code">${escapeHtml(d.log_path)}</td>
          <td><button type="button" data-discover-bind="${idx}" class="btn-primary">Bind</button></td>
        </tr>
      `
      )
      .join("");
    body.querySelectorAll("[data-discover-bind]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        const idx = Number(event.currentTarget.dataset.discoverBind);
        const target = discovered[idx];
        bind(target);
      });
    });
  }

  async function discover() {
    const cwd = readCwd();
    if (!cwd) {
      setMessage("請先選擇 workspace。", true);
      return;
    }
    setMessage("掃描中...");
    try {
      const payload = await Ao.postJson("/sessions/discover", {
        workspace_path: cwd,
      });
      const discovered = payload.discovered || [];
      renderResults(discovered);
      setMessage(`找到 ${discovered.length} 個外部 session。`);
    } catch (error) {
      setMessage(`掃描失敗：${error.message}`, true);
    }
  }

  async function bind(item) {
    setMessage(`綁定 ${item.agent_id} / ${item.external_session_id}...`);
    try {
      const session = await Ao.postJson("/sessions/bind", {
        agent_id: item.agent_id,
        external_session_id: item.external_session_id,
        workspace_path: readCwd(),
        log_path: item.log_path,
        started_at: item.started_at,
      });
      setMessage(
        `已綁定為 session ${session.id}（attachable=${session.attachable}）`
      );
      Ao.refreshSessions?.();
    } catch (error) {
      setMessage(`綁定失敗：${error.message}`, true);
    }
  }

  function init() {
    const discoverBtn = byId("discover-run");
    if (discoverBtn) discoverBtn.addEventListener("click", discover);
    const refreshBtn = byId("discover-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", discover);
    toggleChrome();
    renderResults([]);
  }

  Ao.DiscoverBind = {
    init,
    refresh: discover,
  };
})(window.AgenticOs);

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initApprovalWorkbench(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let eventSource = null;

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function formatArgv(argv) {
    return asArray(argv).join(" ");
  }

  function renderCard(approval) {
    const status = String(approval.status || "unknown");
    const isPending = status === "pending";
    const argvText = formatArgv(approval.argv);
    const policyResult = approval.decision_reason
      ? `${status}: ${approval.decision_reason}`
      : approval.reason || "-";
    return `
      <article class="approval-card" data-approval-id="${escapeHtml(approval.id)}">
        <header class="approval-card-head">
          <span class="cell-id">${escapeHtml(approval.id)}</span>
          <span class="${statusPillClass(status)}">${escapeHtml(status)}</span>
          <span>${escapeHtml(approval.agent_id)}</span>
        </header>
        <dl class="approval-card-body">
          <div><dt>觸發原因</dt><dd>${escapeHtml(approval.reason || "")}</dd></div>
          <div><dt>來源 session</dt><dd class="cell-id">${escapeHtml(approval.source_session_id)}</dd></div>
          <div><dt>argv</dt><dd class="cell-code">${escapeHtml(argvText)}</dd></div>
          <div><dt>cwd</dt><dd class="cell-code">${escapeHtml(approval.cwd || "")}</dd></div>
          <div><dt>政策結果</dt><dd>${escapeHtml(policyResult)}</dd></div>
        </dl>
        <footer class="approval-card-actions">
          <button type="button" data-action="view-session-events" data-session-id="${escapeHtml(approval.source_session_id)}">稽核事件</button>
          <button type="button" data-action="approve-approval" data-approval-id="${escapeHtml(approval.id)}" ${isPending ? "" : "disabled"}>核准</button>
          <button type="button" data-action="reject-approval" data-approval-id="${escapeHtml(approval.id)}" ${isPending ? "" : "disabled"}>拒絕</button>
          <button type="button" data-action="retry-approval-session" data-session-id="${escapeHtml(approval.source_session_id)}" data-approval-id="${escapeHtml(approval.id)}" ${isPending ? "" : "disabled"}>重試</button>
          <span class="approval-retry-result" id="approval-retry-${escapeHtml(approval.id)}" aria-live="polite"></span>
        </footer>
      </article>
    `;
  }

  function statusPillClass(status) {
    if (status === "pending") {
      return "pill is-pending";
    }
    if (status === "approved") {
      return "pill is-healthy";
    }
    if (status === "rejected" || status === "expired") {
      return "pill is-unhealthy";
    }
    return "pill";
  }

  async function loadWorkbench() {
    const container = byId("approvals-workbench");
    if (!container) {
      return;
    }
    try {
      const statusFilter = byId("approval-status-filter")?.value || "";
      const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
      const data = await Ao.apiFetch(`${Ao.buildEndpoint("approvals")}${params}`);
      const approvals = asArray(data.approvals);
      if (!approvals.length) {
        container.innerHTML = '<p class="message">尚無核准請求。</p>';
        return;
      }
      container.innerHTML = approvals.map(renderCard).join("");
    } catch (error) {
      container.innerHTML = `<p class="message is-error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function retrySession(sessionId, approvalId) {
    const resultEl = byId(`approval-retry-${approvalId}`);
    try {
      const result = await Ao.postEmpty(Ao.buildEndpoint("sessionRetry", { session_id: sessionId }));
      const summary = `decision=${result.decision || "-"} reason=${result.reason || "-"} session_id=${result.session_id || result.id || "-"}`;
      if (resultEl) {
        resultEl.textContent = summary;
      }
      await loadWorkbench();
      return result;
    } catch (error) {
      const detail = error.payload?.detail || error.message;
      const text =
        typeof detail === "object"
          ? `decision=${detail.decision || "-"} reason=${detail.reason || JSON.stringify(detail)} session_id=${detail.session_id || "-"}`
          : String(detail);
      if (resultEl) {
        resultEl.textContent = text;
      }
      throw error;
    }
  }

  function connectApprovalStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    if (Ao.getConnectionProfile()?.mode !== "remote") {
      return;
    }
    const base = Ao.apiBase();
    try {
      eventSource = new EventSource(`${base}${Ao.buildEndpoint("events")}`);
      eventSource.onmessage = () => {
        loadWorkbench();
      };
      eventSource.onerror = () => {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
      };
    } catch (error) {
      console.warn("approval stream unavailable", error);
    }
  }

  function disconnectStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  Ao.ApprovalWorkbench = {
    loadWorkbench,
    retrySession,
    connectApprovalStream,
    disconnectStream,
    renderCard,
  };
})(window.AgenticOs);

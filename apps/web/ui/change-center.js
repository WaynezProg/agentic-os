"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initChangeCenter(Ao) {
  const APPLYABLE_STATUSES = new Set(["previewed", "approved"]);
  const ROLLBACKABLE_STATUSES = new Set(["verified", "partial"]);
  const PENDING_STATUSES = new Set(["previewed", "approved", "applying"]);
  const STATUS_LABELS = Object.freeze({
    previewed: "待確認",
    approved: "已核准",
    applying: "套用中",
    verified: "已驗證",
    partial: "部分成功",
    failed: "失敗",
    rolled_back: "已回滾",
    rollback_failed: "回滾失敗",
    stale: "已過期",
  });

  const escapeHtml = Ao.escapeHtml;
  let currentChanges = [];
  let selectedChangeId = "";
  let initialized = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function display(value, fallback = "—") {
    if (value === undefined || value === null || value === "") {
      return fallback;
    }
    return String(value);
  }

  function safeStatus(status) {
    return Object.hasOwn(STATUS_LABELS, status) ? status : "failed";
  }

  function statusLabel(status) {
    return STATUS_LABELS[safeStatus(status)];
  }

  function observedTime(value) {
    if (!value) {
      return "未知";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return String(value);
    }
    return parsed.toLocaleString("zh-TW", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function setMessage(message, isError = false) {
    const target = byId("change-message");
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.changes") ?? Ao.isLocalWritable();
  }

  function replaceChange(change) {
    const index = currentChanges.findIndex((item) => item.id === change.id);
    if (index === -1) {
      currentChanges = [change, ...currentChanges];
    } else {
      currentChanges = currentChanges.map((item) => (item.id === change.id ? change : item));
    }
    selectedChangeId = change.id;
  }

  function renderChangeCard(change) {
    const status = safeStatus(change.status);
    const selected = change.id === selectedChangeId;
    return `
      <button
        type="button"
        class="change-card${selected ? " is-selected" : ""}"
        data-change-select="${escapeHtml(change.id)}"
        aria-current="${selected ? "true" : "false"}"
      >
        <span class="change-card__head">
          <strong>${escapeHtml(display(change.operation))}</strong>
          <span class="change-status is-${status}">${escapeHtml(statusLabel(status))}</span>
        </span>
        <span class="change-card__environment">${escapeHtml(display(change.environment_id))}</span>
        <span class="change-card__time">${escapeHtml(observedTime(change.updated_at))}</span>
      </button>
    `;
  }

  function renderLists() {
    const pending = currentChanges.filter((change) => PENDING_STATUSES.has(change.status));
    const history = currentChanges.filter((change) => !PENDING_STATUSES.has(change.status));
    const pendingTarget = byId("change-pending-list");
    const historyTarget = byId("change-history-list");
    if (!pendingTarget || !historyTarget) {
      return;
    }
    pendingTarget.innerHTML = pending.length
      ? pending.map(renderChangeCard).join("")
      : '<p class="empty-state">沒有待確認變更。</p>';
    historyTarget.innerHTML = history.length
      ? history.map(renderChangeCard).join("")
      : '<p class="empty-state">尚無變更紀錄。</p>';
    byId("change-pending-count").textContent = String(pending.length);
    byId("change-history-count").textContent = String(history.length);
  }

  function renderJsonSection(title, value, className = "") {
    return `
      <details class="change-detail-section"${title === "Diff" ? " open" : ""}>
        <summary>${escapeHtml(title)}</summary>
        <pre class="change-json ${className}">${escapeHtml(JSON.stringify(value ?? {}, null, 2))}</pre>
      </details>
    `;
  }

  function renderVerification(change) {
    const verification = change.verification;
    if (!verification) {
      return '<p class="empty-state">套用後才會產生 verification。</p>';
    }
    const checks = Array.isArray(verification.checks) ? verification.checks : [];
    return `
      <div class="change-verification">
        <div class="change-verification__summary">
          <strong>Verification</strong>
          <span class="change-status is-${safeStatus(verification.status)}">${escapeHtml(statusLabel(verification.status))}</span>
        </div>
        <ul class="change-checks">
          ${
            checks.length
              ? checks
                  .map(
                    (check) => `
                      <li class="${check.passed ? "is-passed" : "is-failed"}">
                        <span aria-hidden="true">${check.passed ? "✓" : "✕"}</span>
                        <span>${escapeHtml(display(check.name, "verification check"))}</span>
                      </li>
                    `,
                  )
                  .join("")
              : "<li>沒有逐項 checks。</li>"
          }
        </ul>
        ${renderJsonSection("Observed evidence", verification.observed)}
      </div>
    `;
  }

  function renderRestartRequirements(change) {
    const requirements = Array.isArray(change.restart_requirements)
      ? change.restart_requirements
      : [];
    if (!requirements.length) {
      return '<p class="empty-state">不需要重新啟動。</p>';
    }
    return `
      <ul class="change-restart-list">
        ${requirements.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    `;
  }

  function renderActions(change) {
    if (!isWritable()) {
      return "";
    }
    const canApply = APPLYABLE_STATUSES.has(change.status);
    const canRollback =
      ROLLBACKABLE_STATUSES.has(change.status) && Boolean(change.backup_ref);
    if (!canApply && !canRollback) {
      return "";
    }
    return `
      <div class="change-detail__buttons">
        ${
          canApply
            ? `<button type="button" class="btn-primary" data-change-apply="${escapeHtml(change.id)}">套用並驗證</button>`
            : ""
        }
        ${
          canRollback
            ? `<button type="button" data-change-rollback="${escapeHtml(change.id)}">Rollback</button>`
            : ""
        }
      </div>
    `;
  }

  function renderDetail(change) {
    const target = byId("change-detail");
    if (!target) {
      return;
    }
    if (!change) {
      target.innerHTML = '<p class="empty-state">從左側選擇一筆變更。</p>';
      return;
    }
    const status = safeStatus(change.status);
    target.innerHTML = `
      <div class="change-detail__head">
        <div>
          <p class="eyebrow">${escapeHtml(change.id)}</p>
          <h3>${escapeHtml(display(change.operation))}</h3>
          <p>${escapeHtml(display(change.environment_id))} · ${escapeHtml(observedTime(change.updated_at))}</p>
        </div>
        <span class="change-status is-${status}">${escapeHtml(statusLabel(status))}</span>
      </div>
      ${renderActions(change)}
      <dl class="change-detail__facts">
        <div><dt>Target surfaces</dt><dd>${escapeHtml((change.target_surfaces || []).join(", ") || "—")}</dd></div>
        <div><dt>Backup reference</dt><dd class="cell-code">${escapeHtml(display(change.backup_ref))}</dd></div>
        <div><dt>建立時間</dt><dd>${escapeHtml(observedTime(change.created_at))}</dd></div>
      </dl>
      <section class="change-detail-block" aria-labelledby="change-restart-heading">
        <h4 id="change-restart-heading">Restart requirements</h4>
        ${renderRestartRequirements(change)}
      </section>
      <section class="change-detail-block" aria-labelledby="change-verification-heading">
        <h4 id="change-verification-heading">Verification details</h4>
        ${renderVerification(change)}
      </section>
      ${renderJsonSection("Diff", change.diff, "change-json--diff")}
      ${renderJsonSection("Validation", change.validation)}
      ${renderJsonSection("Redacted request", change.redacted_request)}
      ${renderJsonSection("Before evidence", change.before_evidence)}
      ${change.rollback ? renderJsonSection("Rollback result", change.rollback) : ""}
    `;
  }

  function selectFromCurrent() {
    if (!currentChanges.length) {
      selectedChangeId = "";
      renderLists();
      renderDetail(null);
      return;
    }
    const selected = currentChanges.find((change) => change.id === selectedChangeId);
    const change = selected || currentChanges[0];
    selectedChangeId = change.id;
    renderLists();
    renderDetail(change);
  }

  async function load({ force = false } = {}) {
    setMessage("正在載入變更紀錄…");
    try {
      if (force) {
        Ao.DataCache?.invalidate("changes");
      }
      const loader = () => Ao.apiFetch(Ao.buildEndpoint("changes"));
      const payload = Ao.DataCache
        ? await Ao.DataCache.get("changes", loader, 1000)
        : await loader();
      currentChanges = Array.isArray(payload.changes) ? payload.changes : [];
      selectFromCurrent();
      setMessage(`已載入 ${currentChanges.length} 筆變更。`);
      return payload;
    } catch (error) {
      setMessage(`變更紀錄載入失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function loadDetail(changeId) {
    selectedChangeId = changeId;
    renderLists();
    setMessage(`正在載入 ${changeId}…`);
    try {
      const path = Ao.buildEndpoint("changeDetail", { change_id: changeId });
      const loader = () => Ao.apiFetch(path);
      const change = Ao.DataCache
        ? await Ao.DataCache.get(`change:${changeId}`, loader, 1000)
        : await loader();
      replaceChange(change);
      renderLists();
      renderDetail(change);
      setMessage(`已載入 ${changeId}。`);
      return change;
    } catch (error) {
      setMessage(`變更明細載入失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  function publishUpdate(change) {
    document.dispatchEvent(
      new CustomEvent("agentic-os:change-updated", { detail: { change } }),
    );
  }

  async function applyChange(changeId) {
    setMessage(`正在套用並驗證 ${changeId}…`);
    try {
      const change = await Ao.postEmpty(
        Ao.buildEndpoint("changeApply", { change_id: changeId }),
      );
      replaceChange(change);
      renderLists();
      renderDetail(change);
      publishUpdate(change);
      setMessage(`變更 ${changeId}：${statusLabel(change.status)}。`);
      return change;
    } catch (error) {
      const staleChange = error.payload?.status === "stale" ? error.payload : null;
      if (staleChange) {
        replaceChange(staleChange);
        renderLists();
        renderDetail(staleChange);
        publishUpdate(staleChange);
        setMessage("目標在預覽後已改變；這筆變更已標記為 stale，請重新預覽。", true);
        return staleChange;
      }
      setMessage(`套用失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function rollbackChange(changeId) {
    setMessage(`正在 rollback ${changeId}…`);
    try {
      const change = await Ao.postEmpty(
        Ao.buildEndpoint("changeRollback", { change_id: changeId }),
      );
      replaceChange(change);
      renderLists();
      renderDetail(change);
      publishUpdate(change);
      setMessage(`Rollback ${change.status === "rolled_back" ? "已驗證" : "完成"}。`);
      return change;
    } catch (error) {
      const failedChange =
        error.payload?.status === "rollback_failed" ? error.payload : null;
      if (failedChange) {
        replaceChange(failedChange);
        renderLists();
        renderDetail(failedChange);
        publishUpdate(failedChange);
        setMessage("Rollback verification 失敗；目標可能在套用後被再次修改。", true);
        return failedChange;
      }
      setMessage(`Rollback 失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function open(changeId) {
    selectedChangeId = changeId;
    Ao.Navigation?.show?.("changes", "change-center", { skipLoad: true });
    await load({ force: true });
    return loadDetail(changeId);
  }

  function toggleChrome() {
    const selected = currentChanges.find((change) => change.id === selectedChangeId);
    if (selected) {
      renderDetail(selected);
    }
  }

  function init() {
    if (initialized) {
      return;
    }
    initialized = true;
    byId("change-refresh")?.addEventListener("click", () => {
      load({ force: true }).catch(() => {});
    });
    byId("panel-change-center")?.addEventListener("click", (event) => {
      const selectButton = event.target.closest("[data-change-select]");
      if (selectButton) {
        loadDetail(selectButton.dataset.changeSelect).catch(() => {});
        return;
      }
      const applyButton = event.target.closest("[data-change-apply]");
      if (applyButton) {
        applyChange(applyButton.dataset.changeApply).catch(() => {});
        return;
      }
      const rollbackButton = event.target.closest("[data-change-rollback]");
      if (rollbackButton) {
        rollbackChange(rollbackButton.dataset.changeRollback).catch(() => {});
      }
    });
  }

  Ao.ChangeCenter = {
    APPLYABLE_STATUSES,
    ROLLBACKABLE_STATUSES,
    init,
    load,
    loadDetail,
    open,
    applyChange,
    rollbackChange,
    toggleChrome,
    renderLists,
    renderDetail,
  };
})(window.AgenticOs);

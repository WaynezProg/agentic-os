"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initEnvironmentManager(Ao) {
  const STATUS_LABELS = Object.freeze({
    healthy: "正常",
    degraded: "需處理",
    missing: "未安裝",
    configured_only: "僅有設定",
    auth_required: "需要登入",
    stale: "資料過期",
    unsupported: "不支援",
    unknown: "未知",
  });

  const SURFACE_LABELS = Object.freeze({
    cli: "CLI",
    config: "設定",
    capability: "Capabilities",
    runtime: "Runtime",
    desktop: "Desktop app",
    ide: "IDE extension",
  });

  const CONFIGURED_STATUSES = new Set([
    "healthy",
    "degraded",
    "configured_only",
    "auth_required",
    "stale",
  ]);

  const escapeHtml = Ao.escapeHtml;
  let currentEnvironments = [];
  let selectedEnvironmentId = "";
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
    return Object.hasOwn(STATUS_LABELS, status) ? status : "unknown";
  }

  function statusLabel(status) {
    return STATUS_LABELS[safeStatus(status)];
  }

  function surfaceLabel(kind) {
    return SURFACE_LABELS[kind] || display(kind, "未知 surface");
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

  function configuredSurfaceCount(environment) {
    return (environment.surfaces || []).filter((surface) =>
      CONFIGURED_STATUSES.has(surface.status),
    ).length;
  }

  function cliSummary(environment) {
    const cli = (environment.surfaces || []).find((surface) => surface.kind === "cli");
    if (!cli || cli.status === "missing") {
      return "未偵測";
    }
    return display(cli.version, display(cli.path));
  }

  function primaryAction(environment) {
    const actionSurface = (environment.surfaces || []).find(
      (surface) => surface.action_required,
    );
    if (actionSurface) {
      return actionSurface.action_required;
    }
    const cli = (environment.surfaces || []).find((surface) => surface.kind === "cli");
    return cli?.status === "missing" ? "安裝 CLI" : "查看詳情";
  }

  function setMessage(message, isError = false) {
    const target = byId("environment-message");
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function renderList(environments = currentEnvironments) {
    const target = byId("environment-list");
    if (!target) {
      return;
    }
    if (!environments.length) {
      target.innerHTML = '<p class="empty-state">尚未偵測到支援的 Agent 環境。</p>';
      return;
    }
    target.innerHTML = environments
      .map((environment) => {
        const status = safeStatus(environment.overall_status);
        const selected = environment.id === selectedEnvironmentId;
        return `
          <article class="environment-card${selected ? " is-selected" : ""}">
            <div class="environment-card__head">
              <div>
                <h3>${escapeHtml(display(environment.label, environment.id))}</h3>
                <p>${escapeHtml(display(environment.tool_kind))}</p>
              </div>
              <span class="environment-status is-${status}">${escapeHtml(statusLabel(status))}</span>
            </div>
            <dl class="environment-card__facts">
              <div><dt>CLI</dt><dd>${escapeHtml(cliSummary(environment))}</dd></div>
              <div><dt>已設定 surfaces</dt><dd>${configuredSurfaceCount(environment)} / ${(environment.surfaces || []).length}</dd></div>
              <div><dt>Active sessions</dt><dd>${Number(environment.active_sessions) || 0}</dd></div>
              <div><dt>待處理變更</dt><dd>${Number(environment.pending_change_count) || 0}</dd></div>
            </dl>
            <p class="environment-card__action"><strong>建議動作</strong>${escapeHtml(primaryAction(environment))}</p>
            <div class="environment-card__buttons">
              <button
                type="button"
                data-environment-select="${escapeHtml(environment.id)}"
                aria-current="${selected ? "true" : "false"}"
              >查看詳情</button>
              <button type="button" data-environment-refresh="${escapeHtml(environment.id)}">重新偵測</button>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function renderEvidence(surface) {
    const evidenceItems = Array.isArray(surface.evidence) ? surface.evidence : [];
    if (!evidenceItems.length) {
      return '<p class="environment-surface__empty">沒有額外證據。</p>';
    }
    return `
      <ul class="environment-evidence">
        ${evidenceItems
          .map(
            (evidence) => `
              <li>
                <strong>${escapeHtml(display(evidence.source, "證據"))}</strong>
                <span>${escapeHtml(display(evidence.detail))}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
    `;
  }

  function renderSurface(surface) {
    const status = safeStatus(surface.status);
    return `
      <article class="environment-surface">
        <div class="environment-surface__head">
          <h4>${escapeHtml(surfaceLabel(surface.kind))}</h4>
          <span class="environment-status is-${status}">${escapeHtml(statusLabel(status))}</span>
        </div>
        <dl class="environment-surface__facts">
          <div><dt>來源</dt><dd>${escapeHtml(display(surface.source))}</dd></div>
          <div><dt>版本</dt><dd>${escapeHtml(display(surface.version))}</dd></div>
          <div><dt>路徑</dt><dd class="cell-code">${escapeHtml(display(surface.path))}</dd></div>
          <div><dt>觀察時間</dt><dd>${escapeHtml(observedTime(surface.observed_at))}</dd></div>
        </dl>
        ${surface.detail ? `<p class="environment-surface__detail">${escapeHtml(surface.detail)}</p>` : ""}
        <p class="environment-surface__action">
          <strong>建議動作</strong>
          ${escapeHtml(display(surface.action_required, "目前不需處理"))}
        </p>
        <details class="environment-surface__evidence">
          <summary>觀察證據</summary>
          ${renderEvidence(surface)}
        </details>
      </article>
    `;
  }

  function renderCapabilities(capabilityNames) {
    const groups = Object.entries(capabilityNames || {}).filter(
      ([, names]) => Array.isArray(names) && names.length,
    );
    if (!groups.length) {
      return '<p class="empty-state">未偵測到 capabilities。</p>';
    }
    return groups
      .map(
        ([group, names]) => `
          <div class="environment-capability-group">
            <h4>${escapeHtml(group)}</h4>
            <div class="environment-capability-list">
              ${names
                .slice(0, 20)
                .map((name) => `<span class="badge">${escapeHtml(name)}</span>`)
                .join("")}
              ${names.length > 20 ? `<span class="badge">另有 ${names.length - 20} 項</span>` : ""}
            </div>
          </div>
        `,
      )
      .join("");
  }

  function renderDetail(environment) {
    const target = byId("environment-detail");
    if (!target) {
      return;
    }
    if (!environment) {
      target.innerHTML = '<p class="empty-state">從清單選擇一個環境。</p>';
      return;
    }
    const status = safeStatus(environment.overall_status);
    target.innerHTML = `
      <div class="environment-detail__head">
        <div>
          <p class="eyebrow">${escapeHtml(display(environment.id))}</p>
          <h3>${escapeHtml(display(environment.label, environment.id))}</h3>
          <p>${escapeHtml(display(environment.tool_kind))} · 最後觀察 ${escapeHtml(observedTime(environment.observed_at))}</p>
        </div>
        <div class="environment-detail__actions">
          <span class="environment-status is-${status}">${escapeHtml(statusLabel(status))}</span>
          <button type="button" data-environment-refresh="${escapeHtml(environment.id)}">重新偵測</button>
        </div>
      </div>
      <section aria-labelledby="environment-surfaces-heading">
        <h4 id="environment-surfaces-heading" class="environment-section-heading">Surfaces</h4>
        <div class="environment-surface-grid">
          ${(environment.surfaces || []).map(renderSurface).join("")}
        </div>
      </section>
      <section aria-labelledby="environment-capabilities-heading">
        <h4 id="environment-capabilities-heading" class="environment-section-heading">Capabilities</h4>
        <div class="environment-capabilities">
          ${renderCapabilities(environment.capability_names)}
        </div>
      </section>
    `;
  }

  function selectFromCurrent() {
    if (!currentEnvironments.length) {
      selectedEnvironmentId = "";
      renderDetail(null);
      return;
    }
    const selected = currentEnvironments.find(
      (environment) => environment.id === selectedEnvironmentId,
    );
    const environment = selected || currentEnvironments[0];
    selectedEnvironmentId = environment.id;
    renderList();
    renderDetail(environment);
  }

  async function load({ force = false } = {}) {
    setMessage("正在盤點 Agent 環境…");
    try {
      if (force) {
        Ao.DataCache?.invalidate("environments");
      }
      const loader = () => Ao.apiFetch(Ao.buildEndpoint("environments"));
      const payload = Ao.DataCache
        ? await Ao.DataCache.get("environments", loader, 1500)
        : await loader();
      currentEnvironments = Array.isArray(payload.environments) ? payload.environments : [];
      selectFromCurrent();
      setMessage(`已盤點 ${currentEnvironments.length} 個 Agent 環境。`);
      return payload;
    } catch (error) {
      setMessage(`環境盤點失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function loadDetail(environmentId) {
    selectedEnvironmentId = environmentId;
    renderList();
    setMessage(`正在載入 ${environmentId} 明細…`);
    try {
      const path = Ao.buildEndpoint("environmentDetail", {
        environment_id: environmentId,
      });
      const loader = () => Ao.apiFetch(path);
      const environment = Ao.DataCache
        ? await Ao.DataCache.get(`environment:${environmentId}`, loader, 1500)
        : await loader();
      currentEnvironments = currentEnvironments.map((item) =>
        item.id === environment.id ? environment : item,
      );
      renderList();
      renderDetail(environment);
      setMessage(`已載入 ${display(environment.label, environment.id)}。`);
      return environment;
    } catch (error) {
      setMessage(`環境明細載入失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function refreshAll() {
    setMessage("正在重新偵測全部環境…");
    try {
      const payload = await Ao.postEmpty(Ao.buildEndpoint("environmentsRefresh"));
      currentEnvironments = Array.isArray(payload.environments) ? payload.environments : [];
      selectFromCurrent();
      setMessage(`已重新偵測 ${currentEnvironments.length} 個 Agent 環境。`);
      return payload;
    } catch (error) {
      setMessage(`重新偵測失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  async function refreshOne(environmentId) {
    setMessage(`正在重新偵測 ${environmentId}…`);
    try {
      const environment = await Ao.postEmpty(
        Ao.buildEndpoint("environmentRefresh", { environment_id: environmentId }),
      );
      selectedEnvironmentId = environment.id;
      currentEnvironments = currentEnvironments.map((item) =>
        item.id === environment.id ? environment : item,
      );
      renderList();
      renderDetail(environment);
      setMessage(`已重新偵測 ${display(environment.label, environment.id)}。`);
      return environment;
    } catch (error) {
      setMessage(`重新偵測失敗：${String(error.message || error)}`, true);
      throw error;
    }
  }

  function init() {
    if (initialized) {
      return;
    }
    initialized = true;
    byId("environment-refresh-all")?.addEventListener("click", () => {
      refreshAll().catch(() => {});
    });
    byId("panel-environment-list")?.addEventListener("click", (event) => {
      const selectButton = event.target.closest("[data-environment-select]");
      if (selectButton) {
        loadDetail(selectButton.dataset.environmentSelect).catch(() => {});
        return;
      }
      const refreshButton = event.target.closest("[data-environment-refresh]");
      if (refreshButton) {
        refreshOne(refreshButton.dataset.environmentRefresh).catch(() => {});
      }
    });
  }

  Ao.EnvironmentManager = {
    STATUS_LABELS,
    SURFACE_LABELS,
    init,
    load,
    loadDetail,
    refreshAll,
    refreshOne,
    renderList,
    renderDetail,
  };
})(window.AgenticOs);

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initDailyDashboard(Ao) {
  const QUICK_ACTIONS = Object.freeze([
    { id: "switch-profile", label: "切換 profile", affordance: "ui.write.profile" },
    { id: "open-repair", label: "修復設定", affordance: "ui.repair.config" },
    { id: "approve", label: "核准佇列", affordance: null },
    { id: "rollback", label: "設定還原", affordance: "ui.write.harness-config" },
    { id: "start-template", label: "啟動範本", affordance: "ui.write.run-template" },
  ]);
  const ATTENTION_TYPES = Object.freeze({
    environment: "environment-attention",
    change: "change-attention",
    approval: "approval-attention",
    session: "session-attention",
    verified: "verified-change",
  });
  const ENVIRONMENT_ATTENTION_STATUSES = new Set([
    "degraded",
    "missing",
    "auth_required",
    "stale",
  ]);
  const ACTIVE_SESSION_STATUSES = new Set(["queued", "running", "stopping"]);

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function isActionAllowed(actionId) {
    if (!actionId) {
      return true;
    }
    return Ao.RemoteConsole?.isActionAllowed(actionId) ?? Ao.isLocalWritable();
  }

  function cwdQuery() {
    const cwd = Ao.Workspace?.getActiveCwd?.() || "";
    return cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
  }

  function renderQuickActions() {
    const container = byId("dashboard-quick-actions");
    if (!container) {
      return;
    }
    const allowed = QUICK_ACTIONS.filter((action) => isActionAllowed(action.affordance));
    const blocked = QUICK_ACTIONS.filter((action) => !isActionAllowed(action.affordance));
    container.innerHTML = `
      <div class="actions">
        ${allowed
          .map(
            (action) =>
              `<button type="button" class="btn-primary" data-action="${escapeHtml(action.id)}">${escapeHtml(action.label)}</button>`,
          )
          .join("")}
      </div>
      ${
        blocked.length
          ? `<p class="message">遠端模式隱藏：${blocked.map((action) => escapeHtml(action.label)).join("、")}</p>`
          : ""
      }`;
  }

  function renderDashboard(body) {
    byId("dashboard-cwd").textContent = body.cwd || "-";
    byId("dashboard-profile").textContent = body.active_profile || "-";
    byId("dashboard-provider").textContent = body.provider || "-";
    byId("dashboard-model").textContent = body.model || "-";
    byId("dashboard-harness").textContent = body.harness_id || "-";
    const sessions = body.sessions || {};
    byId("dashboard-sessions").textContent = t("dashboardSessions", {
      running: sessions.running ?? 0,
      failed: sessions.failed ?? 0,
      total: sessions.total ?? 0,
    });
    byId("dashboard-approvals").textContent = t("dashboardApprovals", {
      pending: body.pending_approvals ?? 0,
    });
    byId("dashboard-patches").textContent = String(body.recent_config_patches ?? 0);
    const harnesses = Array.isArray(body.harnesses) ? body.harnesses : [];
    byId("dashboard-harnesses").textContent = harnesses.length ? harnesses.join(", ") : "-";
  }

  function renderAttention(items) {
    const container = byId("home-attention-list");
    const count = byId("home-attention-count");
    if (!container || !count) {
      return;
    }
    container.classList.remove("is-error");
    count.textContent = String(items.length);
    if (!items.length) {
      container.innerHTML = '<p class="empty-state">目前沒有需處理事項。</p>';
      return;
    }
    container.innerHTML = items
      .map(
        (item) => `
          <button
            type="button"
            class="home-attention-item is-${item.type}"
            data-home-attention="${item.type}"
            data-home-area="${item.area}"
            data-home-view="${item.view}"
            ${item.environmentId ? `data-home-environment="${escapeHtml(item.environmentId)}"` : ""}
            ${item.changeId ? `data-home-change="${escapeHtml(item.changeId)}"` : ""}
          >
            <span class="home-attention-item__copy">
              <strong>${escapeHtml(item.label)}</strong>
              <span>${escapeHtml(item.detail)}</span>
            </span>
            <span class="home-attention-item__action">${escapeHtml(item.action)}</span>
          </button>
        `,
      )
      .join("");
  }

  async function loadAttentionData() {
    const [environmentData, changeData, approvalData, sessionData] = await Promise.all([
      Ao.DataCache.get(
        "environments",
        () => Ao.apiFetch(Ao.buildEndpoint("environments")),
        1500,
      ),
      Ao.DataCache.get("changes", () => Ao.apiFetch(Ao.buildEndpoint("changes")), 1000),
      Ao.DataCache.get(
        "approvals-pending",
        () => Ao.apiFetch(`${Ao.buildEndpoint("approvals")}?status=pending`),
        1000,
      ),
      Ao.DataCache.get("sessions", () => Ao.apiFetch(Ao.buildEndpoint("sessions")), 1000),
    ]);

    const environments = Array.isArray(environmentData.environments)
      ? environmentData.environments
      : [];
    const changes = Array.isArray(changeData.changes) ? changeData.changes : [];
    const approvals = Array.isArray(approvalData.approvals) ? approvalData.approvals : [];
    const sessions = Array.isArray(sessionData.sessions) ? sessionData.sessions : [];
    const items = [];

    environments
      .filter((environment) => ENVIRONMENT_ATTENTION_STATUSES.has(environment.overall_status))
      .slice(0, 5)
      .forEach((environment) => {
        items.push({
          type: ATTENTION_TYPES.environment,
          area: "environments",
          view: "environment-list",
          environmentId: environment.id,
          label: `${environment.label || environment.id} 需處理`,
          detail: `環境狀態：${environment.overall_status}`,
          action: "查看環境",
        });
      });

    changes
      .filter((change) => change.status === "stale" || change.status === "partial")
      .slice(0, 5)
      .forEach((change) => {
        items.push({
          type: ATTENTION_TYPES.change,
          area: "changes",
          view: "change-center",
          changeId: change.id,
          label: `${change.operation} · ${change.status}`,
          detail: `環境：${change.environment_id}`,
          action: "檢查變更",
        });
      });

    if (approvals.length) {
      items.push({
        type: ATTENTION_TYPES.approval,
        area: "changes",
        view: "approvals",
        label: `${approvals.length} 筆待核准`,
        detail: "核准後才能繼續受 policy 保護的操作。",
        action: "開啟核准",
      });
    }

    sessions
      .filter((session) => ACTIVE_SESSION_STATUSES.has(session.status))
      .slice(0, 5)
      .forEach((session) => {
        items.push({
          type: ATTENTION_TYPES.session,
          area: "sessions",
          view: "sessions",
          label: `${session.agent_id || "Agent"} · ${session.status}`,
          detail: session.id,
          action: "查看 session",
        });
      });

    changes
      .filter((change) => change.status === "verified")
      .slice(0, 3)
      .forEach((change) => {
        items.push({
          type: ATTENTION_TYPES.verified,
          area: "changes",
          view: "change-center",
          changeId: change.id,
          label: `${change.operation} 已驗證`,
          detail: `環境：${change.environment_id}`,
          action: "查看證據",
        });
      });

    renderAttention(items);
  }

  async function loadAttention() {
    try {
      await loadAttentionData();
    } catch (error) {
      const container = byId("home-attention-list");
      if (container) {
        container.textContent = `需處理事項載入失敗：${error.message}`;
        container.classList.add("is-error");
      }
      const count = byId("home-attention-count");
      if (count) {
        count.textContent = "!";
      }
    }
  }

  async function loadFleetSummary() {
    try {
      const healthData = await Ao.DataCache.get(
        "fleet-health",
        () => Ao.apiFetch(Ao.buildEndpoint("fleetHealth")),
        1500,
      );
      const instances = Array.isArray(healthData.instances) ? healthData.instances : [];
      const upCount = instances.filter((item) => item.state === "up").length;
      const downCount = instances.filter((item) => item.state === "down").length;
      byId("overview-health-body").innerHTML = t("overviewHealth", {
        up: upCount,
        down: downCount,
        total: instances.length,
      });
    } catch {
      byId("overview-health-body").textContent = t("overviewError");
    }

    try {
      const capData = await Ao.DataCache.get(
        "fleet-capacity",
        () => Ao.apiFetch(Ao.buildEndpoint("fleetCapacity")),
        1500,
      );
      byId("overview-capacity-body").textContent = t("overviewCapacity", {
        running: capData.running_sessions,
        max: capData.max_running_sessions,
      });
    } catch {
      byId("overview-capacity-body").textContent = t("overviewError");
    }

    try {
      const appData = await Ao.DataCache.get(
        "approvals-pending",
        () => Ao.apiFetch(`${Ao.buildEndpoint("approvals")}?status=pending`),
        1000,
      );
      const pending = Array.isArray(appData.approvals) ? appData.approvals.length : 0;
      byId("overview-approvals-body").textContent = t("overviewApprovalsPending", { pending });
    } catch {
      byId("overview-approvals-body").textContent = t("overviewError");
    }
  }

  async function loadDashboard() {
    renderQuickActions();
    const workspaceCard = byId("dashboard-workspace-body");
    if (workspaceCard) {
      workspaceCard.textContent = t("loading");
    }
    try {
      const body = await Ao.DataCache.get(
        "workspace-dashboard",
        () => Ao.apiFetch(`${Ao.buildEndpoint("workspacesDashboard")}${cwdQuery()}`),
        1000,
      );
      renderDashboard(body);
      byId("overview-sessions-body").textContent = t("overviewSessions", {
        running: body.sessions?.running ?? 0,
        total: body.sessions?.total ?? 0,
      });
      if (workspaceCard) {
        workspaceCard.textContent = t("dashboardWorkspaceReady", { cwd: body.cwd || "-" });
      }
    } catch (error) {
      if (workspaceCard) {
        workspaceCard.textContent = error.message;
        workspaceCard.classList.add("is-error");
      }
    }
    await Promise.all([loadFleetSummary(), loadAttention()]);
    if (Ao.DashboardV2?.loadDashboardV2) {
      await Ao.DashboardV2.loadDashboardV2();
    }
    if (Ao.ProductPolish?.refresh) {
      await Ao.ProductPolish.refresh();
    }
  }

  function revealSection(id) {
    const section = document.getElementById(id);
    if (!section) {
      return;
    }
    if (section.tagName === "DETAILS") {
      section.open = true;
    }
    section.scrollIntoView({ behavior: "smooth" });
  }

  function handleQuickAction(action) {
    if (action === "switch-profile") {
      Ao.showTab("agents");
      revealSection("profile-editor-section");
      return;
    }
    if (action === "open-repair") {
      Ao.showTab("overview");
      document.getElementById("product-repair-config")?.click();
      return;
    }
    if (action === "approve") {
      Ao.showTab("approvals");
      return;
    }
    if (action === "rollback") {
      Ao.showTab("harnesses");
      document.getElementById("config-patch-history")?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    if (action === "start-template") {
      Ao.showTab("agents");
      revealSection("run-template-section");
      Ao.RunTemplateLauncher?.loadTemplates?.();
    }
  }

  function handleAttention(button) {
    const environmentId = button.dataset.homeEnvironment;
    const changeId = button.dataset.homeChange;
    if (environmentId) {
      Ao.Navigation.show("environments", "environment-list", { skipLoad: true });
      Ao.EnvironmentManager.load()
        .then(() => Ao.EnvironmentManager.loadDetail(environmentId))
        .catch((error) => console.warn("environment attention open failed", error));
      return;
    }
    if (changeId) {
      Ao.ChangeCenter?.open?.(changeId)?.catch((error) => {
        console.warn("change attention open failed", error);
      });
      return;
    }
    Ao.Navigation.show(button.dataset.homeArea, button.dataset.homeView);
  }

  function bindControls() {
    document.addEventListener("workspace-changed", () => {
      Ao.DataCache.invalidate("workspace-dashboard");
      if (document.getElementById("panel-overview")?.classList.contains("is-active")) {
        loadDashboard();
      }
    });
    document.addEventListener("click", (event) => {
      const attentionButton = event.target.closest("[data-home-attention]");
      if (attentionButton) {
        handleAttention(attentionButton);
        return;
      }
      const button = event.target.closest("#dashboard-quick-actions [data-action]");
      if (!button) {
        return;
      }
      handleQuickAction(button.dataset.action);
    });
    byId("dashboard-refresh")?.addEventListener("click", () => {
      Ao.DataCache.invalidate();
      loadDashboard();
    });
  }

  function init() {
    bindControls();
  }

  Ao.DailyDashboard = {
    init,
    loadDashboard,
    loadAttention,
    handleQuickAction,
    handleAttention,
  };
})(window.AgenticOs);

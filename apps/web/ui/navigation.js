"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initNavigation(Ao) {
  const AREA_VIEWS = Object.freeze({
    home: ["overview"],
    environments: ["environment-list", "tools", "agentic", "agents", "harnesses", "fleet"],
    sessions: ["chat", "vibe-coding", "sessions", "logs", "memory"],
    capabilities: ["skills", "catalog"],
    changes: ["change-center", "approvals", "audit"],
    settings: ["settings-home"],
  });

  const LEGACY_VIEW_AREA = Object.freeze({
    overview: "home",
    tools: "environments",
    agentic: "environments",
    agents: "environments",
    harnesses: "environments",
    fleet: "environments",
    chat: "sessions",
    "vibe-coding": "sessions",
    sessions: "sessions",
    logs: "sessions",
    memory: "sessions",
    skills: "capabilities",
    catalog: "capabilities",
    approvals: "changes",
    audit: "changes",
  });

  const VIEW_LABELS = Object.freeze({
    overview: "首頁",
    "environment-list": "環境總覽",
    tools: "工具探索",
    agentic: "Agentic 盤點",
    agents: "Harness 實例",
    harnesses: "原生設定",
    fleet: "健康與容量",
    chat: "聊天啟動",
    "vibe-coding": "Vibe Coding",
    sessions: "執行紀錄",
    logs: "日誌",
    memory: "記憶",
    skills: "Skills / MCP",
    catalog: "介面目錄",
    "change-center": "變更中心",
    approvals: "核准",
    audit: "稽核",
    "settings-home": "設定",
  });

  let activeArea = "home";
  let activeView = "overview";
  let initialized = false;

  function renderViewSwitcher(area) {
    const switcher = document.getElementById("area-view-switcher");
    if (!switcher) {
      return;
    }
    const views = AREA_VIEWS[area] || [];
    switcher.replaceChildren();
    switcher.hidden = views.length <= 1;
    views.forEach((view) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "view-switcher__button";
      button.dataset.openArea = area;
      button.dataset.openView = view;
      button.textContent = VIEW_LABELS[view] || view;
      const selected = view === activeView;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
      switcher.append(button);
    });
  }

  function show(area, view = AREA_VIEWS[area]?.[0], options = {}) {
    if (!AREA_VIEWS[area] || !AREA_VIEWS[area].includes(view)) {
      throw new Error(`Unknown navigation target: ${area}/${view}`);
    }
    activeArea = area;
    activeView = view;
    document.querySelectorAll("[data-area]").forEach((button) => {
      const selected = button.dataset.area === area;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
    });
    document.querySelectorAll("[data-view]").forEach((panel) => {
      const selected = panel.dataset.view === view;
      panel.classList.toggle("is-active", selected);
      panel.hidden = !selected;
    });
    renderViewSwitcher(area);
    document.dispatchEvent(
      new CustomEvent("agentic-os:navigation", {
        detail: { area, view, skipLoad: Boolean(options.skipLoad) },
      }),
    );
  }

  function init() {
    if (initialized) {
      return;
    }
    initialized = true;
    document.querySelectorAll("[data-area]").forEach((button) => {
      button.addEventListener("click", () => show(button.dataset.area));
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-open-view]");
      if (!button) {
        return;
      }
      show(button.dataset.openArea, button.dataset.openView);
    });
    show(activeArea, activeView);
  }

  function current() {
    return { area: activeArea, view: activeView };
  }

  function areaForView(view) {
    if (view === "environment-list") {
      return "environments";
    }
    if (view === "change-center") {
      return "changes";
    }
    if (view === "settings-home") {
      return "settings";
    }
    return LEGACY_VIEW_AREA[view] || null;
  }

  Ao.Navigation = {
    AREA_VIEWS,
    LEGACY_VIEW_AREA,
    VIEW_LABELS,
    init,
    show,
    current,
    areaForView,
  };
})(window.AgenticOs);

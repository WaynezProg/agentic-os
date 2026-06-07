"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initWorkspaceManager(Ao) {
  const CWD_INPUT_IDS = Object.freeze([
    "profile-cwd-input",
    "setup-cwd",
    "run-cwd",
    "policy-eval-cwd",
  ]);

  let activeCwd = "";

  function byId(id) {
    return document.getElementById(id);
  }

  function getActiveCwd() {
    return activeCwd;
  }

  function appendCwdQuery(path) {
    const cwd = getActiveCwd();
    if (!cwd) {
      return path;
    }
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}cwd=${encodeURIComponent(cwd)}`;
  }

  function syncCwdInputs(path) {
    const value = path || "";
    CWD_INPUT_IDS.forEach((id) => {
      const element = byId(id);
      if (element) {
        element.value = value;
      }
    });
  }

  function emitChanged() {
    document.dispatchEvent(
      new CustomEvent("workspace-changed", { detail: { cwd: activeCwd || "" } }),
    );
  }

  function renderSelector(workspaces) {
    const select = byId("workspace-select");
    if (!select) {
      return;
    }
    const rows = Array.isArray(workspaces) ? workspaces : [];
    if (!rows.length) {
      select.innerHTML = '<option value="">（尚無工作區）</option>';
      return;
    }
    select.innerHTML = rows
      .map((workspace) => {
        const path = workspace.path || "";
        const label = workspace.label || path;
        const selected = path === activeCwd ? " selected" : "";
        return `<option value="${escapeAttr(path)}"${selected}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

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

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.workspace") ?? Ao.isLocalWritable();
  }

  function toggleChrome() {
    const writable = isWritable();
    const addBtn = byId("workspace-add");
    const pathInput = byId("workspace-path-input");
    if (addBtn) {
      addBtn.hidden = !writable;
    }
    if (pathInput) {
      pathInput.hidden = !writable;
    }
  }

  async function loadFromServer() {
    const data = await Ao.apiFetch(Ao.buildEndpoint("workspaces"));
    activeCwd = data.active || "";
    renderSelector(data.workspaces);
    syncCwdInputs(activeCwd);
    toggleChrome();
    return data;
  }

  async function setActiveCwd(path) {
    const trimmed = String(path || "").trim();
    if (!trimmed) {
      return;
    }
    if (isWritable()) {
      await Ao.apiFetch(Ao.buildEndpoint("workspacesActive"), {
        method: "PUT",
        body: JSON.stringify({ path: trimmed }),
      });
    }
    activeCwd = trimmed;
    syncCwdInputs(trimmed);
    renderSelector((await Ao.apiFetch(Ao.buildEndpoint("workspaces"))).workspaces);
    emitChanged();
  }

  async function addWorkspace(path) {
    const trimmed = String(path || "").trim();
    if (!trimmed) {
      return;
    }
    await Ao.postJson(Ao.buildEndpoint("workspaces"), { path: trimmed, set_active: true });
    await loadFromServer();
    emitChanged();
  }

  function bindControls() {
    const select = byId("workspace-select");
    if (select) {
      select.addEventListener("change", () => {
        const path = select.value;
        if (path) {
          setActiveCwd(path).catch((error) => {
            const status = byId("workspace-status");
            if (status) {
              status.textContent = error.message;
              status.classList.add("is-error");
            }
          });
        }
      });
    }
    byId("workspace-add")?.addEventListener("click", () => {
      const path = byId("workspace-path-input")?.value || "";
      addWorkspace(path).catch((error) => {
        const status = byId("workspace-status");
        if (status) {
          status.textContent = error.message;
          status.classList.add("is-error");
        }
      });
    });
    CWD_INPUT_IDS.forEach((id) => {
      const element = byId(id);
      if (!element) {
        return;
      }
      element.addEventListener("change", () => {
        const path = element.value.trim();
        if (path && path !== activeCwd && isWritable()) {
          setActiveCwd(path).catch(() => {
            syncCwdInputs(activeCwd);
          });
        }
      });
    });
  }

  async function init() {
    bindControls();
    toggleChrome();
    try {
      await loadFromServer();
      const status = byId("workspace-status");
      if (status) {
        status.textContent = activeCwd ? activeCwd : "未選工作區";
        status.classList.remove("is-error");
      }
    } catch (error) {
      const status = byId("workspace-status");
      if (status) {
        status.textContent = error.message;
        status.classList.add("is-error");
      }
    }
  }

  Ao.Workspace = {
    init,
    loadFromServer,
    getActiveCwd,
    setActiveCwd,
    appendCwdQuery,
    syncCwdInputs,
    isWritable,
    toggleChrome,
  };
})(window.AgenticOs);

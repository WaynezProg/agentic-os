"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initProviderSwitchboard(Ao) {
  const PATCH_SOURCE = "web-provider-switchboard";

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let pendingProfile = null;
  let pendingScope = "local";
  let previewBaseMtime = null;

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setMessage(message, isError = false) {
    const target = byId("provider-switchboard-message");
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function cwdQuery() {
    const cwd = Ao.Workspace?.getActiveCwd?.() || "";
    return cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
  }

  function resolvedCwd() {
    return Ao.Workspace?.getActiveCwd?.() || "";
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.profile") ?? Ao.isLocalWritable();
  }

  function toggleChrome() {
    const writable = isWritable();
    const controls = byId("provider-switchboard-controls");
    if (controls) {
      controls.hidden = !writable;
    }
  }

  function setText(id, value) {
    const element = byId(id);
    if (element) {
      element.textContent = value || "-";
    }
  }

  async function loadDashboardBits() {
    const cwd = resolvedCwd();
    const query = cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
    try {
      const dashboard = await Ao.apiFetch(`${Ao.buildEndpoint("workspacesDashboard")}${query}`);
      const profile = dashboard.active_profile || "-";
      const provider = dashboard.provider || "-";
      const model = dashboard.model || "-";
      setText("switchboard-active-profile-panel", profile);
      setText("switchboard-provider-panel", provider);
      setText("switchboard-model-panel", model);
      setText("switchboard-topbar-profile", profile);
      setText("switchboard-topbar-provider", provider);
      setText("switchboard-topbar-model", model);
      setText("switchboard-harness", dashboard.harness_id || "-");
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function loadLastSession() {
    const cwd = resolvedCwd();
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("sessions"));
      const sessions = Array.isArray(data.sessions) ? data.sessions : [];
      const filtered = cwd
        ? sessions.filter((session) => String(session.cwd || "") === cwd)
        : sessions;
      const latest = filtered[0];
      if (!latest) {
        byId("switchboard-last-session").textContent = "-";
        byId("switchboard-last-provider").textContent = "-";
        byId("switchboard-last-model").textContent = "-";
        return;
      }
      byId("switchboard-last-session").textContent = latest.id || "-";
      byId("switchboard-last-provider").textContent = latest.resolved_provider || "-";
      byId("switchboard-last-model").textContent = latest.resolved_model || "-";
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function loadProfileChoices() {
    const body = byId("provider-switchboard-profiles-body");
    if (!body) {
      return;
    }
    body.innerHTML = '<tr><td colspan="5">載入中…</td></tr>';
    try {
      const data = await Ao.apiFetch(`${Ao.buildEndpoint("profiles")}${cwdQuery()}`);
      const profiles = Array.isArray(data.run_profiles) ? data.run_profiles : [];
      if (!profiles.length) {
        body.innerHTML = '<tr><td colspan="5">尚無 profile。</td></tr>';
        return;
      }
      const active = byId("switchboard-active-profile-panel")?.textContent || "";
      body.innerHTML = profiles
        .map((profile) => {
          const isActive = profile.name === active;
          return `
            <tr>
              <td>${escapeHtml(profile.name)}</td>
              <td>${escapeHtml(profile.provider)}</td>
              <td>${escapeHtml(profile.model)}</td>
              <td>${escapeHtml(profile.harness_id)}</td>
              <td>
                <button type="button" data-action="switchboard-use-profile"
                  data-profile-name="${escapeHtml(profile.name)}"
                  data-profile-scope="${escapeHtml(profile.scope || "local")}"
                  ${isActive ? "disabled" : ""}>切換</button>
              </td>
            </tr>`;
        })
        .join("");
    } catch (error) {
      body.innerHTML = `<tr><td colspan="5" class="message is-error">${escapeHtml(error.message)}</td></tr>`;
    }
  }

  function buildProfileQuery(scope, dryRun, baseMtime) {
    const params = new URLSearchParams({ scope, dry_run: dryRun ? "true" : "false", source: PATCH_SOURCE });
    const cwd = resolvedCwd();
    if (cwd) {
      params.set("cwd", cwd);
    }
    if (baseMtime !== null && baseMtime !== undefined) {
      params.set("base_mtime", String(baseMtime));
    }
    return params.toString();
  }

  async function switchProfile(name, scopeHint) {
    if (!isWritable()) {
      return;
    }
    setMessage(`切換 profile：${name}…`);
    try {
      const detail = await Ao.apiFetch(
        `${Ao.buildEndpoint("profileDetail", { name })}${cwdQuery()}`,
      );
      const scope = detail.scope || scopeHint || "local";
      pendingProfile = {
        name: detail.name,
        harness_id: detail.harness_id,
        provider: detail.provider,
        model: detail.model,
        message_prefix: detail.message_prefix || "",
        default_env: detail.default_env || {},
        max_tokens_budget: detail.max_tokens_budget,
        cwd_root: detail.cwd_root,
        cwd_prefix: detail.cwd_prefix,
        repo_glob: detail.repo_glob,
      };
      pendingScope = scope;
      const dryPath = `${Ao.buildEndpoint("profiles")}?${buildProfileQuery(scope, true, null)}`;
      const preview = await Ao.postJson(dryPath, pendingProfile);
      previewBaseMtime = preview.base_mtime ?? null;
      const applyPath = `${Ao.buildEndpoint("profiles")}?${buildProfileQuery(scope, false, previewBaseMtime)}`;
      await Ao.postJson(applyPath, pendingProfile);
      const projectPath = resolvedCwd();
      if (projectPath) {
        const encoded = projectPath.split("/").map(encodeURIComponent).join("/");
        await Ao.postJson(`${Ao.buildEndpoint("profileBind", { project_path: encoded })}`, {
          run_profile: name,
        });
      }
      pendingProfile = null;
      previewBaseMtime = null;
      setMessage(`已切換至 profile：${name}`);
      await refresh();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function refresh() {
    toggleChrome();
    await Promise.allSettled([loadDashboardBits(), loadLastSession(), loadProfileChoices()]);
  }

  function bindControls() {
    byId("provider-switchboard-refresh")?.addEventListener("click", () => {
      refresh();
    });
    document.addEventListener("workspace-changed", () => {
      refresh();
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action='switchboard-use-profile']");
      if (!button) {
        return;
      }
      switchProfile(button.dataset.profileName, button.dataset.profileScope || "local");
    });
  }

  function init() {
    bindControls();
    refresh();
  }

  Ao.ProviderSwitchboard = {
    init,
    refresh,
    switchProfile,
    toggleChrome,
  };
})(window.AgenticOs);

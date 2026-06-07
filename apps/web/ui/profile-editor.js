"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initProfileEditor(Ao) {
  const PATCH_SOURCE = "web-profile-editor";
  const ENV_VAR_PATTERN = /^[A-Z][A-Z0-9_]*$/;

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let previewBaseMtime = null;
  let pendingProfile = null;
  let pendingScope = "local";

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Missing element: ${id}`);
    }
    return element;
  }

  function isWritable() {
    return Ao.isLocalWritable();
  }

  function toggleEditorChrome() {
    const writable = isWritable();
    const controls = document.getElementById("profile-editor-controls");
    const history = document.getElementById("profile-patch-history");
    if (controls) {
      controls.hidden = !writable;
    }
    if (history) {
      history.hidden = !writable;
    }
  }

  function setMessage(message, isError = false) {
    const target = byId("profile-patch-message");
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function clearValidationErrors() {
    const target = byId("profile-validation-errors");
    target.textContent = "";
    target.hidden = true;
  }

  function renderValidationErrors(errors) {
    const target = byId("profile-validation-errors");
    const list = Array.isArray(errors) ? errors : [String(errors)];
    target.hidden = false;
    target.innerHTML = list.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
  }

  function resetApplyState() {
    previewBaseMtime = null;
    pendingProfile = null;
    byId("profile-apply").disabled = true;
  }

  function formatDiff(diff) {
    if (!diff) {
      return "（無 diff）";
    }
    return JSON.stringify(diff, null, 2);
  }

  function parseEnvVarNames(text) {
    return String(text || "")
      .split(",")
      .map((key) => key.trim())
      .filter((key) => key.length > 0);
  }

  function validateEnvVarNames(names) {
    const invalid = names.filter((name) => !ENV_VAR_PATTERN.test(name));
    if (invalid.length) {
      throw new Error(`default_env 僅接受 env-var 名稱：${invalid.join(", ")}`);
    }
  }

  function buildProfileFromForm() {
    const name = byId("profile-name").value.trim();
    const harnessId = byId("profile-harness-id").value.trim();
    const provider = byId("profile-provider").value.trim();
    const model = byId("profile-model").value.trim();
    if (!name || !harnessId || !provider || !model) {
      throw new Error("name、harness_id、provider、model 為必填");
    }
    const envNames = parseEnvVarNames(byId("profile-default-env").value);
    validateEnvVarNames(envNames);
    const profile = {
      name,
      harness_id: harnessId,
      provider,
      model,
      message_prefix: byId("profile-message-prefix").value,
      default_env: Object.fromEntries(envNames.map((key) => [key, key])),
    };
    const budgetRaw = byId("profile-max-tokens").value.trim();
    if (budgetRaw) {
      const budget = Number(budgetRaw);
      if (!Number.isInteger(budget) || budget < 0) {
        throw new Error("max_tokens_budget 必須是非負整數");
      }
      profile.max_tokens_budget = budget;
    }
    const cwdRoot = byId("profile-cwd-root").value.trim();
    if (cwdRoot) {
      profile.cwd_root = cwdRoot;
    }
    const cwdPrefix = byId("profile-cwd-prefix").value.trim();
    if (cwdPrefix) {
      profile.cwd_prefix = cwdPrefix;
    }
    const repoGlob = byId("profile-repo-glob").value.trim();
    if (repoGlob) {
      profile.repo_glob = repoGlob;
    }
    return profile;
  }

  function fillFormFromProfile(profile) {
    byId("profile-name").value = profile.name || "";
    byId("profile-harness-id").value = profile.harness_id || "";
    byId("profile-provider").value = profile.provider || "";
    byId("profile-model").value = profile.model || "";
    byId("profile-message-prefix").value = profile.message_prefix || "";
    byId("profile-max-tokens").value =
      profile.max_tokens_budget === null || profile.max_tokens_budget === undefined
        ? ""
        : String(profile.max_tokens_budget);
    const envKeys = profile.default_env ? Object.keys(profile.default_env) : [];
    byId("profile-default-env").value = envKeys.join(", ");
    byId("profile-cwd-root").value = profile.cwd_root || "";
    byId("profile-cwd-prefix").value = profile.cwd_prefix || "";
    byId("profile-repo-glob").value = profile.repo_glob || "";
  }

  function buildProfileQuery(scope, dryRun, baseMtime) {
    const params = new URLSearchParams({ scope, dry_run: dryRun ? "true" : "false" });
    if (baseMtime !== null && baseMtime !== undefined) {
      params.set("base_mtime", String(baseMtime));
    }
    params.set("source", PATCH_SOURCE);
    return params.toString();
  }

  async function loadProfiles() {
    toggleEditorChrome();
    const body = byId("profile-list-body");
    body.innerHTML = "<tr><td colspan=\"5\">載入中…</td></tr>";
    clearValidationErrors();
    resetApplyState();
    byId("profile-diff-preview").textContent = "選擇或建立 profile 後按「預覽變更」。";
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("profiles"));
      const profiles = Array.isArray(data.run_profiles) ? data.run_profiles : [];
      const bindings = Array.isArray(data.project_bindings) ? data.project_bindings : [];
      renderProfileList(profiles, bindings, data.cwd);
      if (isWritable()) {
        await Ao.PatchRollback.loadPatchHistory({
          harness: "agentic_os",
          containerId: "profile-patch-history-body",
          emptyMessage: "尚無 profile 修補紀錄。",
        });
      }
    } catch (error) {
      body.innerHTML = `<tr><td colspan="5" class="message is-error">${escapeHtml(error.message)}</td></tr>`;
    }
  }

  function renderProfileList(profiles, bindings, cwd) {
    const body = byId("profile-list-body");
    if (!profiles.length) {
      body.innerHTML = "<tr><td colspan=\"5\">尚無 run profile。</td></tr>";
    } else {
      body.innerHTML = profiles
        .map(
          (profile) => `
        <tr>
          <td>${escapeHtml(profile.name)}</td>
          <td>${escapeHtml(profile.harness_id)}</td>
          <td>${escapeHtml(profile.provider)}</td>
          <td>${escapeHtml(profile.model)}</td>
          <td>
            <button type="button" data-action="profile-select" data-profile-name="${escapeHtml(profile.name)}">編輯</button>
          </td>
        </tr>`,
        )
        .join("");
    }
    const bindingBody = byId("profile-bindings-body");
    if (!bindings.length) {
      bindingBody.innerHTML = "<tr><td colspan=\"3\">尚無 project 綁定。</td></tr>";
    } else {
      bindingBody.innerHTML = bindings
        .map(
          (row) => `
        <tr>
          <td class="cell-code">${escapeHtml(row.project_path)}</td>
          <td>${escapeHtml(row.run_profile)}</td>
          <td>${row.project_path === cwd ? "（目前 cwd）" : "-"}</td>
        </tr>`,
        )
        .join("");
    }
  }

  async function selectProfile(name) {
    try {
      const data = await Ao.apiFetch(Ao.buildEndpoint("profileDetail", { name }));
      fillFormFromProfile(data);
      setMessage(`已載入 profile：${name}`);
      resetApplyState();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function dryRunProfile() {
    clearValidationErrors();
    resetApplyState();
    const preview = byId("profile-diff-preview");
    preview.textContent = "預覽中…";
    try {
      const profile = buildProfileFromForm();
      const scope = byId("profile-scope").value;
      pendingScope = scope;
      pendingProfile = profile;
      const path = `${Ao.buildEndpoint("profiles")}?${buildProfileQuery(scope, true, null)}`;
      const result = await Ao.postJson(path, profile);
      previewBaseMtime = result.base_mtime ?? null;
      preview.textContent = formatDiff(result.diff);
      byId("profile-apply").disabled = false;
      setMessage(
        previewBaseMtime === null || previewBaseMtime === undefined
          ? "預覽完成，確認後可套用。"
          : `預覽完成，base_mtime=${previewBaseMtime}。`,
      );
    } catch (error) {
      preview.textContent = formatDiff(error.payload?.detail || error.message);
      handlePatchError(error);
    }
  }

  async function applyProfile() {
    if (!pendingProfile) {
      setMessage("請先預覽變更。", true);
      return;
    }
    clearValidationErrors();
    try {
      const path = `${Ao.buildEndpoint("profiles")}?${buildProfileQuery(pendingScope, false, previewBaseMtime)}`;
      await Ao.postJson(path, pendingProfile);
      byId("profile-diff-preview").textContent = "已套用。";
      setMessage(`已套用 profile：${pendingProfile.name}`);
      resetApplyState();
      await loadProfiles();
    } catch (error) {
      if (error.status === 409 && error.payload?.detail?.error === "stale_target") {
        setMessage("檔案已變更（stale_target），已重新預覽。", true);
        await dryRunProfile();
        return;
      }
      handlePatchError(error);
    }
  }

  async function deleteProfile(cascade = false) {
    const name = byId("profile-name").value.trim();
    if (!name) {
      setMessage("請先選擇要刪除的 profile。", true);
      return;
    }
    const scope = byId("profile-scope").value;
    const params = new URLSearchParams({
      scope,
      cascade: cascade ? "true" : "false",
      source: PATCH_SOURCE,
    });
    try {
      const result = await Ao.apiFetch(
        `${Ao.buildEndpoint("profileDelete", { name })}?${params}`,
        { method: "DELETE" },
      );
      setMessage(`已刪除 profile：${name}（patch_id=${result.patch_id}）`);
      byId("profile-bound-projects").hidden = true;
      resetApplyState();
      await loadProfiles();
    } catch (error) {
      if (error.status === 409 && error.payload?.detail?.error === "bound" && !cascade) {
        const projects = error.payload.detail.projects || [];
        const panel = byId("profile-bound-projects");
        panel.hidden = false;
        panel.textContent = `此 profile 仍綁定：${projects.join(", ")}。確認 cascade 刪除？`;
        return;
      }
      handlePatchError(error);
    }
  }

  async function bindProject() {
    const projectPath = byId("profile-bind-path").value.trim();
    const runProfile = byId("profile-bind-name").value.trim();
    if (!projectPath || !runProfile) {
      setMessage("bind 需要 project_path 與 run_profile。", true);
      return;
    }
    try {
      const encoded = projectPath.split("/").map(encodeURIComponent).join("/");
      await Ao.postJson(`${Ao.buildEndpoint("profileBind", { project_path: encoded })}`, {
        run_profile: runProfile,
      });
      setMessage(`已綁定 ${projectPath} → ${runProfile}`);
      await loadProfiles();
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  function handlePatchError(error) {
    const detail = error.payload?.detail;
    if (detail && Array.isArray(detail.validation_errors)) {
      renderValidationErrors(detail.validation_errors);
      setMessage("驗證失敗", true);
      return;
    }
    if (error.status === 403 && detail?.error === "forbidden_path") {
      setMessage(detail.message || "forbidden_path", true);
      return;
    }
    setMessage(error.message, true);
  }

  async function reloadAfterRollback() {
    await loadProfiles();
  }

  function bindControls() {
    byId("profile-load").addEventListener("click", () => {
      loadProfiles();
    });
    byId("profile-dry-run").addEventListener("click", () => {
      dryRunProfile();
    });
    byId("profile-apply").addEventListener("click", () => {
      applyProfile();
    });
    byId("profile-delete").addEventListener("click", () => {
      deleteProfile(false);
    });
    byId("profile-delete-cascade").addEventListener("click", () => {
      deleteProfile(true);
    });
    byId("profile-bind-submit").addEventListener("click", () => {
      bindProject();
    });
    byId("profile-new").addEventListener("click", () => {
      fillFormFromProfile({
        name: "",
        harness_id: "",
        provider: "",
        model: "",
        message_prefix: "",
        default_env: {},
      });
      resetApplyState();
      setMessage("建立新 profile。");
    });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action='profile-select']");
      if (!button) {
        return;
      }
      selectProfile(button.dataset.profileName);
    });
  }

  function init() {
    bindControls();
    toggleEditorChrome();
    resetApplyState();
  }

  Ao.ProfileEditor = {
    init,
    loadProfiles,
    reloadAfterRollback,
    isWritable,
  };
})(window.AgenticOs);

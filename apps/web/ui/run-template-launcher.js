"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initRunTemplateLauncher(Ao) {
  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let selectedTemplateId = null;

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

  function cwdQuery() {
    const cwd = Ao.Workspace?.getActiveCwd?.() || "";
    return cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.run-template") ?? Ao.isLocalWritable();
  }

  function toggleChrome() {
    const writable = isWritable();
    const controls = document.getElementById("run-template-editor-controls");
    if (controls) {
      controls.hidden = !writable;
    }
  }

  function setMessage(message, isError = false) {
    const target = byId("run-template-message");
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function parseVariables(text) {
    return String(text || "")
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }

  function buildVariableInputs(required) {
    const container = byId("run-template-variables");
    const vars = Array.isArray(required) ? required : [];
    if (!vars.length) {
      container.innerHTML = '<p class="message">此範本無變數。</p>';
      return;
    }
    container.innerHTML = vars
      .map(
        (name) => `
        <div class="eval-grid eval-grid--compact">
          <label for="rt-var-${escapeHtml(name)}">${escapeHtml(name)}</label>
          <input id="rt-var-${escapeHtml(name)}" type="text" data-rt-var="${escapeHtml(name)}" spellcheck="false" />
        </div>`,
      )
      .join("");
  }

  function collectVariables(required) {
    const vars = Array.isArray(required) ? required : [];
    const values = {};
    vars.forEach((name) => {
      const input = document.querySelector(`[data-rt-var="${name}"]`);
      values[name] = input?.value?.trim() || "";
    });
    return values;
  }

  function fillEditorForm(template) {
    byId("rt-name").value = template.name || "";
    byId("rt-harness-id").value = template.harness_id || "";
    byId("rt-cwd").value = template.cwd || Ao.Workspace?.getActiveCwd?.() || "";
    byId("rt-profile").value = template.profile_name || "";
    byId("rt-message-template").value = template.message_template || "";
    byId("rt-required-variables").value = (template.required_variables || []).join(", ");
    byId("rt-approval-hint").value = template.approval_policy_hint || "";
    buildVariableInputs(template.required_variables || []);
  }

  function buildPayloadFromForm() {
    return {
      name: byId("rt-name").value.trim(),
      harness_id: byId("rt-harness-id").value.trim(),
      cwd: byId("rt-cwd").value.trim() || Ao.Workspace?.getActiveCwd?.() || "",
      profile_name: byId("rt-profile").value.trim() || null,
      message_template: byId("rt-message-template").value,
      required_variables: parseVariables(byId("rt-required-variables").value),
      approval_policy_hint: byId("rt-approval-hint").value.trim(),
    };
  }

  async function loadTemplates() {
    toggleChrome();
    const body = byId("run-template-list-body");
    body.innerHTML = '<tr><td colspan="5">載入中…</td></tr>';
    try {
      const data = await Ao.apiFetch(`${Ao.buildEndpoint("runTemplates")}${cwdQuery()}`);
      const templates = Array.isArray(data.templates) ? data.templates : [];
      if (!templates.length) {
        body.innerHTML = '<tr><td colspan="5">尚無 run template。</td></tr>';
        return;
      }
      body.innerHTML = templates
        .map(
          (template) => `
          <tr>
            <td>${escapeHtml(template.name)}</td>
            <td>${escapeHtml(template.harness_id)}</td>
            <td class="cell-code">${escapeHtml(template.cwd)}</td>
            <td>${escapeHtml((template.required_variables || []).join(", "))}</td>
            <td>
              <button type="button" data-action="rt-select" data-template-id="${escapeHtml(template.id)}">編輯</button>
              <button type="button" data-action="rt-launch" data-template-id="${escapeHtml(template.id)}">啟動</button>
            </td>
          </tr>`,
        )
        .join("");
    } catch (error) {
      body.innerHTML = `<tr><td colspan="5" class="message is-error">${escapeHtml(error.message)}</td></tr>`;
    }
  }

  async function selectTemplate(templateId) {
    selectedTemplateId = templateId;
    const template = await Ao.apiFetch(
      Ao.buildEndpoint("runTemplateDetail", { template_id: templateId }),
    );
    fillEditorForm(template);
    byId("run-template-editor-controls").hidden = false;
    setMessage(`已載入範本：${template.name}`);
  }

  async function saveTemplate() {
    const payload = buildPayloadFromForm();
    if (!payload.name || !payload.harness_id || !payload.cwd || !payload.message_template) {
      setMessage("name、harness_id、cwd、message_template 為必填。", true);
      return;
    }
    if (selectedTemplateId) {
      await Ao.apiFetch(Ao.buildEndpoint("runTemplateDetail", { template_id: selectedTemplateId }), {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setMessage(`已更新範本：${payload.name}`);
    } else {
      const created = await Ao.postJson(Ao.buildEndpoint("runTemplates"), payload);
      selectedTemplateId = created.id;
      setMessage(`已建立範本：${payload.name}`);
    }
    await loadTemplates();
  }

  async function deleteTemplate() {
    if (!selectedTemplateId) {
      setMessage("請先選擇範本。", true);
      return;
    }
    await Ao.apiFetch(Ao.buildEndpoint("runTemplateDetail", { template_id: selectedTemplateId }), {
      method: "DELETE",
    });
    selectedTemplateId = null;
    byId("run-template-editor-controls").hidden = true;
    setMessage("已刪除範本。");
    await loadTemplates();
  }

  async function previewTemplate(templateId) {
    const id = templateId || selectedTemplateId;
    if (!id) {
      setMessage("請先選擇範本。", true);
      return;
    }
    const template = await Ao.apiFetch(Ao.buildEndpoint("runTemplateDetail", { template_id: id }));
    const variables = collectVariables(template.required_variables || []);
    const params = new URLSearchParams({
      variables: JSON.stringify(variables),
    });
    const preview = await Ao.apiFetch(
      `${Ao.buildEndpoint("runTemplatePreview", { template_id: id })}?${params}`,
    );
    byId("run-template-preview").textContent = JSON.stringify(preview, null, 2);
    setMessage("預覽完成。");
  }

  async function launchTemplate(templateId) {
    const id = templateId || selectedTemplateId;
    if (!id) {
      setMessage("請先選擇範本。", true);
      return;
    }
    const template = await Ao.apiFetch(Ao.buildEndpoint("runTemplateDetail", { template_id: id }));
    const variables = collectVariables(template.required_variables || []);
    const result = await Ao.postJson(Ao.buildEndpoint("sessionRun"), {
      template_id: id,
      variables,
    });
    byId("run-template-preview").textContent = JSON.stringify(result, null, 2);
    setMessage(`已啟動 session：${result.id || "-"}`);
  }

  function newTemplate() {
    selectedTemplateId = null;
    fillEditorForm({
      name: "",
      harness_id: "",
      cwd: Ao.Workspace?.getActiveCwd?.() || "",
      message_template: "",
      required_variables: [],
      profile_name: "",
      approval_policy_hint: "",
    });
    byId("run-template-editor-controls").hidden = false;
    setMessage("建立新範本。");
  }

  function bindControls() {
    byId("run-template-load").addEventListener("click", () => {
      loadTemplates();
    });
    byId("rt-save").addEventListener("click", () => {
      saveTemplate().catch((error) => setMessage(error.message, true));
    });
    byId("rt-delete").addEventListener("click", () => {
      deleteTemplate().catch((error) => setMessage(error.message, true));
    });
    byId("rt-preview").addEventListener("click", () => {
      previewTemplate().catch((error) => setMessage(error.message, true));
    });
    byId("rt-launch-form").addEventListener("click", () => {
      launchTemplate().catch((error) => setMessage(error.message, true));
    });
    byId("run-template-new").addEventListener("click", newTemplate);
    byId("rt-required-variables").addEventListener("change", () => {
      buildVariableInputs(parseVariables(byId("rt-required-variables").value));
    });
    document.addEventListener("workspace-changed", () => {
      const cwd = Ao.Workspace?.getActiveCwd?.() || "";
      if (byId("rt-cwd") && !byId("rt-cwd").value.trim()) {
        byId("rt-cwd").value = cwd;
      }
    });
    document.addEventListener("click", (event) => {
      const selectBtn = event.target.closest("[data-action='rt-select']");
      if (selectBtn) {
        selectTemplate(selectBtn.dataset.templateId).catch((error) => setMessage(error.message, true));
        return;
      }
      const launchBtn = event.target.closest("[data-action='rt-launch']");
      if (launchBtn) {
        selectTemplate(launchBtn.dataset.templateId)
          .then(() => launchTemplate(launchBtn.dataset.templateId))
          .catch((error) => setMessage(error.message, true));
      }
    });
  }

  function init() {
    bindControls();
    toggleChrome();
    loadTemplates().catch(() => {});
  }

  Ao.RunTemplateLauncher = {
    init,
    loadTemplates,
    launchTemplate,
    selectTemplate,
    toggleChrome,
  };
})(window.AgenticOs);

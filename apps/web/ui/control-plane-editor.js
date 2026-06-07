"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initControlPlaneEditor(Ao) {
  const ENV_NAME_REGEX = /^[A-Z][A-Z0-9_]*$/;
  const SECRET_VALUE_PATTERN =
    /(token|secret|password|passwd|apikey|api_key|api-key|authorization|bearer)=([^\s&]+)/i;
  const SECRET_FLAG_PATTERN =
    /(--(?:token|secret|password|passwd|api-key|api_key|authorization|bearer))\s+([^\s&]+)/i;

  const HTML_ENTITIES = Object.freeze({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  });

  let editTarget = null;

  function escapeHtml(value) {
    const text = value === null || value === undefined || value === "" ? "-" : String(value);
    return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Missing element: ${id}`);
    }
    return element;
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.control-plane") ?? Ao.isLocalWritable();
  }

  function setMessage(message, isError = false) {
    const target = byId("control-plane-message");
    target.textContent = message;
    target.classList.toggle("is-error", isError);
  }

  function clearValidationErrors() {
    byId("control-plane-validation-errors").hidden = true;
    byId("control-plane-validation-errors").textContent = "";
  }

  function renderValidationErrors(errors) {
    const target = byId("control-plane-validation-errors");
    const list = Array.isArray(errors) ? errors : [String(errors)];
    target.hidden = false;
    target.innerHTML = list.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
  }

  function toggleEditorChrome() {
    const writable = isWritable();
    const controls = document.getElementById("control-plane-editor-controls");
    if (controls) {
      controls.hidden = !writable;
    }
    document.querySelectorAll(".control-plane-action-col").forEach((cell) => {
      cell.hidden = !writable;
    });
    document.querySelectorAll("th.control-plane-action-col").forEach((cell) => {
      cell.hidden = !writable;
    });
  }

  function parseCommaList(text) {
    return String(text || "")
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }

  function parseArgs(text) {
    return String(text || "")
      .trim()
      .split(/\s+/)
      .filter((part) => part.length > 0);
  }

  function looksLikeSecretValue(value) {
    const text = String(value || "");
    if (!text || text.includes("[REDACTED]")) {
      return false;
    }
    if (SECRET_VALUE_PATTERN.test(text) || SECRET_FLAG_PATTERN.test(text)) {
      return true;
    }
    if (text.includes("=") && /(token|secret|password|api.?key|bearer)/i.test(text)) {
      return true;
    }
    return false;
  }

  function validateEnvKeys(keys) {
    const errors = [];
    keys.forEach((key) => {
      if (!ENV_NAME_REGEX.test(key)) {
        errors.push(`env key 必須為大寫名稱（^[A-Z][A-Z0-9_]*$）：${key}`);
      }
      if (looksLikeSecretValue(key)) {
        errors.push(`env key 不可含 secret 值：${key}`);
      }
    });
    return errors;
  }

  function validateNoSecretsInFields(fields) {
    const errors = [];
    fields.forEach(({ label, value }) => {
      if (looksLikeSecretValue(value)) {
        errors.push(`${label} 不可含明碼 secret；請改用 env-var 名稱引用`);
      }
    });
    return errors;
  }

  function hideAllForms() {
    ["control-plane-skill-form", "control-plane-mcp-form", "control-plane-policy-form"].forEach(
      (id) => {
        const el = document.getElementById(id);
        if (el) {
          el.hidden = true;
        }
      },
    );
    editTarget = null;
  }

  function cancelEdit() {
    hideAllForms();
    clearValidationErrors();
    setMessage("");
  }

  function showSkillForm(skillId, record) {
    hideAllForms();
    editTarget = { domain: "skills", id: skillId };
    byId("control-plane-skill-id").textContent = skillId;
    byId("cp-skill-label").value = record?.label || "";
    byId("cp-skill-description").value = record?.description || "";
    byId("cp-skill-content").value = record?.description || "";
    byId("cp-skill-source").value = record?.source || "local";
    byId("cp-skill-entrypoint").value = record?.entrypoint || "";
    byId("cp-skill-tags").value = asArray(record?.tags).join(", ");
    byId("cp-skill-enabled").checked = record?.enabled !== false;
    byId("control-plane-skill-form").hidden = false;
    setMessage(`編輯技能 ${skillId}`);
  }

  function showMcpForm(serverId, record) {
    hideAllForms();
    editTarget = { domain: "mcp", id: serverId };
    byId("control-plane-mcp-id").textContent = serverId;
    byId("cp-mcp-label").value = record?.label || "";
    byId("cp-mcp-description").value = record?.description || "";
    byId("cp-mcp-transport").value = record?.transport || "stdio";
    // Operator re-enters command/url — never pre-fill redacted values (L2).
    byId("cp-mcp-command").value = "";
    byId("cp-mcp-args").value = "";
    byId("cp-mcp-url").value = "";
    byId("cp-mcp-env").value = asArray(record?.env_keys).join(", ");
    byId("cp-mcp-enabled").checked = record?.enabled !== false;
    byId("control-plane-mcp-form").hidden = false;
    setMessage(`編輯 MCP ${serverId} — 重新輸入 command/url（預覽已 redact，不可回送）`);
  }

  function showPolicyForm(agentId, record) {
    hideAllForms();
    editTarget = { domain: "policy", id: agentId };
    byId("control-plane-policy-id").textContent = agentId;
    byId("cp-policy-enabled").checked = record?.enabled !== false;
    byId("cp-policy-readonly").checked = record?.readonly === true;
    byId("cp-policy-skills").value = asArray(record?.allowed_skill_ids).join(", ");
    byId("cp-policy-mcp").value = asArray(record?.allowed_mcp_server_ids).join(", ");
    byId("cp-policy-tools").value = asArray(record?.allowed_tool_names).join(", ");
    byId("cp-policy-approval-tools").value = asArray(
      record?.approval_required_tool_names,
    ).join(", ");
    byId("cp-policy-models").value = asArray(record?.allowed_model_ids).join(", ");
    byId("cp-policy-cwd-roots").value = asArray(record?.cwd_roots).join(", ");
    byId("cp-policy-rate-limit").value = String(record?.rate_limit_per_minute ?? 60);
    byId("control-plane-policy-form").hidden = false;
    setMessage(`編輯政策 ${agentId}`);
  }

  async function openEdit(domain, id) {
    clearValidationErrors();
    try {
      let path;
      if (domain === "skills") {
        path = Ao.buildEndpoint("skillDetail", { skill_id: id });
      } else if (domain === "mcp") {
        path = Ao.buildEndpoint("mcpDetail", { server_id: id });
      } else {
        path = Ao.buildEndpoint("policyDetail", { agent_id: id });
      }
      const record = await Ao.apiFetch(path);
      if (domain === "skills") {
        showSkillForm(id, record);
      } else if (domain === "mcp") {
        showMcpForm(id, record);
      } else {
        showPolicyForm(id, record);
      }
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function openCreate(domain) {
    clearValidationErrors();
    const id = window.prompt(
      domain === "skills" ? "新技能 ID" : domain === "mcp" ? "新 MCP ID" : "代理 ID（政策）",
    );
    if (!id || !id.trim()) {
      return;
    }
    const trimmed = id.trim();
    if (domain === "skills") {
      showSkillForm(trimmed, null);
    } else if (domain === "mcp") {
      showMcpForm(trimmed, null);
    } else {
      showPolicyForm(trimmed, null);
    }
  }

  function buildSkillPayload() {
    const content = byId("cp-skill-content").value.trim();
    const summary = byId("cp-skill-description").value.trim();
    return {
      label: byId("cp-skill-label").value.trim(),
      description: content || summary,
      source: byId("cp-skill-source").value.trim() || "local",
      entrypoint: byId("cp-skill-entrypoint").value.trim(),
      tags: parseCommaList(byId("cp-skill-tags").value),
      enabled: byId("cp-skill-enabled").checked,
    };
  }

  function buildMcpPayload(isNew) {
    const command = byId("cp-mcp-command").value.trim();
    const args = parseArgs(byId("cp-mcp-args").value);
    const url = byId("cp-mcp-url").value.trim();
    const envKeys = parseCommaList(byId("cp-mcp-env").value);
    const commandPreview = command ? [command, ...args] : args;
    const payload = {
      label: byId("cp-mcp-label").value.trim(),
      description: byId("cp-mcp-description").value.trim(),
      transport: byId("cp-mcp-transport").value.trim() || "stdio",
      env_keys: envKeys,
      enabled: byId("cp-mcp-enabled").checked,
    };
    if (url) {
      payload.url = url;
      payload.command_preview = [];
    } else if (commandPreview.length || isNew) {
      payload.command_preview = commandPreview;
      payload.url = null;
    } else {
      payload.command_preview = [];
      payload.url = null;
    }
    return payload;
  }

  function buildPolicyPayload() {
    return {
      enabled: byId("cp-policy-enabled").checked,
      readonly: byId("cp-policy-readonly").checked,
      allowed_skill_ids: parseCommaList(byId("cp-policy-skills").value),
      allowed_mcp_server_ids: parseCommaList(byId("cp-policy-mcp").value),
      allowed_tool_names: parseCommaList(byId("cp-policy-tools").value),
      approval_required_tool_names: parseCommaList(byId("cp-policy-approval-tools").value),
      allowed_model_ids: parseCommaList(byId("cp-policy-models").value),
      cwd_roots: parseCommaList(byId("cp-policy-cwd-roots").value),
      rate_limit_per_minute: Number(byId("cp-policy-rate-limit").value) || 60,
    };
  }

  function validatePayload(domain, payload, isNew) {
    const errors = [];
    if (domain === "skills") {
      if (!payload.label) {
        errors.push("label 必填");
      }
    } else if (domain === "mcp") {
      if (!payload.label) {
        errors.push("label 必填");
      }
      errors.push(...validateEnvKeys(payload.env_keys));
      errors.push(
        ...validateNoSecretsInFields([
          { label: "command", value: byId("cp-mcp-command").value },
          { label: "args", value: byId("cp-mcp-args").value },
          { label: "url", value: byId("cp-mcp-url").value },
        ]),
      );
      if (isNew && !payload.url && !payload.command_preview.length) {
        errors.push("新建 MCP 需填 command 或 url");
      }
    } else {
      errors.push(...validateEnvKeys([]));
    }
    return errors;
  }

  async function evaluateCurrentPolicy(agentId) {
    const cwd = Ao.Workspace?.getActiveCwd?.() || "";
    const payload = {
      agent_id: agentId,
      cwd: cwd || null,
    };
    const data = await Ao.apiFetch(Ao.buildEndpoint("policyEvaluate"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return data;
  }

  async function applyHookPatch() {
    const harnessId = byId("cp-hook-harness").value.trim();
    const event = byId("cp-hook-event").value.trim();
    const command = byId("cp-hook-command").value.trim();
    if (!harnessId || !event || !command) {
      setMessage("hook 需要 harness、event、command。", true);
      return;
    }
    const scope = byId("cp-hook-scope").value || "project";
    const path = Ao.Workspace?.appendCwdQuery
      ? Ao.Workspace.appendCwdQuery(
          `${Ao.buildEndpoint("harnessConfigPatch", { harness_id: harnessId })}?scope=${encodeURIComponent(scope)}&dry_run=false`,
        )
      : `${Ao.buildEndpoint("harnessConfigPatch", { harness_id: harnessId })}?scope=${encodeURIComponent(scope)}&dry_run=false`;
    const result = await Ao.postJson(path, {
      ops: [{ op: "merge", path: `hooks.${event}`, value: [{ command }] }],
      source: "web-control-plane-hook",
      base_mtime: null,
    });
    byId("control-plane-diff-preview").textContent = result.diff
      ? JSON.stringify(result.diff, null, 2)
      : "（hook 已套用）";
    setMessage(`已追加 hook ${event} → ${harnessId}`);
  }

  async function saveCurrent() {
    if (!editTarget) {
      return;
    }
    clearValidationErrors();
    const { domain, id } = editTarget;
    const isNew = !(await recordExists(domain, id));
    let payload;
    let path;
    if (domain === "skills") {
      payload = buildSkillPayload();
      path = Ao.buildEndpoint("skillUpsert", { skill_id: id });
    } else if (domain === "mcp") {
      payload = buildMcpPayload(isNew);
      path = Ao.buildEndpoint("mcpUpsert", { server_id: id });
    } else {
      payload = buildPolicyPayload();
      path = Ao.buildEndpoint("policyUpsert", { agent_id: id });
    }
    const errors = validatePayload(domain, payload, isNew);
    if (errors.length) {
      renderValidationErrors(errors);
      return;
    }
    try {
      const result = await Ao.postJson(path, payload);
      const diffText = result.diff ? JSON.stringify(result.diff, null, 2) : "（已套用）";
      byId("control-plane-diff-preview").textContent = diffText;
      setMessage(`已儲存 ${domain}/${id}（patch_id: ${result.patch_id || "-"})`);
      if (domain === "policy") {
        try {
          const evaluation = await evaluateCurrentPolicy(id);
          setMessage(
            `已儲存政策 ${id}；evaluate → ${evaluation.decision}: ${evaluation.reason || "-"}`,
          );
        } catch (evalError) {
          setMessage(`已儲存，但 evaluate 失敗：${evalError.message}`, true);
        }
      }
      hideAllForms();
      if (Ao.reloadControlPlaneTables) {
        await Ao.reloadControlPlaneTables();
      }
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function evaluatePolicyForm() {
    if (!editTarget || editTarget.domain !== "policy") {
      setMessage("請先開啟政策表單。", true);
      return;
    }
    try {
      const evaluation = await evaluateCurrentPolicy(editTarget.id);
      setMessage(`evaluate → ${evaluation.decision}: ${evaluation.reason || "-"}`);
    } catch (error) {
      setMessage(error.message, true);
    }
  }

  async function recordExists(domain, id) {
    try {
      if (domain === "skills") {
        await Ao.apiFetch(Ao.buildEndpoint("skillDetail", { skill_id: id }));
      } else if (domain === "mcp") {
        await Ao.apiFetch(Ao.buildEndpoint("mcpDetail", { server_id: id }));
      } else {
        await Ao.apiFetch(Ao.buildEndpoint("policyDetail", { agent_id: id }));
      }
      return true;
    } catch (error) {
      if (error.status === 404) {
        return false;
      }
      throw error;
    }
  }

  async function disableRecord(domain, id) {
    let path;
    if (domain === "skills") {
      path = Ao.buildEndpoint("skillDisable", { skill_id: id });
    } else if (domain === "mcp") {
      path = Ao.buildEndpoint("mcpDisable", { server_id: id });
    } else {
      setMessage("政策不支援 disable", true);
      return;
    }
    await Ao.postEmpty(path);
    setMessage(`已停用 ${domain}/${id}`);
    if (Ao.reloadControlPlaneTables) {
      await Ao.reloadControlPlaneTables();
    }
  }

  function historyPath(domain, id) {
    if (domain === "skills") {
      return Ao.buildEndpoint("skillHistory", { skill_id: id });
    }
    if (domain === "mcp") {
      return Ao.buildEndpoint("mcpHistory", { server_id: id });
    }
    return Ao.buildEndpoint("policyHistory", { agent_id: id });
  }

  function rollbackPathFn(domain, id) {
    return (patch) => {
      if (domain === "skills") {
        return `${Ao.buildEndpoint("skillRollback", { skill_id: id })}?to=${encodeURIComponent(patch.patch_id)}`;
      }
      if (domain === "mcp") {
        return `${Ao.buildEndpoint("mcpRollback", { server_id: id })}?to=${encodeURIComponent(patch.patch_id)}`;
      }
      return `${Ao.buildEndpoint("policyRollback", { agent_id: id })}?to=${encodeURIComponent(patch.patch_id)}`;
    };
  }

  async function toggleHistory(domain, id, containerId) {
    const container = document.getElementById(containerId);
    if (!container) {
      return;
    }
    if (!container.hidden && container.dataset.loadedFor === `${domain}:${id}`) {
      container.hidden = true;
      return;
    }
    container.hidden = false;
    container.dataset.loadedFor = `${domain}:${id}`;
    await Ao.PatchRollback.loadPatchHistory({
      historyPath: historyPath(domain, id),
      rollbackPathFn: rollbackPathFn(domain, id),
      containerId: `${containerId}-body`,
      emptyMessage: "尚無歷史紀錄。",
    });
  }

  async function reloadAfterRollback() {
    if (Ao.reloadControlPlaneTables) {
      await Ao.reloadControlPlaneTables();
    }
  }

  function bindEvents() {
    byId("cp-policy-evaluate")?.addEventListener("click", () => {
      evaluatePolicyForm().catch((error) => setMessage(error.message, true));
    });
    byId("cp-hook-apply")?.addEventListener("click", () => {
      applyHookPatch().catch((error) => setMessage(error.message, true));
    });
  }

  Ao.ControlPlaneEditor = {
    toggleEditorChrome,
    bindEvents,
    reloadAfterRollback,
    openEdit,
    openCreate,
    saveCurrent,
    cancelEdit,
    disableRecord,
    toggleHistory,
    evaluatePolicyForm,
    applyHookPatch,
  };
})(window.AgenticOs);

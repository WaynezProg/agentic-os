"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initConfigEditor(Ao) {
  const PATCH_SOURCE = "web-config-editor";

  const HARNESS_CONFIG_DESCRIPTOR = Object.freeze({
    family: "harness",
    label: "Harness 原生設定",
    basePath: "/harness-config",
    scopes: ["user", "project", "local"],
    endpoints: {
      effective: "harnessConfigEffective",
      diff: "harnessConfigDiff",
      explain: "harnessConfigExplain",
      patch: "harnessConfigPatch",
    },
    harnessSelectId: "harness-config-id",
    elementPrefix: "config",
    patchHistoryContainerId: "config-patch-history-body",
    patchHistorySectionId: "config-patch-history",
    editorControlsId: "config-editor-controls",
    loadButtonId: "harness-config-load",
    effectiveSnippetId: "harness-config-snippet",
  });

  function assertDescriptor(descriptor) {
    if (descriptor.family === "harness" && descriptor.basePath !== "/harness-config") {
      throw new Error("harness descriptor must bind to /harness-config");
    }
    if (descriptor.family === "agentic" && descriptor.basePath !== "/config") {
      throw new Error("agentic descriptor must bind to /config");
    }
  }

  function elId(descriptor, suffix) {
    return `${descriptor.elementPrefix}-${suffix}`;
  }

  function byId(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`Missing element: ${id}`);
    }
    return element;
  }

  function getHarnessId(descriptor) {
    return byId(descriptor.harnessSelectId).value;
  }

  function isWritable() {
    return Ao.RemoteConsole?.isActionAllowed("ui.write.harness-config") ?? Ao.isLocalWritable();
  }

  function withWorkspaceCwd(path) {
    if (Ao.Workspace?.appendCwdQuery) {
      return Ao.Workspace.appendCwdQuery(path);
    }
    return path;
  }

  function createConfigEditor(descriptor) {
    assertDescriptor(descriptor);

    let previewBaseMtime = null;
    let lastPreviewOps = null;

    function toggleEditorChrome() {
      const writable = isWritable();
      const controls = document.getElementById(descriptor.editorControlsId);
      const history = document.getElementById(descriptor.patchHistorySectionId);
      if (controls) {
        controls.hidden = !writable;
      }
      if (history) {
        history.hidden = !writable;
      }
      toggleValueField();
    }

    function setMessage(message, isError = false) {
      const target = byId(elId(descriptor, "patch-message"));
      target.textContent = message;
      target.classList.toggle("is-error", isError);
    }

    function clearValidationErrors() {
      const target = byId(elId(descriptor, "validation-errors"));
      target.textContent = "";
      target.hidden = true;
    }

    function renderValidationErrors(errors) {
      const target = byId(elId(descriptor, "validation-errors"));
      const list = Array.isArray(errors) ? errors : [String(errors)];
      target.hidden = false;
      target.innerHTML = list.map((item) => `<div>${escapeHtml(String(item))}</div>`).join("");
    }

    function toggleValueField() {
      const op = byId(elId(descriptor, "op")).value;
      const valueField = byId(elId(descriptor, "value"));
      const isRemove = op === "remove";
      valueField.disabled = isRemove;
      valueField.required = !isRemove && isWritable();
    }

    function resetApplyState() {
      previewBaseMtime = null;
      lastPreviewOps = null;
      byId(elId(descriptor, "apply")).disabled = true;
    }

    function formatDiff(diff) {
      if (!diff) {
        return "（無 diff）";
      }
      return JSON.stringify(diff, null, 2);
    }

    function buildPatchQuery(scope, dryRun) {
      const params = new URLSearchParams({
        scope,
        dry_run: dryRun ? "true" : "false",
      });
      return params.toString();
    }

    function buildPatchOpsFromForm() {
      const op = byId(elId(descriptor, "op")).value;
      const path = byId(elId(descriptor, "path")).value.trim();
      if (!path) {
        throw new Error("path 為必填");
      }
      const patchOp = { op, path };
      if (op === "merge") {
        const rawValue = byId(elId(descriptor, "value")).value.trim();
        if (!rawValue) {
          throw new Error("merge 操作需要 JSON value");
        }
        try {
          patchOp.value = JSON.parse(rawValue);
        } catch {
          throw new Error("value 必須是合法 JSON");
        }
      }
      return [patchOp];
    }

    async function loadEffective() {
      toggleEditorChrome();
      const harnessId = getHarnessId(descriptor);
      const snippet = byId(descriptor.effectiveSnippetId);
      snippet.textContent = "載入中…";
      clearValidationErrors();
      resetApplyState();
      byId(elId(descriptor, "diff-preview")).textContent = "編輯 path patch 後按「預覽變更」。";
      try {
        const data = await Ao.apiFetch(
          withWorkspaceCwd(
            Ao.buildEndpoint(descriptor.endpoints.effective, { harness_id: harnessId }),
          ),
        );
        const payload = {
          harness_id: data.harness_id,
          scopes_present: data.scopes_present,
          entries: data.entries,
        };
        const text = JSON.stringify(payload, null, 2);
        snippet.textContent = text.length > 4096 ? `${text.slice(0, 4096)}\n…（已截斷）` : text;
        if (isWritable()) {
          await Ao.PatchRollback.loadPatchHistory({
            harness: harnessId,
            containerId: descriptor.patchHistoryContainerId,
          });
        }
      } catch (error) {
        snippet.textContent = error.message;
      }
    }

    async function runPatch(dryRun, ops, baseMtime) {
      const harnessId = getHarnessId(descriptor);
      const scope = byId(elId(descriptor, "scope")).value;
      const path = withWorkspaceCwd(
        `${Ao.buildEndpoint(descriptor.endpoints.patch, { harness_id: harnessId })}?${buildPatchQuery(scope, dryRun)}`,
      );
      const payload = {
        ops,
        source: PATCH_SOURCE,
        base_mtime: baseMtime ?? null,
      };
      return Ao.postJson(path, payload);
    }

    function extractValidationErrors(error) {
      const detail = error.payload?.detail;
      if (detail && Array.isArray(detail.validation_errors)) {
        return detail.validation_errors;
      }
      if (Array.isArray(error.payload?.validation_errors)) {
        return error.payload.validation_errors;
      }
      return null;
    }

    function isStaleTarget(error) {
      const detail = error.payload?.detail;
      return error.status === 409 && detail?.error === "stale_target";
    }

    function isForbiddenPath(error) {
      const detail = error.payload?.detail;
      return error.status === 403 && detail?.error === "forbidden_path";
    }

    async function dryRunPatch() {
      clearValidationErrors();
      resetApplyState();
      const preview = byId(elId(descriptor, "diff-preview"));
      preview.textContent = "預覽中…";
      try {
        const ops = buildPatchOpsFromForm();
        const result = await runPatch(true, ops, null);
        previewBaseMtime = result.base_mtime ?? null;
        lastPreviewOps = ops;
        preview.textContent = formatDiff(result.diff);
        byId(elId(descriptor, "apply")).disabled = false;
        setMessage(
          previewBaseMtime === null || previewBaseMtime === undefined
            ? "預覽完成（無 base_mtime），確認後可套用。"
            : `預覽完成，base_mtime=${previewBaseMtime}。確認後可套用。`,
        );
      } catch (error) {
        preview.textContent = formatDiff(error.payload?.detail || error.message);
        const validationErrors = extractValidationErrors(error);
        if (validationErrors) {
          renderValidationErrors(validationErrors);
        } else if (isForbiddenPath(error)) {
          const detail = error.payload?.detail;
          setMessage(detail?.message || "forbidden_path", true);
        } else {
          setMessage(error.message, true);
        }
      }
    }

    async function applyPatch() {
      if (!lastPreviewOps?.length) {
        setMessage("請先預覽變更。", true);
        return;
      }
      clearValidationErrors();
      try {
        const result = await runPatch(false, lastPreviewOps, previewBaseMtime);
        const patchId = result.patch_id || "(unknown)";
        byId(elId(descriptor, "diff-preview")).textContent = formatDiff(result.diff);
        setMessage(`已套用 patch_id=${patchId}`);
        resetApplyState();
        await loadEffective();
      } catch (error) {
        if (isStaleTarget(error)) {
          setMessage("檔案已變更（stale_target），已重新預覽，請確認 diff 後再套用。", true);
          await dryRunPatch();
          return;
        }
        const validationErrors = extractValidationErrors(error);
        if (validationErrors) {
          renderValidationErrors(validationErrors);
          setMessage("schema 驗證失敗", true);
          return;
        }
        if (isForbiddenPath(error)) {
          const detail = error.payload?.detail;
          setMessage(detail?.message || "forbidden_path", true);
          return;
        }
        setMessage(error.message, true);
      }
    }

    async function reloadAfterRollback() {
      await loadEffective();
    }

    function bindControls() {
      byId(elId(descriptor, "op")).addEventListener("change", toggleValueField);
      byId(elId(descriptor, "dry-run")).addEventListener("click", () => {
        dryRunPatch();
      });
      byId(elId(descriptor, "apply")).addEventListener("click", () => {
        applyPatch();
      });
    }

    function init() {
      bindControls();
      toggleEditorChrome();
      resetApplyState();
    }

    return {
      descriptor,
      init,
      loadEffective,
      dryRunPatch,
      applyPatch,
      reloadAfterRollback,
      isWritable,
      toggleEditorChrome,
    };
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

  Ao.createConfigEditor = createConfigEditor;
  Ao.HarnessConfigEditor = createConfigEditor(HARNESS_CONFIG_DESCRIPTOR);
})(window.AgenticOs);

"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initActions(Ao) {
  const DELEGATED_ACTIONS = new Set([
    "catalog-enable-mcp",
    "catalog-disable-mcp",
    "patch-rollback",
    "control-plane-rollback",
    "cp-edit",
    "cp-create",
    "cp-save",
    "cp-cancel",
    "cp-disable",
    "cp-history",
  ]);

  function isDelegatedAction(action) {
    return DELEGATED_ACTIONS.has(action);
  }

  async function dispatchDelegatedAction(action, button) {
    if (action === "catalog-enable-mcp") {
      const name = button.dataset.mcpName;
      const scope = button.dataset.mcpScope || "project";
      await Ao.CatalogEditor.stageEnableMcp(name, scope);
      return;
    }
    if (action === "catalog-disable-mcp") {
      const name = button.dataset.mcpName;
      const scope = button.dataset.mcpScope || "project";
      Ao.CatalogEditor.stageDisableMcp(name, scope);
      return;
    }
    if (action === "control-plane-rollback") {
      const path = button.dataset.rollbackPath;
      await Ao.PatchRollback.rollbackPatch(path, "web-control-plane-rollback");
      await Ao.ControlPlaneEditor.reloadAfterRollback();
      const container = button.closest("[data-history-domain]");
      if (container) {
        await Ao.ControlPlaneEditor.toggleHistory(
          container.dataset.historyDomain,
          container.dataset.historyId,
          container.id,
        );
      }
      return;
    }
    if (action === "cp-edit") {
      await Ao.ControlPlaneEditor.openEdit(button.dataset.domain, button.dataset.recordId);
      return;
    }
    if (action === "cp-create") {
      await Ao.ControlPlaneEditor.openCreate(button.dataset.domain);
      return;
    }
    if (action === "cp-save") {
      await Ao.ControlPlaneEditor.saveCurrent();
      return;
    }
    if (action === "cp-cancel") {
      Ao.ControlPlaneEditor.cancelEdit();
      return;
    }
    if (action === "cp-disable") {
      await Ao.ControlPlaneEditor.disableRecord(button.dataset.domain, button.dataset.recordId);
      return;
    }
    if (action === "cp-history") {
      await Ao.ControlPlaneEditor.toggleHistory(
        button.dataset.domain,
        button.dataset.recordId,
        button.dataset.historyContainer,
      );
      return;
    }
    if (action === "patch-rollback") {
      const patchId = button.dataset.patchId;
      await Ao.PatchRollback.rollbackPatch(patchId, "web-patch-rollback");
      if (button.closest("#config-patch-history")) {
        await Ao.HarnessConfigEditor.reloadAfterRollback();
        return;
      }
      if (button.closest("#profile-patch-history")) {
        await Ao.ProfileEditor.reloadAfterRollback();
        return;
      }
      if (button.closest("#registry-patch-history")) {
        await Ao.RegistryEditor.reloadAfterRollback();
        return;
      }
      if (button.closest(".cp-history-row")) {
        await Ao.ControlPlaneEditor.reloadAfterRollback();
        return;
      }
      const harness = document.getElementById("catalog-harness")?.value;
      if (Ao.CatalogEditor?.loadCatalog) {
        await Ao.CatalogEditor.loadCatalog();
      } else if (harness) {
        await Ao.PatchRollback.loadPatchHistory({
          harness,
          containerId: "catalog-patch-history-body",
        });
      }
    }
  }

  Ao.dispatchDelegatedAction = dispatchDelegatedAction;
  Ao.isDelegatedAction = isDelegatedAction;
  Ao.dispatchCatalogAction = dispatchDelegatedAction;
  Ao.isCatalogAction = isDelegatedAction;
})(window.AgenticOs);

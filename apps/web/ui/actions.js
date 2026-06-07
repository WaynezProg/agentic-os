"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initActions(Ao) {
  const DELEGATED_ACTIONS = new Set([
    "catalog-enable-mcp",
    "catalog-disable-mcp",
    "patch-rollback",
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

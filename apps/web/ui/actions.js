"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initActions(Ao) {
  const CATALOG_ACTIONS = new Set([
    "catalog-enable-mcp",
    "catalog-disable-mcp",
    "patch-rollback",
  ]);

  function isCatalogAction(action) {
    return CATALOG_ACTIONS.has(action);
  }

  async function dispatchCatalogAction(action, button) {
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
      const harness = document.getElementById("catalog-harness")?.value;
      await Ao.PatchRollback.rollbackPatch(patchId, "web-patch-rollback");
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

  Ao.dispatchCatalogAction = dispatchCatalogAction;
  Ao.isCatalogAction = isCatalogAction;
})(window.AgenticOs);

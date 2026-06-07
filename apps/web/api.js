"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initApi(Ao) {
  Ao.DEFAULT_API_URL = "http://127.0.0.1:8767";

  Ao.ENDPOINTS = Object.freeze({
    health: "/health",
    agents: "/agents",
    sessions: "/sessions",
    sessionDetail: "/sessions/{session_id}",
    sessionLogs: "/sessions/{session_id}/logs",
    sessionStop: "/sessions/{session_id}/stop",
    sessionRetry: "/sessions/{session_id}/retry",
    events: "/events",
    sessionEvents: "/sessions/{session_id}/events",
    sessionTimeline: "/sessions/{session_id}/timeline",
    sessionAttach: "/sessions/{session_id}/attach",
    sessionRun: "/sessions",
    sessionSummary: "/sessions/{session_id}/memory/summary",
    sessionReview: "/sessions/{session_id}/memory/review",
    memoryReview: "/memory/review",
    memoryApprove: "/memory/review/{item_id}/approve",
    memoryReject: "/memory/review/{item_id}/reject",
    memoryList: "/memory",
    memorySearch: "/memory/search",
    skills: "/skills",
    skillDetail: "/skills/{skill_id}",
    skillUpsert: "/skills/{skill_id}",
    skillDisable: "/skills/{skill_id}/disable",
    skillHistory: "/skills/{skill_id}/history",
    skillRollback: "/skills/{skill_id}/rollback",
    mcp: "/mcp",
    mcpDetail: "/mcp/{server_id}",
    mcpUpsert: "/mcp/{server_id}",
    mcpDisable: "/mcp/{server_id}/disable",
    mcpHistory: "/mcp/{server_id}/history",
    mcpRollback: "/mcp/{server_id}/rollback",
    policySummary: "/policy",
    policyDetail: "/policy/{agent_id}",
    policyUpsert: "/policy/{agent_id}",
    policyHistory: "/policy/{agent_id}/history",
    policyRollback: "/policy/{agent_id}/rollback",
    policyEvaluate: "/policy/evaluate",
    approvals: "/approvals",
    approvalApprove: "/approvals/{approval_id}/approve",
    approvalReject: "/approvals/{approval_id}/reject",
    fleetHealth: "/fleet/health",
    fleetInstanceHealth: "/fleet/{agent_id}/health",
    fleetEvents: "/fleet/events",
    fleetCapacity: "/fleet/capacity",
    fleetProbe: "/fleet/probe",
    auditEvents: "/audit/events",
    auditPolicyCoverage: "/audit/policy-coverage",
    harnesses: "/harnesses",
    harnessHealth: "/harnesses/{harness_id}/health",
    catalogSurfaces: "/catalog/{harness}/surfaces",
    catalogPatch: "/catalog/{harness}/surfaces/patch",
    patches: "/patches",
    patchDetail: "/patches/{patch_id}",
    patchRollback: "/patches/{patch_id}/rollback",
    harnessConfigEffective: "/harness-config/{harness_id}/effective",
    harnessConfigDiff: "/harness-config/{harness_id}/diff",
    harnessConfigExplain: "/harness-config/{harness_id}/explain",
    harnessConfigPatch: "/harness-config/{harness_id}/patch",
    profiles: "/profiles",
    profileDetail: "/profiles/{name}",
    profileDelete: "/profiles/{name}",
    profileDiff: "/profiles/{name}/diff",
    profileBind: "/projects/{project_path}/bind-profile",
    registryAgents: "/registry/agents",
    registryAgentDisable: "/registry/agents/{id}/disable",
    registrySchema: "/registry/schema",
    approvalsFiltered: "/approvals",
    remoteAffordances: "/remote/affordances",
    remoteDevices: "/remote/devices",
    setupExport: "/setup/export",
    setupImport: "/setup/import",
    diagnosticsResources: "/diagnostics/resources",
    setupLogsZip: "/setup/logs.zip",
    versionInfo: "/version",
  });

  let connectionProfile = null;

  Ao.setConnectionProfile = function setConnectionProfile(profile) {
    connectionProfile = profile;
  };

  Ao.getConnectionProfile = function getConnectionProfile() {
    return connectionProfile;
  };

  Ao.isLocalWritable = function isLocalWritable() {
    return connectionProfile?.mode !== "remote";
  };

  function apiBase() {
    const el = document.getElementById("api-url");
    const value = (el?.value || Ao.DEFAULT_API_URL).trim();
    return value.replace(/\/+$/, "");
  }

  Ao.apiBase = apiBase;

  Ao.buildEndpoint = function buildEndpoint(name, params = {}) {
    let path = Ao.ENDPOINTS[name];
    Object.entries(params).forEach(([key, value]) => {
      path = path.replace(`{${key}}`, encodeURIComponent(value));
    });
    return path;
  };

  function parseJson(text) {
    try {
      return JSON.parse(text);
    } catch {
      return { detail: text };
    }
  }

  function normalizeErrorDetail(detail) {
    if (typeof detail === "string") {
      return detail;
    }
    return JSON.stringify(detail);
  }

  async function apiFetchViaDesktop(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const body =
      options.body === undefined
        ? null
        : typeof options.body === "string"
          ? options.body
          : JSON.stringify(options.body);
    try {
      const text = await window.__TAURI__.core.invoke("connection_api_fetch", {
        method,
        path,
        body,
      });
      return text ? parseJson(text) : {};
    } catch (error) {
      const message = String(error);
      const errorObject = new Error(message);
      errorObject.status = 0;
      errorObject.payload = { detail: message };
      throw errorObject;
    }
  }

  Ao.apiFetch = async function apiFetch(path, options = {}) {
    if (connectionProfile?.mode === "remote" && window.__TAURI__?.core?.invoke) {
      return apiFetchViaDesktop(path, options);
    }
    const headers = {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(`${apiBase()}${path}`, { ...options, headers });
    const text = await response.text();
    const payload = text ? parseJson(text) : {};

    if (!response.ok) {
      const detail = normalizeErrorDetail(payload.detail || response.statusText);
      const error = new Error(`${response.status} ${detail}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  };

  Ao.postEmpty = async function postEmpty(path) {
    return Ao.apiFetch(path, { method: "POST", body: JSON.stringify({}) });
  };

  Ao.postJson = async function postJson(path, payload) {
    return Ao.apiFetch(path, { method: "POST", body: JSON.stringify(payload) });
  };
})(window.AgenticOs);

"use strict";

/** @type {Record<string, string>} */
const I18N = Object.freeze({
  sectionAgents: "代理",
  sectionSessions: "執行",
  sectionLogs: "日誌",
  sectionMemory: "記憶",
  sectionSkills: "技能 / MCP",
  sectionFleet: "機群健康",
  sectionHarnesses: "Harness 實例",
  sectionCatalog: "工作流介面",
  sectionApprovals: "核准佇列",
  sectionAudit: "稽核紀錄",
  sectionOverview: "總覽",

  statusChecking: "檢查中…",
  statusNotChecked: "尚未檢查",
  statusConnected: "已連線",
  statusOffline: "無法連線",

  emptyNoAgents: "沒有代理資料。",
  emptyNoSessions: "沒有執行紀錄。",
  emptyNoReview: "審核佇列是空的。",
  emptyNoMemory: "沒有已核准的記憶。",
  emptyNoSkills: "沒有技能。",
  emptyNoMcp: "沒有 MCP 伺服器。",
  emptyNoApprovals: "沒有待處理核准。",
  emptyNoPolicies: "沒有政策。",
  emptyNoEvents: "這個 session 沒有事件。",
  emptyLoadSessionEvents: "先選一個 session 才能看事件。",
  emptyNoTimeline: "時間軸還是空的。",
  emptySelectSession: "從左邊列表選一個 session。",
  emptyNoFleetHealth: "還沒有機群健康資料，按「立即探測」。",
  emptyNoFleetEvents: "沒有機群事件。",
  emptyNoAudit: "沒有稽核事件。",
  emptyNoHarnesses: "尚未設定 Harness。",
  emptyNoHarnessHealth: "沒有 Harness 實例。",
  emptyNoSurfaces: "找不到工作流介面。",
  emptyNoApprovalsTab: "沒有核准項目。",
  emptyNoData: "尚無資料。",
  emptyClickLoadAudit: "按「載入」查看稽核事件。",
  emptyClickLoadApprovals: "按「載入」查看核准。",
  emptySelectHarnessLoad: "選 Harness 後按「載入」。",
  emptyHarnessConfig: "選 Harness 並載入有效原生設定。",

  loading: "載入中…",
  loadingHarnesses: "載入 Harness…",
  loadingHealth: "載入健康狀態…",
  probing: "探測中…",
  probeNow: "立即探測",

  btnRun: "執行",
  btnCancel: "取消",
  btnOpen: "開啟",
  btnLogs: "日誌",
  btnAttach: "附加",
  btnSummarize: "摘要",
  btnReviewCreate: "建立審核",
  btnRetry: "重試",
  btnStop: "停止",
  btnApprove: "核准",
  btnReject: "拒絕",
  btnSummary: "摘要",
  btnCheck: "檢查",
  btnLoad: "載入",
  btnSearch: "搜尋",
  btnEvaluate: "評估",
  btnRefresh: "重新整理",

  selectedSession: "已選：{id}",
  enterSessionId: "請輸入 session ID。",
  logsLoaded: "已載入 {count} 筆，顯示最近 {shown} 筆",
  sessionCreated: "已建立 session：{id}，狀態：{status}",
  agentMessageRequired: "請填代理與訊息。",
  agentIdRequired: "請填 agent_id。",
  rejectionPrompt: "拒絕原因",
  deprecated: "已淘汰",

  detailSession: "Session",
  detailAgent: "代理",
  detailStatus: "狀態",
  detailUpdated: "更新時間",

  overviewHealth: "{up} 正常、{down} 異常，共 {total} 個",
  overviewCapacity: "{running}/{max} 個執行中",
  overviewSessions: "{running} 執行中，共 {total} 筆",
  overviewApprovalsPending: "{pending} 筆待核准",
  overviewError: "讀取失敗",

  policyReadonly: "唯讀",
  policyWrite: "寫入",
  truncated: "…（已截斷）",
  fleetProbed: "已探測 {count} 個實例",
  probeNow: "立即探測",

  runPreviewCwdEmpty: "（未填：由 daemon 使用啟動時工作目錄）",
  runPreviewCwd: "工作目錄：{cwd}",
  runPreviewArgv: "啟動指令：{argv}",
  runPreviewWaitingMessage: "（輸入訊息後顯示實際 argv）",
  sessionCreatedWithArgv: "已建立 session {id}（{status}）\n{argv}",
});

/**
 * @param {string} key
 * @param {Record<string, string | number>} [params]
 */
function t(key, params = {}) {
  const template = I18N[key];
  if (template === undefined) {
    return key;
  }
  return template.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ""));
}

const SECTION_TITLES = Object.freeze({
  agents: I18N.sectionAgents,
  sessions: I18N.sectionSessions,
  logs: I18N.sectionLogs,
  memory: I18N.sectionMemory,
  skills: I18N.sectionSkills,
  fleet: I18N.sectionFleet,
  harnesses: I18N.sectionHarnesses,
  catalog: I18N.sectionCatalog,
  approvals: I18N.sectionApprovals,
  audit: I18N.sectionAudit,
  overview: I18N.sectionOverview,
});

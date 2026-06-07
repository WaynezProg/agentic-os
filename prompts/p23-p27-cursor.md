# Cursor 實作 prompt — P23–P27（一條 branch、staged commits、一顆 PR）

你是在 `agentic-os` repo 工作的實作 agent。本批做完 P23–P27 五個 phase，**單一 branch、每個 phase 一個 commit、最後開一顆 PR**。先讀 `CLAUDE.md` 與 specs：`042-mcp-skill-policy-ui.md`、`043-approval-workbench.md`、`044-remote-operator-console.md`、`045-import-export-setup.md`、`046-product-polish.md`。Spec 對 scope 有最終約束力。

P18–P22 已 merge（PR #10），這批的後端依賴大多已存在；**P23/P24 是純前端**，P25/P26/P27 只加少量、明確的後端。

## 0. Branch / commit / PR

- 從 `docs/p16-p27-specs` 開 `feat/p23-p27-management-remote-polish`。
- 分階段 commit（不要 mega-commit）：
  1. `feat: P23 mcp/skill/policy management UI`
  2. `feat: P24 approval workbench`
  3. `feat: P25 remote operator console`
  4. `feat: P26 project setup import/export`
  5. `feat: P27 desktop product polish`
- 每顆 commit 自己 `uv run pytest -q && uv run ruff check . && node --check`（改到的 .js 全跑）全綠才往下。
- PR base = `docs/p16-p27-specs`，body 列每個 acceptance 對應測試。同一 PR 更新對應 spec 與 README phase 表。

## 1. 紅線（CLAUDE.md，違反直接 reject）

- **不新增 daemon / supervisor / process owner / 背景 updater**；單一 `agentd` 擁有一切。P27 update-check 只能是 stub/no-op。
- **不啟動/連線任何東西**：P23 不可 spawn MCP server、不做 live connectivity test（只做 static 驗證）。
- 不接 LLM / embedding / vector DB / cloud sync。
- Secrets 一律以 **env-var 名稱**引用；values 永不顯示、永不寫入、永不離開 daemon。所有對外輸出先過 `control_plane._redact_value`。
- 不重命名既有 endpoint / CLI verb；產品語彙照 README。
- 改 code 後跑相關 test/lint。新增 route 要 additive。

## 2. 共用前端 shell（全部復用，不要重造）

- `apps/web/api.js`：`apiFetch / postJson / postEmpty / buildEndpoint / isLocalWritable / getConnectionProfile`；`ENDPOINTS` map 在這裡擴充。
- `apps/web/ui/rollback.js`：history table + rollback（**見 landmine L1，要參數化**）。
- form 編輯模式參考 `ui/profile-editor.js` / `ui/registry-editor.js` / `ui/catalog-editor.js`：load → 表單 → dry-run（存 `base_mtime`）→ diff → apply → rollback；`409 stale_target` 自動 re-dry-run、`422 validation_errors` / `403 forbidden_path` inline。
- script include 順序在 `index.html`（api.js → ui/rollback.js → ui/*editor.js → 新檔 → actions.js → app.js）。
- remote 模式唯讀：`Ao.isLocalWritable()===false` 時藏編輯 chrome（P25 進一步用 affordances 細分）。
- 既有 tabs：`agents/sessions/logs/memory/skills(技能/MCP)/fleet/harnesses/catalog/approvals/audit/overview`。`panel-skills`（index.html:481）目前是唯讀表格（`skills-body/mcp-body/policy-summary-body`）；`panel-approvals`（:873）是簡單列表。**P23/P24 是 extend 這兩個既有 panel，不是新 tab。**

---

## 3. P23 — MCP / Skill / Policy 管理 UI（commit 1）

Spec 042。後端 P22 已給 history+rollback。把 `panel-skills` 的唯讀表格升級成可編輯 + 歷史/還原。

### 後端現況（直接用，**不要加後端 route**）
- mutation：`POST /skills/{id}`、`POST /mcp/{id}`、`POST /policy/{id}`（request model：`SkillUpsertRequest`/`McpServerUpsertRequest`/`PolicyUpsertRequest`，api.py:149/164/174）；`/.../{id}/disable`、`/deprecate`、`/undeprecate`。
- P22 歷史/還原：`GET /{skills|mcp|policy}/{id}/history`、`POST /{skills|mcp|policy}/{id}/rollback?to=<patch_id|version>`，envelope `{patch_id,applied,diff,audit_event_id}`，history row 形狀已對齊 rollback.js（`patch_id,target_kind,surface_id,target_path,source,created_at,rolled_back_at,version`）。

### 必做
- 新檔 `apps/web/ui/control-plane-editor.js`（form-based）：
  - MCP form：`label, transport, command_preview(陣列), url, env_keys(只名稱), enabled, scope`。
  - Skill form / Policy form 對齊各自的 `*UpsertRequest`。
  - 每個 record 一個「歷史」展開，列 `GET /{domain}/{id}/history`，每列「還原」呼叫 `POST /{domain}/{id}/rollback?to=`。
- **static 驗證 only**：shape / env-name regex `^[A-Z][A-Z0-9_]*$` / 選配「PATH 上有無此 binary」皆可，但**不可 spawn、不可連線**。沒有「測試連線 / 啟動 server」按鈕。

### Landmines
- **L1（關鍵，跨頁）**：`ui/rollback.js` 的 `loadPatchHistory` 與 `rollbackPatch` 寫死 `/patches`。control_plane 的 history 在 `/{domain}/{id}/history`、rollback 在 `POST /{domain}/{id}/rollback?to=`。**把 rollback.js 參數化**：`loadPatchHistory({ historyPath, rollbackFn, containerId })`、`rollbackPatch` 接受完整 path。保留既有 `/patches` 呼叫者（profiles/registry/config）行為不變（給預設值）。envelope/row 已相容，差別只在 URL 與 rollback 帶 `?to=`。
- **L2（redaction，重演 P16 bug）**：`GET /mcp/{id}` 回的是**已 redact** 的 `command_preview`/`url`。編輯 MCP 時**絕不可**把 redact 後的值再 submit 回去（會把 `[REDACTED]` 寫進設定）。編輯一律走「operator 重新輸入」表單（command/args 或 url，env 以名稱）——和 P16 catalog enable 同一招。
- **L3**：env_keys 只接受名稱；表單在 submit 前用 `control_plane` secret pattern 擋掉任何看起來像值的輸入，明碼 token 不得到達 API。

### 測試
- `tests/test_web.py`：static 契約（新檔存在、`src="ui/control-plane-editor.js"`、必要 element id）。
- `tests/test_api.py`：mcp/skill/policy create/edit/disable round-trip；history+rollback；redaction 斷言（編輯後設定不含 `[REDACTED]`、不含明碼）。

---

## 4. P24 — Approval Workbench（commit 2）

Spec 043。把 `panel-approvals` 從清單升級成「每筆顯示足夠 context 即可裁決」。後端已存在。

### 後端現況（用既有）
- `GET /approvals`（已回 `source_session_id, agent_id, cwd, argv, reason, status, decision_reason`）、`GET /approvals/{id}`、`POST /approvals/{id}/approve`、`POST /approvals/{id}/reject`。
- retry：`POST /sessions/{id}/retry`（**會重評 policy**，回 `decision/reason/session_id`）。
- 遠端事件流：`GET /events`（SSE，需 remote bearer；032 approval stream）。

### 必做
- 每筆 request 卡片：trigger reason、source session、argv、cwd、policy decision/reason。
- approve / reject / **retry** 按鈕；audit 連結（指向 `agentctl sessions events <id>` 等效的 session event trail）。

### Landmines
- **L4**：retry 只能呼叫 `POST /sessions/{id}/retry`（重評 policy），並把回傳的 `decision/reason/session_id` inline 顯示。**不得**另開任何 respawn 路徑（P3.6 已封 retry bypass，不能重開）。
- **L5**：argv 可能含 secret。只顯示 record 裡**已 redact** 的 argv（audit metadata 已過 `_redact_value`），**不要在前端重組原始 argv**。
- **L6（remote parity）**：approve/reject/retry 在 remote 模式走 gateway（受 034 HTTPS/loopback policy 與 P14 token 約束）；workbench 消費 `GET /events` SSE 做 live 更新。

### 測試
- `tests/test_web.py`：workbench 渲染 trigger reason + source session + argv + cwd + policy result。
- `tests/test_api.py`：approve/reject/retry 走 gated endpoint。

---

## 5. P25 — Remote Operator Console（commit 3）

Spec 044。remote 模式只露 remote-safe 操作，**隱藏** localhost-only admin（不是露出來再 403）。

### localhost-only 路由（來源 `remote_api.py` + `remote_gateway.require_localhost_operator`）
`POST /remote/pairing/start`、`POST /remote/pairing/complete`、`GET /remote/devices`、`DELETE /remote/devices/{id}`、`POST /remote/devices/{id}/rotate`。

### 必做（唯一新後端）
- **抽出單一真相來源**：把 localhost-only action 集合抽到一個共用模組（如 `remote_affordances.py`，`LOCALHOST_ONLY_ACTIONS`），讓 route guard 與 affordance list 不能 diverge。
- 新 route `GET /remote/affordances` → `{ "localhost_only": [action_ids] }`，由上述常數產生。
- 前端 remote console：顯示 gateway 可達性、token 狀態（P14 `expires_at`，**不露 token 值**）、approval stream；操作面**只**依 `GET /remote/affordances` 來 gate（不要在 JS 硬寫清單）。
- 每個 remote 呼叫遵守 034 transport policy（HTTPS 或 loopback-http；非 loopback 不得明文 Bearer）。

### Landmines
- **L7**：affordance 清單與 `require_localhost_operator` 必須同源。加一個測試斷言「每個被 `require_localhost_operator` 守的 route 都有對應 action id 在 `LOCALHOST_ONLY_ACTIONS`」，反向也成立——防止漂移。
- **L8**：token 值永不送到 client（現況已是）；console 不得請求 token 值，只顯示 status + `expires_at`。

### 測試
- `tests/test_web.py` + `tests/test_remote_access.py`：remote 模式隱藏 localhost-only；token 狀態不洩值；affordances 與 guard 同源。

---

## 6. P26 — Project Setup Import / Export（commit 4）

Spec 045。把一個專案的 agent 設定（profiles/policies/MCP/skills/commands/hooks）匯出成可攜 bundle，異地 import 前先 dry-run。**這是本批唯一較重的後端。**

### 必做
- 新後端模組（如 `import_export.py`）+ routes：
  - `GET /setup/export?cwd=` → bundle（每筆 record 過 `_redact_value`；bundle schema **無任何 secret value 欄位**，只有 env-var 名稱）。
  - `POST /setup/import?dry_run=true` → 對現況的 diff（每個 item 一個 diff）。
  - `POST /setup/import?dry_run=false` → apply。
- **import 是 driver，不是 bulk raw write**：每個 imported change 走既有 per-domain endpoint（catalog patch、config patch、profile patch（POST/DELETE）、registry POST、skill/mcp/policy upsert+rollback），於是每筆都拿到自己的 `patch_id` + validation + audit，且可逐項 rollback。
- **path 可攜**：export 把 `cwd_roots/log_paths/bindings` 的絕對路徑 tokenize（`${PROJECT_ROOT}`、`${HOME}`）；import 還原並在 dry-run diff 列出任何無法解析的絕對路徑給 operator 修。

### Landmines
- **L9（#1 風險 secret 外洩）**：exporter 每筆過 `_redact_value`，bundle 無 secret value 欄位；import 把 env-var 名稱對目標機 env 解析，**缺名稱要大聲 fail**，絕不接受/詢問明碼。
- **L10（不可繞 gate）**：禁止任何跳過 validation/policy/audit 的 bulk 寫入；import 一律經既有 patch/policy 路徑。

### 測試
- `tests/test_*import_export*`（新）：export→import round-trip 等價；import dry-run 先出 diff 再寫；exported bundle 零 secret value（redaction 斷言）；import 經 patch/validation/policy 路徑（code review + 測試斷言有 patch_id/audit）。

---

## 7. P27 — Desktop Product Polish（commit 5）

Spec 046。讓 `.app` 日常可用：first-run wizard、health diagnostics、broken-config repair、logs download、version info、update-check **placeholder**。desktop shell（specs 028/029）已存在，**不要重建 Tauri shell**。

### 必做
- diagnostics view：復用 P8 `GET /diagnostics/resources`（已存在，api.py:2291）顯示 health/resource snapshot。
- first-run wizard（web UI）：引導 registry + profile 設定（呼叫既有 P20 registry、P18/P19 profile endpoint）。
- **broken-config repair**：用 `SafeEditEngine` 產 dry-run patch → 顯示 diff → 帶 snapshot/backup apply、可 `POST /patches/{id}/rollback`。**絕不直接寫檔**；無法表達成 validated patch 的修復，標成手動步驟，不自動套。
- logs download：走 P6 bounded-read 路徑（既有 `/sessions/{id}/logs`、`/harnesses/{id}/logs`），輸出前 `_redact_value`，**server 端打包成 zip**（redaction 不能由 client 跳過）。可加 `GET /setup/logs.zip` 之類 route。
- version info：靜態顯示版本；update-check 是 manual「檢查」打一個 version endpoint 或 no-op stub。**不得**背景 updater / auto-download。

### Landmines
- **L11**：repair = safe-edit dry-run + diff + backup + rollback，永不 ad-hoc write。
- **L12**：update-check 不得新增 process owner / 背景程序。
- **L13**：logs download 一定經 bounded-read + redaction，server 端 zip。

### 測試
- `tests/test_*diagnostics*`：diagnostics 表面 health/resource snapshot。
- logs download 的 bounded-read + redaction unit 測試。

---

## 8. Landmine 總表

- **L1**：`ui/rollback.js` 參數化以支援 control_plane 的 `/{domain}/{id}/history` + `rollback?to=`，保留 `/patches` 既有行為。
- **L2**：MCP 編輯走 operator 重新輸入，**絕不**回送 redact 後的值（重演 P16 `[REDACTED]` bug）。
- **L3 / L8 / L9**：secret 一律名稱；submit 前擋明碼；export 過 `_redact_value` 且 schema 無 value 欄位；token 值不離 daemon。
- **L4**：retry 只走 `POST /sessions/{id}/retry`（重評 policy），不另開 respawn。
- **L5**：argv 顯示用已 redact 的記錄，不重組原值。
- **L7**：`/remote/affordances` 與 `require_localhost_operator` 同源 + 漂移防護測試。
- **L10**：import 經既有 per-domain gate，逐項 patch_id/audit，禁 bulk raw write。
- **L11/L12/L13**：repair 走 safe-edit patch；無背景 updater；logs download bounded+redacted+server-zip。
- 新 route 僅 P25（affordances）、P26（export/import）、P27（version/logs.zip）；P23/P24 零新後端 route。

## 9. 收尾驗證（PR 前，逐項貼輸出）

```bash
uv run pytest -q          # 全綠（目前 566，本批會增加）
uv run ruff check .       # clean
node --check apps/web/app.js
node --check apps/web/ui/control-plane-editor.js
# 其餘改到的 .js 也跑 node --check
```

手動：local 模式 P23（mcp/skill/policy 編輯 + 歷史還原）、P24（approve/reject/retry + audit 連結）、P26（export→import dry-run→apply→逐項 rollback）走一輪；remote 模式確認 P25 隱藏 localhost-only、token 狀態不洩值。更新 README phase 表（P23–P27）與各 spec 狀態；PR body 列每個 acceptance 對應測試檔。

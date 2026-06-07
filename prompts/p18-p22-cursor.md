# Cursor 實作 prompt — P18–P22（一條 branch、staged commits、一顆 PR）

你是在 `agentic-os` repo 工作的實作 agent。本批一次做完 P18–P22 五個 phase，**單一 branch、每個 phase 一個 commit、最後開一顆 PR**。先讀 `CLAUDE.md` 與下列 specs，再動手：`specs/037-profile-backend-patch.md`、`038-profile-provider-ui.md`、`039-registry-editor-backend.md`、`040-registry-editor-ui.md`、`041-mcp-skill-policy-rollback-backend.md`。Specs 對 scope 有最終約束力，行為與 spec 衝突要先停下來講。

## 0. Branch / commit / PR

- 從 `docs/p16-p27-specs` 開 `feat/p18-p22-profiles-registry-rollback`。
- Commit 分階段，**不要一顆 mega-commit**（review 安全網靠這個）：
  1. `feat: P18 profile backend delete/diff/rollback via SafeEditEngine`
  2. `feat: P19 profile/provider UI`
  3. `feat: P20 registry editor backend (safe write)`
  4. `feat: P21 registry editor UI`
  5. `feat: P22 mcp/skill/policy rollback backend`
- 每顆 commit 自己要 `uv run pytest -q && uv run ruff check . && node --check` 全綠才往下。
- PR base = `docs/p16-p27-specs`，body 列每個 phase 的 acceptance 對應測試。

## 1. 紅線（CLAUDE.md，違反直接 reject）

- 不新增 daemon / supervisor / process owner；單一 `agentd` 擁有一切。
- 不接 LLM / embedding / vector DB / cloud sync。
- Secrets 一律以 **env-var 名稱**引用，URL/command preview 存前 redact（`control_plane.py` 的 `_redact_*`）。
- 不重命名既有 endpoint / CLI verb；產品語彙照 README 對照表。
- 改 config/TOML/JSON 後要 parse 驗證；改 code 後跑相關 test/lint。
- 同一 PR 更新對應 spec 與 README phase 表（`test_web.py` 會 assert 措辭）。

> 注意：P16/P17 的「零新 route」**不適用本批**。P18/P20/P22 是 backend phase，**本來就要加 route**。加 route 是對的，但只能 additive，不要改既有 route 形狀。

## 2. 共用機制事實（先吃透，五個 phase 都靠這個）

### SafeEditEngine（`src/agentic_os/safe_edit.py`）
- `apply(target: PatchTarget, ops, *, source, dry_run=False, base_mtime=None) -> PatchResult`。
- 流程：load doc → 逐 op 檢查 `schema_registry.is_path_allowed(target.harness_id, target.kind, op.path)`（不允許→`PermissionError`）→ `PatchEngine.apply` 算 `after` → `schema_registry.validate_document`（有 error→`ValidationError`）→ `base_mtime` 比對（不符→`ConflictError("stale_target")`）→ snapshot →寫檔→ audit。
- `PatchResult` 帶 `base_mtime`（dry-run 回 `current_mtime`）。**這是樂觀鎖 token，apply 必須帶回**。
- `rollback(patch_id, *, source)` 透過 `BackupStore.restore` 還原檔案。
- file_format `"toml"` 用 `toml_io.atomic_write_toml`（`tomli_w.dumps`，generic 格式）；`"json"` 用 `atomic_write_json`。

### 錯誤碼對應（照 `config_patch_endpoint`，api.py:1728 起，逐字 mirror）
- `ValidationError` → `422 {"validation_errors": [...]}`
- `PermissionError` → `403 {"error":"forbidden_path","message":...}`
- `ConflictError` → `409 {"error":"stale_target"}`
- `ValueError`（ops 等）→ `422 {"validation_errors":[...]}`
- 成功 → `_patch_result_dict(result)`（api.py:1591，含 `patch_id/applied/diff/validation/backup/audit_event_id/base_mtime`）。
- body model 用既有 `PatchOpsRequest`（`ops: list[dict]`, `source`, `base_mtime`）。

### schema_registry（`src/agentic_os/schema_registry.py`）
- 新 kind 要同時做兩件事，缺一就被擋：
  - `_PATH_WHITELIST` 加 `("agentic_os","run_profile")` 與 `("agentic_os","registry")` 的 prefix tuple。
  - 加 schema 檔，檔名規則是 `{kind}@v1.json`，路徑 `src/agentic_os/schemas/agentic_os/`：即 `run_profile@v1.json`、`registry@v1.json`（對照既有 `config@v1.json`）。
- `validate_document` 找不到 schema 會回 `["no schema for ..."]` → 直接擋掉 apply。所以 schema 一定要先有。

### BackupStore / /patches 復用
- file-based domain（profile TOML、agents.toml）的 `harness_id` 用 `"agentic_os"`，rollback 直接複用 `POST /patches/{id}/rollback`，前端 `ui/rollback.js` 的 `loadPatchHistory({harness:"agentic_os"})` 也能列。
- `BackupStore.restore`（backup_store.py:107）是**純 file-copy（`backup_paths[0]` → `target_path`），沒有 callback**。這點對 P22 是硬限制，見下。

---

## 3. P18 — Profile backend（commit 1）

Spec 037。現況：`profiles.py` 有 `upsert_run_profile / bind_project_profile / list_profiles / show_profile / resolve_*`，**全部經 `_write_bundle` 自訂 serializer 直接寫檔**。缺 delete / diff / rollback。

### 必做（spec 明寫「所有 profile mutation 走引擎，`_write_bundle` 降級，single writer = engine」）
1. 新增 schema `schemas/agentic_os/run_profile@v1.json`，validate **整個 bundle doc**：`{run_profiles:{<name>:{harness_id,provider,model,...}}, project_profiles:[{project_path,run_profile}]}`，required 對齊 `RunProfileInput`（harness_id/provider/model 必填）。
2. whitelist 加 `("agentic_os","run_profile"): ("run_profiles","project_profiles")`。
3. **把現有 mutation 全部改走 `SafeEditEngine.apply`**（PatchTarget: `harness_id="agentic_os"`, `kind="run_profile"`, `target_kind="run_profile"`, `file_format="toml"`, `file_path=` global(`~/.agentic-os/profiles.toml`)/local(`<cwd>/.agentic-os/profiles.toml`)，`scope ∈ {local,global}`）：
   - `POST /profiles`（upsert）→ merge op 在 `run_profiles.<name>`。
   - `POST /projects/{path}/bind-profile` → 改 `project_profiles` list（見 landmine L6 的 remove+merge 兩 op 寫法）。
   - **`_write_bundle` 降級成只給引擎當 TOML serializer 用，或直接由 `atomic_write_toml` 取代；不可再當獨立寫入路徑。** 完成後 profile 只有一個 writer = 引擎。
4. 新 route `DELETE /profiles/{name}?scope=&cascade=false&dry_run=false`：
   - 編 `remove` op 在 `run_profiles.<name>`。
   - **safe-by-default**：若該 profile 被 `project_profiles` 綁定且 `cascade!=true` → `409 {"error":"bound","projects":[...]}`，不刪。
   - `cascade=true` → 同一個 patch 內一起移除對應 bindings（delete + unbind 一起 rollback）。
   - 回 `_patch_result_dict`。
5. diff：spec acceptance「structured before/after」。dry-run patch 的 `result.diff` 已足夠當 edit 預覽；另加 `GET /profiles/{name}/diff?scope=&other_scope=` 用 `PatchEngine.diff` 比兩個 scope 的 bundle（或回該 profile 的 before/after），結構化回傳即可。
6. scope vocab 用 `{local,global}`，**不要**套用 `CONFIG_PATCH_SCOPES`（那是 config family 的 user/project/local）。

### 測試（`tests/test_*profile*` / `test_api.py`）
- delete 後 `list_profiles` 不再有該 profile；被綁定時 409 帶 projects；cascade 後 binding 清掉。
- delete 的 `patch_id` 經 `/patches/{id}/rollback` 能還原。
- 單一 writer：斷言 mutation 後 `/patches` 有對應 entry（harness_id `agentic_os`）。
- 若有測試 assert profiles.toml 精確字串，改成 parse 後比語意（格式會因 `tomli_w` 改變，見 L2）。

---

## 4. P19 — Profile / Provider UI（commit 2）

Spec 038。純前端，跑在 P18 之上。解的是每日痛點：per-project 切 provider/model。

- **復用 operation shell**：`api.js`（`apiFetch/postJson/buildEndpoint/isLocalWritable`）、`ui/rollback.js`（`loadPatchHistory({harness:"agentic_os"})` + `rollbackPatch`）。
- **form-based**（參考 `ui/catalog-editor.js` 把表單編成 PatchOps，而非 `config-editor.js` 的 raw path）。新檔 `apps/web/ui/profile-editor.js`。
- 表單欄位：`name, harness_id, provider, model, message_prefix, max_tokens_budget, default_env(只接受 env-var 名稱), cwd_root/cwd_prefix/repo_glob, scope(local|global)`。
  - credential/secret 欄位：**只有 env-var 名稱輸入**，client-side validate `^[A-Z][A-Z0-9_]*$`，**沒有 secret 值欄位**。
- 流程：list → 選/新增 → 編輯 → **dry-run（存 `base_mtime`）→ diff → apply（帶 `base_mtime`）→ rollback**。`409 stale_target` 自動 re-dry-run；`422 validation_errors`、`403 forbidden_path` inline 顯示。**base_mtime 一定要從 dry-run 帶到 apply**（照 config-editor.js 的作法）。
- delete UX：先送不帶 cascade，收到 `409 bound` 就顯示 bound projects，要使用者明確確認後才帶 `?cascade=true` 重送。
- bind project → profile；顯示 resolved profile（`GET /profiles` 已回 bindings）。
- validation 以 server 為準：表單只做輕量 shape hint，權威規則回顯 server 的 `validation_errors`。
- remote 模式唯讀（`Ao.isLocalWritable()===false` 時藏掉編輯 chrome，同 config-editor）。
- 在 `apps/web/index.html` 的 script 區（api.js→rollback→catalog-editor→config-editor→**新檔**→actions→app.js 順序）掛入，新增對應 tab 的 DOM（含所有 element id），在 `app.js` wiring。
- `ENDPOINTS` map 補 profile 相關路徑。

### 測試（`tests/test_web.py` + `test_api.py`）
- `test_web.py` 是 static-file 契約：照既有 `config-editor.js` 那套 assertion 風格，斷言新檔存在、index.html 有 `src="ui/profile-editor.js"`、必要 element id 存在。
- create/edit/delete round-trip 經 API（`test_api.py`）。
- redaction：default_env 只存名稱，斷言不出現值。

---

## 5. P20 — Registry editor backend（commit 3）

Spec 039。現況：`registry.py` 唯讀（`_load/list_agents/get/build_run/validate_registry`）。`agents.toml` 是 `[[agents]]` 陣列，doc = `{"agents":[...]}`。`AgentDefinition`（models.py）有 `enabled:bool=True`，disable = set false。

### 必做
1. schema `schemas/agentic_os/registry@v1.json` validate `{agents:[<AgentDefinition 形狀>]}`，欄位對齊 P3.7（`specs/007`）與 `models.AgentDefinition`。
2. whitelist 加 `("agentic_os","registry"): ("agents",)`。
3. 新 route（create/update/disable），全部走 `SafeEditEngine.apply`（PatchTarget: `harness_id="agentic_os"`, `kind="registry"`, `target_kind="registry"`, `file_format="toml"`, `file_path=registry_path`）：
   - `POST /registry/agents?dry_run=false` body = 一個 instance 物件。**list-by-id 語意**：在 Python 端讀現有 agents、依 `id` 取代或新增，組出完整 `after` list，再用兩個 op 表達整列取代：`remove agents` + `merge agents = <完整新 list>`（因為 `PatchEngine` 對 list 的 merge 是 append，會產生重複；whole-list replace 最乾淨）。
   - `POST /registry/agents/{id}/disable?dry_run=false` → 同樣 whole-list replace，把該 id 的 `enabled=false`。
   - 回 `_patch_result_dict`。
4. **`validate_registry` 語意 gate 要在 patch path 內**（schema 只擋結構，擋不掉 missing health_command 等語意）。建議：給 `SafeEditEngine.apply` 加 optional 參數 `extra_validator: Callable[[dict[str,Any]], list[str]] | None = None`，在算出 `after` 之後、stale 檢查/寫檔之前跑，回傳 errors 就 raise `ValidationError`。route 傳入一個把 `after["agents"]` parse 成 `AgentDefinition` 再呼叫 `validate_registry` 的 validator（`errors`→422；`warnings` 照回但放行）。**不要在 route 複製 apply 邏輯。**
5. **Registry 記憶體 cache（關鍵 landmine L1）**：`registry = Registry(registry_path)` 在 `create_app`（api.py:191）只建構一次，`list_agents()` 回 cache。寫檔後 cache 不會更新。
   - 在 `Registry` 加 `reload(self)`：`self._agents = self._load()`。
   - 每次 registry `apply` 成功後呼叫 `registry.reload()`。
   - **`patches_rollback`（api.py:1679）也要處理**：rollback 還原 agents.toml 後，若 `entry.target_path == str(registry_path)` 就 `registry.reload()`。否則 rollback 後記憶體仍是舊的，launch 會用錯 config。
6. cwd_mode enum 給前端：加一個小 route（如 `GET /registry/schema`）回 `{"cwd_mode":["required","optional","ignored"], ...}`，P21 dropdown 從這裡拿，不要在 JS 硬寫。

### 測試（`tests/test_registry.py` 新增 + `test_api.py`）
- create → reload 後出現在 `list_agents`（**一定要驗 reload 後**）。
- 不合法 instance 被 `validate_registry` 擋（422）。
- backup 有寫；`/patches/{id}/rollback` 後 agents.toml 還原**且** `list_agents` 反映還原（驗 reload）。
- 只有引擎寫 agents.toml（無第二 writer）。

---

## 6. P21 — Registry editor UI（commit 4）

Spec 040。純前端，跑在 P20 之上。

- 新檔 `apps/web/ui/registry-editor.js`，form-based，復用 shell（api.js + rollback.js + base_mtime 流程）。
- 欄位：`label, command, cwd_mode(dropdown，options 來自 P20 的 enum route), health_command, attach_command, log_paths, default_provider`。
- 流程：dry-run validate → diff → apply → rollback，同 P19。`validate_registry` 的 errors/warnings 在 apply 前 inline 顯示。
- command/health_command/attach_command 是 shell 面，**只顯示引擎回來的 redacted diff，不要在前端重組原值**。
- remote 唯讀。掛 index.html script + DOM + app.js wiring + ENDPOINTS。

### 測試
- `test_web.py` static 契約（新檔、`src="ui/registry-editor.js"`、element id）。
- create/edit/disable round-trip；validation errors/warnings 在 apply 前可見。

---

## 7. P22 — MCP / Skill / Policy rollback backend（commit 5，backend-only，UI 是 P23 不做）

Spec 041。現況：`control_plane.py` 的 `ControlPlaneStore`（SQLite，tables `skills/mcp_servers/agent_policies`）只有 `upsert_*/disable_*/deprecate_*/undeprecate_*`，**沒有 history/rollback/backup**。

### 機制決定（重要 landmine L3 — spec 的偏好做法現有引擎做不到）
spec 寫「偏好複用 `BackupStore` + 一個 restore callback，讓 `/patches/{id}/rollback` 也涵蓋這些 domain」。**但 `BackupStore.restore` 是寫死 file-copy、沒有 callback 機制**，硬塞 DB row 進 file rollback 路徑會動到 P16/P17 依賴的檔案 rollback，風險高。

**採 DB-native 做法，回傳同一個 envelope**（spec 真正要的「same envelope」是指 **response 形狀一致**，讓未來 P23 的 `ui/rollback.js` 不用分 domain branch，不是指共用儲存）：
1. 加 history table（如 `control_plane_history`）欄位含 `entity_type(skill|mcp|policy), entity_id, patch_id, version, snapshot_json, source, created_at, rolled_back_at`。
2. **snapshot-on-mutate**：在每個 `upsert_*/disable_*/deprecate_*/undeprecate_*` 寫入前，把**當前**record 快照一份。
3. 新 route（6 條）：`GET /{skills|mcp|policy}/{id}/history`、`POST /{skills|mcp|policy}/{id}/rollback?to=<patch_id|version>`。
   - mutation 結果與 rollback 回傳 envelope：`{patch_id, applied, diff, audit_event_id}`。
   - history row 形狀對齊 `ui/rollback.js` 會讀的欄位（`patch_id, target_kind, surface_id/target_path, source, created_at, rolled_back_at`），讓 P23 能直接用。
   - rollback：用快照經既有 `upsert_*` 重新套用。
4. **redaction（landmine L7）**：快照存的是**已 redact** 的 record（env-var 名稱，無值）。MCP `command_preview`/`url` 在 upsert 時已 redact（control_plane.py:380-381），快照沿用 `_redact_value`。秘密值永不進 history。
5. policy rollback 當成一般 policy 變更：發 audit event，gate 下次 evaluate 自然重讀（不要做特殊 bypass）。

### 測試（`tests/test_control_plane.py` + `test_policy_aware_run.py`）
- 每次 mutation 都寫一筆 prior-version snapshot。
- rollback 精確還原前一版。
- snapshot 不含 secret 值（redaction 斷言）。
- policy rollback 後 policy gate 立即生效（`test_policy_aware_run.py`）。

---

## 8. Landmine 總表（會咬人、spec 沒明寫）

- **L1 Registry 記憶體 cache**：P20 寫入後與 `/patches` rollback 還原後都要 `registry.reload()`（含 generic rollback handler 判 target_path==registry_path）。
- **L2 Profile TOML 重排**：走引擎後 `tomli_w` 會重排 profiles.toml；`_read_bundle` 容忍，但 assert 精確字串的測試要改成語意比較。
- **L3 P22 不能用 file rollback**：`BackupStore.restore` 無 callback，走 DB-native + 相同 response envelope，別動 file rollback 路徑。
- **L4 validate_registry gate**：用 `apply()` 的 optional `extra_validator` hook，別在 route 複製寫入邏輯。
- **L5 PatchEngine.diff 是 top-level shallow**：刪一個 profile 會顯示整個 `run_profiles` before/after，正確但冗長，**別去改 diff 粒度**（會破壞共用契約）。
- **L6 list 用 remove+merge 兩 op**：`project_profiles`、`agents` 這種 list 要整列取代時，用 `remove <path>` + `merge <path>=<新 list>` 一個 patch 內兩 op；別靠 index 算或 merge-append。
- **L7 P22 快照 redact**：存已 redact 的 record。
- **L8 新 route OK**：本批本來就要加 route，但 additive，別改既有形狀。
- **L9 single writer**：每個 domain 改完只能有一個 writer（profile→引擎、registry→引擎）。
- **L10 base_mtime 貫穿**：P19/P21 form 必須把 dry-run 的 `base_mtime` 帶到 apply，409 自動 re-dry-run。

## 9. 收尾驗證（PR 前，逐項貼輸出）

```bash
uv run pytest -q          # 目標：全綠（目前 ~555，本批會增加）
uv run ruff check .       # clean
uv run ruff format --check .
node --check apps/web/app.js
node --check apps/web/ui/profile-editor.js
node --check apps/web/ui/registry-editor.js
# 其餘改到的 .js 也跑 node --check
```

手動：local 模式各走一輪——Profile（建立→改 provider/model→dry-run→apply→rollback→delete with cascade）、Registry（建立 instance→disable→驗 list_agents 反映→rollback→驗 reload）、確認 remote 模式三個編輯面皆唯讀。

更新：`README.md` phase 表（P18–P22）、各對應 spec 狀態（Draft→Implemented 視慣例）。PR body 列每個 acceptance 對應的測試檔。

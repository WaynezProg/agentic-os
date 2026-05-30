# 024–026 Harness Manager Extension Design

Date: 2026-05-30
Status: Implemented (core in ea4590d; debt closure in 2026-05-30-024-026-debt-closure-design.md)
Author: agentic-os team

## 背景與目標

`agentic-os` 已建立 P3.7～P6 的 substrate，能列舉 harness、launch/run、
健康/漂移、policy、catalog、timeline 與設定掃描，但離「日常可用 Harness 管理總控台」仍缺：

1. harness adapter 行為不一致（run/health/attach/version/log 的 API 行為沒有統一契約）。
2. 缺少「這個 repo 這段工作用哪組 profile」的可持續決策模型。
3. 無法跨 harness 建立可預期的 usage/cost/quota 觀測。

本設計定義三個最小可交付群：`024 Adapter Contract v1`、`025 Run / Project Profile`、`026 Usage Ledger`。

## 非目標

- 不做 MCP/skills 的安裝與生命週期管理。
- 不做 harness 的工具迴圈、planner、planner-mesh、雲端同步。
- 不做 provider billing API 直接整合（例如即時查詢帳務）。
- 不做 UI 編輯器式複雜表單（仍以 API/CLI 為先，UI 增加展示）。

## 1) 024 Adapter Contract v1（P1）

### 目標
把 `claude` / `codex` / `opencode` / `qwen` / `openclaw` / `hermes`
對齊到同一份「可驗證契約」，降低後續 UI/CLI/agent 行為差異。

### 資料契約

新增 `src/agentic_os/adapter_contract.py` 與模型：

- `HarnessAdapterContract`（回傳給 API）：
  - `harness_id`（e.g. `claude`）
  - `contract_version`（固定先用 `v1`）
  - `launch.supported`（bool）
  - `launch.command_template`（`SessionStartRequest.template`）
  - `health.command_template`
  - `version.command_template`
  - `attach.command_template`
  - `logs.log_paths`
  - `capability`：`interactive`, `supports_attach`, `supports_session_id`, `supports_config_native`
  - `required_env`（名稱清單）
  - `error_modes`（`not_found`、`timeout`、`auth_error`、`parse_error`）

- `AgentDefinition` 仍保留現有執行欄位；契約欄位可由現有 `registry` + `harness profile` 推導。對外 API 不直接新增隱式欄位。

### API/CLI 變更（v1.0）

- `GET /harness-contracts`：回傳全部 harness 的 `HarnessAdapterContract`。
- `GET /harness-contracts/{harness_id}`：回傳單一契約。
- `GET /harnesses/{harness_id}/attach`：保持目前 `POST /sessions/{id}/attach` 作為 session-level API。
- CLI 增加：
  - `agentctl harness-contracts list`
  - `agentctl harness-contracts show <harness_id>`

### 測試邊界

- API schema 驗證：`contract_version`、`harness_id`、`error_modes`。
- 對未知 harness 回 `400`，錯誤 body 含 `supported` 列表。
- 至少 1 類 harness 的 `supports_attach=false` 仍可預覽。

### 成功條件

- 所有既有 harness 在 v1 契約中有 deterministic 回應。
- `agentctl harness-contracts list` 可列舉 6 個 harness 且不依賴 CLI 成功。

## 2) 025 Run Profile / Project Profile（P2）

### 目標
把「repo + task」如何選 harness/model/provider/env/profile」變成可預測設定，不靠操作員記憶。

### 設計

- 新增 profile 規格為「二層」：
  - `run_profile`（策略）
  - `project_profile`（選擇規則）

#### `run_profile`

- 存放欄位：
  - `name`
  - `harness_id`
  - `provider`
  - `model`
  - `default_env`
  - `message_prefix`
  - `max_tokens_budget`（可選）
  - `notes`
- 每條 profile 支援 `cwd_root`、`cwd_prefix`、`repo_glob` 選配。

#### `project_profile`

- 對一個 project_path 綁定 `run_profile` 名稱。
- 可 fallback：`global`（當找不到專案映射時）。

### 設定位置

- Control-plane 配置（不寫入 harness 原生檔）：
  - `~/.agentic-os/profiles.toml`
  - `<cwd>/.agentic-os/profiles.toml`

> 不併入 `config.toml` 的 `harness` 欄位，避免和既有 config scope 混淆。

### API/CLI

- `GET /profiles`
- `GET /profiles/{name}`
- `POST /profiles`
- `POST /projects/{path}/bind-profile`
- `POST /sessions` 新增可選欄位：`profile`。

- CLI：
  - `agentctl profiles list`
  - `agentctl profiles show <name>`
  - `agentctl profiles set --cwd . --name default --harness claude --provider anthropic --model sonnet`
  - `agentctl run <harness> --cwd . --message "..." --profile default`
  - `agentctl profile bind --cwd . --project . --name default`

### 決策流程

`POST /sessions` 時：

1. 先取 `profile`（如未給，解析 project profile）
2. 解析為 `resolved_profile`（含 harness/model/provider/env override）
3. 用 `resolved_profile` 進行 launch + policy evaluation（policy input 仍取 `resolved_profile.provider/model`）。

### 成功條件

- `--profile` 明確指定能 override session 命令。
- project profile 在無 `--profile` 時可自動生效。
- 不變更既有 harness 行為：policy 決策仍可重現。

## 3) 026 Usage Ledger（P3）

### 目標
以「可證據」為底，不做外部補帳：提供每 harness/session 可觀測的 token/cost/quota 近似值。

### 定義

- `UsageRecord`：`session_id, harness_id, provider, model, run_profile, cwd, started_at, ended_at, input_tokens, output_tokens, total_tokens, cost_usd, currency, source, raw_evidence`
- 來源：
  - `session stdout/stderr` parser（優先）：從可 parsable JSON 提取 usage。
  - fallback：`0`。

### parser 契約

- `UsageParser` 介面：
  - `supports(harness_id)`
  - `extract(lines: list[dict]) -> UsageRecord`。
- 先實作 `openclaw/claude/opencode/codex` 三個 parser；其餘先回零值。
- 不保存原始密鑰，只保留 token/cost 數字與 hash 後來源摘要。

### API/CLI/UI

- `GET /usage/summary?from=&to=&harness_id=&provider=`
- `GET /usage/sessions/{session_id}`
- `GET /usage/quotas?scope=daily|session`
- CLI：
  - `agentctl usage summary --from ... --to ...`
  - `agentctl usage session <session_id>`
  - `agentctl usage quota`（顯示剩餘風險，非即時扣費）。

### 限制與合規

- 不保證與 provider 計費一致，`cost_usd` 為**估算值**。
- 未提供 provider 金鑰；只做 local 監測。

### 成功條件

- 能列出歷史 session usage；有 session 無資料時顯示 `N/A` 不報錯。
- 日/週聚合可顯示趨勢且可排序。
- 錯誤/格式不符時可追溯 parser 來源與 fallback 路徑。

## 依賴順序與分期

1. `024`：先確立 adapter 契約，避免 profile/usage 直接繞過一致回應。
2. `025`：用契約擴張 session 建立流程，先不牽涉 usage。
3. `026`：在 `024+025` 穩定後補 usage parser 與報表。

## 風險

- 不同 harness 輸出格式不一致，usage parser 可能大量 fallback；短期只保證「可否得出」不是「完全精準」。
- Project profile 來源過多（global + local）容易衝突；需明確優先順序。
- 契約穩定度：`contract_version` 變更需 schema 相容策略（先 `v1`，非破壞式新增欄位）。

## 實作前置驗收（不做 code）

- 先把這份設計同時對齊 `docs/superpowers/plans/2026-05-30-spec-schedule-018-plus-design.md`。
- README 保持 `Harness Manager` 定位（`Local Harness Manager control plane`）。
- 目前 018–023 覆蓋範圍維持不變。


# 010 — Configuration Scope Mapper (P5)

Status: Draft
Date: 2026-05-30

## Positioning

P5 定義 agentic-os 的設定範圍（scope）層級，支援多個 harness instance 在不同 scope 的設定讀取、合併與顯示。類似 Claude Code 的 Managed / User / Project / Local 設定視圖，但只做「讀取、合併、顯示」，不修改設定檔。

| Phase | Existing result | Harness Manager substrate role | Owns | Does not own |
|-------|-----------------|--------------------------------|------|--------------|
| P5 | configuration scope mapper | multi-scope config view per harness instance | read, merge, display effective config across scopes | modifying config files, writing configs, harness-internal config loading |

## Scope Levels

| Scope | Location | Priority |
|-------|----------|----------|
| managed | 系統層級 baseline（machine/org） | 最低 |
| user | `~/.agentic-os/config.toml` | 次低 |
| project | `<cwd>/.agentic-os/config.toml` | 次高 |
| local | `<cwd>/.agentic-os.local/config.toml` | 最高 |

Scope resolution: 從給定的 `--cwd` 向上尋找 `.agentic-os/config.toml`，找到即為 project scope。local scope 只在 cwd 目錄下。

## CLI Commands

```bash
# 顯示單一 harness 在指定 cwd 下的有效設定
agentctl config effective openclaw@work --cwd ~/Projects/demo

# 比較 scopes 之間的差異
agentctl config diff openclaw@work --scope user --scope project

# 解釋設定值從哪裡來
agentctl config explain openclaw@work --cwd ~/Projects/demo
```

## API Endpoints

```
GET /config/{harness_id}/effective?cwd=<path>
GET /config/{harness_id}/diff?scope_a=<a>&scope_b=<b>&cwd=<path>
GET /config/{harness_id}/explain?cwd=<path>
```

## Out of Scope

- 不修改或寫入任何設定檔
- 不解析 harness-internal 的設定格式（只處理 agentic-os 自身的 config.toml）
- 不做設定驗證或提示（那是 harness 的責任）

## Compatibility

既有的 P4 harness instance profile（agents.toml）維持不變。P5 是額外的 scope layer，從 project 目錄讀取補充設定。

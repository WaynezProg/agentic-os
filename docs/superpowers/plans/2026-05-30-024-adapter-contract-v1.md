# Adapter Contract v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

I'm using the `writing-plans` skill to create the implementation plan.

**Goal:** 提供 `/harness-contracts` 及對應 CLI，讓所有註冊 harness 回傳一致的 `HarnessAdapterContract`，供 run / attach / logs / health 工具決策使用。

**Architecture:** 新增 `adapter_contract` 模組定義資料結構與 `contract_from_agent` 映射邏輯；`api.py` 只做 HTTP 介面與輸入驗證；`client.py` / `cli.py` 專責呼叫封裝與輸出。既有 `/harnesses` 行為保持不變。

**Tech Stack:** FastAPI、Typer、Pydantic、pytest、Typer CliRunner。

---

## File Structure

| File | Changes |
|---|---|
| `src/agentic_os/adapter_contract.py` | 新增 `HarnessAdapterContract`、`CommandTemplate`、`ContractCapabilities` 與 `contract_from_agent` |
| `src/agentic_os/api.py` | 新增 `/harness-contracts`、`/harness-contracts/{harness_id}` |
| `src/agentic_os/client.py` | 新增 `list_harness_contracts` / `show_harness_contract` |
| `src/agentic_os/cli.py` | 新增 `harness-contracts list/show` |
| `tests/test_adapter_contract.py` | 契約模型與 builder 測試（新檔） |
| `tests/test_api.py` | 契約 API 行為測試 |
| `tests/test_cli.py` | CLI 呼叫測試 |

---

### Task 1: 建立 Adapter Contract Schema 與 Builder

**Files:**
- Create: `src/agentic_os/adapter_contract.py`
- Create: `tests/test_adapter_contract.py`

- [ ] **Step 1: 寫入失敗測試（模型輸出固定欄位）**

```python
from pydantic import BaseModel
from agentic_os.adapter_contract import contract_from_agent


def test_contract_from_agent_has_required_fields() -> None:
    fake_agent = type(
        "Agent",
        (),
        {
            "id": "claude",
            "command": ["claude", "--print", "{message}"],
            "health_command": ["claude", "--status"],
            "version_command": ["claude", "--version"],
            "attach_command": ["claude", "resume", "{session_id}"],
            "env": {"ANTHROPIC_API_KEY": "x"},
            "config_path": "/home/user/.claude/settings.toml",
            "log_paths": ["/tmp/claude.log"],
            "cwd_mode": "session",
        },
    )()
    contract = contract_from_agent(fake_agent)

    assert isinstance(contract, BaseModel)
    assert contract.contract_version == "v1"
    assert contract.launch.command_template == ["claude", "--print", "{message}"]
    assert contract.health.command_template == ["claude", "--status"]
    assert contract.version.command_template == ["claude", "--version"]
    assert contract.attach.command_template == ["claude", "resume", "{session_id}"]
    assert contract.capability.interactive is True
    assert contract.required_env == ["ANTHROPIC_API_KEY"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_adapter_contract.py::test_contract_from_agent_has_required_fields -q`
Expected: FAIL (module/function not found).

- [ ] **Step 3: 實作 `adapter_contract.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ContractVersion = Literal["v1"]


class CommandTemplate(BaseModel):
    command_template: list[str]


class ContractCapabilities(BaseModel):
    interactive: bool = False
    supports_attach: bool = False
    supports_session_id: bool = False
    supports_config_native: bool = False


class HarnessAdapterContract(BaseModel):
    harness_id: str
    contract_version: ContractVersion = "v1"
    launch: CommandTemplate
    health: CommandTemplate
    version: CommandTemplate
    attach: CommandTemplate
    logs: dict[str, list[str]]
    capability: ContractCapabilities = Field(default_factory=ContractCapabilities)
    required_env: list[str] = Field(default_factory=list)
    error_modes: list[str] = Field(
        default_factory=lambda: ["not_found", "timeout", "auth_error", "parse_error"]
    )


_SUPPORTS_SESSION_ID = {"openclaw", "hermes", "opencode"}
_INTERACTIVE_HINT = {"interactive": False, "supports_attach": False, "supports_session_id": False}


def _required_env(agent) -> list[str]:
    return sorted(agent.env.keys()) if getattr(agent, "env", None) else []


def contract_from_agent(agent) -> HarnessAdapterContract:
    harness_id = getattr(agent, "id")
    capability = ContractCapabilities(
        interactive=getattr(agent, "interactive", False),
        supports_attach=bool(getattr(agent, "attach_command", [])),
        supports_session_id=harness_id in _SUPPORTS_SESSION_ID,
        supports_config_native=getattr(agent, "config_path", None) is not None,
    )
    return HarnessAdapterContract(
        harness_id=harness_id,
        launch=CommandTemplate(command_template=list(getattr(agent, "command", []))),
        health=CommandTemplate(command_template=list(getattr(agent, "health_command", []))),
        version=CommandTemplate(command_template=list(getattr(agent, "version_command", []))),
        attach=CommandTemplate(command_template=list(getattr(agent, "attach_command", []))),
        logs={"log_paths": list(getattr(agent, "log_paths", []))},
        capability=capability,
        required_env=_required_env(agent),
    )
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_adapter_contract.py::test_contract_from_agent_has_required_fields -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/adapter_contract.py tests/test_adapter_contract.py
git commit -m "feat: add harness adapter contract model"
```

---

### Task 2: 新增 Harness Contract API

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: 寫入失敗測試（list/show）**

```python
def test_harness_contracts_list_and_show(tmp_path) -> None:
    # with registry fixture for shell + claude
    response = client.get("/harness-contracts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert all(item["contract_version"] == "v1" for item in payload["contracts"])


def test_harness_contracts_show_unknown(tmp_path) -> None:
    response = client.get("/harness-contracts/missing")
    assert response.status_code == 400
    assert "supported" in response.json()["detail"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_api.py -k "harness_contract" -q`
Expected: FAIL (endpoint missing / payload mismatch).

- [ ] **Step 3: 實作路由**

```python
from agentic_os.adapter_contract import contract_from_agent


@app.get("/harness-contracts")
def list_harness_contracts() -> dict[str, object]:
    registry_agents = registry.list_agents()
    contracts = sorted(
        (contract_from_agent(agent).model_dump() for agent in registry_agents),
        key=lambda row: row["harness_id"],
    )
    return {"contracts": contracts, "count": len(contracts)}


@app.get("/harness-contracts/{harness_id}")
def show_harness_contract(harness_id: str) -> dict[str, object]:
    try:
        agent = registry.get(harness_id)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail={"message": f"unknown harness: {harness_id}", "supported": [a.id for a in registry.list_agents()]},
        )
    return contract_from_agent(agent).model_dump()
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_api.py -k "harness_contract" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(api): expose harness contract list/show endpoints"
```

---

### Task 3: 擴充 Client API

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 寫入失敗測試**

```python
def test_client_calls_harness_contract_endpoints(monkeypatch) -> None:
    fake = RecordingClient()
    monkeypatch.setattr("agentic_os.cli.make_client", lambda *_args, **_kwargs: fake)
    client = agentic_os.client.AgenticOSClient(base_url="http://example.com")
    assert client.list_harness_contracts()["contracts"] == []
    assert client.show_harness_contract("shell")["harness_id"] == "shell"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_cli.py -k "harness_contract" -q`
Expected: FAIL (methods not implemented).

- [ ] **Step 3: 實作 client methods**

```python
class AgenticOSClient:
    ...

    def list_harness_contracts(self) -> dict[str, object]:
        return self._get("/harness-contracts")

    def show_harness_contract(self, harness_id: str) -> dict[str, object]:
        return self._get(f"/harness-contracts/{_validate_path_id(harness_id)}")
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_cli.py -k "harness_contract" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/client.py tests/test_cli.py
git commit -m "feat(client): add harness contract methods"
```

---

### Task 4: 實作 `harness-contracts` CLI

**Files:**
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 寫入失敗測試**

```python
def test_cli_harness_contract_commands(monkeypatch) -> None:
    fake = RecordingClient()
    monkeypatch.setattr("agentic_os.cli.make_client", lambda *_args, **_kwargs: fake)
    runner = CliRunner()

    list_result = runner.invoke(cli.app, ["harness-contracts", "list"])
    assert list_result.exit_code == 0

    show_result = runner.invoke(cli.app, ["harness-contracts", "show", "shell"])
    assert show_result.exit_code == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_cli.py -k "harness_contract" -q`
Expected: FAIL (command group missing / wrong path).

- [ ] **Step 3: 實作 CLI**

```python
harness_contract_cmd = typer.Typer(help="Inspect harness adapter contracts.")
app.add_typer(harness_contract_cmd, name="harness-contracts")


@harness_contract_cmd.command("list")
def harness_contracts_list(api: str | None = _api_option()) -> None:
    data = _run_api_call(lambda: make_client(api).list_harness_contracts())
    for contract in data["contracts"]:
        typer.echo(f"{contract['harness_id']}\t{contract['contract_version']}\t{contract['required_env']}")


@harness_contract_cmd.command("show")
def harness_contracts_show(harness_id: str, api: str | None = _api_option()) -> None:
    _echo_json(_run_api_call(lambda: make_client(api).show_harness_contract(harness_id)))
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_cli.py -k "harness_contract" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(cli): add harness-contracts list/show"
```

---

### Self-Review

- [ ] `contract_version` 一律回傳 `"v1"`。
- [ ] `supports_session_id` 對於 `openclaw`/`hermes`/`opencode` 為 true，其它 false。
- [ ] unknown harness 回傳 400 並列出 `supported`。
- [ ] `/harness-contracts` 與 `/harnesses` 同步回傳一致的 harness 列表。
- [ ] 所有測試都按 TDD 流程先寫 fail -> 實作 -> pass。

### Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-024-adapter-contract-v1.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Use `superpowers:executing-plans` for checkpointed in-session execution

Which approach?

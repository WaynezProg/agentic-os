# Adapter Contract v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Adapter Contract v2 through API and CLI with deterministic semantic harness contracts and golden fixture coverage.

**Architecture:** Keep v1 as the default compatibility contract. Add v2 Pydantic models and mapping in `adapter_contract.py`, then expose the selected version through API, client, and CLI query/option plumbing. Golden fixtures lock the seven semantic harness payloads while direct unit tests assert important semantics that fixtures alone cannot prove.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, Typer, pytest, Ruff.

---

## File Structure

- Modify: `src/agentic_os/adapter_contract.py`
  - Owns v1 models today.
  - Add v2 models, semantic mappings, version selector helpers, and `contract_from_agent_v2()`.
- Modify: `src/agentic_os/api.py`
  - Add `version` query parameter to `/harness-contracts` endpoints.
  - Return v1 by default and v2 when `version=v2`.
- Modify: `src/agentic_os/client.py`
  - Add optional `version` parameter to harness contract client calls.
- Modify: `src/agentic_os/cli.py`
  - Add `--version` option to `agentctl harness-contracts list|show`.
- Modify: `tests/test_adapter_contract.py`
  - Add direct v2 semantic tests and fixture comparison tests.
- Modify: `tests/test_api.py`
  - Add v2 endpoint tests and unsupported version tests.
- Modify: `tests/test_cli.py`
  - Add client and CLI `--version v2` tests.
- Create: `tests/fixtures/adapter_contract_v2/*.json`
  - Golden payloads for `claude`, `codex`, `cursor`, `hermes`, `openclaw`, `opencode`, `qwen`.
- Modify: `specs/024-adapter-contract-v1.md`
  - Add follow-up pointer that v2 exists while v1 remains default.

---

### Task 1: Add v2 Models and Direct Semantics

**Files:**
- Modify: `src/agentic_os/adapter_contract.py`
- Modify: `tests/test_adapter_contract.py`

- [ ] **Step 1: Write failing v2 unit tests**

Append these tests to `tests/test_adapter_contract.py`:

```python
from pathlib import Path

from agentic_os.adapter_contract import (
    SEMANTIC_HARNESS_IDS,
    HarnessAdapterContractV2,
    contract_from_agent_v2,
)
from agentic_os.registry import Registry


def test_contract_v2_cursor_semantics() -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get("cursor"))

    assert isinstance(contract, HarnessAdapterContractV2)
    assert contract.contract_version == "v2"
    assert contract.launch.prompt_input_mode == "argv"
    assert contract.launch.output_mode == "plain_text"
    assert contract.launch.requires_workspace is True
    assert contract.resume.supported is True
    assert contract.resume.identity_kind == "upstream_session_id"
    assert contract.resume.requires_discovered_identity is True
    assert contract.attach.supported is True
    assert contract.config.native_supported is True
    assert ".cursor/cli-config.json" in contract.config.native_files
    assert ".cursor/mcp.json" in contract.config.native_files
    assert ".cursor/hooks.json" in contract.config.native_files
    assert contract.surface.hook_scan is True
    assert contract.policy.launch_gate is True
    assert contract.policy.runtime_enforcement is False
    assert contract.capability_matrix["resume"] is True
    assert contract.capability_matrix["json_output"] is False


def test_contract_v2_openclaw_declares_json_usage() -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get("openclaw"))

    assert contract.launch.output_mode == "json"
    assert contract.usage.supported is True
    assert contract.usage.source == "openclaw"
    assert contract.usage.evidence_mode == "json"
    assert contract.capability_matrix["json_output"] is True
    assert contract.capability_matrix["usage_parse"] is True


def test_contract_v2_semantic_harness_set_excludes_shell() -> None:
    assert SEMANTIC_HARNESS_IDS == (
        "claude",
        "codex",
        "cursor",
        "hermes",
        "openclaw",
        "opencode",
        "qwen",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
```

Expected: failure importing `SEMANTIC_HARNESS_IDS`, `HarnessAdapterContractV2`, or `contract_from_agent_v2`.

- [ ] **Step 3: Implement v2 models and mapping**

Add these imports and aliases to `src/agentic_os/adapter_contract.py`:

```python
from typing import Any, Literal

ContractVersion = Literal["v1"]
ContractVersionAny = Literal["v1", "v2"]
PromptInputMode = Literal["argv", "stdin", "file", "json"]
OutputMode = Literal["plain_text", "json", "jsonl", "tool_events", "mixed"]
NativeIdentityKind = Literal["none", "upstream_session_id", "conversation_id", "thread_id"]
ResumeStrategy = Literal["unsupported", "command", "best_effort"]
LogStreamContract = Literal["none", "text", "json", "jsonl", "mixed"]
EventTimelineMode = Literal["stdout_stderr_only"]
UsageEvidenceMode = Literal["json", "jsonl", "text_regex", "none"]
ConfigFileKind = Literal["json", "toml", "markdown"]
ConfigScopeName = Literal["user", "project", "local"]
```

Add the v2 models below `HarnessAdapterContract`:

```python
class LaunchContractV2(BaseModel):
    supported: bool = True
    command_template: list[str] = Field(default_factory=list)
    prompt_input_mode: PromptInputMode = "argv"
    output_mode: OutputMode = "plain_text"
    cwd_mode: str = "optional"
    requires_workspace: bool = False


class NativeSessionContractV2(BaseModel):
    supported: bool = False
    command_template: list[str] = Field(default_factory=list)
    identity_kind: NativeIdentityKind = "none"
    requires_discovered_identity: bool = False
    strategy: ResumeStrategy = "unsupported"


class LogContractV2(BaseModel):
    paths: list[str] = Field(default_factory=list)
    stdout_contract: LogStreamContract = "text"
    stderr_contract: LogStreamContract = "text"
    event_timeline: EventTimelineMode = "stdout_stderr_only"


class UsageContractV2(BaseModel):
    supported: bool = False
    source: str = "fallback"
    evidence_mode: UsageEvidenceMode = "none"
    fields: list[str] = Field(default_factory=list)


class ConfigContractV2(BaseModel):
    native_supported: bool = False
    scopes: list[ConfigScopeName] = Field(default_factory=list)
    primary_path: str | None = None
    native_files: list[str] = Field(default_factory=list)
    file_kinds: list[ConfigFileKind] = Field(default_factory=list)
    redacts_secrets: bool = True


class SurfaceContractV2(BaseModel):
    mcp_scan: bool = False
    skill_scan: bool = False
    command_scan: bool = False
    hook_scan: bool = False
    subagent_scan: bool = False
    native_config_scan: bool = False


class PolicyContractV2(BaseModel):
    launch_gate: bool = True
    preflight_config_warning: bool = True
    runtime_enforcement: bool = False
    native_policy: bool = False
    notes: str = "agentic-os currently gates launch and preflight warnings only."


class HarnessAdapterContractV2(BaseModel):
    harness_id: str
    contract_version: Literal["v2"] = "v2"
    launch: LaunchContractV2
    resume: NativeSessionContractV2
    attach: NativeSessionContractV2
    log: LogContractV2
    usage: UsageContractV2
    config: ConfigContractV2
    surface: SurfaceContractV2
    policy: PolicyContractV2 = Field(default_factory=PolicyContractV2)
    capability_matrix: dict[str, bool] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    error_modes: list[str] = Field(
        default_factory=lambda: ["not_found", "timeout", "auth_error", "parse_error"]
    )
```

Add semantic constants and helper functions:

```python
SUPPORTED_CONTRACT_VERSIONS: tuple[str, ...] = ("v1", "v2")
SEMANTIC_HARNESS_IDS = ("claude", "codex", "cursor", "hermes", "openclaw", "opencode", "qwen")

_JSON_OUTPUT_HARNESSES = {"openclaw"}
_TEXT_REGEX_USAGE_HARNESSES = {"claude", "codex", "cursor", "hermes", "opencode", "qwen"}
_USAGE_SOURCE_BY_HARNESS = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor",
    "hermes": "fallback",
    "openclaw": "openclaw",
    "opencode": "opencode",
    "qwen": "fallback",
}
_CURSOR_NATIVE_FILES = [
    ".cursor/cli-config.json",
    ".cursor/mcp.json",
    ".cursor/hooks.json",
]
_JSON_CONFIG_HARNESSES = {"claude", "cursor"}
_TOML_CONFIG_HARNESSES = {"codex", "hermes", "openclaw", "opencode", "qwen"}
_HOOK_SCAN_HARNESSES = {"claude", "cursor"}


def contract_from_agent_v2(agent: AgentDefinition) -> HarnessAdapterContractV2:
    supports_native_identity = agent.id in _SESSION_ID_CAPABLE_HARNESSES or agent.id == "cursor"
    output_mode: OutputMode = "json" if agent.id in _JSON_OUTPUT_HARNESSES else "plain_text"
    usage_evidence: UsageEvidenceMode = (
        "json"
        if agent.id in _JSON_OUTPUT_HARNESSES
        else "text_regex"
        if agent.id in _TEXT_REGEX_USAGE_HARNESSES
        else "none"
    )
    usage_supported = usage_evidence != "none"
    native_supported = agent.config_path is not None
    config_scopes: list[ConfigScopeName] = (
        ["user", "project", "local"] if native_supported else []
    )
    native_files = _native_config_files(agent.id)
    file_kinds = _config_file_kinds(agent.id, native_supported)
    resume = NativeSessionContractV2(
        supported=supports_native_identity,
        command_template=list(agent.attach_command or []),
        identity_kind="upstream_session_id" if supports_native_identity else "none",
        requires_discovered_identity=supports_native_identity,
        strategy="command" if agent.attach_command else "best_effort" if supports_native_identity else "unsupported",
    )
    attach = NativeSessionContractV2(
        supported=bool(agent.attach_command),
        command_template=list(agent.attach_command or []),
        identity_kind="upstream_session_id" if supports_native_identity else "none",
        requires_discovered_identity=supports_native_identity,
        strategy="command" if agent.attach_command else "unsupported",
    )
    surface = SurfaceContractV2(
        mcp_scan=native_supported,
        skill_scan=native_supported,
        command_scan=native_supported,
        hook_scan=agent.id in _HOOK_SCAN_HARNESSES,
        subagent_scan=native_supported,
        native_config_scan=native_supported,
    )
    capability_matrix = {
        "launch": bool(agent.command),
        "resume": resume.supported,
        "attach": attach.supported,
        "json_output": output_mode == "json",
        "mcp_scan": surface.mcp_scan,
        "skill_scan": surface.skill_scan,
        "usage_parse": usage_supported,
        "native_policy": False,
        "sandbox": False,
        "config_scopes": bool(config_scopes),
    }
    return HarnessAdapterContractV2(
        harness_id=agent.id,
        launch=LaunchContractV2(
            supported=bool(agent.command),
            command_template=list(agent.command),
            output_mode=output_mode,
            cwd_mode=agent.cwd_mode,
            requires_workspace=agent.cwd_mode == "required",
        ),
        resume=resume,
        attach=attach,
        log=LogContractV2(paths=list(agent.log_paths)),
        usage=UsageContractV2(
            supported=usage_supported,
            source=_USAGE_SOURCE_BY_HARNESS.get(agent.id, "fallback"),
            evidence_mode=usage_evidence,
            fields=[
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cost_usd",
                "currency",
                "raw_evidence",
            ],
        ),
        config=ConfigContractV2(
            native_supported=native_supported,
            scopes=config_scopes,
            primary_path=agent.config_path,
            native_files=native_files,
            file_kinds=file_kinds,
            redacts_secrets=True,
        ),
        surface=surface,
        capability_matrix=capability_matrix,
        required_env=sorted(agent.env.keys()),
    )


def _native_config_files(harness_id: str) -> list[str]:
    if harness_id == "cursor":
        return list(_CURSOR_NATIVE_FILES)
    if harness_id == "claude":
        return [".claude/settings.json"]
    if harness_id == "codex":
        return [".codex/config.toml"]
    if harness_id == "opencode":
        return [".opencode/config.toml"]
    if harness_id == "qwen":
        return [".qwen/config.toml"]
    if harness_id == "openclaw":
        return [".openclaw/config.toml"]
    if harness_id == "hermes":
        return [".hermes/config.toml"]
    return []


def _config_file_kinds(harness_id: str, native_supported: bool) -> list[ConfigFileKind]:
    if not native_supported:
        return []
    if harness_id in _JSON_CONFIG_HARNESSES:
        return ["json"]
    if harness_id in _TOML_CONFIG_HARNESSES:
        return ["toml"]
    return []
```

Run `rtk uv run ruff format src/agentic_os/adapter_contract.py tests/test_adapter_contract.py` after editing.

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
rtk uv run ruff check src/agentic_os/adapter_contract.py tests/test_adapter_contract.py
```

Expected: adapter contract tests pass and Ruff reports no issues.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/agentic_os/adapter_contract.py tests/test_adapter_contract.py
git commit -m "feat: add adapter contract v2 models"
```

---

### Task 2: Add Golden Fixtures

**Files:**
- Create: `tests/fixtures/adapter_contract_v2/claude.json`
- Create: `tests/fixtures/adapter_contract_v2/codex.json`
- Create: `tests/fixtures/adapter_contract_v2/cursor.json`
- Create: `tests/fixtures/adapter_contract_v2/hermes.json`
- Create: `tests/fixtures/adapter_contract_v2/openclaw.json`
- Create: `tests/fixtures/adapter_contract_v2/opencode.json`
- Create: `tests/fixtures/adapter_contract_v2/qwen.json`
- Modify: `tests/test_adapter_contract.py`

- [ ] **Step 1: Write failing fixture coverage tests**

Append to `tests/test_adapter_contract.py`:

```python
import json
import pytest


FIXTURE_DIR = Path("tests/fixtures/adapter_contract_v2")


@pytest.mark.parametrize("harness_id", SEMANTIC_HARNESS_IDS)
def test_contract_v2_matches_golden_fixture(harness_id: str) -> None:
    registry = Registry(Path("examples/agents.toml"))
    contract = contract_from_agent_v2(registry.get(harness_id))
    fixture_path = FIXTURE_DIR / f"{harness_id}.json"

    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert contract.model_dump(mode="json") == expected


def test_contract_v2_fixtures_cover_only_semantic_harnesses() -> None:
    fixture_ids = tuple(sorted(path.stem for path in FIXTURE_DIR.glob("*.json")))

    assert fixture_ids == SEMANTIC_HARNESS_IDS
    assert "shell" not in fixture_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
```

Expected: fixture tests fail because `tests/fixtures/adapter_contract_v2/*.json` do not exist.

- [ ] **Step 3: Generate checked-in fixture files**

Run this exact script from repo root:

```bash
rtk uv run python - <<'PY'
import json
from pathlib import Path

from agentic_os.adapter_contract import SEMANTIC_HARNESS_IDS, contract_from_agent_v2
from agentic_os.registry import Registry

out = Path("tests/fixtures/adapter_contract_v2")
out.mkdir(parents=True, exist_ok=True)
registry = Registry(Path("examples/agents.toml"))

for harness_id in SEMANTIC_HARNESS_IDS:
    contract = contract_from_agent_v2(registry.get(harness_id))
    payload = contract.model_dump(mode="json")
    (out / f"{harness_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
PY
```

- [ ] **Step 4: Run tests to verify fixture coverage passes**

Run:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
rtk uv run python -m json.tool tests/fixtures/adapter_contract_v2/cursor.json >/dev/null
```

Expected: tests pass and JSON parser exits 0.

- [ ] **Step 5: Commit Task 2**

```bash
git add tests/test_adapter_contract.py tests/fixtures/adapter_contract_v2
git commit -m "test: add adapter contract v2 fixtures"
```

---

### Task 3: Expose v2 in API

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Append these tests near existing harness contract tests in `tests/test_api.py`:

```python
def test_harness_contracts_list_v2(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts?version=v2")

    assert response.status_code == 200
    payload = response.json()
    contracts = payload["contracts"]
    harness_ids = {item["harness_id"] for item in contracts}
    assert "cursor" in harness_ids
    assert "shell" in harness_ids
    assert payload["count"] >= 8
    assert all(item["contract_version"] == "v2" for item in contracts)
    cursor = next(item for item in contracts if item["harness_id"] == "cursor")
    assert cursor["launch"]["prompt_input_mode"] == "argv"
    assert cursor["config"]["native_files"] == [
        ".cursor/cli-config.json",
        ".cursor/mcp.json",
        ".cursor/hooks.json",
    ]
    assert cursor["policy"]["runtime_enforcement"] is False


def test_harness_contracts_show_v2(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts/openclaw?version=v2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "v2"
    assert payload["launch"]["output_mode"] == "json"
    assert payload["usage"]["evidence_mode"] == "json"
    assert payload["capability_matrix"]["json_output"] is True


def test_harness_contracts_unsupported_version(tmp_path: Path) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "agents.toml"
    client = TestClient(create_app(state_dir=tmp_path / ".agentic-os", registry_path=examples))

    response = client.get("/harness-contracts?version=v3")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "message": "unsupported contract version: v3",
        "supported": ["v1", "v2"],
    }
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
rtk uv run pytest tests/test_api.py -k harness_contract -q
```

Expected: v2 tests fail because API ignores or rejects no `version` parameter.

- [ ] **Step 3: Implement API version selection**

In `src/agentic_os/api.py`, update imports:

```python
from agentic_os.adapter_contract import (
    SUPPORTED_CONTRACT_VERSIONS,
    contract_from_agent,
    contract_from_agent_v2,
)
```

Add helper inside `create_app()` near contract endpoints:

```python
    def _contract_payload(agent: AgentDefinition, version: str) -> dict[str, object]:
        if version == "v1":
            return contract_from_agent(agent).model_dump()
        if version == "v2":
            return contract_from_agent_v2(agent).model_dump(mode="json")
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unsupported contract version: {version}",
                "supported": list(SUPPORTED_CONTRACT_VERSIONS),
            },
        )
```

Update endpoints:

```python
    @app.get("/harness-contracts")
    def list_harness_contracts(version: str = Query(default="v1")) -> dict[str, object]:
        agents = registry.list_agents()
        contracts = [_contract_payload(agent, version) for agent in agents]
        contracts.sort(key=lambda contract: str(contract["harness_id"]))
        return {"contracts": contracts, "count": len(contracts)}

    @app.get("/harness-contracts/{harness_id}")
    def show_harness_contract(
        harness_id: str, version: str = Query(default="v1")
    ) -> dict[str, object]:
        try:
            agent = registry.get(harness_id)
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"unknown harness: {harness_id}",
                    "supported": [agent.id for agent in registry.list_agents()],
                },
            )
        return _contract_payload(agent, version)
```

- [ ] **Step 4: Run API tests**

Run:

```bash
rtk uv run pytest tests/test_api.py -k harness_contract -q
rtk uv run ruff check src/agentic_os/api.py tests/test_api.py
```

Expected: harness contract API tests pass and Ruff reports no issues.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat: expose adapter contract v2 api"
```

---

### Task 4: Wire Client and CLI Version Option

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing client and CLI tests**

Update `FakeClient` in `tests/test_cli.py`:

```python
    def list_harness_contracts(self, version: str = "v1") -> dict[str, object]:
        self.calls.append(("list_harness_contracts", (), {"version": version}))
        return {
            "contracts": [
                {
                    "harness_id": "shell",
                    "contract_version": version,
                    "required_env": [],
                }
            ],
            "count": 1,
        }

    def show_harness_contract(self, harness_id: str, version: str = "v1") -> dict[str, object]:
        self.calls.append(("show_harness_contract", (harness_id,), {"version": version}))
        return {"harness_id": harness_id, "contract_version": version}
```

Update `test_client_calls_harness_contract_endpoints`:

```python
def test_client_calls_harness_contract_endpoints(monkeypatch: Any) -> None:
    client = AgenticClient(base_url="http://example.com")
    calls: list[tuple[str, dict[str, object] | None]] = []
    responses: list[dict[str, object]] = [
        {"contracts": [], "count": 0},
        {"harness_id": "shell", "contract_version": "v2"},
    ]

    def fake_get(path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        calls.append((path, params))
        return responses.pop(0)

    monkeypatch.setattr(client, "_get", fake_get)
    assert client.list_harness_contracts(version="v2")["contracts"] == []
    assert client.show_harness_contract("shell", version="v2")["harness_id"] == "shell"
    assert calls == [
        ("/harness-contracts", {"version": "v2"}),
        ("/harness-contracts/shell", {"version": "v2"}),
    ]
```

Update `test_cli_harness_contract_commands`:

```python
def test_cli_harness_contract_commands(monkeypatch: Any) -> None:
    fake = FakeClient()
    install_fake_client(monkeypatch, fake)
    runner = CliRunner()

    list_result = runner.invoke(cli.app, ["harness-contracts", "list", "--version", "v2"])
    assert list_result.exit_code == 0
    assert "shell\tv2" in list_result.output

    show_result = runner.invoke(cli.app, ["harness-contracts", "show", "shell", "--version", "v2"])
    assert show_result.exit_code == 0
    assert '"contract_version": "v2"' in show_result.output
    assert fake.calls[-2:] == [
        ("list_harness_contracts", (), {"version": "v2"}),
        ("show_harness_contract", ("shell",), {"version": "v2"}),
    ]
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
rtk uv run pytest tests/test_cli.py -k harness_contract -q
```

Expected: tests fail because client and CLI signatures do not accept `version`.

- [ ] **Step 3: Implement client version params**

In `src/agentic_os/client.py`:

```python
    def list_harness_contracts(self, version: str = "v1") -> dict[str, Any]:
        return self._get("/harness-contracts", params={"version": version})

    def show_harness_contract(self, harness_id: str, version: str = "v1") -> dict[str, Any]:
        return self._get(
            f"/harness-contracts/{_validate_path_id(harness_id)}",
            params={"version": version},
        )
```

- [ ] **Step 4: Implement CLI version options**

In `src/agentic_os/cli.py`, update commands:

```python
@harness_contract_cmd.command("list")
def harness_contracts_list(
    version: str = typer.Option("v1", "--version", help="Contract version: v1 or v2."),
    api: str | None = _api_option(),
) -> None:
    data = _run_api_call(lambda: make_client(api).list_harness_contracts(version=version))
    for contract in data.get("contracts", []):
        typer.echo(
            f"{contract['harness_id']}\t{contract['contract_version']}\t{contract['required_env']}"
        )


@harness_contract_cmd.command("show")
def harness_contracts_show(
    harness_id: str,
    version: str = typer.Option("v1", "--version", help="Contract version: v1 or v2."),
    api: str | None = _api_option(),
) -> None:
    _echo_json(
        _run_api_call(lambda: make_client(api).show_harness_contract(harness_id, version=version))
    )
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
rtk uv run pytest tests/test_cli.py -k harness_contract -q
rtk uv run ruff check src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
```

Expected: harness contract CLI tests pass and Ruff reports no issues.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat: add adapter contract v2 cli"
```

---

### Task 5: Docs Pointer and Full Verification

**Files:**
- Modify: `specs/024-adapter-contract-v1.md`

- [ ] **Step 1: Update spec pointer**

Append to `specs/024-adapter-contract-v1.md`:

```markdown
## v2 follow-up

Adapter Contract v2 is additive and exposed only when callers request `version=v2` or
`--version v2`. v1 remains the default compatibility response.

Design: `docs/superpowers/specs/2026-05-31-adapter-contract-v2-design.md`
```

- [ ] **Step 2: Run focused contract verification**

Run:

```bash
rtk uv run pytest tests/test_adapter_contract.py -q
rtk uv run pytest tests/test_api.py -k harness_contract -q
rtk uv run pytest tests/test_cli.py -k harness_contract -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run full local gate**

Run:

```bash
rtk uv run pytest -q
rtk uv run ruff check .
rtk uv run ruff format --check .
rtk uv run python -m compileall -q src tests
git diff --check
```

Expected:

- `pytest`: all tests pass.
- `ruff check`: `All checks passed!`
- `ruff format --check`: all files already formatted.
- `compileall`: exits 0.
- `git diff --check`: exits 0 with no output.

- [ ] **Step 4: Commit Task 5**

```bash
git add specs/024-adapter-contract-v1.md
git commit -m "docs: note adapter contract v2"
```

- [ ] **Step 5: Final branch status**

Run:

```bash
git status --short --branch
git log --oneline -6
```

Expected: branch is ahead of origin by the new plan/spec/implementation commits, with no unstaged changes.

---

## Self-Review Checklist

- The plan implements every locked scope item in `docs/superpowers/specs/2026-05-31-adapter-contract-v2-design.md`.
- v1 remains default for API and CLI.
- v2 must be explicit through `version=v2` or `--version v2`.
- `shell` can appear in API v2 list because registry still lists it, but fixture coverage excludes it from the semantic matrix.
- Golden fixtures cover exactly the seven semantic harnesses.
- Runtime policy enforcement remains false and documented.
- No SessionRecord schema or supervisor lifecycle changes are included.


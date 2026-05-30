# Run Profile / Project Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

I'm using the `writing-plans` skill to create the implementation plan.

**Goal:** 建立 profile 決策鏈，讓 `agentctl run` 可透過 `--profile` 或 project path binding 覆寫 harness/provider/model/env/message_prefix/max_tokens_budget，並記錄 resolved context 到 session metadata。

**Architecture:** 新增 `profiles` 模組，負責 profile 定義、TOML 讀寫與專案綁定解析。`api.py` 只負責 resolve + 套用，`models/storage` 紀錄 resolved metadata，`cli` 透過 profile API 進行查詢與綁定。

**Tech Stack:** FastAPI、Typer、Pydantic、tomllib / tomllib-writer、sqlite migration、pytest。

---

## File Structure

| File | Changes |
|---|---|
| `src/agentic_os/profiles.py` | 新增 profile model、parser、resolver、文件儲存 helper |
| `src/agentic_os/models.py` | `SessionRunRequest` 新增 `profile`、`SessionRecord` 新增 resolved 欄位 |
| `src/agentic_os/storage.py` | sessions table 新增 resolved 欄位與 migration |
| `src/agentic_os/api.py` | 新增 `/profiles*`、`/projects/{path}/bind-profile`，run 流程整合 resolver |
| `src/agentic_os/client.py` | 新增 profiles client methods |
| `src/agentic_os/cli.py` | `run` 增加 `--profile`；新增 `profiles` 子命令 |
| `tests/test_profiles.py` | profile parser/resolver 單元測試（新檔） |
| `tests/test_api.py` | API 行為、run override、policy 整合測試 |
| `tests/test_cli.py` | client/cli 請求參數測試 |

---

### Task 1: 建立 Profile 模型、Parser 與 Resolver

**Files:**
- Create: `src/agentic_os/profiles.py`
- Create: `tests/test_profiles.py`

- [ ] **Step 1: 寫入失敗測試（parser / 最長路徑比對）**

```python
def test_profiles_load_and_resolve_prefix_match() -> None:
    profile_toml = """
    [run_profiles.default]
    harness_id = "claude"
    provider = "anthropic"
    model = "claude-3-7-sonnet-latest"
    message_prefix = "You are concise.\n"
    max_tokens_budget = 120000
    default_env = { CLAUDE_PROFILE = "1" }

    [[project_profiles]]
    project_path = "/Users/me/repos/app-a"
    run_profile = "default"

    [[project_profiles]]
    project_path = "/Users/me/repos/app"
    run_profile = "default"
    """

    run_profiles, bindings = load_profiles_from_text(profile_toml)
    assert resolve_project_profile("/Users/me/repos/app-a/src", bindings) == "default"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_profiles.py::test_profiles_load_and_resolve_prefix_match -q`
Expected: FAIL (module not found).

- [ ] **Step 3: 實作 `profiles.py`**

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunProfile:
    name: str
    harness_id: str
    provider: str
    model: str
    default_env: dict[str, str]
    message_prefix: str = ""
    max_tokens_budget: int | None = None


@dataclass(frozen=True)
class ProjectProfileBinding:
    project_path: str
    run_profile: str


@dataclass(frozen=True)
class ResolvedRunContext:
    resolved_profile: str
    harness_id: str
    provider: str
    model: str
    message: str
    default_env: dict[str, str]
    max_tokens_budget: int | None = None


def load_profiles(profile_path: Path) -> dict[str, RunProfile]:
    raw = tomllib.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    result: dict[str, RunProfile] = {}
    for name, row in raw.get("run_profiles", {}).items():
        result[name] = RunProfile(
            name=name,
            harness_id=row["harness_id"],
            provider=row["provider"],
            model=row["model"],
            default_env=dict(row.get("default_env", {})),
            message_prefix=row.get("message_prefix", ""),
            max_tokens_budget=row.get("max_tokens_budget"),
        )
    return result


def load_project_bindings(profile_path: Path) -> list[ProjectProfileBinding]:
    raw = tomllib.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    result = []
    for row in raw.get("project_profiles", []):
        result.append(ProjectProfileBinding(project_path=row["project_path"], run_profile=row["run_profile"]))
    return result


def resolve_project_profile(project_path: str, bindings: list[ProjectProfileBinding]) -> str | None:
    if not project_path:
        return None
    target = Path(project_path).resolve().as_posix()
    matches = [b for b in bindings if target.startswith(b.project_path.rstrip("/") + "/") or target == b.project_path]
    if not matches:
        return None
    return sorted(matches, key=lambda b: len(b.project_path), reverse=True)[0].run_profile


def resolve_profile(requested_profile: str | None, cwd: str | None, run_profiles: dict[str, RunProfile], bindings: list[ProjectProfileBinding], message: str) -> ResolvedRunContext:
    profile_name = requested_profile or resolve_project_profile(cwd or "", bindings)
    if profile_name is None:
        profile_name = "default"
    profile = run_profiles[profile_name]
    return ResolvedRunContext(
        resolved_profile=profile.name,
        harness_id=profile.harness_id,
        provider=profile.provider,
        model=profile.model,
        message=f"{profile.message_prefix}{message}",
        default_env=dict(profile.default_env),
        max_tokens_budget=profile.max_tokens_budget,
    )
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_profiles.py::test_profiles_load_and_resolve_prefix_match -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/profiles.py tests/test_profiles.py
git commit -m "feat(profiles): add parser and resolver for run/project profiles"
```

---

### Task 2: 加入 Session Run Profile 到資料模型

**Files:**
- Modify: `src/agentic_os/models.py`
- Modify: `src/agentic_os/storage.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: 寫入失敗測試（session 可保存 resolved metadata）**

```python
def test_session_record_stores_resolved_profile_metadata() -> None:
    req = SessionRunRequest(agent_id="claude", message="ping", cwd="/tmp", profile="default")
    # resolve_profile -> claude / model
    # 寫入後讀出包含 resolved_profile/resolved_model/resolved_provider
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_api.py -k "resolved_profile" -q`
Expected: FAIL (model/schema not ready).

- [ ] **Step 3: 擴充 request / session schema**

```python
class SessionRunRequest(BaseModel):
    ...
    profile: str | None = None


class SessionRecord(BaseModel):
    ...
    resolved_profile: str | None = None
    resolved_provider: str | None = None
    resolved_model: str | None = None
```

- [ ] **Step 4: 實作 storage migration**

```python
def migrate_sessions(conn: sqlite3.Connection) -> None:
    if not _table_has_column(conn, "sessions", "resolved_profile"):
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_profile TEXT")
    if not _table_has_column(conn, "sessions", "resolved_provider"):
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_provider TEXT")
    if not _table_has_column(conn, "sessions", "resolved_model"):
        conn.execute("ALTER TABLE sessions ADD COLUMN resolved_model TEXT")
```

- [ ] **Step 5: 對 API run + retry 寫入 resolved metadata**

```python
resolved = resolve_profile(request.profile, request.cwd, profiles, bindings, request.message)
agent_id = resolved.harness_id
effective_message = resolved.message
env = {**agent.env, **resolved.default_env}

session = SessionRecord(
    agent_id=agent_id,
    resolved_profile=resolved.resolved_profile,
    resolved_provider=resolved.provider,
    resolved_model=resolved.model,
    ...
)
```

- [ ] **Step 6: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_api.py -k "resolved_profile" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/models.py src/agentic_os/storage.py tests/test_api.py
git commit -m "feat: persist resolved profile context into sessions"
```

---

### Task 3: 新增 Profiles API 與 Project binding

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: 寫入失敗測試（profile 列表 / 綁定）**

```python
def test_profile_endpoints_and_project_binding(tmp_path) -> None:
    response = client.post("/profiles")
    ...
    response = client.post(f"/projects{tmp_path}/bind-profile", json={"run_profile": "default"})
    assert response.status_code == 200
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_api.py -k "profile" -q`
Expected: FAIL (endpoints missing).

- [ ] **Step 3: 實作 profile endpoints**

```python
@app.get("/profiles")
def list_profiles() -> dict[str, object]:
    return {
        "global": list(load_profiles(global_profile_path()).values()),
        "local": list(load_profiles(local_profile_path()).values()),
    }


@app.get("/profiles/{name}")
def show_profile(name: str) -> RunProfile:
    ...


@app.post("/projects/{project_path:path}/bind-profile")
def bind_project_profile(project_path: str, body: ProjectProfileBindRequest) -> dict[str, object]:
    target = Path(project_path).resolve().as_posix()
    _write_project_binding(target, body.run_profile)
    return {"project_path": target, "run_profile": body.run_profile}
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_api.py -k "profile" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(api): add profiles and project profile binding endpoints"
```

---

### Task 4: CLI 與 Client 串接

**Files:**
- Modify: `src/agentic_os/client.py`
- Modify: `src/agentic_os/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 寫入失敗測試（run 傳 profile）**

```python
def test_run_command_passes_profile_flag(monkeypatch) -> None:
    runner = CliRunner()
    fake_client = RecordingClient()
    monkeypatch.setattr("agentic_os.cli.make_client", lambda *_args, **_kwargs: fake_client)
    result = runner.invoke(cli.app, ["run", "claude", "--profile", "default", "hello"])
    assert result.exit_code == 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_cli.py -k "run_command_passes_profile_flag" -q`
Expected: FAIL (profile flag unsupported).

- [ ] **Step 3: 實作 client 和 CLI**

```python
def list_profiles(self) -> dict[str, Any]:
    return self._get("/profiles")

def show_profile(self, name: str) -> dict[str, object]:
    return self._get(f"/profiles/{_validate_path_id(name)}")

def bind_project_profile(self, project_path: str, run_profile: str) -> dict[str, object]:
    return self._post(f"/projects/{_validate_path_id(project_path)}/bind-profile", {"run_profile": run_profile})

@run_app.command("run")
def run_cmd(..., profile: str | None = typer.Option(None, "--profile"), ...):
    ...
    run_client.run_session(agent_id=agent_id, message=message, profile=profile)
```

- [ ] **Step 4: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_cli.py -k "run_command_passes_profile_flag or profiles" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_os/client.py src/agentic_os/cli.py tests/test_cli.py
git commit -m "feat(cli): add profile flag and profile management commands"
```

---

### Task 5: policy + retry 一致性（使用 profile model）

**Files:**
- Modify: `src/agentic_os/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: 寫入失敗測試（policy 使用 profile model_id）**

```python
def test_profile_model_enforced_in_policy(tmp_path) -> None:
    # 設定 allow-model-policy 不含 run profile model
    # 以 profile 送訊息應回傳拒絕
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `rtk uv run pytest tests/test_api.py -k "policy_model_enforced" -q`
Expected: FAIL (policy evaluator未吃 resolved model)。

- [ ] **Step 3: 將 resolved model 帶入 policy evaluate**

```python
policy_request = PolicyEvaluationRequest(
    harness_id=resolved.harness_id,
    cwd=request.cwd,
    model_id=resolved.model,
)
```

- [ ] **Step 4: retry 使用相同 resolved context**

```python
prev = db.get_session(request.session_id)
resolved_profile = prev.resolved_profile
resolved_model = prev.resolved_model
```

- [ ] **Step 5: 跑測試確認 pass**

Run: `rtk uv run pytest tests/test_api.py -k "policy_model_enforced or retry_profile" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_os/api.py tests/test_api.py
git commit -m "feat(policy): evaluate profiles through model-aware policy path"
```

---

### Self-Review

- [ ] 指定 `--profile` 在沒有 profile 時回退 default，且不影響既有 `agent_id` 預設行為。
- [ ] 專案綁定以最長 path match 決定 profile，避免 `/repos/app` 把 `/repos/app-two` 搶走。
- [ ] `SessionRecord` 需要持久化 `resolved_profile/resolved_provider/resolved_model` 以供 retry 查用。
- [ ] 回測 `POST /projects/{path}/bind-profile` 寫入格式可重複覆寫且 idempotent。
- [ ] `/profiles` / `/profiles/{name}` 與 `run --profile` 行為可跨 `/harnesses`/policy 一致性測試。

### Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-025-run-project-profile.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Use `superpowers:executing-plans` for checkpointed in-session execution

Which approach?

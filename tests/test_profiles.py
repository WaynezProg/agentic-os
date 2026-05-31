from pathlib import Path

from agentic_os import profiles


def test_profiles_load_and_resolve_prefix_match(tmp_path: Path) -> None:
    app_a = tmp_path / "app-a"
    app_root = tmp_path / "app"
    app_a.mkdir()
    app_root.mkdir()
    profile_toml = f"""
[run_profiles.default]
harness_id = "claude"
provider = "anthropic"
model = "claude-3-7-sonnet-latest"
message_prefix = "You are concise.\\n"
max_tokens_budget = 120000
default_env = {{ CLAUDE_PROFILE = "1" }}

[[project_profiles]]
project_path = "{app_a.resolve()}"
run_profile = "default"

[[project_profiles]]
project_path = "{app_root.resolve()}"
run_profile = "default"
"""
    profile_path = tmp_path / "profiles.toml"
    profile_path.write_text(profile_toml, encoding="utf-8")
    bundle = profiles._read_bundle(profile_path)
    bindings = bundle.project_bindings
    assert profiles.resolve_project_profile(str((app_a / "src").resolve()), bindings) == "default"
    assert (
        profiles.resolve_project_profile(str((app_root / "extra").resolve()), bindings) == "default"
    )


def test_explicit_unknown_profile_raises_even_when_no_profiles_exist() -> None:
    try:
        profiles.resolve_profile(
            "missing",
            "/tmp",
            "hello",
            {},
            [],
            "shell",
        )
    except ValueError as exc:
        assert "unknown run profile: missing" in str(exc)
    else:
        raise AssertionError("expected unknown profile to raise")


def test_stale_project_binding_raises_unknown_profile(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    project.mkdir()

    try:
        profiles.resolve_profile(
            None,
            str(project),
            "hello",
            {},
            [(str(project), "missing")],
            "shell",
        )
    except ValueError as exc:
        assert "unknown run profile: missing" in str(exc)
    else:
        raise AssertionError("expected stale binding to raise")


def test_upsert_run_profile_local_and_global(tmp_path: Path, monkeypatch) -> None:
    global_root = tmp_path / "global-home"
    monkeypatch.setattr(
        profiles, "global_profile_path", lambda: global_root / ".agentic-os" / "profiles.toml"
    )

    local_repo = tmp_path / "repo"
    local_repo.mkdir()
    profile = profiles.RunProfileInput(
        name="dev",
        harness_id="cursor",
        provider="cursor",
        model="default",
        max_tokens_budget=1000,
    )
    profiles.upsert_run_profile(profile, scope="local", cwd=local_repo)
    loaded = profiles.show_profile("dev", cwd=local_repo)
    assert loaded is not None
    assert loaded.harness_id == "cursor"

    profiles.upsert_run_profile(
        profiles.RunProfileInput(
            name="global-default",
            harness_id="shell",
            provider="local",
            model="local",
        ),
        scope="global",
    )
    assert profiles.show_profile("global-default", cwd=local_repo) is not None


def test_bind_project_profile_preserves_local_profiles(tmp_path: Path) -> None:
    cwd = tmp_path / "repo"
    cwd.mkdir()
    profile_path = cwd / ".agentic-os" / "profiles.toml"
    profile_path.parent.mkdir()
    profile_path.write_text(
        """
[run_profiles.default]
harness_id = "shell"
provider = "local"
model = "local-model"
message_prefix = ""
default_env = {}
""",
        encoding="utf-8",
    )

    profiles.bind_project_profile(str(cwd), "default", cwd)

    bundle = profiles._read_bundle(profile_path)
    assert "default" in bundle.run_profiles
    assert bundle.project_bindings == [(str(cwd.resolve()), "default")]

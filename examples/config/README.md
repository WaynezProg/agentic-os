# Configuration Scope Samples

Example config files demonstrating the four scope levels used by
`agentctl config explain/effective/diff`.

## Load order (lowest → highest priority)

| Scope     | File path                          | Purpose |
|-----------|------------------------------------|---------|
| managed   | `/etc/agentic-os/config.toml`      | Org/machine baseline. Applied to all instances. |
| user      | `~/.agentic-os/config.toml`        | User-level defaults for your account. |
| project   | `<repo>/.agentic-os/config.toml`   | Project-specific settings, shared with collaborators. |
| local     | `<repo>/.agentic-os.local/config.toml` | Temporary dev overrides. **Do not commit to git.** |

Higher priority scopes override lower ones for the same key.

## Quick test

```bash
# Copy user + project + local samples into your real paths:
cp examples/config/user/agentic-os.toml ~/.agentic-os/config.toml
mkdir -p .agentic-os
cp examples/config/project/.agentic-os/config.toml .agentic-os/config.toml
mkdir -p .agentic-os.local
cp examples/config/project/.agentic-os.local/config.toml .agentic-os.local/config.toml

# See the merged effective config:
uv run agentctl config effective openclaw --cwd .

# Compare user vs project scope:
uv run agentctl config diff openclaw --cwd . --scope-a user --scope-b project

# See where each value comes from:
uv run agentctl config explain openclaw --cwd .
```

## Version control

The repo's `.gitignore` includes an exception for `examples/config/project/.agentic-os/` so these
samples are tracked. In your own projects, `.agentic-os/` and `.agentic-os.local/` are ignored.

## File format

All scopes use TOML. Top-level keys are harness ids (e.g. `[openclaw]`).

```toml
[openclaw]
default_provider = "anthropic"
workspace_roots = ["~/project"]
```

from __future__ import annotations

from pathlib import Path

from test_api import make_client

GATEWAY_HEADERS = {"X-Agentic-OS-Gateway": "1"}


def test_run_template_preview_and_launch_records_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = make_client(
        tmp_path,
        command=["/usr/bin/printf", "%s\\n", "{{message}}"],
        model_arg=["--model", "{{model}}"],
    )

    created = client.post(
        "/run-templates",
        json={
            "name": "review-code",
            "harness_id": "shell",
            "cwd": str(repo),
            "message_template": "Review {{target}}",
            "required_variables": ["target"],
        },
    )
    assert created.status_code == 201
    template_id = created.json()["id"]

    preview = client.get(
        f"/run-templates/{template_id}/preview",
        params={"variables": '{"target":"main"}'},
    )
    assert preview.status_code == 200
    assert preview.json()["argv"][-1] == "Review main" or "Review main" in preview.json()["argv"]

    run = client.post(
        "/sessions",
        json={
            "template_id": template_id,
            "variables": {"target": "main"},
        },
    )
    assert run.status_code == 200
    session = client.get(f"/sessions/{run.json()['id']}").json()
    assert session["source_template_id"] == template_id


def test_run_template_write_rejects_gateway_client(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = make_client(tmp_path)

    response = client.post(
        "/run-templates",
        headers=GATEWAY_HEADERS,
        json={
            "name": "blocked",
            "harness_id": "shell",
            "cwd": str(repo),
            "message_template": "noop",
        },
    )
    assert response.status_code == 403

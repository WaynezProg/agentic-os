from agentic_os.adapter_contract import SEMANTIC_HARNESS_IDS
from agentic_os.environment_adapters import get_adapter, iter_adapters
from agentic_os.environment_models import Environment, SurfaceObservation


def test_built_in_adapters_are_the_semantic_harness_set() -> None:
    assert tuple(adapter.id for adapter in iter_adapters()) == SEMANTIC_HARNESS_IDS


def test_adapter_declares_independent_surfaces() -> None:
    adapter = get_adapter("codex")

    assert adapter.binary_name == "codex"
    assert adapter.config_relative_path == ".codex"
    assert adapter.desktop_app_names == ("Codex.app", "ChatGPT.app")
    assert adapter.cli is True
    assert adapter.config is True
    assert adapter.capabilities is True
    assert adapter.native_sessions is True
    assert adapter.desktop is True
    assert adapter.ide is False
    assert adapter.config_activation == "next_session"


def test_runtime_and_ide_support_are_not_inferred_from_cli_support() -> None:
    assert get_adapter("openclaw").runtime is True
    assert get_adapter("cursor").ide is True
    assert get_adapter("qwen").runtime is False
    assert get_adapter("qwen").desktop is False


def test_unknown_adapter_can_be_looked_up_without_raising() -> None:
    assert get_adapter("shell", required=False) is None


def test_environment_keeps_surface_evidence_independent() -> None:
    environment = Environment(
        id="codex",
        label="Codex",
        tool_kind="vibe_coding",
        overall_status="degraded",
        surfaces=[
            SurfaceObservation(
                kind="cli",
                status="healthy",
                source="which",
                version="codex-cli 1.2.3",
            ),
            SurfaceObservation(
                kind="desktop",
                status="missing",
                source="application_bundle",
            ),
        ],
    )

    assert environment.surfaces[0].status == "healthy"
    assert environment.surfaces[1].status == "missing"
    assert environment.surfaces[0].observed_at

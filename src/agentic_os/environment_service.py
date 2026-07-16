from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentic_os.agentic_inventory import (
    AgenticInventoryResult,
    build_agentic_inventory,
)
from agentic_os.capability_inventory import (
    ToolCapabilities,
    read_all_capabilities,
    read_tool_capabilities,
)
from agentic_os.config_inventory import ConfigSummary, read_config_summary
from agentic_os.environment_adapters import (
    EnvironmentAdapter,
    get_adapter,
    iter_adapters,
)
from agentic_os.environment_models import (
    Environment,
    ObservationEvidence,
    SurfaceObservation,
    SurfaceStatus,
)
from agentic_os.fleet import FleetStore, HealthState
from agentic_os.models import AgentDefinition
from agentic_os.native_session_service import NativeSessionService
from agentic_os.registry import Registry
from agentic_os.tool_discovery import (
    ToolDiscoveryResult,
    detect_tool,
    invalidate_cache,
)

ToolDetector = Callable[[AgentDefinition], ToolDiscoveryResult]
ConfigReader = Callable[[str, str], ConfigSummary]
CapabilityReader = Callable[[str, Path | None], ToolCapabilities]
RuntimeReader = Callable[..., AgenticInventoryResult]
ApplicationFinder = Callable[[tuple[str, ...], Path], Path | None]
PendingChangeCounter = Callable[[str], int]


@dataclass(frozen=True)
class EnvironmentSnapshot:
    environment: Environment
    agent: AgentDefinition
    discovery: ToolDiscoveryResult
    config: ConfigSummary
    capabilities: ToolCapabilities | None
    runtime_inventory: AgenticInventoryResult | None


def find_application_bundle(names: tuple[str, ...], home: Path) -> Path | None:
    roots = (Path("/Applications"), Path("/System/Applications"), home / "Applications")
    for name in names:
        for root in roots:
            candidate = root / name
            if candidate.is_dir():
                return candidate
    return None


class EnvironmentService:
    def __init__(
        self,
        *,
        registry: Registry,
        capability_home: Path | None,
        native_sessions: NativeSessionService,
        fleet_store: FleetStore,
        tool_detector: ToolDetector = detect_tool,
        config_reader: ConfigReader = read_config_summary,
        capability_reader: CapabilityReader = read_tool_capabilities,
        runtime_reader: RuntimeReader = build_agentic_inventory,
        all_capabilities_reader: Callable[[Path | None], list[ToolCapabilities]] = (
            read_all_capabilities
        ),
        application_finder: ApplicationFinder = find_application_bundle,
        pending_change_counter: PendingChangeCounter | None = None,
    ) -> None:
        self.registry = registry
        self.home = capability_home or Path.home()
        self.native_sessions = native_sessions
        self.fleet_store = fleet_store
        self.tool_detector = tool_detector
        self.config_reader = config_reader
        self.capability_reader = capability_reader
        self.runtime_reader = runtime_reader
        self.all_capabilities_reader = all_capabilities_reader
        self.application_finder = application_finder
        self.pending_change_counter = pending_change_counter or (lambda _environment_id: 0)

    def observe(self, environment_id: str | None = None) -> list[Environment]:
        return [snapshot.environment for snapshot in self.snapshots(environment_id)]

    def snapshots(self, environment_id: str | None = None) -> list[EnvironmentSnapshot]:
        adapters = (
            (get_adapter(environment_id),)
            if environment_id is not None
            else iter_adapters()
        )
        normalized_adapters = [adapter for adapter in adapters if adapter is not None]
        session_scan = self.native_sessions.scan(
            environment_id=environment_id,
            limit=self.native_sessions.max_files,
        )
        session_counts: dict[str, int] = {}
        for session in session_scan.sessions:
            if session.active:
                session_counts[session.environment_id] = (
                    session_counts.get(session.environment_id, 0) + 1
                )
        registered = {agent.id: agent for agent in self.registry.list_agents()}
        return [
            self._observe_one(
                adapter,
                registered.get(adapter.id),
                active_sessions=session_counts.get(adapter.id, 0),
            )
            for adapter in normalized_adapters
        ]

    def refresh(self) -> None:
        invalidate_cache()

    def compatibility_discovery(self) -> list[ToolDiscoveryResult]:
        snapshots = {snapshot.environment.id: snapshot for snapshot in self.snapshots()}
        results: list[ToolDiscoveryResult] = []
        for agent in self.registry.list_agents():
            if not agent.enabled:
                continue
            snapshot = snapshots.get(agent.id)
            results.append(snapshot.discovery if snapshot else self.tool_detector(agent))
        return sorted(results, key=lambda result: result.agent_id)

    def compatibility_config_inventory(
        self,
    ) -> list[tuple[AgentDefinition, ConfigSummary]]:
        snapshots = {snapshot.environment.id: snapshot for snapshot in self.snapshots()}
        results: list[tuple[AgentDefinition, ConfigSummary]] = []
        for agent in self.registry.list_agents():
            if not agent.enabled or not agent.config_path:
                continue
            snapshot = snapshots.get(agent.id)
            summary = (
                snapshot.config
                if snapshot and snapshot.agent.config_path == agent.config_path
                else self.config_reader(agent.id, agent.config_path)
            )
            results.append((agent, summary))
        return results

    def compatibility_capabilities(self) -> list[ToolCapabilities]:
        return self.all_capabilities_reader(self.home)

    def compatibility_agentic_inventory(self) -> list[AgenticInventoryResult]:
        snapshots = {snapshot.environment.id: snapshot for snapshot in self.snapshots()}
        results: list[AgenticInventoryResult] = []
        for agent in self.registry.list_agents():
            if not agent.enabled or agent.tool_kind != "agentic_runtime":
                continue
            snapshot = snapshots.get(agent.id)
            inventory = snapshot.runtime_inventory if snapshot else None
            results.append(
                inventory
                or self.runtime_reader(agent_id=agent.id, config_path=agent.config_path)
            )
        return results

    def _observe_one(
        self,
        adapter: EnvironmentAdapter,
        registered_agent: AgentDefinition | None,
        *,
        active_sessions: int,
    ) -> EnvironmentSnapshot:
        agent = registered_agent or self._synthetic_agent(adapter)
        discovery = self.tool_detector(agent)
        cli_surface = self._cli_surface(discovery)

        raw_config_path = agent.config_path or str(self.home / adapter.config_relative_path)
        config_path = str(Path(raw_config_path).expanduser())
        config = self.config_reader(adapter.id, config_path)
        config_surface = self._config_surface(
            config_path,
            config,
            cli_installed=discovery.installed,
        )

        capabilities: ToolCapabilities | None = None
        runtime_inventory: AgenticInventoryResult | None = None
        capability_names: dict[str, list[str]]
        if adapter.runtime:
            runtime_inventory = self.runtime_reader(
                agent_id=adapter.id,
                config_path=config_path,
            )
            capability_names = {
                "skills": [item.identifier for item in runtime_inventory.skills],
                "mcp_servers": [
                    item.identifier for item in runtime_inventory.mcp_servers
                ],
                "tools": [item.identifier for item in runtime_inventory.tools],
                "flows": [item.identifier for item in runtime_inventory.flows],
            }
            capability_surface = self._runtime_capability_surface(
                runtime_inventory,
                config_path,
                cli_installed=discovery.installed,
            )
        else:
            capabilities = self.capability_reader(adapter.id, self.home)
            capability_names = {
                "skills": capabilities.skills,
                "mcp_servers": capabilities.mcp_servers,
                "plugins": capabilities.plugins,
                "memory_files": [item.path for item in capabilities.memory_files],
            }
            capability_surface = self._capability_surface(
                capabilities,
                cli_installed=discovery.installed,
            )

        runtime_surface = self._runtime_surface(adapter, discovery)
        desktop_surface = self._application_surface(
            "desktop",
            adapter.desktop,
            adapter.desktop_app_names,
        )
        ide_surface = self._application_surface(
            "ide",
            adapter.ide,
            adapter.ide_app_names,
        )
        surfaces = [
            cli_surface,
            config_surface,
            capability_surface,
            runtime_surface,
            desktop_surface,
            ide_surface,
        ]
        environment = Environment(
            id=adapter.id,
            label=adapter.label,
            tool_kind=adapter.tool_kind,
            overall_status=self._overall_status(adapter, surfaces),
            surfaces=surfaces,
            capability_names=capability_names,
            active_sessions=active_sessions,
            pending_change_count=self.pending_change_counter(adapter.id),
        )
        return EnvironmentSnapshot(
            environment=environment,
            agent=agent,
            discovery=discovery,
            config=config,
            capabilities=capabilities,
            runtime_inventory=runtime_inventory,
        )

    def _synthetic_agent(self, adapter: EnvironmentAdapter) -> AgentDefinition:
        config_path = self.home / adapter.config_relative_path
        return AgentDefinition(
            id=adapter.id,
            label=adapter.label,
            command=[adapter.binary_name],
            version_command=[adapter.binary_name, "--version"],
            config_path=str(config_path),
            tool_kind=adapter.tool_kind,
        )

    @staticmethod
    def _cli_surface(discovery: ToolDiscoveryResult) -> SurfaceObservation:
        status: SurfaceStatus
        if not discovery.installed:
            status = "missing"
        elif discovery.version_error:
            status = "degraded"
        else:
            status = "healthy"
        return SurfaceObservation(
            kind="cli",
            status=status,
            source="binary_discovery",
            version=discovery.version,
            path=discovery.binary_path,
            detail=discovery.version_error,
            action_required="安裝或修正 CLI PATH" if not discovery.installed else None,
            evidence=[
                ObservationEvidence(
                    source="which",
                    detail=discovery.binary_path or "binary not found",
                )
            ],
        )

    @staticmethod
    def _config_surface(
        config_path: str,
        config: ConfigSummary,
        *,
        cli_installed: bool,
    ) -> SurfaceObservation:
        exists = Path(config_path).exists()
        if not exists:
            status: SurfaceStatus = "missing"
        elif config.parse_error:
            status = "degraded"
        elif cli_installed:
            status = "healthy"
        else:
            status = "configured_only"
        return SurfaceObservation(
            kind="config",
            status=status,
            source="config_inventory",
            path=config.config_source,
            detail=config.parse_error,
            action_required="修正設定檔格式" if config.parse_error else None,
            evidence=[
                ObservationEvidence(
                    source="filesystem",
                    detail="config path exists" if exists else "config path missing",
                )
            ],
        )

    @staticmethod
    def _capability_surface(
        capabilities: ToolCapabilities,
        *,
        cli_installed: bool,
    ) -> SurfaceObservation:
        if capabilities.error:
            status: SurfaceStatus = "degraded"
        elif not capabilities.present:
            status = "missing"
        elif cli_installed:
            status = "healthy"
        else:
            status = "configured_only"
        return SurfaceObservation(
            kind="capability",
            status=status,
            source="capability_inventory",
            detail=capabilities.error,
            action_required="修正 capability 設定" if capabilities.error else None,
        )

    @staticmethod
    def _runtime_capability_surface(
        inventory: AgenticInventoryResult,
        config_path: str,
        *,
        cli_installed: bool,
    ) -> SurfaceObservation:
        config_present = Path(config_path).exists()
        if inventory.error:
            status: SurfaceStatus = "degraded"
        elif not config_present:
            status = "missing"
        elif cli_installed:
            status = "healthy"
        else:
            status = "configured_only"
        return SurfaceObservation(
            kind="capability",
            status=status,
            source="agentic_inventory",
            detail=inventory.error,
        )

    def _runtime_surface(
        self,
        adapter: EnvironmentAdapter,
        discovery: ToolDiscoveryResult,
    ) -> SurfaceObservation:
        if not adapter.runtime:
            return SurfaceObservation(
                kind="runtime",
                status="unsupported",
                source="adapter",
            )
        record = self.fleet_store.get_health(adapter.id)
        if record is None:
            return SurfaceObservation(
                kind="runtime",
                status="unknown" if discovery.installed else "missing",
                source="fleet_health",
                action_required="執行 health probe" if discovery.installed else None,
            )
        status_by_state: dict[HealthState, SurfaceStatus] = {
            HealthState.UP: "healthy",
            HealthState.DEGRADED: "degraded",
            HealthState.DOWN: "degraded",
            HealthState.UNKNOWN: "unknown",
        }
        return SurfaceObservation(
            kind="runtime",
            status=status_by_state[record.state],
            source="fleet_health",
            version=record.version,
            detail=record.message,
            observed_at=record.updated_at,
        )

    def _application_surface(
        self,
        kind: str,
        supported: bool,
        names: tuple[str, ...],
    ) -> SurfaceObservation:
        if not supported:
            return SurfaceObservation(
                kind=kind,
                status="unsupported",
                source="adapter",
            )
        found = self.application_finder(names, self.home)
        return SurfaceObservation(
            kind=kind,
            status="healthy" if found else "missing",
            source="application_bundle",
            path=str(found) if found else None,
            detail=", ".join(names),
        )

    @staticmethod
    def _overall_status(
        adapter: EnvironmentAdapter,
        surfaces: list[SurfaceObservation],
    ) -> SurfaceStatus:
        by_kind = {surface.kind: surface for surface in surfaces}
        statuses = [surface.status for surface in surfaces if surface.status != "unsupported"]
        if "auth_required" in statuses:
            return "auth_required"
        if "degraded" in statuses:
            return "degraded"
        if "stale" in statuses:
            return "stale"

        cli_status = by_kind["cli"].status
        if cli_status == "missing":
            if any(status in {"healthy", "configured_only"} for status in statuses):
                return "degraded"
            return "missing"
        if adapter.runtime and by_kind["runtime"].status == "unknown":
            return "unknown"
        if cli_status == "healthy":
            return "healthy"
        if "configured_only" in statuses:
            return "configured_only"
        return "unknown"

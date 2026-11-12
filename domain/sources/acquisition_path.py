from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceAcquisitionPath:
    project_id: str
    workflow_run_id: str
    source_id: str
    landing_url: str
    terminal_url: str
    navigation_chain: tuple[str, ...]
    diagnostics: dict = field(default_factory=dict)

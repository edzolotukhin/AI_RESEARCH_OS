"""CMF facade contracts; no provider, persistence or method implementation imports."""
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar, Literal

from application.research_kernel.contracts import MethodAdapter

D = TypeVar("D")
B = TypeVar("B")
N = TypeVar("N")
Stage = Literal["search", "evidence", "research_quality", "analysis", "report", "review"]


@dataclass(frozen=True)
class Capabilities:
    research_mode: str
    support_kinds: tuple[str, ...]
    formats: tuple[str, ...]
    approval_gates: tuple[str, ...]
    findings: bool = True
    insights: bool = True


@dataclass(frozen=True)
class MethodIdentity:
    method_id: str
    version: str
    name: str
    contract_version: int
    design_version: str
    adapter_version: str
    execution_version: int
    integrity_version: str
    sufficiency_version: str
    analysis_version: str
    review_version: str
    report_version: str


class MethodBinding(Protocol[D, B, N]):
    identity: MethodIdentity
    capabilities: Capabilities

    def validate_design(self, design: D, brief: B) -> None: ...
    def research_needs(self, design: D) -> tuple[N, ...]: ...
    def research_adapter(self, *, context, config, primitives, readiness, evidence) -> MethodAdapter: ...
    def run_stage(self, stage: Stage, context, delegate: Callable): ...
    def report_sources(self, project_id: str, run_ids: set[str], delegate: Callable): ...

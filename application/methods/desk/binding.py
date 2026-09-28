"""CMF Desk v1 delegates to accepted services; no copied research policy."""
from application.methods.contracts import Capabilities, MethodIdentity
from application.research.design_validator import validate_research_design
from application.methods.desk.adapter import DeskAdapter
from domain.planning.research_design import ResearchDesign, InformationNeed
from domain.research_brief import ResearchBrief


class DeskBinding:
    identity = MethodIdentity("DESK", "1", "Desk Research", 1, "desk-1", "desk-v1", 1,
                              "ark04-06", "desk-1", "desk-1", "desk-1", "desk-1")
    capabilities = Capabilities("adaptive_external", ("text_citation",), ("PDF", "PPTX"),
                                ("design", "report"))

    def validate_design(self, design: ResearchDesign, brief: ResearchBrief | None) -> None:
        validate_research_design(design, brief=brief)

    def research_needs(self, design: ResearchDesign) -> tuple[InformationNeed, ...]:
        return tuple(design.information_needs)

    def research_adapter(self, *, context, config, primitives, readiness, evidence):
        sources = primitives.extraction._source_repository
        if sources is None or getattr(readiness, "_source_repository", None) is not sources:
            raise RuntimeError("CMF requires the same canonical Source repository in readiness/extraction")
        needs = self.research_needs(context.workflow_template.research_design_snapshot)
        adapter = DeskAdapter(context, config, primitives, readiness, evidence)
        if tuple(adapter.design.information_needs) != needs:
            raise RuntimeError("CMF Research Need binding mismatch")
        return adapter

    def run_stage(self, stage, context, delegate):
        if stage not in ("search", "evidence", "research_quality", "analysis", "report", "review"):
            raise ValueError("Unsupported Desk stage")
        # Existing executors own persisted Evidence loading, integrity, analysis,
        # review/revision and budget semantics; CMF never fabricates their outputs.
        return delegate(context)

    def report_sources(self, project_id, run_ids, delegate):
        return delegate(project_id, run_ids)

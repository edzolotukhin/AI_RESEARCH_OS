"""Shared persisted ResearchQuestion coverage contract for Report and Review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.planning.research_design import ResearchDesign
from domain.reports.report import Report

CONTRACT_KEY = "rq_coverage_contract"
CONTRACT_VERSION = "desk_report_rq_coverage_v1"
MAX_RQ_IDS = 128


class CoverageContractError(ValueError):
    def __init__(self, *codes: str) -> None:
        self.codes = tuple(codes)[:16]
        super().__init__(",".join(self.codes))


@dataclass(frozen=True)
class ReportCoverageContract:
    mode: str
    required_rq_ids: tuple[str, ...]
    excluded_rq_ids: tuple[str, ...]
    source: str = "persisted"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": CONTRACT_VERSION,
            "mode": self.mode,
            "required_rq_ids": list(self.required_rq_ids),
            "excluded_rq_ids": list(self.excluded_rq_ids),
        }


def build_report_coverage_contract(
    *, design: ResearchDesign, limited: bool,
    required_rq_ids: tuple[str, ...],
) -> ReportCoverageContract:
    design_ids = tuple(question.id for question in design.research_questions)
    required = _bounded_ids(required_rq_ids, field="required_rq_ids")
    unknown = set(required) - set(design_ids)
    if unknown:
        raise CoverageContractError("coverage_contract_foreign_required_rq")
    if limited:
        if not required:
            raise CoverageContractError("coverage_contract_limited_without_required_rqs")
        excluded = tuple(item for item in design_ids if item not in set(required))
        return ReportCoverageContract("limited", required, excluded)
    if set(required) != set(design_ids):
        raise CoverageContractError("coverage_contract_complete_required_set_mismatch")
    return ReportCoverageContract("complete", tuple(sorted(design_ids)), ())


def resolve_report_coverage_contract(
    *, report: Report, design: ResearchDesign,
) -> ReportCoverageContract:
    design_ids = tuple(question.id for question in design.research_questions)
    raw = report.metadata.get(CONTRACT_KEY)
    if raw is None:
        return ReportCoverageContract(
            "complete", tuple(sorted(design_ids)), (),
            source="historical_complete_fallback",
        )
    if not isinstance(raw, dict) or raw.get("version") != CONTRACT_VERSION:
        raise CoverageContractError("coverage_contract_malformed")
    mode = raw.get("mode")
    if mode not in {"complete", "limited"}:
        raise CoverageContractError("coverage_contract_invalid_mode")
    required = _bounded_ids(raw.get("required_rq_ids"), field="required_rq_ids")
    excluded = _bounded_ids(raw.get("excluded_rq_ids"), field="excluded_rq_ids")
    design_set = set(design_ids)
    if (set(required) | set(excluded)) - design_set:
        raise CoverageContractError("coverage_contract_foreign_rq")
    if set(required) & set(excluded):
        raise CoverageContractError("coverage_contract_overlapping_rq_sets")
    if set(required) | set(excluded) != design_set:
        raise CoverageContractError("coverage_contract_incomplete_partition")
    if mode == "complete" and (set(required) != design_set or excluded):
        raise CoverageContractError("coverage_contract_complete_required_set_mismatch")
    if mode == "limited" and (not required or not excluded):
        raise CoverageContractError(
            "coverage_contract_limited_without_required_rqs"
            if not required else "coverage_contract_limited_without_exclusions"
        )
    report_scope = report.metadata.get("report_scope")
    if report_scope in {"complete", "limited"} and report_scope != mode:
        raise CoverageContractError("coverage_contract_report_scope_mismatch")
    return ReportCoverageContract(mode, required, excluded)


def validate_report_against_coverage_contract(
    *, report: Report, contract: ReportCoverageContract,
) -> tuple[str, ...]:
    errors: list[str] = []
    claimed = {
        rq_id for section in report.sections for rq_id in section.research_question_refs
    }
    for rq_id in sorted(claimed.intersection(contract.excluded_rq_ids)):
        errors.append(f"coverage_contract_excluded_rq_claimed:{rq_id}")
    if contract.mode == "limited":
        disclosed = " ".join(report.limitations).casefold()
        for rq_id in contract.excluded_rq_ids:
            if rq_id.casefold() not in disclosed:
                errors.append(f"coverage_contract_excluded_rq_not_disclosed:{rq_id}")
    return tuple(errors)


def excluded_rq_limitation(contract: ReportCoverageContract) -> str | None:
    if contract.mode != "limited" or not contract.excluded_rq_ids:
        return None
    return "Unsupported ResearchQuestions: " + ", ".join(contract.excluded_rq_ids) + "."


def required_research_question_texts(
    *, design: ResearchDesign, contract: ReportCoverageContract,
) -> tuple[str, ...]:
    required = set(contract.required_rq_ids)
    return tuple(
        question.question for question in design.research_questions
        if question.id in required
    )


def _bounded_ids(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CoverageContractError(f"coverage_contract_{field}_malformed")
    normalized = tuple(str(item).strip() for item in value)
    if (
        len(normalized) > MAX_RQ_IDS or any(not item for item in normalized)
        or len(set(normalized)) != len(normalized)
    ):
        raise CoverageContractError(f"coverage_contract_{field}_malformed")
    return tuple(sorted(normalized))

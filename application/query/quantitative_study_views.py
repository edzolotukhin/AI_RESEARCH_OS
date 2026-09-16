"""Immutable, presentation-safe views for the Quantitative product UI."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ProductStatusView:
    key: str; label: str; severity: str; explanation: str = ""; actions: tuple[str, ...] = ()

@dataclass(frozen=True)
class NavigationItemView:
    key: str; label: str; href: str; active: bool

@dataclass(frozen=True)
class MetricView:
    label: str; value: str; detail: str = ""; tone: str = "blue"

@dataclass(frozen=True)
class VariableView:
    name: str; label: str; analytical_type: str; role: str; measurement: str; missing: str

@dataclass(frozen=True)
class AnalysisItemView:
    title: str; status: ProductStatusView; population: str; weighting: str; result_count: int; limitations: tuple[str, ...] = ()

@dataclass(frozen=True)
class ResultItemView:
    variable: str; statistic: str; value: str; numerator: str; denominator: str; population: str; base: str; filter_definition: str; weighting: str; grouped_categories: str = ""

@dataclass(frozen=True)
class FindingView:
    text: str; support_count: int; method: str

@dataclass(frozen=True)
class InsightView:
    text: str; support_count: int

@dataclass(frozen=True)
class ReportSectionView:
    title: str; narrative: str

@dataclass(frozen=True)
class QuantitativeStudyView:
    study_id: str; title: str; description: str; workflow_status: str; status: ProductStatusView
    navigation: tuple[NavigationItemView, ...]; metrics: tuple[MetricView, ...]
    stages: tuple[tuple[str, ProductStatusView, str], ...]
    research_questions: tuple[str, ...]; analytical_requirement_count: int
    methodology: str; population: str; geography: str; weighting: str
    dataset_filename: str; dataset_format: str; respondent_count: int | None; variable_count: int | None
    dataset_validation: str; variables: tuple[VariableView, ...]; qc_issue_count: int
    analyses: tuple[AnalysisItemView, ...]; results: tuple[ResultItemView, ...]
    findings: tuple[FindingView, ...]; insights: tuple[InsightView, ...]
    report_title: str; report_sections: tuple[ReportSectionView, ...]; report_status: ProductStatusView
    limitations: tuple[str, ...]; warnings: tuple[str, ...]
    can_upload: bool; can_run_qc: bool; can_resume: bool
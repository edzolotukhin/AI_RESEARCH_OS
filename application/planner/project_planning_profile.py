from __future__ import annotations

from dataclasses import dataclass

from domain.research_method import DESK, QUANTITATIVE


PROJECT_PLANNING_PROFILE_VERSION = "pf02-project-contract-v4"
PROJECT_PLANNING_PROFILE_KEY = "project_planning_profile"


@dataclass(frozen=True)
class ProjectPlanningProfile:
    methods: tuple[str, ...]
    language: str
    version: str = PROJECT_PLANNING_PROFILE_VERSION

    def to_metadata(self) -> dict[str, object]:
        return {
            "version": self.version,
            "methods": list(self.methods),
            "language": self.language,
        }


def project_planning_instructions(profile: ProjectPlanningProfile) -> str:
    methods = ", ".join(profile.methods)
    method_contract = _method_contract(profile.methods)
    return f"""

---

# PROJECT-LEVEL PLANNING PROFILE

Profile version: {profile.version}
Selected methods: {methods}
Required output language: {profile.language}

This invocation creates a HIGH-LEVEL PROJECT RESEARCH CONTRACT, not a
method execution design. Base every human-facing generated string on the
brief and write it in the required output language.

{method_contract}

Generate genuine research questions that address the business question and
objectives. First reason from the business question, objective, geography,
market/category, timeframe, and context. Decompose an objective into multiple
non-duplicative questions only when it contains distinct answer dimensions
such as magnitude, change, composition, drivers, barriers, behavior, or group
differences. Each question must name the substantive phenomenon to establish,
not wrap or paraphrase the objective.

For every question, specify concrete information needs: the measure,
classification, comparison, trend, distribution, or contextual fact needed to
answer it. Source strategy must follow those needs. Analysis steps must explain
how the evidence answers the questions. Deliverables must reflect the resulting
questions and analysis rather than a fixed generic list.

Do not expose planning scaffolding such as "derived from brief" or "what
evidence is required to address". Do not fabricate sources, sample sizes,
questionnaires, weighting, statistical tests, models, codebooks, datasets, or
respondent counts. Keep Quantitative content at the level of evidence required;
do not specify TAM/SAM/SOM or CAGR calculations, sample design, questionnaire
modules, scales, price-research techniques, weighting, significance tests,
regression/SEM, elasticity models, or other downstream QZ methodology. This
restriction applies to questions, needs, sources, analysis, deliverables,
assumptions, and limitations in every output language.
""".strip()


def _method_contract(methods: tuple[str, ...]) -> str:
    selected = set(methods)
    if selected == {QUANTITATIVE}:
        return (
            "The project uses QUANTITATIVE research only. Describe primary "
            "structured measurement and quantitative evidence at a high level. "
            "Do not assume Desk research, public-source sufficiency, secondary-"
            "source synthesis, or absence of primary fieldwork. Detailed target "
            "population, questionnaire, sampling, weighting, and statistical "
            "analysis remain downstream in the Quantitative method flow."
        )
    if selected == {DESK}:
        return (
            "The project uses DESK research only. Use relevant secondary/open "
            "evidence and synthesis where supported by the brief; do not inject "
            "generic source families that are irrelevant to its objectives."
        )
    return (
        "The project uses both DESK and QUANTITATIVE research. Represent both "
        "evidence streams at a high level: Desk contributes relevant secondary/"
        "open evidence and Quantitative contributes primary structured "
        "measurement. Do not collapse the contract into Desk-only planning. "
        "Detailed Quantitative methodology remains downstream, and no actual "
        "cross-method findings synthesis is performed here."
    )

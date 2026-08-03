"""Serbia Microgreens planner missing-objective fixture for semantic correction tests."""

from __future__ import annotations

import copy
import json

from tests.fixtures.serbia_bounded_research_design import SERBIA_BOUNDED_RESEARCH_DESIGN
from tests.fixtures.serbia_microgreens_brief import SERBIA_MICROGREENS_BRIEF

_MISSING_OBJECTIVE = SERBIA_MICROGREENS_BRIEF["objectives"][9]

SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN: dict = copy.deepcopy(SERBIA_BOUNDED_RESEARCH_DESIGN)
SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN["research_questions"] = copy.deepcopy(
    SERBIA_BOUNDED_RESEARCH_DESIGN["research_questions"][:-1],
)
SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN_JSON = json.dumps(
    SERBIA_MISSING_ENTRY_OBJECTIVE_DESIGN,
    ensure_ascii=True,
)

SERBIA_MISSING_ENTRY_OBJECTIVE_TEXT = _MISSING_OBJECTIVE

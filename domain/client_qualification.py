from dataclasses import dataclass


@dataclass
class ClientQualification:

    summary: str

    project_understanding: str

    understanding_score: int

    project_state: str

    next_question: str

    missing_information: list[str]
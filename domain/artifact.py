from dataclasses import dataclass


@dataclass
class Artifact:
    artifact_type: str
    title: str
    content: str

    status: str = "Draft"
    version: int = 1
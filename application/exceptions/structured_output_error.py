class StructuredOutputError(Exception):
    """
    Raised when an LLM response cannot be converted into structured JSON.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str = "unknown",
        candidate_count: int = 0,
        syntax_valid_count: int = 0,
        contract_valid_count: int = 0,
        source_preview: str = "",
    ) -> None:
        details = [
            f"stage={stage}",
            f"candidates={candidate_count}",
            f"syntax_valid={syntax_valid_count}",
            f"contract_valid={contract_valid_count}",
        ]

        if source_preview:
            details.append(f"preview={source_preview!r}")

        super().__init__(f"{message} ({', '.join(details)})")

        self.stage = stage
        self.candidate_count = candidate_count
        self.syntax_valid_count = syntax_valid_count
        self.contract_valid_count = contract_valid_count
        self.source_preview = source_preview

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
        candidate_preview: str = "",
        candidate_length: int = 0,
        json_decode_message: str = "",
        json_error_line: int | None = None,
        json_error_column: int | None = None,
        json_error_position: int | None = None,
        is_truncated: bool = False,
        finish_reason: str | None = None,
        output_tokens: int | None = None,
        max_output_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        incomplete_reason: str | None = None,
        configured_reasoning_effort: str | None = None,
        visible_output_length: int | None = None,
        reasoning_budget_exhausted: bool = False,
        attempts: int = 1,
    ) -> None:
        details = [
            f"stage={stage}",
            f"candidates={candidate_count}",
            f"syntax_valid={syntax_valid_count}",
            f"contract_valid={contract_valid_count}",
        ]

        if attempts > 1:
            details.append(f"attempts={attempts}")

        if is_truncated:
            details.append("truncated=true")

        if reasoning_budget_exhausted:
            details.append("reasoning_budget_exhausted=true")

        if finish_reason:
            details.append(f"finish_reason={finish_reason}")

        if incomplete_reason:
            details.append(f"incomplete_reason={incomplete_reason}")

        if configured_reasoning_effort:
            details.append(f"reasoning_effort={configured_reasoning_effort}")

        if output_tokens is not None:
            details.append(f"output_tokens={output_tokens}")

        if reasoning_tokens is not None:
            details.append(f"reasoning_tokens={reasoning_tokens}")

        if max_output_tokens is not None:
            details.append(f"max_output_tokens={max_output_tokens}")

        if visible_output_length is not None:
            details.append(f"visible_output_length={visible_output_length}")

        if json_decode_message:
            details.append(f"json_error={json_decode_message!r}")

        if json_error_line is not None:
            details.append(f"line={json_error_line}")

        if json_error_column is not None:
            details.append(f"column={json_error_column}")

        if json_error_position is not None:
            details.append(f"position={json_error_position}")

        if candidate_length:
            details.append(f"candidate_length={candidate_length}")

        preview = candidate_preview or source_preview

        if preview:
            details.append(f"preview={preview!r}")

        super().__init__(f"{message} ({', '.join(details)})")

        self.stage = stage
        self.candidate_count = candidate_count
        self.syntax_valid_count = syntax_valid_count
        self.contract_valid_count = contract_valid_count
        self.source_preview = source_preview
        self.candidate_preview = candidate_preview
        self.candidate_length = candidate_length
        self.json_decode_message = json_decode_message
        self.json_error_line = json_error_line
        self.json_error_column = json_error_column
        self.json_error_position = json_error_position
        self.is_truncated = is_truncated
        self.finish_reason = finish_reason
        self.output_tokens = output_tokens
        self.max_output_tokens = max_output_tokens
        self.reasoning_tokens = reasoning_tokens
        self.incomplete_reason = incomplete_reason
        self.configured_reasoning_effort = configured_reasoning_effort
        self.visible_output_length = visible_output_length
        self.reasoning_budget_exhausted = reasoning_budget_exhausted
        self.attempts = attempts

    def with_attempt_context(
        self,
        *,
        attempts: int,
        finish_reason: str | None = None,
        output_tokens: int | None = None,
        max_output_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        incomplete_reason: str | None = None,
        configured_reasoning_effort: str | None = None,
        visible_output_length: int | None = None,
        reasoning_budget_exhausted: bool | None = None,
        is_truncated: bool | None = None,
    ) -> "StructuredOutputError":
        return StructuredOutputError(
            str(self).split(" (", 1)[0],
            stage=self.stage,
            candidate_count=self.candidate_count,
            syntax_valid_count=self.syntax_valid_count,
            contract_valid_count=self.contract_valid_count,
            source_preview=self.source_preview,
            candidate_preview=self.candidate_preview,
            candidate_length=self.candidate_length,
            json_decode_message=self.json_decode_message,
            json_error_line=self.json_error_line,
            json_error_column=self.json_error_column,
            json_error_position=self.json_error_position,
            is_truncated=(
                self.is_truncated
                if is_truncated is None
                else is_truncated
            ),
            finish_reason=finish_reason or self.finish_reason,
            output_tokens=(
                output_tokens
                if output_tokens is not None
                else self.output_tokens
            ),
            max_output_tokens=(
                max_output_tokens
                if max_output_tokens is not None
                else self.max_output_tokens
            ),
            reasoning_tokens=(
                reasoning_tokens
                if reasoning_tokens is not None
                else self.reasoning_tokens
            ),
            incomplete_reason=(
                incomplete_reason
                if incomplete_reason is not None
                else self.incomplete_reason
            ),
            configured_reasoning_effort=(
                configured_reasoning_effort
                if configured_reasoning_effort is not None
                else self.configured_reasoning_effort
            ),
            visible_output_length=(
                visible_output_length
                if visible_output_length is not None
                else self.visible_output_length
            ),
            reasoning_budget_exhausted=(
                self.reasoning_budget_exhausted
                if reasoning_budget_exhausted is None
                else reasoning_budget_exhausted
            ),
            attempts=attempts,
        )

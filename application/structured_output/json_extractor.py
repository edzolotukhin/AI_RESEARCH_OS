from __future__ import annotations


class JsonExtractor:
    """
    Extracts root-level JSON values from text in order of appearance.

    Nested JSON values inside an already extracted root candidate are never
    returned as separate candidates.
    """

    def extract_all(
        self,
        text: str,
    ) -> list[str]:
        if not text.strip():
            return []

        candidates: list[str] = []
        index = 0
        length = len(text)

        while index < length:
            index = self._skip_whitespace(text, index)
            if index >= length:
                break

            if text[index] not in "{[":
                index += 1
                continue

            end_index = self._find_root_container_end(text, index)

            if end_index is None:
                candidates.append(text[index:])
                break

            candidates.append(text[index:end_index])
            index = end_index

        return candidates

    @staticmethod
    def _skip_whitespace(
        text: str,
        index: int,
    ) -> int:
        while index < len(text) and text[index].isspace():
            index += 1

        return index

    def _find_root_container_end(
        self,
        text: str,
        start: int,
    ) -> int | None:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escape:
                    escape = False
                    continue

                if char == "\\":
                    escape = True
                    continue

                if char == '"':
                    in_string = False

                continue

            if char == '"':
                in_string = True
                continue

            if char == opener:
                depth += 1
                continue

            if char == closer:
                depth -= 1
                if depth == 0:
                    return index + 1

        return None

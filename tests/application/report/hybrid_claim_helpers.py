from __future__ import annotations

import copy
from typing import Any, Callable


def semantic_delta(
    request: dict[str, Any], *, text: str = "Підтверджено ", fact_refs: list[str] | None = None,
) -> dict[str, Any]:
    authority = request["authority"]
    refs = fact_refs
    if refs is None:
        refs = [item["fact_ref"] for item in request["numeric_catalog"]["numeric_facts"]]
    segments: list[dict[str, str]] = [{"type": "text", "text": text}]
    for index, ref in enumerate(refs):
        if index:
            segments.append({"type": "text", "text": "; "})
        segments.append({"type": "fact_ref", "fact_ref": ref})
    if text.endswith(" ") and not refs:
        segments[0]["text"] = text.rstrip() + "."
    return {
        "claim_id": authority["claim_id"],
        "assertion": {
            "kind": authority["assertion"]["kind"],
            "certainty": authority["assertion"]["certainty"],
            "direction": authority["assertion"]["direction"],
            "segments": segments,
        },
    }


class LegacyClaimProviderAdapter:
    """Keep structural tests readable while exercising the real H2 boundary."""

    def __init__(self) -> None:
        self.candidates: dict[str, dict[str, Any]] = {}

    def initial(self, callback: Callable[[dict[str, Any]], dict[str, Any]]):
        def provider(request: dict[str, Any]) -> dict[str, Any]:
            if "claims" in request:
                return {"claims": [self._initial_one(item, callback) for item in request["claims"]]}
            return self._initial_one(request, callback)
        return provider

    def repair(self, callback: Callable[[dict[str, Any]], dict[str, Any]]):
        def provider(request: dict[str, Any]) -> dict[str, Any]:
            if "claims" in request:
                return {"claims": [self._repair_one(item, callback) for item in request["claims"]]}
            return self._repair_one(request, callback)
        return provider

    def _initial_one(self, request: dict[str, Any], callback) -> dict[str, Any]:
        result = callback(copy.deepcopy(request["authority"]))
        self.candidates[request["authority"]["claim_id"]] = copy.deepcopy(result)
        return self._to_delta(result, request)

    def _repair_one(self, request: dict[str, Any], callback) -> dict[str, Any]:
        claim_id = request["authority"]["claim_id"]
        legacy_request = copy.deepcopy(request)
        legacy_request["candidate"] = copy.deepcopy(self.candidates[claim_id])
        result = callback(legacy_request)
        return self._to_delta(result, request)

    @staticmethod
    def _to_delta(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        authority = request["authority"]
        converted = copy.deepcopy(result)
        assertion = converted.get("assertion")
        if isinstance(assertion, dict):
            proposition = assertion.get("proposition")
            if proposition == authority["assertion"]["proposition"]:
                converted["assertion"] = semantic_delta(request)["assertion"]
            else:
                converted["assertion"] = {
                    "kind": assertion.get("kind"),
                    "certainty": assertion.get("certainty"),
                    "direction": assertion.get("direction"),
                    "segments": [{"type": "text", "text": proposition}],
                }
        scope = converted.get("scope")
        if isinstance(scope, dict) and scope.get("numeric_facts") == authority["scope"].get("numeric_facts"):
            scope.pop("numeric_facts", None)
        return converted

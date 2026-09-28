"""Explicit immutable method registry. No discovery and no latest-version fallback."""
from types import MappingProxyType
from application.methods.contracts import MethodBinding


class MethodResolutionError(ValueError):
    pass


class MethodRegistry:
    def __init__(self, methods: tuple[MethodBinding, ...]):
        entries = {}
        for method in methods:
            identity = method.identity
            key = (identity.method_id, identity.version)
            if not all(key) or key in entries:
                raise MethodResolutionError(f"Invalid or duplicate method registration: {key}")
            if identity.contract_version != 1:
                raise MethodResolutionError("Unsupported CMF contract")
            from dataclasses import fields
            if any(not getattr(identity, field.name) for field in fields(identity)):
                raise MethodResolutionError("Incomplete method version identity")
            capabilities = method.capabilities
            if capabilities.research_mode not in ("adaptive_external", "persisted_dataset"):
                raise MethodResolutionError("Unsupported research mode")
            if not capabilities.support_kinds or not set(capabilities.support_kinds) <= {"text_citation", "dataset_authority"}:
                raise MethodResolutionError("Unsupported canonical support kind")
            if not set(capabilities.formats) <= {"PDF", "PPTX"}:
                raise MethodResolutionError("Unsupported deliverable format")
            for name in ("validate_design", "research_needs", "research_adapter", "run_stage", "report_sources"):
                if not callable(getattr(method, name, None)):
                    raise MethodResolutionError(f"Incomplete method binding: {name}")
            entries[key] = method
        self._entries = MappingProxyType(entries)

    def resolve(self, method_id: str, version: str) -> MethodBinding:
        try:
            return self._entries[(method_id, version)]
        except KeyError:
            raise MethodResolutionError(f"Unknown method/version: {method_id}/{version}") from None

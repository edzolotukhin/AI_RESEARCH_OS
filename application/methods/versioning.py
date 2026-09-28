"""CMF envelope is nested in the existing immutable activation pin (JSONB)."""
from dataclasses import asdict
import json
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider

from application.methods.catalog import production_methods
from application.methods.desk.profile import PIN, template_marker


def digest(value):
    return Sha256DigestProvider().sha256_hex(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                                       separators=(",", ":")).encode())


def envelope(method, design, brief, profile):
    return {"identity": asdict(method.identity),
            "design_hash": digest(design.to_dict()),
            "brief_hash": digest(brief.to_dict() if brief else None),
            "profile_hash": digest(profile)}


def resolve_pin(pin, *, registry=None):
    if pin is None or "cmf" not in pin:
        return None
    value = pin["cmf"]
    if not isinstance(value, dict) or not isinstance(value.get("identity"), dict):
        raise ValueError("Invalid CMF envelope")
    identity = value["identity"]
    method = (registry or production_methods()).resolve(identity.get("method_id"), identity.get("version"))
    if identity != asdict(method.identity) or pin.get("version") != method.identity.execution_version:
        raise ValueError("CMF pinned implementation is incompatible")
    if set(value) != {"identity", "design_hash", "brief_hash", "profile_hash"}:
        raise ValueError("Incomplete CMF envelope")
    if value["profile_hash"] != digest(pin.get("profile")):
        raise ValueError("CMF pinned budget profile changed")
    return method


def resolve_context(context, *, registry=None):
    marker = template_marker(context.workflow_template) if context.workflow_template else None
    pin = context.execution_metadata.get(PIN)
    if not ((isinstance(marker, dict) and "cmf" in marker) or
            (isinstance(pin, dict) and "cmf" in pin)):
        return None
    if marker != pin:
        raise ValueError("CMF activation pin differs from template")
    method = resolve_pin(pin, registry=registry)
    template = context.workflow_template
    if pin["cmf"] != envelope(method, template.research_design_snapshot,
                              template.research_brief_snapshot, pin["profile"]):
        raise ValueError("CMF approved input snapshot changed")
    return method

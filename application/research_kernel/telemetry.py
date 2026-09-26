"""Allowlisted bridge to PRF-08S; bind via its existing observed decorator."""
from application import research_funnel_telemetry as funnel


def observe_decision(event: dict) -> None:
    fields = {}
    for key in ("action", "reason", "observation", "outcome", "stop"):
        if key in event:
            fields[key] = funnel.safe_text(event[key])
    if "state_revision" in event:
        fields["state_revision"] = int(event["state_revision"])
    if "gaps" in event:
        fields["gaps"] = [dict(need=funnel.safe_text(n), reason=funnel.safe_text(r))
                          for n, r in event["gaps"]]
    if "eligible" in event:
        fields["eligible"] = [funnel.safe_text(v) for v in event["eligible"]]
    if "reservation" in event:
        fields["reservation"] = {funnel.safe_text(k): int(v)
                                 for k, v in event["reservation"].items()}
    funnel.emit("kernel_decision", **fields)

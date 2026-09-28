"""Classify Docker's actual probe result, not host command duration."""
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.structured_output.json_validator import JsonValidator


def parse_worker_state(text):
    """Use the canonical syntax validator; never expose Docker response contents."""
    validated = JsonValidator().validate(text)
    if not validated.is_valid or not isinstance(validated.data, dict):
        raise ValueError("Docker inspection unavailable")
    return validated.data


def classify_worker_health(state):
    if not state.get("Running"):
        return {"status": "CONTAINER NOT RUNNING", "exit_code": state.get("ExitCode")}
    logs = state.get("Health", {}).get("Log", [])
    if not logs:
        return {"status": "EXECUTION FAILURE", "reason": "No completed probe"}
    probe = logs[-1]
    code = probe.get("ExitCode")
    output = probe.get("Output", "")
    if code == 0:
        status = "HEALTHY"
    elif code == -1 and "Health check exceeded timeout" in output:
        status = "HEALTHCHECK TIMEOUT"
    elif code is None or code == -1:
        status = "EXECUTION FAILURE"
    else:
        status = "APPLICATION FAILURE"
    # Arbitrary application output may contain secrets. Retain timestamps/code;
    # expose only the known Engine-generated timeout category, never raw payloads.
    return {"status": status, "exit_code": code, "start": probe.get("Start"),
            "end": probe.get("End"), "diagnostic":
            "Health check exceeded timeout" if status == "HEALTHCHECK TIMEOUT" else None}


if __name__ == "__main__":
    import argparse
    import json
    import subprocess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", help="Exact existing acceptance worker container name")
    args = parser.parse_args()
    try:
        raw = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", args.container],
                             capture_output=True, text=True, timeout=30, check=True)
        result = classify_worker_health(parse_worker_state(raw.stdout))
    except (subprocess.SubprocessError, OSError, ValueError):
        result = {"status": "EXECUTION FAILURE", "reason": "Docker inspection unavailable"}
    print(json.dumps(result))
    raise SystemExit(0 if result["status"] == "HEALTHY" else 1)

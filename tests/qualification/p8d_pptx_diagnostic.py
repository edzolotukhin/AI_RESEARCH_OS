"""Safe, test-only diagnostics for the real Desk PPTX Node renderer.

This invokes the repository's production ``render.mjs`` directly.  It does not
change the production Python renderer and never logs the document payload.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure" / "documents" / "pptx_runtime" / "render.mjs"
MAX_INPUT = 800_000
MAX_DIAGNOSTIC = 2_000


@dataclass(frozen=True)
class DiagnosticResult:
    ok: bool
    category: str
    returncode: int
    stderr: str
    stdout_size: int


def _category(stderr: str, returncode: int) -> str:
    text = stderr.lower()
    if "indivisible pptx token" in text or "safe slide boundary" in text:
        return "pagination"
    if "invalid source identity" in text or "resource limit" in text:
        return "input_validation"
    if "unsafe pptx package" in text or "invalid ooxml package" in text:
        return "ooxml_validation"
    if "pptxgen" in text or "addchart" in text or "addtable" in text:
        return "pptxgenjs"
    return "node_renderer" if returncode else "unknown"


def render_payload(payload: dict, *, node: str | None = None) -> DiagnosticResult:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_INPUT:
        return DiagnosticResult(False, "input_validation", -1, "source exceeds safe diagnostic limit", 0)
    executable = node or os.environ.get("PPTX_NODE_EXECUTABLE", "node")
    try:
        result = subprocess.run(
            [executable, "--max-old-space-size=192", str(SCRIPT)],
            input=encoded, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DiagnosticResult(False, "node_renderer", -1, type(exc).__name__, 0)
    stderr = result.stderr.decode("utf-8", errors="replace")[:MAX_DIAGNOSTIC]
    ok = result.returncode == 0 and result.stdout.startswith(b"PK\x03\x04")
    return DiagnosticResult(ok, "ok" if ok else _category(stderr, result.returncode), result.returncode, stderr, len(result.stdout))


def load_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="diagnose one real PPTX renderer payload")
    parser.add_argument("payload", type=Path, help="operator-provided sanitized JSON payload")
    args = parser.parse_args()
    result = render_payload(load_payload(args.payload))
    print(json.dumps({"ok": result.ok, "category": result.category,
                      "returncode": result.returncode, "stderr": result.stderr,
                      "stdout_size": result.stdout_size}, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

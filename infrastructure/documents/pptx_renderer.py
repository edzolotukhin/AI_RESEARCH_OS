"""Bounded local Node renderer; no report contents enter logs or shell arguments."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess

from application.deliverables.contracts import PdfSourceDocument


class PptxRenderError(RuntimeError):
    pass


class PptxRenderer:
    version = "pptxgenjs-4.0.1-1"
    template_version = "neutral-corporate-1"
    media_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    def render(self, document: PdfSourceDocument) -> bytes:
        script = Path(__file__).resolve().parent / "pptx_runtime" / "render.mjs"
        node = os.environ.get("PPTX_NODE_EXECUTABLE", "node")
        payload = json.dumps(asdict(document), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > 800_000:
            raise PptxRenderError("PPTX source exceeds safe limit")
        try:
            result = subprocess.run(
                [node, "--max-old-space-size=192", str(script)], input=payload,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PptxRenderError("PPTX renderer unavailable or timed out") from exc
        if result.returncode != 0 or not result.stdout.startswith(b"PK\x03\x04") or len(result.stdout) > 10_000_000:
            raise PptxRenderError("PPTX generation failed within safe limits")
        return result.stdout

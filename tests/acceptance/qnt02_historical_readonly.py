"""Read-only historical Quant integrity audit; run inside the existing API container.

The script deliberately emits counts only, never payloads, paths or credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from application.quantitative.state_persistence import authority_fingerprint, decode_quantitative


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protected_payload(path: Path):
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["version"] == "ql-1"
    body = envelope["payload"].encode("utf-8")
    assert sha(body) == envelope["checksum"]
    return decode_quantitative(json.loads(body))


def main() -> None:
    root = Path(os.environ["QUANTITATIVE_PROTECTED_STORAGE_ROOT"])
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                rows = connection.execute(text(
                    "SELECT record_type,project_id,run_id,payload,payload_checksum,"
                    "authority_fingerprint FROM quantitative_state_records"
                )).all()
                pins = connection.scalar(text(
                    "SELECT count(*) FROM workflow_runs "
                    "WHERE task_results ? '_cmf_quant_method_v1'"
                ))
        payload_mismatches = 0
        authority_mismatches = 0
        datasets = []
        report_count = terminal_count = accepted_reports = 0
        report_scopes = set()
        terminal_scopes = set()
        for record_type, project_id, run_id, payload, checksum, fingerprint in rows:
            encoded = json.dumps({"contract_version": "qa-1", "payload": payload},
                                 sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            payload_mismatches += sha(encoded) != checksum
            value = decode_quantitative(payload)
            authority_mismatches += authority_fingerprint(value) != fingerprint
            if record_type.endswith(".DatasetVersion"):
                datasets.append((project_id, run_id, value))
            elif record_type.endswith(".QuantitativeReportCompositionResult"):
                report_count += 1
                report_scopes.add((project_id, run_id))
                accepted_reports += value.accepted_report is not None
            elif record_type.endswith(".QuantitativeTerminalResult"):
                terminal_count += 1
                terminal_scopes.add((project_id, run_id))

        raw_present = manifest_present = raw_checksum_mismatches = manifest_mismatches = 0
        protected_locators = 0
        missing_protected_with_report = missing_protected_with_terminal = 0
        for project_id, run_id, dataset in datasets:
            protected = dataset.storage_locator.startswith("protected-dataset://")
            protected_locators += protected
            scope = sha(f"{project_id}\0{run_id}".encode("utf-8"))
            base = root / scope
            raw = base / f"raw-{sha(dataset.source_file_id.encode())}.ql"
            manifest = base / f"manifest-{sha(dataset.version_id.encode())}.ql"
            if raw.is_file():
                raw_present += 1
                raw_checksum_mismatches += sha(protected_payload(raw)) != dataset.file_checksum
            if manifest.is_file():
                manifest_present += 1
                recorded = protected_payload(manifest)
                manifest_mismatches += (
                    recorded.dataset_fingerprint != dataset.dataset_fingerprint
                    or recorded.file_checksum != dataset.file_checksum
                )
            if protected and (not raw.is_file() or not manifest.is_file()):
                missing_protected_with_report += (project_id, run_id) in report_scopes
                missing_protected_with_terminal += (project_id, run_id) in terminal_scopes
        print("records", len(rows), "payload_mismatches", payload_mismatches,
              "authority_mismatches", authority_mismatches)
        print("datasets", len(datasets), "protected_locators", protected_locators,
              "raw_present", raw_present,
              "raw_checksum_mismatches", raw_checksum_mismatches,
              "manifests_present", manifest_present,
              "manifest_mismatches", manifest_mismatches,
              "missing_protected_with_report", missing_protected_with_report,
              "missing_protected_with_terminal", missing_protected_with_terminal)
        print("reports", report_count, "accepted_reports", accepted_reports,
              "terminals", terminal_count, "legacy_runs_rewritten", pins)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

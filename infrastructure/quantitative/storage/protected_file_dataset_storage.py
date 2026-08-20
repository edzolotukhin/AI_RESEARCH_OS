from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from application.ports.deterministic_digest_provider import DeterministicDigestProvider
from application.ports.quantitative_dataset_ports import DatasetStorage
from application.quantitative.fingerprints import canonical_digest, sha256_bytes
from application.quantitative.state_persistence import decode_quantitative, encode_quantitative
from application.structured_output.json_validator import JsonValidator
from domain.quantitative.dataset import DatasetVersion


class ProtectedDatasetCorruptionError(ValueError): pass


class ProtectedFileDatasetStorage(DatasetStorage):
    """Project/run-scoped durable respondent storage; paths never cross the port."""
    def __init__(self, *, root: str | Path, project_id: str, run_id: str, digest_provider: DeterministicDigestProvider) -> None:
        if not project_id or not run_id: raise ValueError("protected storage requires project and run scope")
        self._digest = digest_provider
        self._json_validator = JsonValidator()
        scope = sha256_bytes(f"{project_id}\0{run_id}".encode(), digest_provider=digest_provider)
        self._root = Path(root).resolve() / scope
        self._root.mkdir(parents=True, exist_ok=True)
        try: os.chmod(self._root, 0o700)
        except OSError: pass

    def _path(self, kind: str, identity: str) -> Path:
        name = sha256_bytes(identity.encode(), digest_provider=self._digest)
        return self._root / f"{kind}-{name}.ql"

    def _put(self, path: Path, payload: Any) -> str:
        body = json.dumps(encode_quantitative(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        envelope = json.dumps({"version": "ql-1", "checksum": sha256_bytes(body, digest_provider=self._digest), "payload": body.decode()}, sort_keys=True, separators=(",", ":")).encode()
        if path.exists():
            if path.read_bytes() != envelope: raise ValueError("immutable protected data collision")
            return "protected-dataset://" + path.stem
        with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(envelope); temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600); os.replace(temporary, path)
        finally:
            if temporary.exists(): temporary.unlink()
        return "protected-dataset://" + path.stem

    def _get(self, path: Path) -> Any:
        try:
            envelope_validation = self._json_validator.validate(path.read_text(encoding="utf-8"))
            if not envelope_validation.is_valid or not isinstance(envelope_validation.data, dict):
                raise ProtectedDatasetCorruptionError("protected envelope is not valid JSON object")
            envelope = envelope_validation.data
            if set(envelope) != {"version", "checksum", "payload"} or not all(isinstance(envelope[key], str) for key in envelope):
                raise ProtectedDatasetCorruptionError("protected envelope structure is invalid")
            body = envelope["payload"].encode()
        except OSError as exc:
            raise ProtectedDatasetCorruptionError("protected payload unreadable") from exc
        if envelope.get("version") != "ql-1" or sha256_bytes(body, digest_provider=self._digest) != envelope.get("checksum"):
            raise ProtectedDatasetCorruptionError("protected payload checksum mismatch")
        payload_validation = self._json_validator.validate(body.decode("utf-8"))
        if not payload_validation.is_valid:
            raise ProtectedDatasetCorruptionError("protected payload JSON is malformed")
        try:
            return decode_quantitative(payload_validation.data)
        except (ValueError, TypeError, KeyError) as exc:
            raise ProtectedDatasetCorruptionError("protected payload structure is invalid") from exc

    def put_raw_file(self, source_file_id: str, data: bytes) -> str: return self._put(self._path("raw", source_file_id), bytes(data))
    def get_raw_file(self, source_file_id: str) -> bytes: return bytes(self._get(self._path("raw", source_file_id)))
    def put_parsed_rows(self, version_id: str, rows: tuple[tuple[Any, ...], ...]) -> str: return self._put(self._path("rows", version_id), rows)
    def get_parsed_rows(self, version_id: str) -> tuple[tuple[Any, ...], ...]: return self._get(self._path("rows", version_id))
    def put_respondent_lineage(self, version_id: str, refs: tuple[str, ...]) -> None: self._put(self._path("lineage", version_id), refs)
    def get_respondent_lineage(self, version_id: str) -> tuple[str, ...]: return self._get(self._path("lineage", version_id))
    def put_protected_respondent_bindings(self, version_id: str, bindings: tuple[tuple[str, str], ...]) -> None: self._put(self._path("bindings", version_id), bindings)
    def get_protected_respondent_bindings(self, version_id: str) -> tuple[tuple[str, str], ...]: return self._get(self._path("bindings", version_id))
    def put_manifest(self, version: DatasetVersion) -> None: self._put(self._path("manifest", version.version_id), version)
    def get_manifest(self, version_id: str) -> DatasetVersion:
        value = self._get(self._path("manifest", version_id))
        if not isinstance(value, DatasetVersion): raise ProtectedDatasetCorruptionError("manifest type mismatch")
        return value

"""Immutable new-run CMF Quant identity and later analysis authority pin."""

from dataclasses import asdict
from application.methods.catalog import production_methods
from application.quantitative.fingerprints import canonical_digest
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider

METHOD_PIN = "_cmf_quant_method_v1"
ANALYSIS_PIN = "_cmf_quant_analysis_v1"


def _fingerprint(value):
    return canonical_digest(value, digest_provider=Sha256DigestProvider())


def make_method_pin(*, project_id: str, run_id: str):
    method = production_methods().resolve("QUANTITATIVE", "1")
    if method.capabilities.research_mode != "persisted_dataset":
        raise ValueError("Quant method is not a persisted-dataset method")
    payload = {"project_id": project_id, "run_id": run_id,
               "identity": asdict(method.identity), "contract": "CMF_QUANT_RUN_V1"}
    return {**payload, "fingerprint": _fingerprint(payload)}


def resolve_method_pin(pin, *, project_id: str, run_id: str):
    if not isinstance(pin, dict) or set(pin) != {"project_id", "run_id", "identity", "contract", "fingerprint"}:
        raise ValueError("Quant CMF method pin is missing or malformed")
    body = {key: value for key, value in pin.items() if key != "fingerprint"}
    if pin["project_id"] != project_id or pin["run_id"] != run_id or pin["contract"] != "CMF_QUANT_RUN_V1" or _fingerprint(body) != pin["fingerprint"]:
        raise ValueError("Quant CMF method pin is inconsistent")
    identity = pin["identity"]
    if not isinstance(identity, dict):
        raise ValueError("Quant CMF identity is malformed")
    method = production_methods().resolve(identity.get("method_id"), identity.get("version"))
    if identity != asdict(method.identity) or method.capabilities.research_mode != "persisted_dataset":
        raise ValueError("Quant CMF pinned implementation is incompatible")
    return method


def make_analysis_pin(*, method_pin, project_id, run_id, dataset, codebook, state):
    method = resolve_method_pin(method_pin, project_id=project_id, run_id=run_id)
    method.bind_dataset(dataset=dataset, codebook=codebook)
    if (dataset.project_id, dataset.run_id) != (project_id, run_id):
        raise ValueError("Quant dataset scope differs from run")
    fields = ("dataset_record_id", "codebook_record_id", "dataset_version_id",
              "dataset_fingerprint", "qc_record_id", "qc_fingerprint", "qc_approval_id",
              "analysis_execution_mode", "analysis_plan_version_id", "analysis_plan_fingerprint",
              "study_weighting_mode", "weight_set_record_id", "weight_set_id",
              "weight_set_fingerprint", "weight_approval_id", "weighting_authority_id",
              "weighting_authority_fingerprint")
    authority = {name: state.get(name, "") for name in fields}
    if any(not isinstance(value, str) for value in authority.values()):
        raise ValueError("Quant analysis authority contains non-scalar state")
    if (authority["dataset_version_id"], authority["dataset_fingerprint"]) != (dataset.version_id, dataset.dataset_fingerprint):
        raise ValueError("Quant analysis authority does not match dataset")
    required = ("dataset_record_id", "codebook_record_id", "qc_record_id", "qc_fingerprint",
                "qc_approval_id", "analysis_plan_version_id", "analysis_plan_fingerprint")
    if any(not authority[key] for key in required) or authority["analysis_execution_mode"] != "DESIGN_AWARE_EXECUTION":
        raise ValueError("CMF Quant requires exact approved design-aware analysis authority")
    if authority["study_weighting_mode"] not in {"UNWEIGHTED", "WEIGHTED"}:
        raise ValueError("CMF Quant weighting mode is unresolved")
    weight_fields = ("weight_set_record_id", "weight_set_id", "weight_set_fingerprint",
                     "weight_approval_id", "weighting_authority_id", "weighting_authority_fingerprint")
    if authority["study_weighting_mode"] == "WEIGHTED" and any(not authority[key] for key in weight_fields):
        raise ValueError("CMF Quant weighted authority is incomplete")
    if authority["study_weighting_mode"] == "UNWEIGHTED" and any(authority[key] for key in weight_fields[:4]):
        raise ValueError("CMF Quant unweighted authority carries a WeightSet")
    body = {"contract": "CMF_QUANT_ANALYSIS_V1", "method_fingerprint": method_pin["fingerprint"],
            "project_id": project_id, "run_id": run_id, "dataset_id": dataset.dataset_id,
            "source_checksum": dataset.file_checksum, "schema_fingerprint": dataset.schema_fingerprint,
            "data_fingerprint": dataset.data_fingerprint, "codebook_fingerprint": codebook.fingerprint,
            "authority": authority}
    return {**body, "fingerprint": _fingerprint(body)}


def verify_analysis_pin(pin, *, method_pin, project_id, run_id, dataset, codebook, state):
    if not isinstance(pin, dict) or "fingerprint" not in pin:
        raise ValueError("Quant analysis pin is missing")
    expected = make_analysis_pin(method_pin=method_pin, project_id=project_id, run_id=run_id,
                                 dataset=dataset, codebook=codebook, state=state)
    if pin != expected:
        raise ValueError("Quant analysis authority changed after binding")


def verify_analysis_state(pin, *, method_pin, state):
    if not isinstance(pin, dict) or pin.get("method_fingerprint") != method_pin["fingerprint"]:
        raise ValueError("Quant analysis pin differs from method")
    body = {key: value for key, value in pin.items() if key != "fingerprint"}
    if _fingerprint(body) != pin.get("fingerprint"):
        raise ValueError("Quant analysis pin fingerprint is invalid")
    authority = pin.get("authority")
    if not isinstance(authority, dict) or any(state.get(key, "") != value for key, value in authority.items()):
        raise ValueError("Quant workflow authority changed after binding")

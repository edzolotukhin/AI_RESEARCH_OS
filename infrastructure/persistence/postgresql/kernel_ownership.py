"""Reserved JSONB keys are owned only by the kernel store, never checkpoints."""
from copy import deepcopy

KEY = "_research_kernel_v1"
FENCE = "_research_kernel_fence_v1"
PIN = "_research_execution_v1"
QUANT_METHOD_PIN = "_cmf_quant_method_v1"
QUANT_ANALYSIS_PIN = "_cmf_quant_analysis_v1"


def checkpoint_results(current: dict, incoming: dict) -> dict:
    result = deepcopy(incoming)
    for key in (KEY, FENCE, PIN, QUANT_METHOD_PIN, QUANT_ANALYSIS_PIN):
        result.pop(key, None)
        if key in current:
            result[key] = deepcopy(current[key])
    return result


def bind_quant_pins(current: dict, checkpoint: dict, binding: dict, *, template_id: str) -> dict:
    """First-write-only Quant pins; ordinary checkpoint writes cannot install or replace them."""
    if template_id != "quantitative-consumer-survey-cmf-v1":
        raise ValueError("Quant pin binding requires a CMF Quant run")
    if not binding or set(binding) - {QUANT_METHOD_PIN, QUANT_ANALYSIS_PIN}:
        raise ValueError("invalid Quant pin binding")
    result = deepcopy(checkpoint)
    for key, value in binding.items():
        if key == QUANT_ANALYSIS_PIN and QUANT_METHOD_PIN not in result and QUANT_METHOD_PIN not in binding:
            raise ValueError("Quant analysis requires a method pin")
        if key in current and current[key] != value:
            raise ValueError("Quant pin cannot be replaced")
        result[key] = deepcopy(value)
    return result

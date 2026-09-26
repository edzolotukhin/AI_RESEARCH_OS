"""Reserved JSONB keys are owned only by the kernel store, never checkpoints."""
from copy import deepcopy

KEY = "_research_kernel_v1"
FENCE = "_research_kernel_fence_v1"
PIN = "_research_execution_v1"


def checkpoint_results(current: dict, incoming: dict) -> dict:
    result = deepcopy(incoming)
    for key in (KEY, FENCE, PIN):
        result.pop(key, None)
        if key in current:
            result[key] = deepcopy(current[key])
    return result

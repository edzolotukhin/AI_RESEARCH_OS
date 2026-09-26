"""Expose SDK transport retries to ARK; legacy calls keep the SDK's own policy."""
import time

from application.research_kernel.dispatch import current_dispatch
from application.execution.execution_budget_retry import is_llm_call_retry


def responses_create(client, kwargs):
    scope = current_dispatch()
    if scope is None:
        return client.responses.create(**kwargs)
    from openai import APIConnectionError, APIStatusError
    retries = client.max_retries
    if type(retries) is not int or not 0 <= retries <= 10:
        raise ValueError("unsupported transport retry ceiling")
    transport = client.with_options(max_retries=0)
    for ordinal in range(retries + 1):
        try:
            return scope.invoke("openai", "responses.create",
                lambda: transport.responses.create(**kwargs),
                retry=bool(ordinal) or is_llm_call_retry())
        except (APIConnectionError, APIStatusError) as error:
            if isinstance(error, APIConnectionError):
                # A timeout/disconnection cannot prove the remote operation did
                # not execute. Even an extractor swallowing the error must stop.
                scope.mark_ambiguous()
                raise
            response = getattr(error, "response", None)
            retryable = isinstance(error, APIConnectionError)
            if response is not None:
                header = response.headers.get("x-should-retry")
                retryable = (header == "true" or
                    (header != "false" and (response.status_code in (408, 409, 429)
                                            or response.status_code >= 500)))
            if not retryable or ordinal == retries:
                raise
            time.sleep(min(8.0, 0.5 * 2 ** ordinal))

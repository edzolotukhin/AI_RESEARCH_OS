"""Version-resolved wrapper over existing canonical stage executors."""
from application.contracts.base_executor import BaseExecutor
from application.methods.versioning import resolve_context


class MethodExecutor(BaseExecutor):
    def __init__(self, stage, delegate, registry):
        self.stage, self.delegate, self.registry = stage, delegate, registry

    def run(self, context):
        method = resolve_context(context, registry=self.registry)
        if method is None:
            return self.delegate.run(context)
        return method.run_stage(self.stage, context, self.delegate.run)

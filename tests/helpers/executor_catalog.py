from application.planner.executor_catalog import ExecutorCatalog
from application.planner.executor_definitions import AGENT_EXECUTOR_CAPABILITIES


def make_test_executor_catalog() -> ExecutorCatalog:
    return ExecutorCatalog.from_capabilities(AGENT_EXECUTOR_CAPABILITIES)

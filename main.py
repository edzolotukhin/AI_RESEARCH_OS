from core.agency import Agency
from examples.brand_health_demo import create_demo_project

from workflow.default_pipeline import create_default_pipeline
from workflow.workflow_engine import WorkflowEngine


def main():

    print("Creating demo project...")

    agency = Agency()

    project = create_demo_project()

    agency.create_project(project)
    agency.save_project(project)

    pipeline = create_default_pipeline()

    engine = WorkflowEngine(pipeline)

    project = engine.run(project)

    print("\nWorkflow completed.\n")
    print(project)


if __name__ == "__main__":
    main()
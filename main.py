from domain.client_request import ClientRequest
from domain.project import Project

from workflow.workflow_engine import WorkflowEngine


def main():

    request = ClientRequest(
        source="Telegram",
        client_name="Nestlé",
        contact_person="John Smith",
        contact_email="john@nestle.com",
        contact_phone="+381600000000",
        message="""
Hello.

We need a market research project in Serbia.

Please send us a commercial proposal.
"""
    )

    project = Project(
        id="P-2026-001",
        name="Nestlé Serbia Research"
    )

    project.client_request = request

    workflow = WorkflowEngine()

    project = workflow.run(project)

    print()
    print("===== CLIENT QUALIFICATION =====")
    print()

    print("Summary:")
    print(project.qualification.summary)

    print()

    print("Project understanding:")
    print(project.qualification.project_understanding)

    print()

    print("Understanding score:")
    print(project.qualification.understanding_score)

    print()

    print("Project state:")
    print(project.qualification.project_state)

    print()

    print("Next question:")
    print(project.qualification.next_question)

    print()

    print("Missing information:")

    for item in project.qualification.missing_information:
        print("-", item)


if __name__ == "__main__":
    main()
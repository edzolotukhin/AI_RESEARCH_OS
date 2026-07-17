from domain.client_request import ClientRequest
from domain.project import Project


def create_demo_project() -> Project:

    request = ClientRequest(
        source="Email",
        client_name="Purina",
        contact_person="John Smith",
        contact_email="john.smith@purina.com",
        contact_phone="+1 555 123 4567",
        message="""
We need a Brand Health study in Ukraine.

The research should evaluate:

- Brand Awareness
- Consideration
- Usage
- Loyalty

The results will be used for marketing strategy.
"""
    )

    return Project(
        id="P001",
        name="Purina Brand Health 2026",
        client_request=request,
    )
from dataclasses import dataclass


@dataclass
class ClientRequest:

    source: str

    client_name: str

    contact_person: str

    contact_email: str

    contact_phone: str

    message: str
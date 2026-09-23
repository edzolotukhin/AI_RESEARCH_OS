"""Explicitly synthetic historical rows for the disposable visual database."""

from infrastructure.persistence.postgresql.mappers.project_mapper import project_to_model


def insert_historical_project(session_factory, project) -> None:
    with session_factory.session() as session:
        session.add(project_to_model(project, version=0))

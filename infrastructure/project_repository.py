from infrastructure.persistence.file.file_project_repository import FileProjectRepository

# Backward-compatible alias for legacy imports.
ProjectRepository = FileProjectRepository

__all__ = ["FileProjectRepository", "ProjectRepository"]

from domain.research_authority import ComposedResearchAuthority, ResearchAuthorityExtension


class InMemoryAuthorityExtensionRepository:
    def __init__(self):
        self._items = {}

    def create_or_get(self, extension):
        existing = self.get_by_idempotency_key(extension.project_id, extension.idempotency_key)
        if existing is not None:
            return existing
        self._items[extension.extension_id] = extension
        return extension

    def get_by_id(self, extension_id):
        return self._items.get(extension_id)

    def get_by_idempotency_key(self, project_id, idempotency_key):
        return next((item for item in self._items.values() if item.project_id == project_id and item.idempotency_key == idempotency_key), None)


class InMemoryComposedAuthorityRepository:
    def __init__(self, extension_repository=None):
        self._items = {}
        self._extensions = extension_repository

    def create_or_get(self, composition):
        existing = self.get_by_digest(composition.composition_digest)
        if existing is not None:
            return existing
        if self._extensions is not None:
            for run_id in composition.member_workflow_run_ids:
                if run_id == composition.parent_source_workflow_run_id:
                    continue
                extension = next((item for item in self._extensions._items.values() if item.extension_workflow_run_id == run_id), None)
                if extension is None or (extension.project_id, extension.research_design_id, extension.parent_source_workflow_run_id) != (composition.project_id, composition.research_design_id, composition.parent_source_workflow_run_id):
                    raise ValueError("composition extension lineage mismatch")
        self._items[composition.composition_id] = composition
        return composition

    def get_by_id(self, composition_id):
        return self._items.get(composition_id)

    def get_by_digest(self, composition_digest):
        return next((item for item in self._items.values() if item.composition_digest == composition_digest), None)

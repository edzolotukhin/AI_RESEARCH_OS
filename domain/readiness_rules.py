from domain.project_brief import ProjectBrief


REQUIRED_FIELDS = {
    "client": "Клиент",
    "research_goal": "Цель исследования",
    "research_objectives": "Задачи исследования",
    "target_audience": "Целевая аудитория",
    "geography": "География исследования"
}


class ReadinessRules:

    @staticmethod
    def check(project_brief: ProjectBrief):

        missing_fields = []

        for field, description in REQUIRED_FIELDS.items():

            value = getattr(project_brief, field)

            if not value:
                missing_fields.append(description)

        return {
            "is_ready": len(missing_fields) == 0,
            "missing_fields": missing_fields
        }
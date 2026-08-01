from domain.research_brief import ResearchBrief


REQUIRED_FIELDS = {
    "title": "Research title",
    "business_question": "Business question",
    "objectives": "Research objectives",
}


class ReadinessRules:

    @staticmethod
    def check(research_brief: ResearchBrief):

        missing_fields = []

        for field, description in REQUIRED_FIELDS.items():

            value = getattr(research_brief, field)

            if not value:
                missing_fields.append(description)

        return {
            "is_ready": len(missing_fields) == 0,
            "missing_fields": missing_fields
        }

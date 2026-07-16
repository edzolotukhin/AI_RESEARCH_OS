from services.project_brief_builder import ProjectBriefBuilder
from core.readiness_rules import ReadinessRules


def main():

    data = {

        "client": "Purina",

        "research_goal": "Оценить здоровье бренда.",

        "research_objectives": [
            "Измерить знание бренда",
            "Измерить использование"
        ],

        "target_audience": "Владельцы собак",

        "geography": "Сербия"
    }

    project_brief = ProjectBriefBuilder.build(data)

    result = ReadinessRules.check(project_brief)

    print()
    print("===== READINESS CHECK =====")
    print()

    print("Ready:", result["is_ready"])

    print()

    print("Missing fields:")

    if result["missing_fields"]:

        for field in result["missing_fields"]:
            print("-", field)

    else:
        print("Нет")


if __name__ == "__main__":
    main()
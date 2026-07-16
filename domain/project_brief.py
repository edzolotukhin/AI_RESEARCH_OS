from dataclasses import dataclass, field
from typing import List


@dataclass
class ProjectBrief:

    # Общая информация
    client: str = ""
    project_title: str = ""

    # Что хочет узнать клиент
    business_problem: str = ""

    # Исследовательская цель
    research_goal: str = ""

    # Задачи исследования
    research_objectives: List[str] = field(default_factory=list)

    # Объект исследования
    research_object: str = ""

    # Целевая аудитория
    target_audience: str = ""

    # География
    geography: str = ""

    # Ограничения
    constraints: List[str] = field(default_factory=list)

    # Сроки
    timeline: str = ""

    # Дополнительные комментарии
    comments: str = ""

    # Вложения
    attachments: List[str] = field(default_factory=list)
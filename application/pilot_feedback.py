from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re

CATEGORIES = {"unclear", "broken", "research_result", "suggestion"}
_SECRET = re.compile(r"(?i)(?:bearer\s+\S+|sk-[a-z0-9_-]{8,}|tvly-[a-z0-9_-]{8,}|(?:api[_-]?key|password)\s*[:=]|postgres(?:ql)?://)")

class FeedbackValidationError(ValueError):
    pass

@dataclass(frozen=True)
class PilotFeedback:
    user_id: str
    category: str
    message: str
    route: str
    project_id: str | None
    role: str | None
    submitted_at: str

def build_feedback(*, user_id: str, category: str, message: str, route: str,
                   project_id: str | None = None, role: str | None = None) -> PilotFeedback:
    category = category.strip().casefold()
    if category not in CATEGORIES:
        raise FeedbackValidationError("Оберіть категорію звернення.")
    message = " ".join(message.split())
    if not 20 <= len(message) <= 2000:
        raise FeedbackValidationError("Повідомлення має містити від 20 до 2000 символів.")
    if _SECRET.search(message):
        raise FeedbackValidationError("Не додавайте паролі, ключі API або рядки підключення.")
    route = route.strip()
    if not route.startswith("/ui/") or route.startswith("//") or "?" in route or len(route) > 200:
        route = "/ui/projects"
    return PilotFeedback(user_id, category, message, route, project_id, role,
                         datetime.now(timezone.utc).isoformat())

def record_feedback(value: PilotFeedback) -> None:
    logging.getLogger("ai_research_os.pilot_feedback").info(
        "pilot_feedback user_id=%r category=%r route=%r project_id=%r role=%r submitted_at=%r message=%r",
        value.user_id, value.category, value.route, value.project_id, value.role,
        value.submitted_at, value.message,
    )

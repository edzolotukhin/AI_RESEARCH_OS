"""Public, content-free Project Activity presentation contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityEventView:
    label: str
    date_time: str
    method: str | None = None


@dataclass(frozen=True)
class ActivityTimeline:
    events: tuple[ActivityEventView, ...] = ()
    history_incomplete: bool = False
    state: str = "ready"

    @property
    def message(self) -> str | None:
        if self.state == "unavailable":
            return "Активність недоступна в поточному режимі зберігання"
        if self.state == "error":
            return "Не вдалося завантажити активність"
        if self.history_incomplete:
            return "Історія за попередній період недоступна"
        if not self.events:
            return "Подій поки немає"
        return None

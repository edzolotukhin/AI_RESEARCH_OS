from abc import ABC


class BaseRegistry(ABC):
    """
    Базовый класс для всех Registry платформы.
    """

    def __init__(self):
        self._items = {}

    def register(self, name: str, item):
        if name in self._items:
            raise ValueError(f"'{name}' is already registered.")

        self._items[name] = item

    def get(self, name: str):
        return self._items.get(name)

    def exists(self, name: str) -> bool:
        return name in self._items

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

    def unregister(self, name: str):
        self._items.pop(name, None)

    def all(self) -> dict:
        return self._items.copy()

    def clear(self):
        self._items.clear()
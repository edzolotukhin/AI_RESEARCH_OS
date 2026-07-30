from abc import ABC, abstractmethod


class BaseLoader(ABC):
    """
    Базовый класс для всех Loader платформы.
    """

    @abstractmethod
    def load(self):
        """
        Выполняет регистрацию компонентов.
        """
        raise NotImplementedError
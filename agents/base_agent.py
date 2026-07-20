class BaseAgent:
    """
    Базовый класс для всех AI-агентов.
    """

    def __init__(self, name: str = ""):
        self.name = name

    def run(self, context):
        """
        Выполнить работу агента.

        Каждый агент обязан реализовать этот метод.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement run()."
        )
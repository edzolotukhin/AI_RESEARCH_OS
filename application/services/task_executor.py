class TaskExecutor:
    """
    Выполняет AI-задачу.

    Оркестрирует:
    - построение prompt;
    - вызов LLM;
    - разбор ответа;
    - обновление Project.
    """

    def __init__(
        self,
        prompt_builder,
        llm,
        json_parser,
    ):

        self.prompt_builder = prompt_builder
        self.llm = llm
        self.json_parser = json_parser

    def execute(
        self,
        task,
        project,
        *knowledge_documents,
    ):

        system_prompt, user_prompt = self.prompt_builder.build(
            task=task,
            project=project,
            *knowledge_documents,
        )

        response = self.llm.ask(
            system_prompt,
            user_prompt,
        )

        data = self.json_parser.parse(
            response,
        )

        return task.parse_response(
            project,
            data,
        )
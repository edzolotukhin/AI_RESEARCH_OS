from domain.workflow import Workflow


def main() -> None:
    workflow = (
        Workflow(
            id="brand_health",
            name="Brand Health",
        )
        .task(
            id="planner",
            name="Planner",
            executor_id="planner",
        )
        .task(
            id="search",
            name="Search",
            executor_id="search",
            depends_on=["planner"],
        )
        .task(
            id="writer",
            name="Writer",
            executor_id="writer",
            depends_on=["search"],
        )
        .build()
    )

    print(workflow)


if __name__ == "__main__":
    main()
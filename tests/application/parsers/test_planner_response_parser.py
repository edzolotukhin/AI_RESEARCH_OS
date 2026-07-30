import unittest

from application.exceptions.planner_parser_error import PlannerParserError
from application.parsers.planner_response_parser import PlannerResponseParser

from tests.fixtures.planner_responses import VALID_PLANNER_RESPONSE


class PlannerResponseParserTests(unittest.TestCase):

    def setUp(self):
        self.parser = PlannerResponseParser()

    def test_parse_valid_response(self):
        dto = self.parser.parse(VALID_PLANNER_RESPONSE)

        self.assertEqual(dto.name, "Brand Health Workflow")
        self.assertEqual(
            dto.goal,
            "Evaluate brand awareness, usage and loyalty.",
        )
        self.assertEqual(len(dto.stages), 1)
        self.assertEqual(len(dto.stages[0].tasks), 2)
        self.assertEqual(
            dto.stages[0].tasks[0].executor_id,
            "planner",
        )

    def test_parse_missing_name_raises_error(self):
        invalid = dict(VALID_PLANNER_RESPONSE)
        del invalid["name"]

        with self.assertRaises(PlannerParserError):
            self.parser.parse(invalid)

    def test_parse_empty_task_id_raises_error(self):
        invalid = {
            "name": "Broken Workflow",
            "goal": "Broken goal",
            "stages": [
                {
                    "id": "stage-1",
                    "name": "Stage",
                    "tasks": [
                        {
                            "id": "",
                            "title": "Task",
                            "executor_id": "planner",
                        }
                    ],
                }
            ],
        }

        with self.assertRaises(PlannerParserError):
            self.parser.parse(invalid)

    def test_parse_invalid_root_type_raises_error(self):
        with self.assertRaises(PlannerParserError):
            self.parser.parse([])

    def test_parse_missing_task_title_raises_error(self):
        invalid = {
            "name": "Broken Workflow",
            "goal": "Broken goal",
            "stages": [
                {
                    "id": "stage-1",
                    "name": "Stage",
                    "tasks": [
                        {
                            "id": "task-1",
                            "executor_id": "planner",
                        }
                    ],
                }
            ],
        }

        with self.assertRaises(PlannerParserError):
            self.parser.parse(invalid)


if __name__ == "__main__":
    unittest.main()

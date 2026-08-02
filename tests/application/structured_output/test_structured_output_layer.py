import inspect
import json
import unittest
from pathlib import Path

from application.exceptions.structured_output_error import StructuredOutputError
from application.planner.payload_contract import PlannerPayloadContract
from application.planner.research_design_payload_contract import (
    ResearchDesignPayloadContract,
)
from tests.helpers.executor_catalog import make_test_executor_catalog
from application.structured_output.json_extractor import JsonExtractor
from application.structured_output.json_repair import JsonRepair
from application.structured_output.json_validator import JsonValidator
from application.structured_output.parser import StructuredOutputParser
from application.structured_output.response_cleaner import ResponseCleaner

from tests.fixtures.planner_responses import (
    EXPLANATORY_PLANNER_JSON,
    MARKDOWN_PLANNER_JSON,
    TRAILING_COMMA_PLANNER_JSON,
    VALID_PLANNER_JSON,
)

PLANNER_OBJECT = '{"name": "plan", "goal": "Goal", "stages": []}'


class JsonExtractorRootLevelTests(unittest.TestCase):

    def setUp(self):
        self.extractor = JsonExtractor()

    def test_a_root_array_with_object_returns_single_array_candidate(self):
        payload = '[{"name": "plan", "stages": []}]'
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].startswith("["))
        self.assertTrue(candidates[0].endswith("]"))

    def test_b_root_array_with_multiple_objects_returns_single_array(self):
        payload = '[\n  {"name": "one", "stages": []},\n  {"name": "two", "stages": []}\n]'
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].startswith("["))

    def test_c_object_with_prefix_and_suffix(self):
        payload = f'Prefix\n{PLANNER_OBJECT}\nSuffix'
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(candidates, [PLANNER_OBJECT])

    def test_d_two_sequential_root_objects(self):
        first = '{"example": true}'
        second = PLANNER_OBJECT
        candidates = self.extractor.extract_all(f"{first}\n{second}")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0], first)
        self.assertEqual(candidates[1], second)

    def test_e_root_array_then_root_object(self):
        array = '[{"example": true}]'
        obj = PLANNER_OBJECT
        candidates = self.extractor.extract_all(f"{array}\n{obj}")

        self.assertEqual(len(candidates), 2)
        self.assertTrue(candidates[0].startswith("["))
        self.assertTrue(candidates[1].startswith("{"))

    def test_f_brackets_inside_string_do_not_break_extraction(self):
        payload = (
            '{"text": "value with } ] { [ characters", '
            '"name": "plan", "stages": []}'
        )
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(len(candidates), 1)
        self.assertTrue(JsonValidator().validate(candidates[0]).is_valid)

    def test_g_escaped_quotes_inside_string(self):
        payload = '{"text": "quoted: \\"example\\"", "name": "plan", "stages": []}'
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(len(candidates), 1)
        self.assertTrue(JsonValidator().validate(candidates[0]).is_valid)

    def test_text_before_root_array(self):
        payload = "Text before\n[1, 2, 3]\nText after"
        candidates = self.extractor.extract_all(payload)

        self.assertEqual(candidates, ["[1, 2, 3]"])


class JsonRepairStrictTests(unittest.TestCase):

    def setUp(self):
        self.repair = JsonRepair()

    def test_h_trailing_comma_before_closing_brace(self):
        result = self.repair.try_repair('{"name": "plan", "stages": [],}')

        self.assertFalse(result.has_unclosed_string)
        self.assertFalse(result.has_unclosed_container)
        self.assertTrue(JsonValidator().validate(result.text).is_valid)

    def test_i_unfinished_array_is_not_repaired(self):
        payload = '{"name": "plan", "stages": ['
        result = self.repair.try_repair(payload)

        self.assertTrue(result.has_unclosed_container)
        self.assertFalse(JsonValidator().validate(result.text).is_valid)

    def test_j_unfinished_object_is_not_repaired(self):
        payload = '{"name": "plan", "stages": []'
        result = self.repair.try_repair(payload)

        self.assertTrue(result.has_unclosed_container)

    def test_k_unfinished_string_is_not_repaired(self):
        payload = '{"name": "unfinished'
        result = self.repair.try_repair(payload)

        self.assertTrue(result.has_unclosed_string)

    def test_l_unfinished_root_array_is_not_repaired(self):
        payload = "[1, 2,"
        result = self.repair.try_repair(payload)

        self.assertTrue(result.has_unclosed_container)


class StructuredOutputPlannerPipelineTests(unittest.TestCase):

    def setUp(self):
        self.contract = PlannerPayloadContract(
            executor_catalog=make_test_executor_catalog(),
        )
        self.parser = StructuredOutputParser()
        self.extractor = JsonExtractor()

    def _parse(self, raw_text: str) -> dict:
        return self.parser.parse(
            raw_text,
            payload_contract=self.contract,
        )

    def test_a_planner_rejects_root_array_with_nested_object(self):
        with self.assertRaises(StructuredOutputError):
            self._parse('[{"name": "plan", "stages": []}]')

    def test_e_planner_selects_second_root_object(self):
        data = self._parse(
            '{"example": true}\n'
            '{"name": "plan", "goal": "Goal", "stages": []}'
        )

        self.assertEqual(data["name"], "plan")

    def test_e_planner_selects_object_after_root_array(self):
        data = self._parse(
            '[{"example": true}]\n'
            '{"name": "plan", "goal": "Goal", "stages": []}'
        )

        self.assertEqual(data["name"], "plan")

    def test_m_broken_final_payload_after_example_raises(self):
        with self.assertRaises(StructuredOutputError):
            self._parse(
                '{"example": true}\n'
                '{"name": "plan", "stages": ['
            )

    def test_n_contract_not_length_determines_selection(self):
        long_invalid = (
            '{"name": "Bad", "goal": "Bad", "notes": "'
            + ("x" * 200)
            + '"}'
        )
        short_valid = '{"name": "plan", "goal": "Goal", "stages": []}'
        data = self._parse(f"{long_invalid}\n{short_valid}")

        self.assertEqual(data["name"], "plan")

    def test_o_selects_last_valid_planner_object(self):
        first = '{"name": "First", "goal": "First", "stages": []}'
        second = '{"name": "Second", "goal": "Second", "stages": []}'
        data = self._parse(f"{first}\n{second}")

        self.assertEqual(data["name"], "Second")

    def test_i_unfinished_array_raises(self):
        with self.assertRaises(StructuredOutputError):
            self._parse('{"name": "plan", "stages": [')

    def test_j_unfinished_object_raises(self):
        with self.assertRaises(StructuredOutputError):
            self._parse('{"name": "plan", "stages": []')

    def test_k_unfinished_string_raises(self):
        with self.assertRaises(StructuredOutputError):
            self._parse('{"name": "unfinished')

    def test_existing_planner_payloads_still_parse(self):
        design_contract = ResearchDesignPayloadContract()
        for payload in (
            VALID_PLANNER_JSON,
            MARKDOWN_PLANNER_JSON,
            EXPLANATORY_PLANNER_JSON,
            TRAILING_COMMA_PLANNER_JSON,
        ):
            data = self.parser.parse(
                payload,
                payload_contract=design_contract,
            )
            self.assertGreaterEqual(len(data["research_questions"]), 1)


class StructuredOutputArchitectureTests(unittest.TestCase):

    def test_p_json_loads_only_in_validator(self):
        project_root = Path(__file__).resolve().parents[3]

        allowed_files = {
            project_root / "application" / "structured_output" / "json_validator.py",
            project_root
            / "application"
            / "planner"
            / "deterministic_design_response.py",
        }

        offenders: list[str] = []

        for path in project_root.rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue

            source = path.read_text(encoding="utf-8")
            if "json.loads" not in source:
                continue

            if path not in allowed_files:
                offenders.append(str(path.relative_to(project_root)))

        self.assertEqual(offenders, [])

    def test_p_no_candidate_length_selection(self):
        project_root = Path(__file__).resolve().parents[3]
        structured_output_dir = project_root / "application" / "structured_output"

        for path in structured_output_dir.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("max(candidates", source)

    def test_p_no_bracket_balancing_in_repair(self):
        repair_source = inspect.getsource(JsonRepair)

        self.assertNotIn("_balance_brackets", repair_source)
        self.assertNotIn("reversed(stack)", repair_source)
        self.assertNotIn('text = f\'{text}"\'', repair_source)

    def test_p_no_datetime_utcnow_in_production(self):
        project_root = Path(__file__).resolve().parents[3]

        for path in project_root.rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue

            source = path.read_text(encoding="utf-8")
            self.assertNotIn("datetime.utcnow(", source)

    def test_planner_service_does_not_reference_raw_llm_text(self):
        from application.planner import service as planner_service_module

        source = inspect.getsource(planner_service_module.PlannerServiceImpl)

        self.assertNotIn("LLMResponse", source)
        self.assertNotIn("json.loads", source)

    def test_does_not_expose_json_decode_error(self):
        catalog = make_test_executor_catalog()
        contract = PlannerPayloadContract(executor_catalog=catalog)
        parser = StructuredOutputParser()

        with self.assertRaises(StructuredOutputError) as ctx:
            parser.parse(
                "{invalid",
                payload_contract=contract,
            )

        self.assertNotIsInstance(ctx.exception, json.JSONDecodeError)


class ResponseCleanerTests(unittest.TestCase):

    def test_removes_markdown_fence(self):
        cleaned = ResponseCleaner().clean(MARKDOWN_PLANNER_JSON)

        self.assertNotIn("```", cleaned)
        self.assertIn('"research_questions"', cleaned)


if __name__ == "__main__":
    unittest.main()

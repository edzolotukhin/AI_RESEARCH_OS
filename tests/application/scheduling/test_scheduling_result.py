import unittest

from application.scheduling.scheduling_result import SchedulingResult


class SchedulingResultTests(unittest.TestCase):

    def test_empty_result(self):
        result = SchedulingResult.empty()

        self.assertEqual(result.ready_task_ids, ())
        self.assertEqual(result.waiting_task_ids, ())
        self.assertEqual(result.skipped_task_ids, ())
        self.assertEqual(result.unchanged_task_ids, ())
        self.assertEqual(result.evaluated_task_ids, ())
        self.assertEqual(result.transition_count, 0)
        self.assertFalse(result.has_changes)
        self.assertFalse(result.has_dependency_failures)

    def test_collections_are_immutable(self):
        result = SchedulingResult(
            ready_task_ids=("a",),
            waiting_task_ids=("b",),
            skipped_task_ids=("c",),
            unchanged_task_ids=("d",),
            evaluated_task_ids=("a", "b", "c", "d"),
            transition_count=3,
            has_changes=True,
            has_dependency_failures=False,
        )

        with self.assertRaises(Exception):
            result.ready_task_ids = ("x",)  # type: ignore[misc]

    def test_transition_count_and_has_changes(self):
        result = SchedulingResult(
            ready_task_ids=("a", "b"),
            waiting_task_ids=("c",),
            skipped_task_ids=(),
            unchanged_task_ids=("d",),
            evaluated_task_ids=("a", "b", "c", "d"),
            transition_count=3,
            has_changes=True,
            has_dependency_failures=False,
        )

        self.assertEqual(result.transition_count, 3)
        self.assertTrue(result.has_changes)

    def test_no_duplicates_in_partition(self):
        result = SchedulingResult(
            ready_task_ids=("a",),
            waiting_task_ids=("b",),
            skipped_task_ids=("c",),
            unchanged_task_ids=("d",),
            evaluated_task_ids=("a", "b", "c", "d"),
            transition_count=3,
            has_changes=True,
            has_dependency_failures=False,
        )

        combined = (
            result.ready_task_ids
            + result.waiting_task_ids
            + result.skipped_task_ids
            + result.unchanged_task_ids
        )

        self.assertEqual(len(combined), len(set(combined)))

    def test_deterministic_task_id_order(self):
        result = SchedulingResult(
            ready_task_ids=("task-1", "task-2"),
            waiting_task_ids=(),
            skipped_task_ids=(),
            unchanged_task_ids=(),
            evaluated_task_ids=("task-1", "task-2"),
            transition_count=2,
            has_changes=True,
            has_dependency_failures=False,
        )

        self.assertEqual(result.ready_task_ids, ("task-1", "task-2"))


if __name__ == "__main__":
    unittest.main()

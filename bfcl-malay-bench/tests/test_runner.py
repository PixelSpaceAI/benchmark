import json
import tempfile
import unittest
from pathlib import Path

from pixel_bench.models import Case, HarnessResponse
from pixel_bench.runner import read_results, run_cases


class FixedAdapter:
    def __init__(self):
        self.calls = 0

    def invoke(self, case):
        self.calls += 1
        return HarnessResponse(
            content="",
            tool_calls=[{"name": "math.factorial", "arguments": {"number": 5}}],
            raw={"tool_calls": [{"name": "math.factorial", "arguments": {"number": 5}}]},
        )


class FlakyAdapter(FixedAdapter):
    def invoke(self, case):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary failure")
        return HarnessResponse(
            content="",
            tool_calls=[{"name": "math.factorial", "arguments": {"number": 5}}],
            raw={},
        )


def make_case(case_id="simple_0", category="simple"):
    return Case(
        id=case_id,
        category=category,
        messages=[{"role": "user", "content": "test"}],
        tools=[],
        ground_truth=[{"math.factorial": {"number": [5]}}],
        raw={},
    )


class RunnerTests(unittest.TestCase):
    def test_writes_results_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            summary = run_cases([make_case()], FixedAdapter(), path)
            rows = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual(summary["accuracy"], 1.0)
        self.assertEqual(rows[0]["status"], "scored")
        self.assertTrue(rows[0]["passed"])
        self.assertIn("latency_ms", rows[0])

    def test_resume_does_not_call_adapter_twice(self):
        adapter = FixedAdapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            run_cases([make_case()], adapter, path)
            summary = run_cases([make_case()], adapter, path, resume=True)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(summary["total"], 1)

    def test_unsupported_case_is_not_sent_to_adapter(self):
        adapter = FixedAdapter()
        case = make_case()
        case.category = "multi_turn_base"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            summary = run_cases([case], adapter, path)

        self.assertEqual(adapter.calls, 0)
        self.assertEqual(summary["unsupported"], 1)

    def test_resume_retries_and_replaces_error_rows(self):
        adapter = FlakyAdapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            first = run_cases([make_case()], adapter, path)
            second = run_cases([make_case()], adapter, path, resume=True)
            rows = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual(first["errors"], 1)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(second["errors"], 0)
        self.assertEqual(second["accuracy"], 1.0)
        self.assertEqual(len(rows), 1)

    def test_interrupted_resume_preserves_prior_and_newly_completed_rows(self):
        class InterruptingAdapter(FixedAdapter):
            def invoke(self, case):
                if case.id == "simple_2":
                    raise KeyboardInterrupt()
                return super().invoke(case)

        prior = {
            "id": "simple_0",
            "category": "simple",
            "status": "scored",
            "passed": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            path.write_text(json.dumps(prior) + "\n", encoding="utf-8")
            with self.assertRaises(KeyboardInterrupt):
                run_cases(
                    [make_case(), make_case("simple_1"), make_case("simple_2")],
                    InterruptingAdapter(),
                    path,
                    resume=True,
                )
            rows = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([row["id"] for row in rows], ["simple_0", "simple_1"])

    def test_resume_ignores_and_compacts_unselected_rows(self):
        unrelated = {
            "id": "multiple_0",
            "category": "multiple",
            "status": "scored",
            "passed": True,
        }
        adapter = FixedAdapter()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            path.write_text(json.dumps(unrelated) + "\n", encoding="utf-8")
            summary = run_cases([make_case()], adapter, path, resume=True)
            rows = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(
            [(row["category"], row["id"]) for row in rows],
            [("simple", "simple_0")],
        )

    def test_read_results_uses_latest_row_for_each_case(self):
        old = {"id": "simple_0", "category": "simple", "status": "error"}
        latest = {
            "id": "simple_0",
            "category": "simple",
            "status": "scored",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            path.write_text(
                json.dumps(old) + "\n" + json.dumps(latest) + "\n",
                encoding="utf-8",
            )
            rows = read_results(path)

        self.assertEqual(rows, [latest])


if __name__ == "__main__":
    unittest.main()

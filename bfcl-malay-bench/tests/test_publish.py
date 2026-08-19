import json
from pathlib import Path
import tempfile
import unittest

from pixel_bench.publish import publish_answers


class PublishAnswersTests(unittest.TestCase):
    def test_publish_answers_combines_cases_and_strips_private_response_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir = root / "data" / "BFCL_V3"
            data_dir.mkdir(parents=True)
            (data_dir / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "simple_0",
                            "question": [[{"role": "user", "content": "Soalan Melayu"}]],
                            "function": [
                                {
                                    "name": "lookup",
                                    "description": "Cari sesuatu",
                                    "parameters": {
                                        "type": "dict",
                                        "properties": {
                                            "query": {
                                                "type": "string",
                                                "description": "Kata carian",
                                            }
                                        },
                                        "required": ["query"],
                                    },
                                }
                            ],
                        },
                        {
                            "id": "simple_1",
                            "question": [[{"role": "user", "content": "Cuba lagi"}]],
                            "function": [],
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            answer_dir = data_dir / "possible_answer"
            answer_dir.mkdir()
            (answer_dir / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    {
                        "id": "simple_0",
                        "ground_truth": [{"lookup": {"query": "sesuatu"}}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            comparison = root / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "dataset": "khursani8/bfcl-ms",
                        "dataset_revision": "abc123",
                        "categories": ["simple"],
                        "total_cases": 2,
                        "results": [
                            {"model": "Model One", "model_id": "model-one"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            responses = root / "responses.jsonl"
            responses.write_text(
                json.dumps(
                    {
                        "id": "simple_0",
                        "category": "simple",
                        "status": "scored",
                        "passed": True,
                        "reason": "tool calls match ground truth",
                        "latency_ms": 42.25,
                        "response": {
                            "content": "Baik, saya akan cari.",
                            "tool_calls": [
                                {
                                    "name": "lookup",
                                    "arguments": {"query": "sesuatu"},
                                    "provider_trace": "private-trace",
                                }
                            ],
                            "metadata": {"harness": "private-name", "api_key": "secret"},
                            "raw": {"provider": "private-provider"},
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with responses.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "id": "simple_1",
                            "category": "simple",
                            "status": "error",
                            "passed": False,
                            "reason": (
                                "provider https://private.example/v1 failed; "
                                "config=/home/private/.env; token=sk-test-secret"
                            ),
                            "latency_ms": 21.5,
                            "response": {"content": "", "tool_calls": []},
                        }
                    )
                    + "\n"
                )

            output = root / "published"
            publish_answers(
                data_dir=root / "data",
                comparison_path=comparison,
                runs={"model-one": responses},
                output_dir=output,
            )

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            category = json.loads((output / "simple.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["total_cases"], 2)
            self.assertEqual(manifest["models"], [{"model_id": "model-one", "model": "Model One"}])
            case = category["cases"][0]
            self.assertEqual(case["question"][0][0]["content"], "Soalan Melayu")
            self.assertEqual(case["functions"][0]["description"], "Cari sesuatu")
            self.assertEqual(case["answers"][0]["content"], "Baik, saya akan cari.")
            self.assertEqual(case["answers"][0]["tool_calls"][0]["name"], "lookup")
            self.assertEqual(case["answers"][0]["reason"], "tool calls match ground truth")
            error_answer = category["cases"][1]["answers"][0]
            self.assertEqual(error_answer["reason"], "benchmark request failed")
            serialized = json.dumps(category)
            self.assertNotIn("private-name", serialized)
            self.assertNotIn("private-provider", serialized)
            self.assertNotIn("private-trace", serialized)
            self.assertNotIn("secret", serialized)
            self.assertNotIn("private.example", serialized)
            self.assertNotIn("/home/private", serialized)
            self.assertNotIn("sk-test-secret", serialized)

    def test_publish_answers_rejects_missing_case_response(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_dir = root / "data" / "BFCL_V3"
            data_dir.mkdir(parents=True)
            (data_dir / "BFCL_v3_simple.json").write_text(
                json.dumps([{"id": "simple_0", "question": "Soalan", "function": []}]),
                encoding="utf-8",
            )
            answer_dir = data_dir / "possible_answer"
            answer_dir.mkdir()
            (answer_dir / "BFCL_v3_simple.json").write_text(
                json.dumps({"id": "simple_0", "ground_truth": []}) + "\n",
                encoding="utf-8",
            )
            comparison = root / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "dataset": "khursani8/bfcl-ms",
                        "dataset_revision": "abc123",
                        "categories": ["simple"],
                        "total_cases": 1,
                        "results": [{"model": "Model One", "model_id": "model-one"}],
                    }
                ),
                encoding="utf-8",
            )
            responses = root / "responses.jsonl"
            responses.touch()

            with self.assertRaisesRegex(ValueError, "missing 1 responses for model-one"):
                publish_answers(
                    data_dir=root / "data",
                    comparison_path=comparison,
                    runs={"model-one": responses},
                    output_dir=root / "published",
                )


if __name__ == "__main__":
    unittest.main()

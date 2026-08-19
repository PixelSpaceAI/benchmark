import json
import tempfile
import unittest
from pathlib import Path

from pixel_bench.dataset import load_cases


class DatasetTests(unittest.TestCase):
    def test_loads_nested_bfcl_messages_and_jsonl_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            (root / "possible_answer").mkdir(parents=True)
            (root / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "simple_0",
                            "question": [
                                [{"role": "user", "content": "Kira lima faktorial."}]
                            ],
                            "function": [
                                {"name": "math.factorial", "parameters": {}}
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (root / "possible_answer" / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    {
                        "id": "simple_0",
                        "ground_truth": [{"math.factorial": {"number": [5]}}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            cases = load_cases(Path(directory), ["simple"])

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].messages[0]["content"], "Kira lima faktorial.")
        self.assertEqual(cases[0].ground_truth[0]["math.factorial"]["number"], [5])

    def test_assigns_stable_ids_to_chatable_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            root.mkdir(parents=True)
            (root / "BFCL_v3_chatable.json").write_text(
                json.dumps([{"question": "Apa khabar?", "function": ""}]),
                encoding="utf-8",
            )

            cases = load_cases(Path(directory), ["chatable"])

        self.assertEqual(cases[0].id, "chatable_0")
        self.assertEqual(cases[0].messages, [{"role": "user", "content": "Apa khabar?"}])

    def test_limits_cases_per_category_during_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            root.mkdir(parents=True)
            (root / "BFCL_v3_chatable.json").write_text(
                json.dumps(
                    [
                        {"question": "Satu", "function": ""},
                        {"question": "Dua", "function": ""},
                    ]
                ),
                encoding="utf-8",
            )

            cases = load_cases(
                Path(directory), ["chatable"], limit_per_category=1
            )

        self.assertEqual([case.id for case in cases], ["chatable_0"])


if __name__ == "__main__":
    unittest.main()

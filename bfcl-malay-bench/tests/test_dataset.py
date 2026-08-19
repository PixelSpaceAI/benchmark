import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pixel_bench.dataset import BASE_URL, REVISION, _download, load_cases


class DatasetTests(unittest.TestCase):
    def test_dataset_revision_is_immutable(self):
        self.assertEqual(
            REVISION, "8b610947fdbf33d75b3d0109419f36f1177d8f0a"
        )
        self.assertIn(f"/resolve/{REVISION}/", BASE_URL)

    def test_download_wraps_timeout_with_url_and_configured_timeout(self):
        url = "https://example.test/dataset.json"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "dataset.json"
            with patch(
                "pixel_bench.dataset.urllib.request.urlopen",
                side_effect=TimeoutError("timed out"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    r"https://example\.test/dataset\.json.*7s",
                ):
                    _download(url, destination, timeout=7)

        self.assertFalse(destination.exists())

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

    def test_answer_backed_category_requires_possible_answer_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            root.mkdir(parents=True)
            (root / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "simple_0",
                            "question": "Kira lima faktorial.",
                            "function": [],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                r"missing ground-truth file.*BFCL_v3_simple\.json",
            ):
                load_cases(Path(directory), ["simple"])

    def test_answer_backed_category_requires_every_selected_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            (root / "possible_answer").mkdir(parents=True)
            (root / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [
                        {"id": "simple_0", "question": "Satu", "function": []},
                        {"id": "simple_1", "question": "Dua", "function": []},
                    ]
                ),
                encoding="utf-8",
            )
            (root / "possible_answer" / "BFCL_v3_simple.json").write_text(
                json.dumps({"id": "simple_0", "ground_truth": []}) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                r"missing ground truth.*simple_1",
            ):
                load_cases(Path(directory), ["simple"])

    def test_answer_backed_category_rejects_answer_row_without_ground_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            (root / "possible_answer").mkdir(parents=True)
            (root / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [{"id": "simple_0", "question": "Satu", "function": []}]
                ),
                encoding="utf-8",
            )
            (root / "possible_answer" / "BFCL_v3_simple.json").write_text(
                json.dumps({"id": "simple_0"}) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                r"missing ground truth.*simple_0",
            ):
                load_cases(Path(directory), ["simple"])

    def test_answer_backed_category_only_requires_selected_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "BFCL_V3"
            (root / "possible_answer").mkdir(parents=True)
            (root / "BFCL_v3_simple.json").write_text(
                json.dumps(
                    [
                        {"id": "simple_0", "question": "Satu", "function": []},
                        {"id": "simple_1", "question": "Dua", "function": []},
                    ]
                ),
                encoding="utf-8",
            )
            (root / "possible_answer" / "BFCL_v3_simple.json").write_text(
                json.dumps({"id": "simple_0", "ground_truth": []}) + "\n",
                encoding="utf-8",
            )

            cases = load_cases(
                Path(directory), ["simple"], limit_per_category=1
            )

        self.assertEqual([case.id for case in cases], ["simple_0"])

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

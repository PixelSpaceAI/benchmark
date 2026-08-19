import argparse
import json
import tempfile
import unittest
from pathlib import Path

from pixel_bench.cli import _run_config, _validate_resume_config
from pixel_bench.dataset import REVISION


def make_args(**overrides):
    values = {
        "data_dir": Path("data/bfcl-ms"),
        "limit": 10,
        "adapter": "command",
        "command": "python examples/demo_adapter.py",
        "base_url": None,
        "model": None,
        "api_key_env": "OPENAI_API_KEY",
        "temperature": 0,
        "timeout": 120,
        "workers": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class CliResumeTests(unittest.TestCase):
    def test_run_identity_includes_immutable_dataset_revision(self):
        config = _run_config(make_args(), ["simple"])

        self.assertEqual(config["dataset_revision"], REVISION)
        self.assertEqual(
            config["dataset_revision"],
            "8b610947fdbf33d75b3d0109419f36f1177d8f0a",
        )

    def test_resume_rejects_incompatible_run_config(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            results_path = output / "responses.jsonl"
            run_path = output / "run.json"
            results_path.write_text("{}\n", encoding="utf-8")
            prior = _run_config(make_args(limit=1), ["simple"])
            run_path.write_text(json.dumps(prior), encoding="utf-8")
            current = _run_config(make_args(limit=2), ["simple"])

            with self.assertRaisesRegex(ValueError, "--no-resume"):
                _validate_resume_config(
                    run_path, results_path, current, resume=True
                )

    def test_resume_rejects_missing_run_config(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            results_path = output / "responses.jsonl"
            results_path.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "run.json is missing"):
                _validate_resume_config(
                    output / "run.json",
                    results_path,
                    _run_config(make_args(), ["simple"]),
                    resume=True,
                )

    def test_no_resume_allows_incompatible_run_config(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            results_path = output / "responses.jsonl"
            run_path = output / "run.json"
            results_path.write_text("{}\n", encoding="utf-8")

            _validate_resume_config(
                run_path,
                results_path,
                _run_config(make_args(), ["simple"]),
                resume=False,
            )

    def test_resume_allows_changed_runtime_only_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            results_path = output / "responses.jsonl"
            run_path = output / "run.json"
            results_path.write_text("{}\n", encoding="utf-8")
            prior = _run_config(make_args(workers=1, timeout=120), ["simple"])
            current = _run_config(make_args(workers=4, timeout=300), ["simple"])
            run_path.write_text(json.dumps(prior), encoding="utf-8")

            _validate_resume_config(run_path, results_path, current, resume=True)


if __name__ == "__main__":
    unittest.main()

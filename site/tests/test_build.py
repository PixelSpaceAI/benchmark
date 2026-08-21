import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).parents[2]
BUILD_MODULE_PATH = REPOSITORY_ROOT / "site" / "build.py"


def load_build_module():
    spec = importlib.util.spec_from_file_location("benchmark_site_build", BUILD_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SiteBuildTests(unittest.TestCase):
    def test_build_copies_assets_and_canonical_results(self):
        build = load_build_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "public"
            build.build_site(REPOSITORY_ROOT, output)

            self.assertTrue((output / ".nojekyll").exists())
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "styles.css").exists())
            self.assertTrue((output / "app.js").exists())
            self.assertTrue((output / "favicon.svg").exists())

            canonical_results = json.loads(
                (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
            )
            published_results = json.loads(
                (output / "data" / "comparison.json").read_text(encoding="utf-8")
            )
            self.assertEqual(published_results, canonical_results)
            answer_manifest = json.loads(
                (output / "data" / "answers" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(answer_manifest["total_cases"], canonical_results["total_cases"])
            for category in canonical_results["categories"]:
                self.assertTrue((output / "data" / "answers" / f"{category}.json").is_file())

            canonical_latency = json.loads(
                (REPOSITORY_ROOT / build.LATENCY_PATH).read_text(encoding="utf-8")
            )
            published_latency = json.loads(
                (output / "data" / "latency.json").read_text(encoding="utf-8")
            )
            self.assertEqual(published_latency, canonical_latency)

            page = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="overall-chart"', page)
            self.assertIn('id="category-controls"', page)
            self.assertIn('id="results-table-body"', page)
            self.assertIn('id="answer-browser"', page)
            self.assertIn('id="serving-speed"', page)
            self.assertIn('id="latency-length-chart"', page)
            self.assertIn('id="latency-table-body"', page)

    def test_build_replaces_stale_output(self):
        build = load_build_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "public"
            output.mkdir()
            (output / build.BUILD_MARKER).touch()
            stale_file = output / "stale.txt"
            stale_file.write_text("old", encoding="utf-8")

            build.build_site(REPOSITORY_ROOT, output)

            self.assertFalse(stale_file.exists())

    def test_build_refuses_to_replace_unmarked_output(self):
        build = load_build_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "public"
            output.mkdir()
            protected_file = output / "keep.txt"
            protected_file.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "refusing to replace"):
                build.build_site(REPOSITORY_ROOT, output)

            self.assertEqual(protected_file.read_text(encoding="utf-8"), "keep")

    def test_validation_rejects_dashboard_schema_drift(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        canonical_results["categories"] = ["simple"]

        with self.assertRaisesRegex(ValueError, "dashboard contract"):
            build._validate_results(canonical_results)

    def test_validation_requires_comparison_between_models(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        canonical_results["results"] = canonical_results["results"][:1]

        with self.assertRaisesRegex(ValueError, "at least two models"):
            build._validate_results(canonical_results)

    def test_validation_rejects_missing_required_key(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        del canonical_results["dataset"]

        with self.assertRaisesRegex(ValueError, "missing: dataset"):
            build._validate_results(canonical_results)

    def test_validation_rejects_nonconsecutive_ranks(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        canonical_results["results"][1]["rank"] = 3

        with self.assertRaisesRegex(ValueError, "consecutive rank"):
            build._validate_results(canonical_results)

    def test_validation_rejects_missing_result_category(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        del canonical_results["results"][0]["by_category"]["simple"]

        with self.assertRaisesRegex(ValueError, "missing category results"):
            build._validate_results(canonical_results)

    def test_validation_rejects_inconsistent_accuracy(self):
        build = load_build_module()
        canonical_results = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )
        canonical_results["results"][0]["accuracy"] = 0.99

        with self.assertRaisesRegex(ValueError, "does not match its counts"):
            build._validate_results(canonical_results)

    def test_latency_validation_rejects_missing_required_key(self):
        build = load_build_module()
        latency = json.loads(
            (REPOSITORY_ROOT / build.LATENCY_PATH).read_text(encoding="utf-8")
        )
        del latency["headline"]

        with self.assertRaisesRegex(ValueError, "missing: headline"):
            build._validate_latency(latency)

    def test_latency_validation_rejects_peak_mismatch(self):
        build = load_build_module()
        latency = json.loads(
            (REPOSITORY_ROOT / build.LATENCY_PATH).read_text(encoding="utf-8")
        )
        latency["headline"]["peak_agg_tok_s"] += 50

        with self.assertRaisesRegex(ValueError, "highest measured aggregate"):
            build._validate_latency(latency)

    def test_latency_validation_rejects_unordered_concurrency(self):
        build = load_build_module()
        latency = json.loads(
            (REPOSITORY_ROOT / build.LATENCY_PATH).read_text(encoding="utf-8")
        )
        latency["by_concurrency"][1]["concurrency"] = 1

        with self.assertRaisesRegex(ValueError, "ascending concurrency"):
            build._validate_latency(latency)

    def test_answer_validation_rejects_unexpected_published_fields(self):
        build = load_build_module()
        comparison = json.loads(
            (REPOSITORY_ROOT / build.RESULTS_PATH).read_text(encoding="utf-8")
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            answer_root = repository_root / build.ANSWERS_PATH
            shutil.copytree(REPOSITORY_ROOT / build.ANSWERS_PATH, answer_root)
            simple_path = answer_root / "simple.json"
            simple = json.loads(simple_path.read_text(encoding="utf-8"))
            simple["cases"][0]["answers"][0]["api_key"] = "must-not-publish"
            simple_path.write_text(json.dumps(simple), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unsafe answer fields"):
                build._validate_answers(repository_root, comparison)

    def test_built_site_contains_no_private_runtime_details(self):
        build = load_build_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "public"
            build.build_site(REPOSITORY_ROOT, output)
            published_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*")
                if path.is_file()
            )

            forbidden_patterns = (
                r"\bsalur\b",
                r"sk-[0-9a-f]{40,}",
                r"/home/temp-dev",
                r"\.env-file",
                r"api_key_env",
            )
            for pattern in forbidden_patterns:
                with self.subTest(pattern=pattern):
                    self.assertIsNone(re.search(pattern, published_text, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()

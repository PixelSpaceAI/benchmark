import importlib.util
import json
from pathlib import Path
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

            page = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="overall-chart"', page)
            self.assertIn('id="category-controls"', page)
            self.assertIn('id="results-table-body"', page)

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


if __name__ == "__main__":
    unittest.main()

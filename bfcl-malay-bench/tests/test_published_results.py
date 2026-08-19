import json
from pathlib import Path
import unittest


class PublishedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        results_path = Path(__file__).parents[1] / "results" / "comparison.json"
        cls.comparison = json.loads(results_path.read_text(encoding="utf-8"))

    def test_results_are_ranked_and_totals_are_consistent(self):
        results = self.comparison["results"]

        self.assertEqual([result["rank"] for result in results], [1, 2, 3, 4])
        self.assertEqual(
            [result["accuracy"] for result in results],
            sorted((result["accuracy"] for result in results), reverse=True),
        )

        for result in results:
            categories = result["by_category"].values()
            self.assertEqual(sum(item["passed"] for item in categories), result["passed"])
            self.assertEqual(sum(item["scored"] for item in categories), result["scored"])
            self.assertEqual(result["scored"], self.comparison["total_cases"])
            self.assertAlmostEqual(
                result["accuracy"], result["passed"] / result["scored"]
            )

            for category in categories:
                self.assertAlmostEqual(
                    category["accuracy"], category["passed"] / category["scored"]
                )


if __name__ == "__main__":
    unittest.main()

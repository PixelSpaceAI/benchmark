import unittest

from pixel_bench.models import Case, HarnessResponse
from pixel_bench.scoring import score_case, summarize


def make_case(category="simple", ground_truth=None, tools=None):
    return Case(
        id=f"{category}_0",
        category=category,
        messages=[{"role": "user", "content": "test"}],
        tools=tools or [],
        ground_truth=ground_truth,
        raw={},
    )


class ScoringTests(unittest.TestCase):
    def test_accepts_one_of_ground_truth_alternatives_and_omitted_optional(self):
        case = make_case(
            ground_truth=[
                {
                    "weather.get": {
                        "city": ["Kuala Lumpur", "KL"],
                        "unit": ["", "celsius"],
                    }
                }
            ]
        )
        response = HarnessResponse(
            content="",
            tool_calls=[
                {"name": "weather.get", "arguments": {"city": "KL"}}
            ],
            raw={},
        )

        result = score_case(case, response)

        self.assertTrue(result.passed)
        self.assertEqual(result.status, "scored")

    def test_matches_parallel_calls_without_order_dependency(self):
        case = make_case(
            category="parallel",
            ground_truth=[
                {"spotify.play": {"artist": ["Taylor Swift"], "duration": [20]}},
                {"spotify.play": {"artist": ["Maroon 5"], "duration": [15]}},
            ],
        )
        response = HarnessResponse(
            content="",
            tool_calls=[
                {
                    "name": "spotify.play",
                    "arguments": {"artist": "Maroon 5", "duration": 15},
                },
                {
                    "name": "spotify.play",
                    "arguments": {"artist": "Taylor Swift", "duration": 20},
                },
            ],
            raw={},
        )

        self.assertTrue(score_case(case, response).passed)

    def test_matches_overlapping_parallel_calls_in_either_response_order(self):
        case = make_case(
            category="parallel",
            ground_truth=[
                {
                    "electromagnetic_force": {
                        "charge1": [1],
                        "charge2": [2],
                        "distance": [3],
                        "medium_permittivity": ["", 8.854e-12],
                    }
                },
                {
                    "electromagnetic_force": {
                        "charge1": [1],
                        "charge2": [2],
                        "distance": [3],
                        "medium_permittivity": [8.854e-12],
                    }
                },
            ],
        )
        omitted_permittivity = {
            "name": "electromagnetic_force",
            "arguments": {"charge1": 1, "charge2": 2, "distance": 3},
        }
        explicit_permittivity = {
            "name": "electromagnetic_force",
            "arguments": {
                "charge1": 1,
                "charge2": 2,
                "distance": 3,
                "medium_permittivity": 8.854e-12,
            },
        }

        for calls in (
            [omitted_permittivity, explicit_permittivity],
            [explicit_permittivity, omitted_permittivity],
        ):
            with self.subTest(calls=calls):
                response = HarnessResponse(content="", tool_calls=calls, raw={})
                self.assertTrue(score_case(case, response).passed)

    def test_matches_nested_parameter_alternatives(self):
        case = make_case(
            category="live_multiple",
            ground_truth=[
                {
                    "drink.change": {
                        "drink_id": ["latte"],
                        "preferences": [
                            {
                                "size": ["large"],
                                "milk": ["coconut"],
                                "note": ["", "boiling hot"],
                            }
                        ],
                    }
                }
            ],
        )
        response = HarnessResponse(
            content="",
            tool_calls=[
                {
                    "name": "drink.change",
                    "arguments": {
                        "drink_id": "latte",
                        "preferences": {"size": "large", "milk": "coconut"},
                    },
                }
            ],
            raw={},
        )

        self.assertTrue(score_case(case, response).passed)

    def test_rejects_extra_arguments(self):
        case = make_case(ground_truth=[{"math.factorial": {"number": [5]}}])
        response = HarnessResponse(
            content="",
            tool_calls=[
                {
                    "name": "math.factorial",
                    "arguments": {"number": 5, "unexpected": True},
                }
            ],
            raw={},
        )

        self.assertFalse(score_case(case, response).passed)

    def test_rejects_list_when_ground_truth_expects_scalar(self):
        case = make_case(ground_truth=[{"math.factorial": {"number": [5]}}])
        response = HarnessResponse(
            content="",
            tool_calls=[
                {"name": "math.factorial", "arguments": {"number": [5]}}
            ],
            raw={},
        )

        self.assertFalse(score_case(case, response).passed)

    def test_accepts_literal_list_wrapped_as_ground_truth_alternative(self):
        case = make_case(
            ground_truth=[{"search": {"columns": [["name", "email"]]}}]
        )
        response = HarnessResponse(
            content="",
            tool_calls=[
                {
                    "name": "search",
                    "arguments": {"columns": ["name", "email"]},
                }
            ],
            raw={},
        )

        self.assertTrue(score_case(case, response).passed)

    def test_accepts_empty_list_ground_truth_value(self):
        case = make_case(ground_truth=[{"classify": {"unmatched": []}}])
        response = HarnessResponse(
            content="",
            tool_calls=[
                {"name": "classify", "arguments": {"unmatched": []}}
            ],
            raw={},
        )

        self.assertTrue(score_case(case, response).passed)

    def test_scores_irrelevance_as_no_tool_call(self):
        case = make_case(category="irrelevance")

        self.assertTrue(
            score_case(case, HarnessResponse("Saya tidak boleh.", [], {})).passed
        )
        self.assertFalse(
            score_case(
                case,
                HarnessResponse(
                    "", [{"name": "wrong", "arguments": {}}], {}
                ),
            ).passed
        )

    def test_scores_live_relevance_using_available_tool_names(self):
        case = make_case(
            category="live_relevance",
            tools=[{"name": "search_engine.query", "parameters": {}}],
        )

        good = HarnessResponse(
            "", [{"name": "search_engine.query", "arguments": {}}], {}
        )
        bad = HarnessResponse("", [{"name": "made_up", "arguments": {}}], {})

        self.assertTrue(score_case(case, good).passed)
        self.assertFalse(score_case(case, bad).passed)

    def test_marks_multi_turn_and_rest_unscored(self):
        empty = HarnessResponse("", [], {})

        self.assertEqual(
            score_case(make_case(category="multi_turn_base"), empty).status,
            "unsupported",
        )
        self.assertEqual(
            score_case(make_case(category="rest"), empty).status, "unsupported"
        )

    def test_summary_excludes_errors_and_unsupported_cases(self):
        results = [
            {"category": "simple", "status": "scored", "passed": True},
            {"category": "simple", "status": "scored", "passed": False},
            {"category": "rest", "status": "unsupported", "passed": None},
            {"category": "simple", "status": "error", "passed": None},
        ]

        summary = summarize(results)

        self.assertEqual(summary["scored"], 2)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["unsupported"], 1)
        self.assertEqual(summary["errors"], 1)


if __name__ == "__main__":
    unittest.main()

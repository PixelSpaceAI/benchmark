from __future__ import annotations

from typing import Any, Iterable

from .models import Case, HarnessResponse, ScoreResult


UNSUPPORTED_CATEGORIES = {
    "rest",
    "multi_turn_base",
    "multi_turn_composite",
    "multi_turn_long_context",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
}
IRRELEVANCE_CATEGORIES = {"irrelevance", "live_irrelevance"}


def _is_empty_allowed(spec: Any) -> bool:
    return isinstance(spec, list) and any(item == "" or item is None for item in spec)


def _scalar_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _matches_spec(actual: Any, spec: Any) -> bool:
    if isinstance(spec, list):
        if not spec:
            return isinstance(actual, (list, tuple)) and not actual
        return any(_matches_candidate(actual, candidate) for candidate in spec)
    if isinstance(spec, dict):
        if not isinstance(actual, dict):
            return False
        allowed_keys = set(spec)
        if any(key not in allowed_keys for key in actual):
            return False
        for key, child_spec in spec.items():
            if key not in actual:
                if _is_empty_allowed(child_spec):
                    continue
                return False
            if not _matches_spec(actual[key], child_spec):
                return False
        return True
    return _scalar_equal(actual, spec)


def _matches_candidate(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return _matches_spec(actual, expected)
    if not isinstance(expected, list):
        return _scalar_equal(actual, expected)
    if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
        return False
    return all(
        _matches_candidate(item, candidate)
        for item, candidate in zip(actual, expected)
    )


def _matches_call(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if len(expected) != 1:
        return False
    name, parameter_spec = next(iter(expected.items()))
    return actual.get("name") == name and _matches_spec(
        actual.get("arguments", {}), parameter_spec
    )


def _matches_calls(
    actual_calls: list[dict[str, Any]], expected_calls: list[dict[str, Any]]
) -> bool:
    if len(actual_calls) != len(expected_calls):
        return False

    actual_matches = [-1] * len(actual_calls)

    def assign(expected_index: int, seen_actual: set[int]) -> bool:
        expected = expected_calls[expected_index]
        for actual_index, actual in enumerate(actual_calls):
            if actual_index in seen_actual or not _matches_call(actual, expected):
                continue
            seen_actual.add(actual_index)
            previous_expected = actual_matches[actual_index]
            if previous_expected == -1 or assign(previous_expected, seen_actual):
                actual_matches[actual_index] = expected_index
                return True
        return False

    return all(assign(expected_index, set()) for expected_index in range(len(expected_calls)))


def score_case(case: Case, response: HarnessResponse) -> ScoreResult:
    if case.category in UNSUPPORTED_CATEGORIES:
        return ScoreResult(
            status="unsupported",
            passed=None,
            reason="requires the official BFCL executable or stateful evaluator",
        )

    if case.category in IRRELEVANCE_CATEGORIES:
        passed = len(response.tool_calls) == 0
        return ScoreResult(
            status="scored",
            passed=passed,
            reason="correctly declined tools" if passed else "made a tool call for an irrelevant prompt",
        )

    if case.category == "live_relevance":
        available = {tool.get("name") for tool in case.tools}
        passed = bool(response.tool_calls) and all(
            call.get("name") in available for call in response.tool_calls
        )
        return ScoreResult(
            status="scored",
            passed=passed,
            reason="called an available tool" if passed else "did not call an available tool",
        )

    if case.category == "chatable":
        passed = not response.tool_calls and bool(response.content.strip())
        return ScoreResult(
            status="scored",
            passed=passed,
            reason="responded without tools" if passed else "expected a non-tool conversational response",
        )

    if case.ground_truth is None:
        return ScoreResult(
            status="unsupported",
            passed=None,
            reason="the dataset does not provide static ground truth for this category",
        )

    passed = _matches_calls(response.tool_calls, case.ground_truth)
    return ScoreResult(
        status="scored",
        passed=passed,
        reason="tool calls match ground truth" if passed else "tool calls differ from ground truth",
    )


def summarize(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    total = scored = passed = errors = unsupported = 0
    category_counts: dict[str, dict[str, int]] = {}
    for row in results:
        total += 1
        category = str(row.get("category"))
        counts = category_counts.setdefault(
            category,
            {"total": 0, "scored": 0, "passed": 0, "errors": 0, "unsupported": 0},
        )
        counts["total"] += 1
        status = row.get("status")
        if status == "scored":
            scored += 1
            counts["scored"] += 1
            if row.get("passed") is True:
                passed += 1
                counts["passed"] += 1
        elif status == "error":
            errors += 1
            counts["errors"] += 1
        elif status == "unsupported":
            unsupported += 1
            counts["unsupported"] += 1

    by_category: dict[str, dict[str, Any]] = {}
    for category, counts in sorted(category_counts.items()):
        by_category[category] = {
            **counts,
            "accuracy": (
                counts["passed"] / counts["scored"] if counts["scored"] else None
            ),
        }

    return {
        "total": total,
        "scored": scored,
        "passed": passed,
        "accuracy": passed / scored if scored else None,
        "errors": errors,
        "unsupported": unsupported,
        "by_category": by_category,
    }

#!/usr/bin/env python3
"""Build the dependency-free benchmark dashboard for GitHub Pages."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil


ASSET_NAMES = ("index.html", "styles.css", "app.js", "favicon.svg")
RESULTS_PATH = Path("bfcl-malay-bench/results/comparison.json")
LATENCY_PATH = Path("pixelbench/results/latency.json")
ANSWERS_PATH = Path("bfcl-malay-bench/results/answers")
BUILD_MARKER = ".pixelspace-benchmark-site"
SUPPORTED_CATEGORIES = ("simple", "multiple", "irrelevance", "chatable")
CASE_KEYS = {"id", "question", "functions", "ground_truth", "answers"}
ANSWER_KEYS = {
    "model_id",
    "status",
    "passed",
    "reason",
    "latency_ms",
    "content",
    "tool_calls",
}


def _require_non_empty_string(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"comparison {field} must be a non-empty string")


def _require_count(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"comparison {field} must be a non-negative integer")


def _validate_score(score: dict, field: str) -> None:
    if not isinstance(score, dict):
        raise ValueError(f"comparison {field} must be an object")
    for key in ("passed", "scored"):
        if key not in score:
            raise ValueError(f"comparison {field} is missing {key}")
        _require_count(score[key], f"{field}.{key}")
    if score["scored"] == 0 or score["passed"] > score["scored"]:
        raise ValueError(f"comparison {field} has invalid counts")
    accuracy = score.get("accuracy")
    if not isinstance(accuracy, (int, float)) or isinstance(accuracy, bool):
        raise ValueError(f"comparison {field}.accuracy must be numeric")
    if not math.isfinite(accuracy) or not 0 <= accuracy <= 1:
        raise ValueError(f"comparison {field}.accuracy must be between zero and one")
    expected_accuracy = score["passed"] / score["scored"]
    if not math.isclose(accuracy, expected_accuracy, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"comparison {field}.accuracy does not match its counts")


def _validate_results(data: dict) -> None:
    required = {
        "benchmark",
        "categories",
        "dataset",
        "dataset_revision",
        "results",
        "total_cases",
    }
    missing = sorted(required.difference(data))
    if missing:
        raise ValueError(f"comparison data is missing: {', '.join(missing)}")
    if len(data["results"]) < 2:
        raise ValueError("comparison data must contain at least two models")
    if tuple(data["categories"]) != SUPPORTED_CATEGORIES:
        raise ValueError("comparison categories do not match the dashboard contract")
    _require_count(data["total_cases"], "total_cases")
    if data["total_cases"] == 0:
        raise ValueError("comparison total_cases must be positive")

    expected_ranks = list(range(1, len(data["results"]) + 1))
    ranks = [result.get("rank") for result in data["results"]]
    if ranks != expected_ranks:
        raise ValueError("comparison results must be ordered by consecutive rank")
    model_ids = set()
    previous_accuracy = math.inf
    for index, result in enumerate(data["results"]):
        if not isinstance(result, dict):
            raise ValueError("comparison results must contain objects")
        for key in ("model", "model_id"):
            _require_non_empty_string(result.get(key), f"results[{index}].{key}")
        if result["model_id"] in model_ids:
            raise ValueError("comparison model_id values must be unique")
        model_ids.add(result["model_id"])

        _validate_score(result, f"results[{index}]")
        _require_count(result.get("errors"), f"results[{index}].errors")
        if result["scored"] != data["total_cases"]:
            raise ValueError(f"{result['model']} scored count does not match total_cases")
        if result["accuracy"] > previous_accuracy:
            raise ValueError("comparison results must be ordered by descending accuracy")
        previous_accuracy = result["accuracy"]

        by_category = result.get("by_category")
        if not isinstance(by_category, dict) or not all(
            category in by_category for category in SUPPORTED_CATEGORIES
        ):
            raise ValueError(f"{result.get('model', 'model')} is missing category results")
        for category in SUPPORTED_CATEGORIES:
            _validate_score(by_category[category], f"results[{index}].by_category.{category}")
        if sum(by_category[category]["passed"] for category in SUPPORTED_CATEGORIES) != result["passed"]:
            raise ValueError(f"{result['model']} category passed counts do not match overall")
        if sum(by_category[category]["scored"] for category in SUPPORTED_CATEGORIES) != result["scored"]:
            raise ValueError(f"{result['model']} category scored counts do not match overall")


def _validate_answers(repository_root: Path, comparison: dict) -> tuple[dict, list[Path]]:
    answer_root = repository_root / ANSWERS_PATH
    manifest_path = answer_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("answer manifest must be an object")
    for key in ("dataset", "dataset_revision", "total_cases"):
        if manifest.get(key) != comparison[key]:
            raise ValueError(f"answer manifest {key} does not match comparison")

    expected_models = [
        {"model_id": result["model_id"], "model": result["model"]}
        for result in comparison["results"]
    ]
    if manifest.get("models") != expected_models:
        raise ValueError("answer manifest models do not match comparison")

    categories = manifest.get("categories")
    if not isinstance(categories, list) or [item.get("id") for item in categories] != comparison[
        "categories"
    ]:
        raise ValueError("answer manifest categories do not match comparison")

    category_paths = []
    total_cases = 0
    expected_model_ids = [model["model_id"] for model in expected_models]
    for category in categories:
        category_id = category["id"]
        filename = category.get("file")
        if filename != f"{category_id}.json":
            raise ValueError(f"answer category {category_id} has an invalid filename")
        path = answer_root / filename
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("category") != category_id:
            raise ValueError(f"answer data for {category_id} has an invalid category")
        cases = document.get("cases")
        if not isinstance(cases, list) or category.get("count") != len(cases):
            raise ValueError(f"answer data for {category_id} has an invalid case count")
        case_ids = set()
        for case in cases:
            if not isinstance(case, dict) or set(case) != CASE_KEYS:
                raise ValueError(f"answer data for {category_id} has an invalid case")
            _require_non_empty_string(case["id"], f"answers.{category_id}.id")
            if case["id"] in case_ids:
                raise ValueError(f"answer data for {category_id} has duplicate ids")
            case_ids.add(case["id"])
            answers = case["answers"]
            if not isinstance(answers, list) or [answer.get("model_id") for answer in answers] != expected_model_ids:
                raise ValueError(f"answer data for {category_id} has invalid model answers")
            for answer in answers:
                if set(answer) != ANSWER_KEYS:
                    raise ValueError(f"answer data for {category_id} has unsafe answer fields")
                if not isinstance(answer["content"], str) or not isinstance(answer["tool_calls"], list):
                    raise ValueError(f"answer data for {category_id} has invalid answer content")
        total_cases += len(cases)
        category_paths.append(path)

    if total_cases != comparison["total_cases"]:
        raise ValueError("answer category counts do not match comparison total_cases")
    return manifest, category_paths


def _require_positive_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"latency {field} must be a number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"latency {field} must be a positive number")


def _validate_latency(data: dict) -> None:
    required = {
        "benchmark",
        "model",
        "host",
        "engine",
        "measured",
        "headline",
        "by_length",
        "by_concurrency",
    }
    missing = sorted(required.difference(data))
    if missing:
        raise ValueError(f"latency data is missing: {', '.join(missing)}")
    for field in ("benchmark", "model", "host", "engine", "measured"):
        _require_non_empty_string(data[field], f"latency {field}")

    headline = data["headline"]
    if not isinstance(headline, dict):
        raise ValueError("latency headline must be an object")
    for field in ("ttft_ms", "decode_tok_s", "peak_agg_tok_s", "sweet_spot"):
        if field not in headline:
            raise ValueError(f"latency headline is missing {field}")
        _require_positive_number(headline[field], f"headline.{field}")

    by_length = data["by_length"]
    if not isinstance(by_length, list) or not by_length:
        raise ValueError("latency by_length must be a non-empty list")
    previous_tokens = 0
    for index, point in enumerate(by_length):
        if not isinstance(point, dict):
            raise ValueError("latency by_length entries must be objects")
        for field in ("tokens", "ttft_ms", "decode_tok_s", "total_ms"):
            _require_positive_number(point.get(field), f"by_length[{index}].{field}")
        if point["tokens"] <= previous_tokens:
            raise ValueError("latency by_length must be ordered by ascending tokens")
        previous_tokens = point["tokens"]

    by_concurrency = data["by_concurrency"]
    if not isinstance(by_concurrency, list) or not by_concurrency:
        raise ValueError("latency by_concurrency must be a non-empty list")
    previous_concurrency = 0
    peak = 0
    for index, point in enumerate(by_concurrency):
        if not isinstance(point, dict):
            raise ValueError("latency by_concurrency entries must be objects")
        for field in ("concurrency", "agg_tok_s", "ttft_ms"):
            _require_positive_number(point.get(field), f"by_concurrency[{index}].{field}")
        _require_count(point.get("failed"), f"by_concurrency[{index}].failed")
        if point["concurrency"] <= previous_concurrency:
            raise ValueError("latency by_concurrency must be ordered by ascending concurrency")
        previous_concurrency = point["concurrency"]
        peak = max(peak, point["agg_tok_s"])

    if not math.isclose(headline["peak_agg_tok_s"], peak, rel_tol=0, abs_tol=1e-9):
        raise ValueError("latency headline.peak_agg_tok_s must equal the highest measured aggregate")


def build_site(repository_root: Path, output: Path) -> None:
    repository_root = repository_root.resolve()
    source = repository_root / "site"
    if output.is_symlink():
        raise ValueError("site output must not be a symbolic link")
    output = output.absolute()

    if output in {repository_root, source}:
        raise ValueError("site output must not replace the repository or source directory")

    data = json.loads((repository_root / RESULTS_PATH).read_text(encoding="utf-8"))
    _validate_results(data)
    answer_manifest, answer_paths = _validate_answers(repository_root, data)

    latency = json.loads((repository_root / LATENCY_PATH).read_text(encoding="utf-8"))
    _validate_latency(latency)

    if output.exists():
        if not output.is_dir() or not (output / BUILD_MARKER).is_file():
            raise ValueError("refusing to replace an output directory not created by this builder")
        shutil.rmtree(output)
    (output / "data").mkdir(parents=True)

    for asset_name in ASSET_NAMES:
        shutil.copy2(source / asset_name, output / asset_name)

    (output / "data" / "comparison.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "data" / "latency.json").write_text(
        json.dumps(latency, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    published_answers = output / "data" / "answers"
    published_answers.mkdir()
    (published_answers / "manifest.json").write_text(
        json.dumps(answer_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for answer_path in answer_paths:
        shutil.copy2(answer_path, published_answers / answer_path.name)
    (output / ".nojekyll").touch()
    (output / BUILD_MARKER).touch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parent.parent
    build_site(repository_root, args.output)


if __name__ == "__main__":
    main()

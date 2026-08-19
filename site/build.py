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
BUILD_MARKER = ".pixelspace-benchmark-site"
SUPPORTED_CATEGORIES = ("simple", "multiple", "irrelevance", "chatable")


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

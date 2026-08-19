from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL in {path}:{line_number}: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"expected an object in {path}:{line_number}")
            rows.append(row)
    return rows


def _ground_truth_by_id(path: Path) -> dict[str, Any]:
    try:
        rows = _read_jsonl(path)
    except FileNotFoundError:
        return {}
    return {
        row["id"]: row["ground_truth"]
        for row in rows
        if isinstance(row.get("id"), str) and "ground_truth" in row
    }


def _safe_answer(model_id: str, row: dict[str, Any]) -> dict[str, Any]:
    response = row.get("response")
    if not isinstance(response, dict):
        response = {}
    tool_calls = response.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []
    tool_calls = [
        {
            "name": call.get("name", ""),
            "arguments": call.get("arguments", {}),
        }
        for call in tool_calls
        if isinstance(call, dict)
    ]
    content = response.get("content")
    if not isinstance(content, str):
        content = ""
    reason = (
        "benchmark request failed"
        if row.get("status") == "error"
        else row.get("reason")
    )
    return {
        "model_id": model_id,
        "status": row.get("status"),
        "passed": row.get("passed"),
        "reason": reason,
        "latency_ms": row.get("latency_ms"),
        "content": content,
        "tool_calls": tool_calls,
    }


def publish_answers(
    *,
    data_dir: Path,
    comparison_path: Path,
    runs: dict[str, Path],
    output_dir: Path,
) -> None:
    comparison = _read_json(comparison_path)
    if not isinstance(comparison, dict):
        raise ValueError("comparison must be an object")
    categories = comparison.get("categories")
    results = comparison.get("results")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise ValueError("comparison categories must be a list of strings")
    if not isinstance(results, list) or not results:
        raise ValueError("comparison results must be a non-empty list")

    models = [
        {"model_id": result.get("model_id"), "model": result.get("model")}
        for result in results
    ]
    if any(
        not isinstance(model["model_id"], str) or not isinstance(model["model"], str)
        for model in models
    ):
        raise ValueError("comparison models require model_id and model strings")
    model_ids = [model["model_id"] for model in models]
    if set(runs) != set(model_ids):
        missing = sorted(set(model_ids).difference(runs))
        extra = sorted(set(runs).difference(model_ids))
        detail = []
        if missing:
            detail.append(f"missing runs: {', '.join(missing)}")
        if extra:
            detail.append(f"unknown runs: {', '.join(extra)}")
        raise ValueError("; ".join(detail))

    responses: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for model_id in model_ids:
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in _read_jsonl(runs[model_id]):
            category = row.get("category")
            case_id = row.get("id")
            if category in categories and isinstance(case_id, str):
                latest[(category, case_id)] = row
        responses[model_id] = latest

    root = data_dir / "BFCL_V3"
    published_categories: list[dict[str, Any]] = []
    category_documents: dict[str, dict[str, Any]] = {}
    expected_case_count = 0

    for category in categories:
        source_path = root / f"BFCL_v3_{category}.json"
        entries = _read_json(source_path)
        if not isinstance(entries, list):
            raise ValueError(f"expected a JSON array in {source_path}")
        ground_truth = _ground_truth_by_id(
            root / "possible_answer" / f"BFCL_v3_{category}.json"
        )
        cases = []
        case_ids = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(f"{source_path} contains a non-object case")
            case_ids.append(entry.get("id") or f"{category}_{index}")
        expected_keys = {(category, case_id) for case_id in case_ids}
        if len(expected_keys) != len(entries):
            raise ValueError(f"{source_path} contains duplicate case ids")
        for model_id in model_ids:
            missing = expected_keys.difference(responses[model_id])
            if missing:
                raise ValueError(f"missing {len(missing)} responses for {model_id} in {category}")

        for entry, case_id in zip(entries, case_ids):
            cases.append(
                {
                    "id": case_id,
                    "question": entry.get("question", ""),
                    "functions": entry.get("function", []),
                    "ground_truth": ground_truth.get(case_id),
                    "answers": [
                        _safe_answer(model_id, responses[model_id][(category, case_id)])
                        for model_id in model_ids
                    ],
                }
            )
        expected_case_count += len(cases)
        filename = f"{category}.json"
        published_categories.append(
            {"id": category, "count": len(cases), "file": filename}
        )
        category_documents[filename] = {
            "schema_version": 1,
            "category": category,
            "cases": cases,
        }

    total_cases = comparison.get("total_cases")
    if total_cases != expected_case_count:
        raise ValueError(
            f"comparison total_cases is {total_cases}, but dataset contains {expected_case_count}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    expected_files = {"manifest.json", *category_documents}
    for existing in output_dir.glob("*.json"):
        if existing.name not in expected_files:
            existing.unlink()
    manifest = {
        "schema_version": 1,
        "dataset": comparison.get("dataset"),
        "dataset_revision": comparison.get("dataset_revision"),
        "total_cases": total_cases,
        "models": models,
        "categories": published_categories,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for filename, document in category_documents.items():
        (output_dir / filename).write_text(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def _run_argument(value: str) -> tuple[str, Path]:
    model_id, separator, path = value.partition("=")
    if not separator or not model_id or not path:
        raise argparse.ArgumentTypeError("runs must use MODEL_ID=PATH")
    return model_id, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish sanitized BFCL prompts and model answers for the result browser."
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--run", action="append", type=_run_argument, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runs = dict(args.run)
    if len(runs) != len(args.run):
        parser.error("each --run model id must be unique")
    publish_answers(
        data_dir=args.data_dir,
        comparison_path=args.comparison,
        runs=runs,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()

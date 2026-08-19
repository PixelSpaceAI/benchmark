from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .models import Case


DATASET_ID = "khursani8/bfcl-ms"
REVISION = "main"
BASE_URL = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{REVISION}/BFCL_V3"

ALL_CATEGORIES = (
    "simple",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
    "java",
    "javascript",
    "rest",
    "sql",
    "live_simple",
    "live_multiple",
    "live_parallel",
    "live_parallel_multiple",
    "live_relevance",
    "live_irrelevance",
    "chatable",
    "multi_turn_base",
    "multi_turn_composite",
    "multi_turn_long_context",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
)
ANSWER_CATEGORIES = {
    "simple",
    "multiple",
    "parallel",
    "parallel_multiple",
    "java",
    "javascript",
    "sql",
    "live_simple",
    "live_multiple",
    "live_parallel",
    "live_parallel_multiple",
    "multi_turn_base",
    "multi_turn_composite",
    "multi_turn_long_context",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
}
DEFAULT_CATEGORIES = ("simple",)
SCOREABLE_SINGLE_TURN_CATEGORIES = tuple(
    category
    for category in ALL_CATEGORIES
    if not category.startswith("multi_turn") and category != "rest"
)


def validate_categories(categories: Iterable[str]) -> list[str]:
    values = list(dict.fromkeys(categories))
    unknown = [category for category in values if category not in ALL_CATEGORIES]
    if unknown:
        raise ValueError(
            f"unknown categories: {', '.join(unknown)}; choose from {', '.join(ALL_CATEGORIES)}"
        )
    return values


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "pixel-bench/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"failed to download {url}: {error}") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(destination)


def sync_dataset(
    data_dir: Path, categories: Iterable[str], *, force: bool = False
) -> list[Path]:
    categories = validate_categories(categories)
    root = data_dir / "BFCL_V3"
    downloaded: list[Path] = []
    for category in categories:
        relative = Path(f"BFCL_v3_{category}.json")
        destination = root / relative
        if force or not destination.exists():
            _download(f"{BASE_URL}/{relative.as_posix()}", destination)
            downloaded.append(destination)
        if category in ANSWER_CATEGORIES:
            answer_relative = Path("possible_answer") / relative
            answer_destination = root / answer_relative
            if force or not answer_destination.exists():
                _download(
                    f"{BASE_URL}/{answer_relative.as_posix()}", answer_destination
                )
                downloaded.append(answer_destination)
    return downloaded


def _load_answers(
    path: Path, selected_ids: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    answers: dict[str, list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL in {path}:{line_number}: {error}") from error
            if selected_ids is None or row["id"] in selected_ids:
                answers[row["id"]] = row["ground_truth"]
    return answers


def _messages(question: Any) -> list[dict[str, Any]]:
    if isinstance(question, str):
        return [{"role": "user", "content": question}]
    if not isinstance(question, list):
        raise ValueError(f"unsupported BFCL question shape: {type(question).__name__}")
    if question and isinstance(question[0], list):
        # Multi-turn cases are retained in raw form, but the adapter gets the
        # first turn only because local scoring marks them unsupported.
        return list(question[0])
    return list(question)


def load_cases(
    data_dir: Path,
    categories: Iterable[str],
    *,
    limit_per_category: int = 0,
) -> list[Case]:
    if limit_per_category < 0:
        raise ValueError("limit_per_category cannot be negative")
    categories = validate_categories(categories)
    root = data_dir / "BFCL_V3"
    cases: list[Case] = []
    for category in categories:
        path = root / f"BFCL_v3_{category}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"missing {path}; run `pixel-bench sync --categories {category}`"
            )
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON in {path}: {error}") from error
        if not isinstance(entries, list):
            raise ValueError(f"expected a JSON array in {path}")
        selected_entries = (
            entries[:limit_per_category] if limit_per_category else entries
        )
        selected_ids = {
            entry.get("id") or f"{category}_{index}"
            for index, entry in enumerate(selected_entries)
        }
        answers = _load_answers(
            root / "possible_answer" / path.name, selected_ids=selected_ids
        )
        for index, entry in enumerate(selected_entries):
            case_id = entry.get("id") or f"{category}_{index}"
            function_value = entry.get("function", [])
            tools = function_value if isinstance(function_value, list) else []
            cases.append(
                Case(
                    id=case_id,
                    category=category,
                    messages=_messages(entry.get("question", "")),
                    tools=tools,
                    ground_truth=answers.get(case_id),
                    raw=entry,
                )
            )
    return cases

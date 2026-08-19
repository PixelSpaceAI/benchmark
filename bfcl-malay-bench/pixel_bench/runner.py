from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from .adapters import Adapter
from .models import Case, HarnessResponse
from .scoring import score_case, summarize


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                if not line.endswith("\n"):
                    # The append was interrupted before the row was durable. Keep
                    # the valid prefix so resume can retry the incomplete case.
                    break
                raise ValueError(f"invalid result JSONL at {path}:{line_number}: {error}") from error
    return rows


def _latest_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_case: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("category"), row.get("id"))
        if key in latest_by_case:
            del latest_by_case[key]
        latest_by_case[key] = row
    return list(latest_by_case.values())


def _write_row(handle, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _compact_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _unsupported_row(case: Case) -> dict[str, Any] | None:
    result = score_case(case, HarnessResponse(content="", tool_calls=[], raw={}))
    if result.status != "unsupported":
        return None
    return {
        "id": case.id,
        "category": case.category,
        "status": result.status,
        "passed": result.passed,
        "reason": result.reason,
        "latency_ms": None,
        "response": None,
    }


def _run_one(case: Case, adapter: Adapter) -> dict[str, Any]:
    unsupported = _unsupported_row(case)
    if unsupported is not None:
        return unsupported
    started = time.perf_counter()
    try:
        response = adapter.invoke(case)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        result = score_case(case, response)
        return {
            "id": case.id,
            "category": case.category,
            "status": result.status,
            "passed": result.passed,
            "reason": result.reason,
            "latency_ms": latency_ms,
            "response": {
                "content": response.content,
                "tool_calls": response.tool_calls,
                "metadata": response.metadata,
                "raw": response.raw,
            },
        }
    except Exception as error:  # A failed case should not abort a long benchmark.
        return {
            "id": case.id,
            "category": case.category,
            "status": "error",
            "passed": None,
            "reason": str(error),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "response": None,
        }


def run_cases(
    cases: Iterable[Case],
    adapter: Adapter,
    results_path: Path,
    *,
    workers: int = 1,
    resume: bool = False,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    cases = list(cases)
    selected_keys = {(case.category, case.id) for case in cases}
    latest_by_case: dict[tuple[Any, Any], dict[str, Any]] = {}
    if resume:
        for row in _latest_rows(_read_rows(results_path)):
            key = (row.get("category"), row.get("id"))
            if key in selected_keys:
                latest_by_case[key] = row
    completed = {
        key
        for key, row in latest_by_case.items()
        if row.get("status") in {"scored", "unsupported"}
    }
    pending = [case for case in cases if (case.category, case.id) not in completed]

    results_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if resume else "w"
    with results_path.open(mode, encoding="utf-8") as handle:
        if workers == 1:
            rows = (_run_one(case, adapter) for case in pending)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            pending_iterator = iter(pending)

            def bounded_rows():
                while batch := list(islice(pending_iterator, workers * 2)):
                    yield from executor.map(
                        lambda case: _run_one(case, adapter), batch
                    )

            rows = bounded_rows()
        try:
            for row in rows:
                _write_row(handle, row)
                latest_by_case[(row.get("category"), row.get("id"))] = row
        finally:
            if workers > 1:
                executor.shutdown(wait=True)

    selected_rows = [
        latest_by_case[(case.category, case.id)]
        for case in cases
        if (case.category, case.id) in latest_by_case
    ]
    _compact_rows(results_path, selected_rows)
    return summarize(selected_rows)


def rescore_rows(cases: Iterable[Case], rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    cases_by_key = {(case.category, case.id): case for case in cases}
    rescored: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        case = cases_by_key.get((row.get("category"), row.get("id")))
        response_value = row.get("response")
        if case is None or not isinstance(response_value, dict):
            rescored.append(row)
            continue
        response = HarnessResponse(
            content=response_value.get("content", ""),
            tool_calls=response_value.get("tool_calls", []),
            raw=response_value.get("raw", {}),
            metadata=response_value.get("metadata", {}),
        )
        result = score_case(case, response)
        row.update(status=result.status, passed=result.passed, reason=result.reason)
        rescored.append(row)
    return rescored


def read_results(path: Path) -> list[dict[str, Any]]:
    return _latest_rows(_read_rows(path))

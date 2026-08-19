from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .adapters import CommandAdapter, OpenAIAdapter
from .dataset import (
    ALL_CATEGORIES,
    DATASET_ID,
    DEFAULT_CATEGORIES,
    REVISION,
    SCOREABLE_SINGLE_TURN_CATEGORIES,
    load_cases,
    sync_dataset,
    validate_categories,
)
from .runner import read_results, rescore_rows, run_cases
from .scoring import summarize


_RESUME_IDENTITY_KEYS = {
    "schema_version",
    "dataset",
    "dataset_revision",
    "data_dir",
    "categories",
    "limit_per_category",
    "adapter",
    "command",
    "base_url",
    "model",
    "temperature",
}


def _categories(values: Iterable[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_CATEGORIES)
    expanded: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if part == "all":
                expanded.extend(ALL_CATEGORIES)
            elif part in {"single-turn", "scoreable"}:
                expanded.extend(SCOREABLE_SINGLE_TURN_CATEGORIES)
            else:
                expanded.append(part)
    return validate_categories(expanded)


def _print_summary(summary: dict[str, Any]) -> None:
    accuracy = summary.get("accuracy")
    accuracy_text = "n/a" if accuracy is None else f"{accuracy:.2%}"
    print(
        f"Scored {summary['scored']}/{summary['total']} cases: "
        f"{summary['passed']} passed, accuracy {accuracy_text}, "
        f"{summary['errors']} errors, {summary['unsupported']} unsupported."
    )
    for category, values in summary.get("by_category", {}).items():
        category_accuracy = values.get("accuracy")
        category_text = "n/a" if category_accuracy is None else f"{category_accuracy:.2%}"
        print(
            f"  {category}: {values['passed']}/{values['scored']} passed "
            f"({category_text}), {values['errors']} errors, "
            f"{values['unsupported']} unsupported"
        )


def _sync(args: argparse.Namespace) -> int:
    categories = _categories(args.categories)
    downloaded = sync_dataset(args.data_dir, categories, force=args.force)
    if downloaded:
        print(f"Downloaded {len(downloaded)} file(s) into {args.data_dir}.")
    else:
        print(f"Dataset is already present in {args.data_dir}.")
    return 0


def _build_adapter(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.adapter == "command":
        if not args.command:
            parser.error("--command is required when --adapter command is selected")
        return CommandAdapter(args.command, timeout=args.timeout)
    if not args.base_url or not args.model:
        parser.error("--base-url and --model are required when --adapter openai is selected")
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    return OpenAIAdapter(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout=args.timeout,
        temperature=args.temperature,
    )


def _run_config(args: argparse.Namespace, categories: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": DATASET_ID,
        "dataset_revision": REVISION,
        "data_dir": str(args.data_dir),
        "categories": categories,
        "limit_per_category": args.limit,
        "adapter": args.adapter,
        "command": args.command if args.adapter == "command" else None,
        "base_url": args.base_url if args.adapter == "openai" else None,
        "model": args.model if args.adapter == "openai" else None,
        "api_key_env": args.api_key_env if args.adapter == "openai" else None,
        "temperature": args.temperature if args.adapter == "openai" else None,
        "timeout": args.timeout,
        "workers": args.workers,
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _validate_resume_config(
    run_path: Path, results_path: Path, config: dict[str, Any], *, resume: bool
) -> None:
    if not resume or not results_path.exists():
        return
    guidance = "use --no-resume or choose a new --output directory"
    if not run_path.exists():
        raise ValueError(f"cannot resume: {run_path} is missing; {guidance}")
    try:
        previous = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot resume: invalid {run_path}; {guidance}") from error
    previous_identity = {key: previous.get(key) for key in _RESUME_IDENTITY_KEYS}
    current_identity = {key: config.get(key) for key in _RESUME_IDENTITY_KEYS}
    if previous_identity != current_identity:
        raise ValueError(
            f"cannot resume: run settings differ from {run_path}; {guidance}"
        )


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    categories = _categories(args.categories)
    if not args.offline:
        downloaded = sync_dataset(args.data_dir, categories)
        if downloaded:
            print(f"Downloaded {len(downloaded)} dataset file(s).")
    cases = load_cases(
        args.data_dir, categories, limit_per_category=args.limit
    )
    if not cases:
        parser.error("no benchmark cases were selected")
    adapter = _build_adapter(args, parser)

    if args.output is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path("runs") / stamp
    else:
        output = args.output
    output.mkdir(parents=True, exist_ok=True)
    results_path = output / "responses.jsonl"
    run_path = output / "run.json"
    config = _run_config(args, categories)
    _validate_resume_config(run_path, results_path, config, resume=args.resume)
    _write_json_atomic(run_path, config)
    print(f"Running {len(cases)} case(s); results: {results_path}")
    summary = run_cases(
        cases,
        adapter,
        results_path,
        workers=args.workers,
        resume=args.resume,
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _print_summary(summary)
    return 1 if summary["errors"] else 0


def _score(args: argparse.Namespace) -> int:
    rows = read_results(args.results)
    categories = validate_categories(
        dict.fromkeys(str(row["category"]) for row in rows).keys()
    )
    if not args.offline:
        sync_dataset(args.data_dir, categories)
    cases = load_cases(args.data_dir, categories)
    rescored = rescore_rows(cases, rows)
    summary = summarize(rescored)
    destination = args.output or args.results.with_name("summary.json")
    destination.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _print_summary(summary)
    print(f"Summary written to {destination}.")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    categories = _categories(args.categories)
    if not args.offline:
        sync_dataset(args.data_dir, categories)
    cases = load_cases(
        args.data_dir, categories, limit_per_category=args.limit
    )
    for case in cases:
        payload = case.adapter_payload()
        if args.show_answer:
            payload["ground_truth"] = case.ground_truth
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixel-bench",
        description="Benchmark a PixelSpace-compatible harness on Malay BFCL v3.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    sync_parser = subparsers.add_parser("sync", help="download benchmark data")
    sync_parser.add_argument("--data-dir", type=Path, default=Path("data/bfcl-ms"))
    sync_parser.add_argument("--categories", nargs="+", default=["all"])
    sync_parser.add_argument("--force", action="store_true")
    sync_parser.set_defaults(handler=_sync)

    run_parser = subparsers.add_parser("run", help="run and score a harness")
    run_parser.add_argument("--data-dir", type=Path, default=Path("data/bfcl-ms"))
    run_parser.add_argument("--categories", nargs="+", default=list(DEFAULT_CATEGORIES))
    run_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="maximum cases per category; use 0 for every case (default: 10)",
    )
    run_parser.add_argument("--adapter", choices=("command", "openai"), required=True)
    run_parser.add_argument("--command", help="command adapter executable and arguments")
    run_parser.add_argument("--base-url", help="OpenAI-compatible server base URL")
    run_parser.add_argument("--model", help="model name sent to the endpoint")
    run_parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    run_parser.add_argument("--temperature", type=float, default=0)
    run_parser.add_argument("--timeout", type=float, default=120)
    run_parser.add_argument("--workers", type=int, default=1)
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--offline", action="store_true")
    run_parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    run_parser.set_defaults(handler=_run)

    score_parser = subparsers.add_parser("score", help="rescore an existing run")
    score_parser.add_argument("--results", type=Path, required=True)
    score_parser.add_argument("--data-dir", type=Path, default=Path("data/bfcl-ms"))
    score_parser.add_argument("--output", type=Path)
    score_parser.add_argument("--offline", action="store_true")
    score_parser.set_defaults(handler=_score)

    inspect_parser = subparsers.add_parser(
        "inspect", help="print adapter request payloads without running a harness"
    )
    inspect_parser.add_argument("--data-dir", type=Path, default=Path("data/bfcl-ms"))
    inspect_parser.add_argument("--categories", nargs="+", default=list(DEFAULT_CATEGORIES))
    inspect_parser.add_argument("--limit", type=int, default=1)
    inspect_parser.add_argument("--show-answer", action="store_true")
    inspect_parser.add_argument("--offline", action="store_true")
    inspect_parser.set_defaults(handler=_inspect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args, parser) if args.subcommand == "run" else args.handler(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

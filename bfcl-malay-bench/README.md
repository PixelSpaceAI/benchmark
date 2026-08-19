# BFCL Malay Bench

`pixel-bench` evaluates tool-calling systems on
[`khursani8/bfcl-ms`](https://huggingface.co/datasets/khursani8/bfcl-ms), a
Malay adaptation of Berkeley Function-Calling Leaderboard v3. It downloads the
dataset, sends each prompt and tool schema to an OpenAI-compatible endpoint or
command-based harness, stores resumable per-case results, and reports accuracy
by category.

Dataset downloads and run identities are pinned to immutable revision
[`8b610947fdbf33d75b3d0109419f36f1177d8f0a`](https://huggingface.co/datasets/khursani8/bfcl-ms/tree/8b610947fdbf33d75b3d0109419f36f1177d8f0a).

The runner has no runtime dependency beyond Python 3.10+.

## Published focused results

The focused suite contains 1,040 cases from `simple`, `multiple`,
`irrelevance`, and `chatable`. These categories emphasize the fields translated
to Malay: user prompts, function descriptions, and parameter descriptions.

| Model | Simple | Multiple | Irrelevance | Chatable | Overall |
|---|---:|---:|---:|---:|---:|
| **ILMU Mini v3.3** | **66.75%** | 62.00% | **85.42%** | **100.00%** | **76.54%** |
| Nemotron 3.5 Lightning | 66.25% | **65.00%** | 79.17% | 99.50% | 75.38% |
| Muse Glimmer 30B | 54.75% | 61.00% | 71.25% | 99.50% | 68.37% |
| Qwen 3.8 27B | 57.50% | 60.50% | 67.08% | 57.50% | 60.29% |

See [RESULTS.md](RESULTS.md) for methodology, failure analysis, latency, and
comparison caveats. Machine-readable values are in
[`results/comparison.json`](results/comparison.json).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Smoke test the runner

```bash
pixel-bench run \
  --adapter command \
  --command "python examples/demo_adapter.py" \
  --categories simple \
  --limit 1 \
  --output runs/demo
```

The smoke run should report `1/1 passed`.

## Benchmark an OpenAI-compatible endpoint

```bash
export MODEL_API_KEY="your-key"

pixel-bench run \
  --adapter openai \
  --base-url https://your-endpoint.example/v1 \
  --model your-model-id \
  --api-key-env MODEL_API_KEY \
  --temperature 0 \
  --categories simple multiple irrelevance chatable \
  --limit 0 \
  --workers 1 \
  --timeout 180 \
  --output runs/your-model-malay-focus
```

Start with one worker and increase only within the endpoint's rate limit. Runs
resume by default: completed cases are skipped and errors are retried. Runtime
settings such as worker count and timeout may change during resume, while the
dataset selection and adapter identity must remain the same.

## Benchmark Pixel Harness

Use the command adapter when Pixel Harness is exposed through a local bridge or
CLI. The command is launched once per case and receives one JSON object on
stdin:

```json
{
  "id": "simple_0",
  "category": "simple",
  "messages": [{"role": "user", "content": "..."}],
  "tools": [{"name": "...", "description": "...", "parameters": {}}],
  "raw": {}
}
```

It must write one JSON object to stdout:

```json
{
  "content": "",
  "tool_calls": [
    {"name": "math.factorial", "arguments": {"number": 5}}
  ],
  "metadata": {"harness": "pixel-harness"}
}
```

Run the focused suite with your bridge:

```bash
pixel-bench run \
  --adapter command \
  --command "python path/to/pixel_harness_adapter.py" \
  --categories simple multiple irrelevance chatable \
  --limit 0 \
  --workers 1 \
  --timeout 180 \
  --output runs/pixel-harness-malay-focus
```

Ground truth is deliberately excluded from the adapter payload. Benchmark
tools should be inert: record the first assistant turn's selected calls, but do
not execute real tools or trigger a second model turn.

## Artifacts

Every run writes:

- `responses.jsonl` — durable per-case status, latency, normalized response,
  metadata, and raw response;
- `summary.json` — aggregate and per-category accuracy;
- `run.json` — non-secret run settings used to validate safe resume.

## Scoring scope

This repository provides a practical harness-integration score, not an official
BFCL leaderboard submission.

- Answer-backed categories use unordered one-to-one structural matching of tool
  names and arguments against accepted ground-truth alternatives.
- `irrelevance` and `live_irrelevance` pass only with zero tool calls.
- `live_relevance` requires at least one available tool name; arguments are not
  evaluated in that category.
- `chatable` requires non-empty visible text and zero tool calls.
- REST and multi-turn categories require the official executable/stateful BFCL
  evaluator and are unsupported by the local scorer.

For leaderboard-comparable results, implement an official BFCL model handler
and run the upstream `bfcl-eval` evaluator.

## Useful commands

```bash
# Download every locally scoreable single-turn category.
pixel-bench sync --categories single-turn

# Inspect the exact non-leaky adapter payload.
pixel-bench inspect --categories simple --limit 1

# Recompute scores without another model call.
pixel-bench score --results runs/your-model/responses.jsonl

# Run the test suite.
python -m unittest discover -s tests -v
```

## Dataset attribution

The benchmark data is the Apache-2.0-licensed Malay adaptation of BFCL v3.
Dataset files from the pinned revision are downloaded into the ignored `data/`
directory and are not vendored here. The runner code in this repository is
licensed under Apache-2.0.

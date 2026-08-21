# pixelbench

`pixelbench` measures the **serving latency and throughput** of an
OpenAI-compatible endpoint — how fast the first token arrives, how many tokens
per second it generates, and how throughput and latency behave as concurrent
requests pile up. It complements the accuracy-focused
[BFCL Malay bench](../bfcl-malay-bench/): that one asks *is the answer right*,
this one asks *how fast does it come back*.

It streams `POST /v1/chat/completions` and has no runtime dependency beyond
[Bun](https://bun.sh).

## Metrics

| Metric | Meaning |
|---|---|
| **TTFT** | Time to first token — the wait before any text appears. |
| **decode tok/s** | Output tokens per second *after* the first token — raw generation speed. |
| **end-to-end tok/s** | Output tokens over the whole request, including TTFT. |
| **total ms** | Wall-clock for the entire request. |
| **aggregate tok/s** | Total output tokens per second with N requests in flight — throughput under load. |

Single-request figures are the median of several runs after a warmup that fills
caches. Concurrency figures fire N requests simultaneously and divide total
output tokens by the wall-clock of the slowest.

### Reasoning models

Models that think before answering (e.g. `nemotron-3.5-lightning`) stream
`reasoning` tokens first, then the reply. `pixelbench` counts a token of *any*
kind for TTFT and throughput, so TTFT is the honest moment the user sees motion
— not the time to the first `content` token, which can be the whole request when
the budget is spent thinking.

## Running it

Point at any reachable OpenAI-compatible endpoint:

```bash
BENCH_BASE_URL=http://localhost:8000/v1 \
BENCH_MODEL=nemotron-3.5-lightning \
BENCH_API_KEY=local-no-auth \
bun bench.ts
```

Or use `run.sh`, which also handles the common case where the gateway is only on
a Compose network (the bundled Pixelspace model at `http://model:8000/v1`) by
shipping `bench.ts` into a container and running it there:

```bash
# gateway reachable locally
BENCH_BASE_URL=http://localhost:8000/v1 ./run.sh

# gateway only inside a Compose network
HOST=user@model-host CONTAINER=pixelspace-api-1 ./run.sh
```

### Configuration

Every option is an environment variable:

| Variable | Default | Meaning |
|---|---|---|
| `BENCH_BASE_URL` | `$CUSTOM_BASE_URL` | Gateway base URL (…/v1). |
| `BENCH_MODEL` | `$CUSTOM_MODEL` | Model id. |
| `BENCH_API_KEY` | `$CUSTOM_API_KEY` | Bearer key. |
| `BENCH_MAX_TOKENS` | `256` | Max tokens generated per request. |
| `BENCH_RUNS` | `5` | Measured sequential runs. |
| `BENCH_WARMUP` | `1` | Discarded warmup runs. |
| `BENCH_CONCURRENCY` | `1,2,4,8` | Concurrency levels for the sweep. |
| `BENCH_TEMPERATURE` | `0` | Sampling temperature. |
| `BENCH_PROMPT` | (a long technical prompt) | The user message. |

Each report is Markdown, with a machine-readable `pixelbench-json` block
appended in an HTML comment for archiving or plotting.

## Published results

`nemotron-3.5-lightning` (NVFP4, 131k context) on **DGX Spark**, served by vLLM,
temperature 0. Measured 2026-08-21.

### Single-request, by output length

| Output tokens | TTFT (ms) | Decode (tok/s) | Total (ms) |
|---|---:|---:|---:|
| 64 | 100 | 163.6 | 492 |
| 256 | 99 | 107.7 | 2,478 |
| 512 | 85 | 97.2 | 5,357 |
| 1024 | 97 | 94.3 | 10,956 |

TTFT stays flat (~90–100 ms) regardless of length; per-token decode falls as the
KV cache grows.

### Throughput vs concurrency (128 tokens each)

| Concurrency | Aggregate (tok/s) | Mean TTFT (ms) | Failed |
|---|---:|---:|---:|
| 1 | 114 | 86 | 0 |
| 2 | 188 | 93 | 0 |
| 4 | 273 | 164 | 0 |
| 8 | 275 | 1,073 | 0 |
| 16 | 266 | 3,071 | 0 |
| 32 | 271 | 6,411 | 0 |

Aggregate throughput plateaus around **275 tok/s** once ~4 requests are in
flight; beyond that, extra concurrency only grows the queue — TTFT climbs from
~160 ms at 4 to ~6.4 s at 32 with no throughput gain. The practical sweet spot
is ~4 concurrent requests.

Raw per-run data is in [`results/`](results/) (`len-*.json`,
`concurrency.json`), each carrying the full `pixelbench-json` record.

## Limitations

- Single node, single GPU; numbers are specific to this DGX Spark + vLLM build
  and will differ on other hardware, quantization, or engine settings.
- One prompt shape and a fixed `max_tokens` per run; real traffic mixes lengths.
- Temperature 0 for repeatability — sampling settings affect speed slightly.
- Throughput is measured client-side (wall-clock over streamed tokens), not from
  server-side scheduler metrics.

## Reproduction

```bash
cd pixelbench
# against the bundled Pixelspace model on its host
HOST=user@model-host CONTAINER=pixelspace-api-1 ./run.sh                 # baseline (256 tok)
BENCH_MAX_TOKENS=1024 BENCH_CONCURRENCY=1 HOST=… CONTAINER=… ./run.sh    # length point
BENCH_MAX_TOKENS=128 BENCH_CONCURRENCY=1,2,4,8,16,32 HOST=… CONTAINER=… ./run.sh  # sweep
```

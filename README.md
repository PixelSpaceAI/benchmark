# PixelSpaceAI Benchmarks

Public evaluation harnesses and reproducible result summaries from
[PixelSpaceAI](https://github.com/PixelSpaceAI).

Explore the results on the
[public benchmark dashboard](https://pixelspaceai.github.io/benchmark/),
including a filterable browser with every prompt and model answer.

## Benchmarks

- [Malay BFCL v3 tool-calling benchmark](bfcl-malay-bench/) — evaluate an
  OpenAI-compatible endpoint or a command-based Pixel Harness integration on
  the Malay adaptation of Berkeley Function-Calling Leaderboard v3.
- [pixelbench](pixelbench/) — serving latency and throughput of an
  OpenAI-compatible endpoint: time to first token, tokens per second, and how
  both behave under concurrency.

Each benchmark directory owns its runner, methodology, results, limitations,
and reproduction instructions.

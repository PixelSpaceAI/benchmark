# Malay-focused tool-calling results

## Headline

ILMU Mini v3.3 ranks first on the 1,040-case focused suite at **76.54%**, with
Nemotron 3.5 Lightning close behind at **75.38%**.

| Rank | Model | Passed / scored | Accuracy |
|---:|---|---:|---:|
| 1 | ILMU Mini v3.3 | 796 / 1,040 | **76.54%** |
| 2 | Nemotron 3.5 Lightning | 784 / 1,040 | 75.38% |
| 3 | Muse Glimmer 30B | 711 / 1,040 | 68.37% |
| 4 | Qwen 3.8 27B | 627 / 1,040 | 60.29% |

## Category results

| Model | Simple | Multiple | Irrelevance | Chatable |
|---|---:|---:|---:|---:|
| ILMU Mini v3.3 | **267/400 (66.75%)** | 124/200 (62.00%) | **205/240 (85.42%)** | **200/200 (100.00%)** |
| Nemotron 3.5 Lightning | 265/400 (66.25%) | **130/200 (65.00%)** | 190/240 (79.17%) | 199/200 (99.50%) |
| Muse Glimmer 30B | 219/400 (54.75%) | 122/200 (61.00%) | 171/240 (71.25%) | 199/200 (99.50%) |
| Qwen 3.8 27B | 230/400 (57.50%) | 121/200 (60.50%) | 161/240 (67.08%) | 115/200 (57.50%) |

Nemotron remains marginally stronger on combined exact tool construction:
`simple` + `multiple` is 395/600 (65.83%) for Nemotron and 391/600 (65.17%)
for ILMU. ILMU takes the aggregate lead through stronger tool restraint and a
perfect conversational score.

## Protocol

- Dataset: `khursani8/bfcl-ms`, revision `main` at execution time.
- Date: 18–19 August 2026.
- Focused categories: `simple`, `multiple`, `irrelevance`, `chatable`.
- Temperature: 0 for ILMU, Nemotron, and Muse; Qwen used its deployment's
  thinking preset.
- Turn scope: first assistant response; no benchmark tool was executed.
- Scorer: Pixel Bench local structural/relevance/conversation scorer.

ILMU was evaluated through the direct OpenAI-compatible adapter. Nemotron,
Muse, and Qwen were evaluated through the Pixel Harness command adapter. The
cases and scoring contract are identical, but request construction and system
prompts differ. Treat the table as an end-to-end deployment comparison, not a
controlled model-only ranking.

## Failure profile

| Model | Argument mismatch | False-positive tool use | Other scored failures |
|---|---:|---:|---:|
| ILMU Mini v3.3 | 168 | 35 | 41 |
| Nemotron 3.5 Lightning | 199 | 50 | 7 |
| Muse Glimmer 30B | 248 | 69 | 12 |
| Qwen 3.8 27B | 231 | 79 | 103 |

“Argument mismatch” means the response used the expected tool-call count and
tool-name multiset but the arguments failed the local structural matcher.
Argument fidelity is the largest shared weakness.

Qwen's 103 “other” failures include 85 `chatable` turns with no visible text.
Because Qwen used a thinking deployment, that result may partly reflect the
model–gateway–Pixel Harness output boundary.

## End-to-end latency

| Model | Median | P95 | Maximum |
|---|---:|---:|---:|
| ILMU Mini v3.3 | **1.50 s** | **10.36 s** | 116.56 s |
| Muse Glimmer 30B | 8.53 s | 31.71 s | 573.56 s |
| Nemotron 3.5 Lightning | 9.30 s | 33.89 s | 157.38 s |
| Qwen 3.8 27B | 10.15 s | 40.13 s | 134.97 s |

Latency includes each adapter path and serving stack. ILMU used direct HTTP;
the other models used a command bridge into Pixel Harness. These values measure
deployment latency, not isolated model inference speed.

Muse showed the sharpest tail: two conversational cases took roughly 573
seconds during recovery. One emitted 55,648 visible characters and the other
returned no visible text.

## Reproducibility and limitations

- This is not an official BFCL leaderboard result.
- The dataset revision was recorded as mutable `main`; published result values
  are snapshots from the stated execution dates.
- The four models were not all served by identical infrastructure or prompts.
- Temperature zero does not guarantee provider-level determinism.
- The focused suite intentionally excludes parallel orchestration, live/API,
  REST, SQL, Java, JavaScript, and multi-turn behavior.
- Raw responses are not published because they contain provider payloads and
  internal harness metadata. Aggregate counts are provided in
  [`results/comparison.json`](results/comparison.json).

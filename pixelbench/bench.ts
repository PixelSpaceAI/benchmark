#!/usr/bin/env bun
/**
 * pixelbench — a tiny load/latency benchmark for an OpenAI-compatible endpoint.
 *
 * It streams chat completions and measures the numbers that actually matter for
 * an interactive agent:
 *
 *   TTFT       time to first token — how long the user stares at a blank box
 *   decode t/s output tokens per second once generation has started
 *   e2e  t/s   output tokens over the whole request (includes TTFT)
 *   total ms   wall-clock for the whole request
 *
 * No dependencies — just `bun bench.ts`. Everything is configurable by env var
 * so it runs the same inside the api container or from any host that can reach
 * the gateway. See README.md.
 */

// ── Config (all overridable by env) ─────────────────────────────────────────
const BASE_URL = (process.env.BENCH_BASE_URL ?? process.env.CUSTOM_BASE_URL ?? 'http://model:8000/v1').replace(/\/+$/, '')
const MODEL = process.env.BENCH_MODEL ?? process.env.CUSTOM_MODEL ?? 'nemotron-3.5-lightning'
const API_KEY = process.env.BENCH_API_KEY ?? process.env.CUSTOM_API_KEY ?? 'local-no-auth'
const MAX_TOKENS = num(process.env.BENCH_MAX_TOKENS, 256)
const RUNS = num(process.env.BENCH_RUNS, 5) // measured sequential runs
const WARMUP = num(process.env.BENCH_WARMUP, 1) // discarded runs first
const CONCURRENCY = (process.env.BENCH_CONCURRENCY ?? '1,2,4,8')
  .split(',')
  .map((s) => parseInt(s.trim(), 10))
  .filter((n) => n > 0)
const TEMPERATURE = num(process.env.BENCH_TEMPERATURE, 0)
const PROMPT =
  process.env.BENCH_PROMPT ??
  'Write a detailed, technical explanation of how a transformer language model generates text token by token. Cover attention, the KV cache, and sampling. Aim for several paragraphs.'

function num(v: string | undefined, d: number): number {
  const n = v ? Number(v) : NaN
  return Number.isFinite(n) ? n : d
}

/**
 * The text carried by one streamed delta, or ''.
 *
 * Reasoning models (nemotron-3.5-lightning) emit an empty `content` first and
 * stream their thinking under `reasoning` (some servers call it
 * `reasoning_content`). Watching only `content` made TTFT never fire, since the
 * whole budget can be spent thinking. First token = first text of any kind.
 */
function tokenText(delta: any): string {
  if (!delta) return ''
  const content = delta.content
  if (typeof content === 'string' && content.length) return content
  const reasoning = delta.reasoning ?? delta.reasoning_content
  if (typeof reasoning === 'string' && reasoning.length) return reasoning
  return ''
}

// ── One streamed request, fully measured ────────────────────────────────────
type Sample = {
  ok: boolean
  ttftMs: number
  totalMs: number
  promptTokens: number
  completionTokens: number
  decodeTokS: number // completion / (total - ttft)
  e2eTokS: number // completion / total
  error?: string
}

async function once(): Promise<Sample> {
  const started = performance.now()
  let ttft = -1
  let completionFromDeltas = 0
  let usageCompletion = 0
  let usagePrompt = 0

  try {
    const res = await fetch(`${BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${API_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL,
        stream: true,
        // Ask vLLM to attach a usage object to the final SSE chunk so token
        // counts are exact rather than estimated from deltas.
        stream_options: { include_usage: true },
        temperature: TEMPERATURE,
        max_tokens: MAX_TOKENS,
        messages: [{ role: 'user', content: PROMPT }],
      }),
    })

    if (!res.ok || !res.body) {
      return failed(started, `HTTP ${res.status} ${(await res.text()).slice(0, 200)}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let nl: number
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim()
        buffer = buffer.slice(nl + 1)
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trim()
        if (data === '[DONE]') continue
        let json: any
        try {
          json = JSON.parse(data)
        } catch {
          continue
        }
        const piece = tokenText(json?.choices?.[0]?.delta)
        if (piece && ttft < 0) ttft = performance.now() - started
        if (piece) completionFromDeltas++
        if (json?.usage) {
          usageCompletion = json.usage.completion_tokens ?? usageCompletion
          usagePrompt = json.usage.prompt_tokens ?? usagePrompt
        }
      }
    }

    const totalMs = performance.now() - started
    const completion = usageCompletion || completionFromDeltas
    if (ttft < 0) ttft = totalMs
    const decodeMs = Math.max(1, totalMs - ttft)
    return {
      ok: true,
      ttftMs: ttft,
      totalMs,
      promptTokens: usagePrompt,
      completionTokens: completion,
      decodeTokS: (completion / decodeMs) * 1000,
      e2eTokS: (completion / totalMs) * 1000,
    }
  } catch (err) {
    return failed(started, err instanceof Error ? err.message : String(err))
  }
}

function failed(started: number, error: string): Sample {
  const totalMs = performance.now() - started
  return { ok: false, ttftMs: totalMs, totalMs, promptTokens: 0, completionTokens: 0, decodeTokS: 0, e2eTokS: 0, error }
}

// ── Stats helpers ───────────────────────────────────────────────────────────
function pct(sorted: number[], p: number): number {
  if (!sorted.length) return 0
  const i = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))
  return sorted[i]
}
function summarize(values: number[]) {
  const s = [...values].sort((a, b) => a - b)
  const mean = s.reduce((a, b) => a + b, 0) / (s.length || 1)
  return { min: s[0] ?? 0, mean, median: pct(s, 50), p95: pct(s, 95), max: s[s.length - 1] ?? 0 }
}
const f = (n: number, d = 1) => n.toFixed(d)

// ── Run: sequential latency, then a concurrency sweep ───────────────────────
async function main() {
  const startedAt = new Date().toISOString()
  console.log(`# pixelbench\n`)
  console.log(`- **when:** ${startedAt}`)
  console.log(`- **endpoint:** \`${BASE_URL}\``)
  console.log(`- **model:** \`${MODEL}\``)
  console.log(`- **max_tokens:** ${MAX_TOKENS} · **temperature:** ${TEMPERATURE} · **runs:** ${RUNS} (+${WARMUP} warmup)`)
  console.log(`- **prompt:** ${PROMPT.length} chars\n`)

  // Warmup (loads weights / fills caches; discarded).
  for (let i = 0; i < WARMUP; i++) await once()

  // Sequential latency runs.
  const runs: Sample[] = []
  for (let i = 0; i < RUNS; i++) {
    const s = await once()
    runs.push(s)
    console.error(
      `  run ${i + 1}/${RUNS}  ${s.ok ? '' : 'FAILED '}ttft=${f(s.ttftMs)}ms total=${f(s.totalMs)}ms ` +
        `out=${s.completionTokens}tok decode=${f(s.decodeTokS)}t/s${s.error ? ' :: ' + s.error : ''}`,
    )
  }
  const ok = runs.filter((r) => r.ok)
  const failures = runs.length - ok.length

  const ttft = summarize(ok.map((r) => r.ttftMs))
  const decode = summarize(ok.map((r) => r.decodeTokS))
  const e2e = summarize(ok.map((r) => r.e2eTokS))
  const total = summarize(ok.map((r) => r.totalMs))
  const outTok = summarize(ok.map((r) => r.completionTokens))
  const promptTokens = ok[0]?.promptTokens ?? 0

  console.log(`## Single-request latency (${ok.length} ok, ${failures} failed)\n`)
  console.log(`prompt tokens ≈ ${promptTokens} · output tokens ≈ ${f(outTok.mean, 0)} (per run)\n`)
  console.log(`| metric | min | mean | median | p95 | max |`)
  console.log(`| --- | --- | --- | --- | --- | --- |`)
  console.log(`| TTFT (ms) | ${f(ttft.min)} | ${f(ttft.mean)} | ${f(ttft.median)} | ${f(ttft.p95)} | ${f(ttft.max)} |`)
  console.log(`| decode (tok/s) | ${f(decode.min)} | ${f(decode.mean)} | ${f(decode.median)} | ${f(decode.p95)} | ${f(decode.max)} |`)
  console.log(`| end-to-end (tok/s) | ${f(e2e.min)} | ${f(e2e.mean)} | ${f(e2e.median)} | ${f(e2e.p95)} | ${f(e2e.max)} |`)
  console.log(`| total (ms) | ${f(total.min)} | ${f(total.mean)} | ${f(total.median)} | ${f(total.p95)} | ${f(total.max)} |\n`)

  // Concurrency sweep: fire C requests at once, measure aggregate throughput.
  const sweep: any[] = []
  console.log(`## Concurrency (aggregate output throughput)\n`)
  console.log(`| concurrency | ok/failed | wall (ms) | total out tok | agg tok/s | mean TTFT (ms) |`)
  console.log(`| --- | --- | --- | --- | --- | --- |`)
  for (const c of CONCURRENCY) {
    const t0 = performance.now()
    const results = await Promise.all(Array.from({ length: c }, () => once()))
    const wall = performance.now() - t0
    const good = results.filter((r) => r.ok)
    const outSum = good.reduce((a, r) => a + r.completionTokens, 0)
    const aggTokS = (outSum / wall) * 1000
    const meanTtft = good.length ? good.reduce((a, r) => a + r.ttftMs, 0) / good.length : 0
    console.log(
      `| ${c} | ${good.length}/${c - good.length} | ${f(wall)} | ${outSum} | ${f(aggTokS)} | ${f(meanTtft)} |`,
    )
    sweep.push({ concurrency: c, ok: good.length, failed: c - good.length, wallMs: wall, outTokens: outSum, aggTokS, meanTtftMs: meanTtft })
  }

  // Machine-readable block for archiving / diffing across runs.
  const record = {
    startedAt,
    endpoint: BASE_URL,
    model: MODEL,
    config: { maxTokens: MAX_TOKENS, temperature: TEMPERATURE, runs: RUNS, warmup: WARMUP, promptChars: PROMPT.length },
    single: { okRuns: ok.length, failures, promptTokens, outputTokens: outTok, ttftMs: ttft, decodeTokS: decode, e2eTokS: e2e, totalMs: total },
    concurrency: sweep,
    rawRuns: runs,
  }
  console.log(`\n<!-- pixelbench-json\n${JSON.stringify(record, null, 2)}\n-->`)
}

main().catch((e) => {
  console.error('pixelbench failed:', e)
  process.exit(1)
})
